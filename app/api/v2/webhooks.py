"""
CrabRes Webhook Receiver — Agent 的耳朵

接收外部平台的事件推送，转化为 EventBus 事件：
- GitHub: star, issue, PR, release
- Stripe/支付: payment_succeeded, subscription
- 自定义: 任意 JSON payload

这是 Agent "感知真实世界" 的关键入口。
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Request, Header, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.security import require_admin

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
):
    """
    GitHub Webhook 接收器

    接收事件：star, issues, pull_request, release, push
    转化为 EventBus 事件供 Daemon 消费
    """
    body = await request.body()
    if not settings.GITHUB_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="GitHub webhook is not configured")
    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="Missing GitHub signature")
    expected = "sha256=" + hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = x_github_event or "unknown"
    action = payload.get("action", "")

    # 提取关键信息
    event_data = {
        "platform": "github",
        "event": event_type,
        "action": action,
        "timestamp": time.time(),
    }

    if event_type == "star":
        event_data.update({
            "user": payload.get("sender", {}).get("login", ""),
            "repo": payload.get("repository", {}).get("full_name", ""),
            "stars": payload.get("repository", {}).get("stargazers_count", 0),
        })
        logger.info(f"⭐ GitHub star from {event_data['user']} on {event_data['repo']}")

    elif event_type == "issues":
        issue = payload.get("issue", {})
        event_data.update({
            "title": issue.get("title", ""),
            "url": issue.get("html_url", ""),
            "user": issue.get("user", {}).get("login", ""),
            "labels": [l.get("name") for l in issue.get("labels", [])],
        })

    elif event_type == "pull_request":
        pr = payload.get("pull_request", {})
        event_data.update({
            "title": pr.get("title", ""),
            "url": pr.get("html_url", ""),
            "user": pr.get("user", {}).get("login", ""),
            "merged": pr.get("merged", False),
        })

    elif event_type == "release":
        release = payload.get("release", {})
        event_data.update({
            "tag": release.get("tag_name", ""),
            "name": release.get("name", ""),
            "url": release.get("html_url", ""),
            "prerelease": release.get("prerelease", False),
        })

    # 发布到 EventBus
    from app.agent.events import get_event_bus
    bus = await get_event_bus()
    await bus.publish(f"webhook.github.{event_type}", event_data)

    return {"status": "received", "event": event_type, "action": action}


@router.post("/generic")
async def generic_webhook(
    request: Request,
    x_webhook_token: Optional[str] = Header(None),
):
    """
    通用 Webhook 接收器

    接收任意 JSON payload，转化为 EventBus 事件。
    用途：Zapier、IFTTT、自定义集成。

    POST /api/webhooks/generic
    Body: {"source": "zapier", "event": "new_signup", "data": {...}}
    """
    if not settings.GENERIC_WEBHOOK_TOKEN:
        raise HTTPException(status_code=503, detail="Generic webhook is not configured")
    if not x_webhook_token or not hmac.compare_digest(
        x_webhook_token, settings.GENERIC_WEBHOOK_TOKEN
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    source = payload.get("source", "unknown")
    event = payload.get("event", "generic")
    data = payload.get("data", payload)

    event_data = {
        "platform": source,
        "event": event,
        "data": data,
        "timestamp": time.time(),
        "ip": request.client.host if request.client else "unknown",
    }

    from app.agent.events import get_event_bus
    bus = await get_event_bus()
    await bus.publish(f"webhook.{source}.{event}", event_data)

    logger.info(f"📨 Generic webhook: {source}/{event}")
    return {"status": "received", "source": source, "event": event}


@router.get("/events")
async def get_events(
    event_type: Optional[str] = None,
    limit: int = 20,
    _admin: dict = Depends(require_admin),
):
    """
    获取最近的 Webhook 事件（调试用）

    GET /api/webhooks/events?event_type=webhook.github&limit=10
    """
    from app.agent.events import get_event_bus
    bus = await get_event_bus()
    events = bus.get_recent_events(event_type=event_type, limit=limit)
    return {"events": events, "count": len(events)}


@router.get("/events/stream")
async def event_stream(
    request: Request,
    event_type: str = "*",
    _admin: dict = Depends(require_admin),
):
    """
    SSE 事件流 — 前端实时接收所有事件

    GET /api/webhooks/events/stream?event_type=*
    """
    from starlette.responses import StreamingResponse
    from app.agent.events import get_event_bus

    bus = await get_event_bus()

    async def generate():
        async for event in bus.subscribe(event_type):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
