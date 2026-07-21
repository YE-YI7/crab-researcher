"""Browser RPC process executed inside one Vercel Sandbox microVM."""

import asyncio
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from patchright.async_api import async_playwright

LOOP = None
PAGE = None
PLAYWRIGHT = None
BROWSER = None
CONTEXT = None


async def identity():
    return PAGE.url, await PAGE.title()


async def unique(selector):
    if not selector or len(selector) > 500:
        raise ValueError("A bounded CSS selector is required")
    locator = PAGE.locator(selector)
    count = await locator.count()
    if count != 1:
        raise ValueError(f"Selector must match exactly one element; matched {count}")
    return locator


async def execute(payload):
    action = payload.get("action")
    params = payload.get("params") or {}
    approved = bool(payload.get("approved"))

    if action == "navigate":
        await PAGE.goto(params.get("url", ""), wait_until="domcontentloaded")
    elif action == "click":
        locator = await unique(params.get("selector", ""))
        element = await locator.evaluate(
            "el => ({tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(), inForm: !!el.closest('form')})"
        )
        if not approved and (element["inForm"] or element["tag"] == "button" or element["type"] in {"submit", "button"}):
            return {"approval_required": "Buttons and form controls require approval before clicking"}
        await locator.click()
    elif action == "fill":
        if not approved:
            return {"approval_required": "Typing into a website requires approval"}
        value = params.get("value", "")
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError("Fill value must be a string of at most 4000 characters")
        locator = await unique(params.get("selector", ""))
        input_type = (await locator.get_attribute("type") or "").lower()
        if input_type in {"password", "file"}:
            raise ValueError("Password and file inputs are not supported")
        await locator.fill(value)
    elif action == "press":
        key = params.get("key", "")
        if key not in {"Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter"}:
            raise ValueError("Unsupported key")
        if key == "Enter" and not approved:
            return {"approval_required": "Enter can submit a form and requires approval"}
        await (await unique(params.get("selector", ""))).press(key)
    elif action == "submit":
        if not approved:
            return {"approval_required": "Final submission requires approval"}
        await (await unique(params.get("selector", ""))).click()
    elif action == "extract":
        selector = params.get("selector") or "body"
        text = (await (await unique(selector)).inner_text())[:20_000]
        url, title = await identity()
        return {
            "url": url,
            "title": title,
            "data": {"selector": selector, "text_preview": text[:1000], "character_count": len(text)},
            "artifact_base64": base64.b64encode(text.encode()).decode(),
            "artifact_kind": "text",
            "artifact_content_type": "text/plain; charset=utf-8",
        }
    elif action == "screenshot":
        image = await PAGE.screenshot(full_page=False, type="png")
        url, title = await identity()
        return {
            "url": url,
            "title": title,
            "data": {"viewport": {"width": 1280, "height": 800}},
            "artifact_base64": base64.b64encode(image).decode(),
            "artifact_kind": "screenshot",
            "artifact_content_type": "image/png",
        }
    else:
        raise ValueError(f"Unsupported browser action: {action}")

    url, title = await identity()
    return {"url": url, "title": title, "data": {}}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_POST(self):
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100_000)
            payload = json.loads(self.rfile.read(length))
            result = asyncio.run_coroutine_threadsafe(execute(payload), LOOP).result(timeout=120)
            body = json.dumps({"ok": True, **result}).encode()
            status = 200
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)[:2000]}).encode()
            status = 400
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


async def main():
    global LOOP, PAGE, PLAYWRIGHT, BROWSER, CONTEXT
    LOOP = asyncio.get_running_loop()
    PLAYWRIGHT = await async_playwright().start()
    BROWSER = await PLAYWRIGHT.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--disable-gpu"])
    CONTEXT = await BROWSER.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=False)
    PAGE = await CONTEXT.new_page()
    server = ThreadingHTTPServer(("127.0.0.1", 4765), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        await asyncio.Event().wait()
    finally:
        server.shutdown()
        await CONTEXT.close()
        await BROWSER.close()
        await PLAYWRIGHT.stop()


asyncio.run(main())
