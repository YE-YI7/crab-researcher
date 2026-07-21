"""Provider interface and local Patchright implementation for browser jobs."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.browser_safety import UnsafeBrowserTarget, validate_public_target


class ApprovalRequired(RuntimeError):
    """Raised when an action can change external state and needs confirmation."""


@dataclass
class BrowserActionResult:
    url: str
    title: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    artifact_bytes: bytes | None = None
    artifact_kind: str | None = None
    artifact_content_type: str | None = None


class BrowserSession(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def execute(self, action: str, params: dict, *, approved: bool = False) -> BrowserActionResult: ...

    @abstractmethod
    async def close(self) -> None: ...


class LocalPatchrightSession(BrowserSession):
    """A development worker session.

    Production should replace this adapter with a dedicated container or
    microVM provider. Chromium's own sandbox remains enabled here.
    """

    def __init__(self, *, allowed_domains: list[str], timeout_seconds: int = 90):
        self.allowed_domains = allowed_domains
        self.timeout_ms = max(10, timeout_seconds) * 1000
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def start(self) -> None:
        from patchright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            accept_downloads=False,
        )

        async def enforce_network_policy(route):
            try:
                await validate_public_target(route.request.url, self.allowed_domains)
            except UnsafeBrowserTarget:
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        await self._context.route("**/*", enforce_network_policy)
        self._page = await self._context.new_page()

    async def _identity(self) -> tuple[str, str]:
        return self._page.url, await self._page.title()

    async def _unique(self, selector: str):
        if not selector or len(selector) > 500:
            raise ValueError("A bounded CSS selector is required")
        locator = self._page.locator(selector)
        count = await locator.count()
        if count != 1:
            raise ValueError(f"Selector must match exactly one element; matched {count}")
        return locator

    async def execute(self, action: str, params: dict, *, approved: bool = False) -> BrowserActionResult:
        if self._page is None:
            raise RuntimeError("Browser session has not started")

        if action == "navigate":
            url = params.get("url", "")
            await validate_public_target(url, self.allowed_domains)
            await self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await validate_public_target(self._page.url, self.allowed_domains)

        elif action == "click":
            locator = await self._unique(params.get("selector", ""))
            element = await locator.evaluate(
                "el => ({tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(), inForm: !!el.closest('form')})"
            )
            if not approved and (element["inForm"] or element["tag"] == "button" or element["type"] in {"submit", "button"}):
                raise ApprovalRequired("Buttons and form controls require approval before clicking")
            await locator.click(timeout=self.timeout_ms)

        elif action == "fill":
            if not approved:
                raise ApprovalRequired("Typing into a website requires approval")
            value = params.get("value", "")
            if not isinstance(value, str) or len(value) > 4000:
                raise ValueError("Fill value must be a string of at most 4000 characters")
            locator = await self._unique(params.get("selector", ""))
            input_type = await locator.get_attribute("type")
            if (input_type or "").lower() in {"password", "file"}:
                raise ValueError("Password and file inputs are not supported in the browser MVP")
            await locator.fill(value, timeout=self.timeout_ms)

        elif action == "press":
            key = params.get("key", "")
            if key not in {"Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter"}:
                raise ValueError("Unsupported key")
            if key == "Enter" and not approved:
                raise ApprovalRequired("Enter can submit a form and requires approval")
            locator = await self._unique(params.get("selector", ""))
            await locator.press(key, timeout=self.timeout_ms)

        elif action == "submit":
            if not approved:
                raise ApprovalRequired("Final submission requires approval")
            locator = await self._unique(params.get("selector", ""))
            await locator.click(timeout=self.timeout_ms)

        elif action == "extract":
            selector = params.get("selector") or "body"
            locator = await self._unique(selector)
            text = (await locator.inner_text(timeout=self.timeout_ms))[:20_000]
            url, title = await self._identity()
            return BrowserActionResult(
                url=url,
                title=title,
                data={"selector": selector, "text_preview": text[:1000], "character_count": len(text)},
                artifact_bytes=text.encode("utf-8"),
                artifact_kind="text",
                artifact_content_type="text/plain; charset=utf-8",
            )

        elif action == "screenshot":
            data = await self._page.screenshot(full_page=False, type="png")
            url, title = await self._identity()
            return BrowserActionResult(
                url=url,
                title=title,
                data={"viewport": {"width": 1280, "height": 800}},
                artifact_bytes=data,
                artifact_kind="screenshot",
                artifact_content_type="image/png",
            )

        else:
            raise ValueError(f"Unsupported browser action: {action}")

        url, title = await self._identity()
        if url and url != "about:blank":
            await validate_public_target(url, self.allowed_domains)
        return BrowserActionResult(url=url, title=title)

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


class VercelSandboxSession(BrowserSession):
    """Runs the browser inside a per-job Vercel Firecracker microVM."""

    def __init__(
        self,
        *,
        allowed_domains: list[str],
        timeout_seconds: int,
        node_binary: str,
        vcpus: int,
    ):
        self.allowed_domains = allowed_domains
        self.timeout_seconds = timeout_seconds
        self.node_binary = node_binary
        self.vcpus = max(1, min(vcpus, 8))
        self._process = None
        self.sandbox_id = None

    async def _request(self, payload: dict, timeout_seconds: int | None = None) -> dict:
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("Vercel Sandbox bridge has not started")
        self._process.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        await self._process.stdin.drain()
        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=timeout_seconds or self.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Vercel Sandbox bridge timed out") from exc
        if not line:
            raise RuntimeError("Vercel Sandbox bridge exited unexpectedly")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "Vercel Sandbox request failed")[:2000])
        return response

    async def start(self) -> None:
        settings = get_settings()
        if not settings.VERCEL_SANDBOX_IMAGE:
            raise RuntimeError("VERCEL_SANDBOX_IMAGE must reference a prepared VCR browser image")
        has_oidc = bool(os.getenv("VERCEL_OIDC_TOKEN"))
        has_access_token = bool(
            settings.VERCEL_TOKEN and settings.VERCEL_PROJECT_ID and settings.VERCEL_TEAM_ID
        )
        if not has_oidc and not has_access_token:
            raise RuntimeError(
                "Vercel Sandbox requires VERCEL_OIDC_TOKEN or VERCEL_TOKEN, VERCEL_PROJECT_ID, and VERCEL_TEAM_ID"
            )
        bridge = Path(__file__).resolve().parents[2] / "sandbox_bridge" / "vercel_bridge.mjs"
        env = os.environ.copy()
        env.update({
            "VERCEL_SANDBOX_IMAGE": settings.VERCEL_SANDBOX_IMAGE,
            "VERCEL_TEAM_ID": settings.VERCEL_TEAM_ID or "",
            "VERCEL_PROJECT_ID": settings.VERCEL_PROJECT_ID or "",
            "VERCEL_TOKEN": settings.VERCEL_TOKEN or "",
        })
        self._process = await asyncio.create_subprocess_exec(
            self.node_binary,
            str(bridge),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        response = await self._request({
            "type": "start",
            "allowedDomains": self.allowed_domains,
            "timeoutMs": self.timeout_seconds * 1000,
            "vcpus": self.vcpus,
        }, timeout_seconds=min(self.timeout_seconds, 60))
        self.sandbox_id = response.get("sandboxId")

    async def execute(self, action: str, params: dict, *, approved: bool = False) -> BrowserActionResult:
        if action == "navigate":
            await validate_public_target(params.get("url", ""), self.allowed_domains)
        if action in {"click", "fill", "press", "submit"}:
            selector = params.get("selector", "")
            if not selector or len(selector) > 500:
                raise ValueError("A bounded CSS selector is required")
        response = await self._request({
            "type": "execute",
            "action": action,
            "params": params,
            "approved": approved,
        })
        if response.get("approval_required"):
            raise ApprovalRequired(response["approval_required"])
        url = response.get("url") or "about:blank"
        if url != "about:blank":
            await validate_public_target(url, self.allowed_domains)
        artifact = response.get("artifact_base64")
        return BrowserActionResult(
            url=url,
            title=response.get("title") or "",
            data=response.get("data") or {},
            artifact_bytes=base64.b64decode(artifact, validate=True) if artifact else None,
            artifact_kind=response.get("artifact_kind"),
            artifact_content_type=response.get("artifact_content_type"),
        )

    async def close(self) -> None:
        if self._process is None:
            return
        try:
            await self._request({"type": "close"}, timeout_seconds=20)
        except Exception:
            pass
        if self._process.returncode is None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None


def create_browser_session(*, provider: str, allowed_domains: list[str], timeout_seconds: int) -> BrowserSession:
    if provider == "local":
        return LocalPatchrightSession(allowed_domains=allowed_domains, timeout_seconds=timeout_seconds)
    if provider == "vercel":
        settings = get_settings()
        return VercelSandboxSession(
            allowed_domains=allowed_domains,
            timeout_seconds=timeout_seconds,
            node_binary=settings.BROWSER_VERCEL_NODE_BINARY,
            vcpus=settings.BROWSER_VERCEL_VCPUS,
        )
    raise RuntimeError(f"Browser provider '{provider}' is not configured")
