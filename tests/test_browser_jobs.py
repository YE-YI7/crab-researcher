"""Security and lifecycle tests for browser sandbox jobs."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import undefer

import app.models  # noqa: F401
from app.api.v2 import browser_jobs
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models.browser import BrowserArtifact, BrowserJob, BrowserStep
from app.models.task import User
from app.services.browser_job_service import run_browser_job
from app.services.browser_provider import ApprovalRequired, BrowserActionResult, BrowserSession
import app.services.browser_provider as browser_provider
from app.services.browser_provider import VercelSandboxSession
from app.services.browser_safety import (
    UnsafeBrowserTarget,
    ValidatedTarget,
    domain_is_allowed,
    validate_public_target,
    validate_target_syntax,
)


class FakeBrowserSession(BrowserSession):
    def __init__(self):
        self.actions = []
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def execute(self, action: str, params: dict, *, approved: bool = False):
        self.actions.append((action, approved))
        if action == "submit" and not approved:
            raise ApprovalRequired("Final submission requires approval")
        if action == "extract":
            return BrowserActionResult(
                url="https://example.com/page",
                title="Example",
                data={"character_count": 12},
                artifact_bytes=b"Example text",
                artifact_kind="text",
                artifact_content_type="text/plain; charset=utf-8",
            )
        if action == "screenshot":
            return BrowserActionResult(
                url="https://example.com/page",
                title="Example",
                artifact_bytes=b"fake-png",
                artifact_kind="screenshot",
                artifact_content_type="image/png",
            )
        return BrowserActionResult(url=params.get("url", "https://example.com/page"), title="Example")

    async def close(self):
        self.closed = True


class FakeBridgeProcess:
    def __init__(self):
        self.responses = asyncio.Queue()
        self.messages = []
        self.returncode = None
        self.stdin = self.FakeStdin(self)
        self.stdout = self.FakeStdout(self)

    class FakeStdin:
        def __init__(self, process):
            self.process = process

        def write(self, data):
            message = json.loads(data)
            self.process.messages.append(message)
            if message["type"] == "start":
                response = {"ok": True, "sandboxId": "sbx_test"}
            elif message["type"] == "execute":
                response = {
                    "ok": True,
                    "url": "https://example.com/",
                    "title": "Example",
                    "data": {"character_count": 7},
                    "artifact_base64": base64.b64encode(b"example").decode(),
                    "artifact_kind": "text",
                    "artifact_content_type": "text/plain; charset=utf-8",
                }
            else:
                response = {"ok": True}
            self.process.responses.put_nowait((json.dumps(response) + "\n").encode())

        async def drain(self):
            return None

    class FakeStdout:
        def __init__(self, process):
            self.process = process

        async def readline(self):
            return await self.process.responses.get()

    async def wait(self):
        self.returncode = 0
        return 0

    def kill(self):
        self.returncode = -9


def test_browser_target_policy_blocks_private_networks():
    assert domain_is_allowed("docs.example.com", ["example.com"])
    assert not domain_is_allowed("evilexample.com", ["example.com"])
    with pytest.raises(UnsafeBrowserTarget):
        validate_target_syntax("http://example.com")
    with pytest.raises(UnsafeBrowserTarget):
        validate_target_syntax("https://127.0.0.1/admin")
    with pytest.raises(UnsafeBrowserTarget):
        validate_target_syntax("https://user:pass@example.com")

    def private_resolver(*args, **kwargs):
        return [(2, 1, 6, "", ("10.0.0.5", 443))]

    with pytest.raises(UnsafeBrowserTarget):
        asyncio.run(validate_public_target("https://example.com", resolver=private_resolver))


def test_vercel_provider_uses_bridge_and_decodes_artifacts(monkeypatch):
    process_holder = {}
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "test-oidc")
    monkeypatch.setattr(browser_provider, "get_settings", lambda: SimpleNamespace(
        VERCEL_SANDBOX_IMAGE="crab-browser:test",
        VERCEL_TOKEN=None,
        VERCEL_PROJECT_ID=None,
        VERCEL_TEAM_ID=None,
    ))

    async def create_process(*args, **kwargs):
        return process_holder["process"]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    async def scenario():
        process = FakeBridgeProcess()
        process_holder["process"] = process
        session = VercelSandboxSession(
            allowed_domains=["example.com"],
            timeout_seconds=90,
            node_binary="node",
            vcpus=1,
        )
        await session.start()
        assert session.sandbox_id == "sbx_test"
        result = await session.execute("extract", {"selector": "body"})
        assert result.artifact_bytes == b"example"
        assert result.url == "https://example.com/"
        await session.close()
        assert [message["type"] for message in process.messages] == ["start", "execute", "close"]

    asyncio.run(scenario())


def test_browser_job_pauses_for_submit_and_resumes(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'browser.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    from app.core.config import get_settings
    get_settings.cache_clear()

    async def scenario():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            user = User(company_name="Tenant", contact_email="browser@example.test", hashed_password="x")
            db.add(user)
            await db.flush()
            job = BrowserJob(
                user_id=user.id,
                start_url="https://example.com",
                allowed_domains=["example.com"],
            )
            job.steps = [
                BrowserStep(position=0, action="navigate", params={"url": "https://example.com"}),
                BrowserStep(position=1, action="extract", params={"selector": "body"}),
                BrowserStep(position=2, action="screenshot", params={}),
                BrowserStep(position=3, action="submit", params={"selector": "button"}, requires_approval=True),
            ]
            db.add(job)
            await db.commit()
            job_id = job.id

        first_session = FakeBrowserSession()
        assert await run_browser_job(job_id, session_factory=sessions, browser_session=first_session)
        assert first_session.closed
        async with sessions() as db:
            waiting = await db.get(BrowserJob, job_id)
            assert waiting.status == "awaiting_approval"
            assert waiting.current_step == 3
            artifacts = (await db.execute(
                select(BrowserArtifact)
                .where(BrowserArtifact.job_id == job_id)
                .options(undefer(BrowserArtifact.content))
            )).scalars().all()
            assert {item.kind for item in artifacts} == {"text", "screenshot"}
            assert {item.content for item in artifacts} == {b"Example text", b"fake-png"}
            step = (await db.execute(select(BrowserStep).where(
                BrowserStep.job_id == job_id,
                BrowserStep.position == 3,
            ))).scalar_one()
            step.approved_at = waiting.updated_at
            step.status = "pending"
            waiting.status = "queued"
            await db.commit()

        resumed_session = FakeBrowserSession()
        assert await run_browser_job(job_id, session_factory=sessions, browser_session=resumed_session)
        assert resumed_session.actions == [("navigate", True), ("submit", True)]
        async with sessions() as db:
            completed = await db.get(BrowserJob, job_id)
            assert completed.status == "completed"
            assert completed.result_summary["steps_completed"] == 4
            assert completed.result_summary["artifact_count"] == 2
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        get_settings.cache_clear()


def test_browser_jobs_api_is_tenant_scoped(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            user = User(company_name="Tenant", contact_email="api-browser@example.test", hashed_password="x")
            db.add(user)
            await db.commit()
            return user.id

    user_id = asyncio.run(setup())

    async def override_db():
        async with sessions() as db:
            yield db

    async def public_target(url: str, allowed_domains=None, **kwargs):
        return ValidatedTarget(url=url, hostname="example.com")

    monkeypatch.setattr(browser_jobs, "validate_public_target", public_target)
    monkeypatch.setattr(browser_jobs, "get_settings", lambda: SimpleNamespace(
        BROWSER_WORKER_ENABLED=True,
        BROWSER_PROVIDER="local",
        BROWSER_MAX_ACTIVE_JOBS_PER_USER=3,
        BROWSER_MAX_STEPS=20,
        BROWSER_RUN_INLINE=False,
    ))

    app = FastAPI()
    app.include_router(browser_jobs.router, prefix="/api")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {create_access_token({'user_id': user_id})}",
        "Idempotency-Key": "browser-request",
    }
    created = client.post("/api/browser-jobs", headers=headers, json={
        "start_url": "https://example.com",
        "goal": "Inspect the landing page",
    })
    assert created.status_code == 202
    job_id = created.json()["id"]
    duplicate = client.post("/api/browser-jobs", headers=headers, json={
        "start_url": "https://example.com",
        "goal": "Inspect the landing page",
    })
    assert duplicate.json()["id"] == job_id
    assert len(client.get("/api/browser-jobs", headers=headers).json()["items"]) == 1
    assert client.get(f"/api/browser-jobs/{job_id}", headers=headers).status_code == 200

    async def add_private_artifact():
        async with sessions() as db:
            artifact = BrowserArtifact(
                job_id=job_id,
                kind="screenshot",
                content_type="image/png",
                content=b"private-png",
                size_bytes=11,
            )
            db.add(artifact)
            await db.commit()
            return artifact.id

    artifact_id = asyncio.run(add_private_artifact())
    artifact_url = f"/api/browser-jobs/{job_id}/artifacts/{artifact_id}"
    artifact_response = client.get(artifact_url, headers=headers)
    assert artifact_response.status_code == 200
    assert artifact_response.content == b"private-png"
    assert artifact_response.headers["cache-control"] == "private, no-store"

    other_headers = {"Authorization": f"Bearer {create_access_token({'user_id': user_id + 1})}"}
    assert client.get(f"/api/browser-jobs/{job_id}", headers=other_headers).status_code == 404
    assert client.get(artifact_url, headers=other_headers).status_code == 404
    assert client.post(f"/api/browser-jobs/{job_id}/cancel", headers=other_headers).status_code == 404
    asyncio.run(engine.dispose())
