"""Regression tests for tenant and external-input security boundaries."""

import hashlib
import hmac
from pathlib import Path

import pytest
import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v2 import daemon, execution, share, webhooks, workspace
from app.core import security
from app.core.security import create_access_token


@pytest.fixture
def client():
    app = FastAPI()
    for router in (
        execution.router,
        workspace.router,
        share.router,
        webhooks.router,
        daemon.router,
    ):
        app.include_router(router, prefix="/api")
    return TestClient(app)


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


def test_execution_requires_user_token(client):
    assert client.get("/api/execution/pending").status_code == 401


def test_execution_state_is_tenant_scoped(client, tmp_path, monkeypatch):
    monkeypatch.setattr(execution, "_tenant_root", lambda uid: tmp_path / str(uid))

    response = client.post(
        "/api/execution/auto-rule",
        headers=_auth(1),
        json={"action_type": "send_email", "auto_approve": True},
    )
    assert response.status_code == 200
    assert client.get("/api/execution/auto-rules", headers=_auth(1)).json()["rules"] == {
        "send_email": True
    }
    assert client.get("/api/execution/auto-rules", headers=_auth(2)).json()["rules"] == {}


def test_workspace_only_lists_current_tenant(client, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(workspace, "WORKSPACE_FALLBACK_ROOT", None)
    (tmp_path / "1" / "workspace").mkdir(parents=True)
    (tmp_path / "2" / "workspace").mkdir(parents=True)
    (tmp_path / "1" / "workspace" / "mine.md").write_text("mine")
    (tmp_path / "2" / "workspace" / "theirs.md").write_text("theirs")

    first = client.get("/api/workspace/files", headers=_auth(1)).json()["files"]
    second = client.get("/api/workspace/files", headers=_auth(2)).json()["files"]
    assert [item["name"] for item in first] == ["mine.md"]
    assert [item["name"] for item in second] == ["theirs.md"]
    assert client.get(
        "/api/workspace/files/read", params={"path": "../../2/workspace/theirs.md"}, headers=_auth(1)
    ).status_code == 403


def test_share_card_requires_matching_signed_token(client):
    token = create_access_token({"user_id": 1, "scope": "share_card"})
    assert client.get("/api/share/card/1", params={"token": token}).status_code == 200
    assert client.get("/api/share/card/2", params={"token": token}).status_code == 403
    assert client.get("/api/share/card/1").status_code == 422


def test_oauth_state_is_provider_bound():
    from app.api.v2.oauth import _oauth_state, _verify_oauth_state
    from fastapi import HTTPException

    state = _oauth_state("google")
    _verify_oauth_state(state, "google")
    with pytest.raises(HTTPException):
        _verify_oauth_state(state, "github")


def test_github_webhook_rejects_bad_signature(client, monkeypatch):
    secret = "test-webhook-secret"
    monkeypatch.setattr(webhooks.settings, "GITHUB_WEBHOOK_SECRET", secret)
    body = b'{"action":"created"}'
    valid = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert client.post("/api/webhooks/github", content=body).status_code == 401
    assert client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "star"},
    ).status_code == 401
    assert client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": valid, "X-GitHub-Event": "star"},
    ).status_code == 200


def test_operational_endpoints_require_dedicated_admin_key(client, monkeypatch):
    monkeypatch.setattr(security.settings, "ADMIN_API_KEY", "admin-secret")
    assert client.get("/api/daemon/status", headers=_auth(1)).status_code == 403
    response = client.get("/api/daemon/status", headers={"X-Admin-Key": "admin-secret"})
    assert response.status_code == 200
    assert response.json()["running"] is False


def test_domain_allowlist_does_not_accept_suffix_attack(monkeypatch):
    monkeypatch.setattr(security.settings, "ALLOWED_SCRAPE_DOMAINS", ["example.com"])
    assert security.validate_domain("https://example.com/page")
    assert security.validate_domain("https://docs.example.com/page")
    assert not security.validate_domain("https://evilexample.com/page")


def test_real_world_execution_is_disabled_by_default():
    from app.agent.engine.execution import ExecutionEngine, ExecutionRequest

    result = asyncio.run(ExecutionEngine().execute(ExecutionRequest(
        action_type="send_email",
        platform="email",
        description="must not send",
        params={"to": "nobody@example.test", "subject": "test", "body": "test"},
    )))
    assert result.status == "disabled"
    assert result.success is False
