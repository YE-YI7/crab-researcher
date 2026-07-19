"""
CrabRes Notifications API — 前端获取 Agent 主动通知

端点：
- GET /notifications — 获取通知列表
- GET /notifications/unread — 获取未读通知
- POST /notifications/{id}/read — 标记已读
- POST /notifications/read-all — 全部已读
- GET /notifications/stream — SSE 实时推送
- GET /goals — 获取目标进度
- POST /goals — 设定目标
- GET /weekly-reports — 获取周报
- GET /autonomous/pending — 获取待确认操作
- POST /autonomous/{id}/approve — 批准操作
- POST /autonomous/{id}/reject — 拒绝操作
- POST /autonomous/rules — 设置自动批准规则
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Notifications & Goals"])


def _get_notifier(request: Request):
    return getattr(request.app.state, "notifier", None)


def _get_daemon(request: Request):
    return getattr(request.app.state, "growth_daemon", None)


# === Notifications ===

@router.get("/notifications")
async def list_notifications(
    request: Request,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    notifier = _get_notifier(request)
    if not notifier:
        return {"notifications": [], "error": "Notifier not initialized"}
    return {"notifications": notifier.get_all(limit)}


@router.get("/notifications/unread")
async def unread_notifications(
    request: Request,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    notifier = _get_notifier(request)
    if not notifier:
        return {"notifications": [], "count": 0}
    unread = notifier.get_unread(limit)
    return {"notifications": unread, "count": len(unread)}


@router.post("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    notifier = _get_notifier(request)
    if not notifier:
        raise HTTPException(503, "Notifier not initialized")
    notifier.mark_read(notification_id)
    return {"status": "read"}


@router.post("/notifications/read-all")
async def mark_all_read(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    notifier = _get_notifier(request)
    if not notifier:
        raise HTTPException(503, "Notifier not initialized")
    notifier.mark_all_read()
    return {"status": "all_read"}


@router.get("/notifications/stream")
async def notification_stream(request: Request):
    """SSE 实时推送通知"""
    notifier = _get_notifier(request)
    if not notifier:
        return {"error": "Notifier not initialized"}

    queue = asyncio.Queue()
    notifier.add_sse_subscriber(queue)

    async def event_generator():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield data
        except asyncio.TimeoutError:
            yield "event: heartbeat\ndata: {}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            notifier.remove_sse_subscriber(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# === Goals ===

class GoalInput(BaseModel):
    objective: str
    key_results: list[dict]


@router.get("/goals")
async def get_goals(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    try:
        from app.agent.engine.goal_tracker import GoalTracker
        daemon = _get_daemon(request)
        memory = daemon.memory if daemon else None
        tracker = GoalTracker(memory)
        return await tracker.check_progress()
    except Exception as e:
        return {"has_goal": False, "error": str(e)}


@router.post("/goals")
async def set_goal(
    body: GoalInput,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    try:
        from app.agent.engine.goal_tracker import GoalTracker
        daemon = _get_daemon(request)
        memory = daemon.memory if daemon else None
        tracker = GoalTracker(memory)
        goal = await tracker.set_goal(body.objective, body.key_results)
        return {"status": "created", "goal_id": goal.id}
    except Exception as e:
        raise HTTPException(500, str(e))


# === Weekly Reports ===

@router.get("/weekly-reports")
async def get_weekly_reports(
    request: Request,
    limit: int = 4,
    current_user: dict = Depends(get_current_user),
):
    try:
        from app.agent.engine.weekly_report import WeeklyReportGenerator
        daemon = _get_daemon(request)
        if not daemon:
            return {"reports": []}
        gen = WeeklyReportGenerator(daemon.memory, daemon.llm)
        reports = await gen.get_recent_reports(limit)
        return {"reports": reports}
    except Exception as e:
        return {"reports": [], "error": str(e)}


@router.post("/weekly-reports/generate")
async def generate_weekly_report(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    try:
        from app.agent.engine.weekly_report import WeeklyReportGenerator
        daemon = _get_daemon(request)
        if not daemon:
            raise HTTPException(503, "Daemon not initialized")
        gen = WeeklyReportGenerator(daemon.memory, daemon.llm)
        report = await gen.generate()
        return {"report": report}
    except Exception as e:
        raise HTTPException(500, str(e))


# === Autonomous Actions ===

@router.get("/autonomous/pending")
async def get_pending_actions(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    try:
        from app.agent.engine.autonomous import AutonomousEngine
        engine = AutonomousEngine()
        pending = engine.get_pending()
        return {
            "pending": [
                {"id": a.id, "type": a.action_type, "risk": a.risk_level,
                 "description": a.description, "created_at": a.created_at}
                for a in pending
            ],
            "auto_rules": engine.get_auto_rules(),
        }
    except Exception as e:
        return {"pending": [], "error": str(e)}


@router.post("/autonomous/{action_id}/approve")
async def approve_action(
    action_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    from app.agent.engine.autonomous import AutonomousEngine
    engine = AutonomousEngine()
    result = engine.approve(action_id)
    if not result:
        raise HTTPException(404, "Action not found")
    return {"status": "approved", "action_id": action_id}


@router.post("/autonomous/{action_id}/reject")
async def reject_action(
    action_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    from app.agent.engine.autonomous import AutonomousEngine
    engine = AutonomousEngine()
    result = engine.reject(action_id)
    if not result:
        raise HTTPException(404, "Action not found")
    return {"status": "rejected", "action_id": action_id}


class AutoRuleInput(BaseModel):
    action_type: str
    auto_approve: bool


@router.post("/autonomous/rules")
async def set_auto_rule(
    body: AutoRuleInput,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    from app.agent.engine.autonomous import AutonomousEngine
    engine = AutonomousEngine()
    engine.set_auto_rule(body.action_type, body.auto_approve)
    return {"status": "updated", "rules": engine.get_auto_rules()}
