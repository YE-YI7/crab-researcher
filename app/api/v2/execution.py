"""
CrabRes Execution API — 前端查看/控制 Agent 执行操作

端点：
- GET  /api/v2/execution/log        — 查看执行日志
- GET  /api/v2/execution/stats       — 执行统计
- GET  /api/v2/execution/pending     — 待审批操作列表
- POST /api/v2/execution/approve     — 批准操作
- POST /api/v2/execution/reject      — 拒绝操作
- POST /api/v2/execution/execute     — 手动触发执行
- GET  /api/v2/execution/actions     — 所有 action 记录
- POST /api/v2/execution/auto-rule   — 设置自动审批规则
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path

from app.core.security import require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/execution", tags=["execution"])


class ApprovalRequest(BaseModel):
    approval_id: str


class ManualExecuteRequest(BaseModel):
    action_type: str
    platform: str
    description: str = ""
    params: dict = Field(default_factory=dict)


class AutoRuleRequest(BaseModel):
    action_type: str
    auto_approve: bool


def _tenant_root(user_id: int) -> Path:
    return Path(".crabres/memory") / str(user_id)


def _get_autonomous(user_id: int):
    from app.agent.engine.autonomous import AutonomousEngine
    return AutonomousEngine(base_dir=_tenant_root(user_id) / "autonomous")


def _get_tracker(user_id: int):
    from app.agent.engine.action_tracker import ActionTracker
    return ActionTracker(base_dir=_tenant_root(user_id) / "actions")


def _get_exec_engine(user_id: int):
    from app.agent.engine.execution import ExecutionEngine
    from app.agent.engine.autonomous import AutonomousEngine
    from app.agent.engine.action_tracker import ActionTracker
    from app.agent.memory import GrowthMemory
    return ExecutionEngine(
        memory=GrowthMemory(base_dir=str(_tenant_root(user_id))),
        autonomous=AutonomousEngine(base_dir=_tenant_root(user_id) / "autonomous"),
        tracker=ActionTracker(base_dir=_tenant_root(user_id) / "actions"),
    )


@router.get("/log")
async def get_execution_log(limit: int = 50, current_user: dict = Depends(require_user)):
    """获取最近的执行日志"""
    engine = _get_exec_engine(current_user["user_id"])
    return {"log": engine.get_execution_log(limit)}


@router.get("/stats")
async def get_execution_stats(current_user: dict = Depends(require_user)):
    """获取执行统计"""
    user_id = current_user["user_id"]
    engine = _get_exec_engine(user_id)
    tracker = _get_tracker(user_id)
    return {
        "engine_stats": engine.get_stats(),
        "tracker_stats": tracker.get_stats(),
    }


@router.get("/pending")
async def get_pending_approvals(current_user: dict = Depends(require_user)):
    """获取待审批操作列表"""
    autonomous = _get_autonomous(current_user["user_id"])
    pending = autonomous.get_pending()
    return {
        "count": len(pending),
        "pending": [
            {
                "id": p.id,
                "action_type": p.action_type,
                "risk_level": p.risk_level,
                "description": p.description,
                "details": p.details,
                "created_at": p.created_at,
            }
            for p in pending
        ],
    }


@router.post("/approve")
async def approve_action(req: ApprovalRequest, current_user: dict = Depends(require_user)):
    """批准一个待审批操作并立即执行"""
    engine = _get_exec_engine(current_user["user_id"])
    try:
        result = await engine.execute_approved(req.approval_id)
        return {
            "status": result.status,
            "success": result.success,
            "platform": result.platform,
            "url": result.url,
            "details": result.details,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject")
async def reject_action(req: ApprovalRequest, current_user: dict = Depends(require_user)):
    """拒绝一个待审批操作"""
    autonomous = _get_autonomous(current_user["user_id"])
    action = autonomous.reject(req.approval_id)
    if not action:
        raise HTTPException(status_code=404, detail="Approval not found")
    return {"status": "rejected", "id": req.approval_id}


@router.post("/execute")
async def manual_execute(req: ManualExecuteRequest, current_user: dict = Depends(require_user)):
    """手动触发一个执行操作"""
    from app.agent.engine.execution import ExecutionEngine, ExecutionRequest

    engine = _get_exec_engine(current_user["user_id"])
    exec_req = ExecutionRequest(
        action_type=req.action_type,
        platform=req.platform,
        description=req.description,
        params=req.params,
        source="manual",
    )
    result = await engine.execute(exec_req)
    return {
        "status": result.status,
        "success": result.success,
        "platform": result.platform,
        "url": result.url,
        "action_id": result.action_id,
        "details": result.details,
        "error": result.error,
    }


@router.get("/actions")
async def get_all_actions(status: Optional[str] = None, current_user: dict = Depends(require_user)):
    """获取所有 action 记录"""
    from app.agent.engine.action_tracker import ActionStatus
    tracker = _get_tracker(current_user["user_id"])
    filter_status = ActionStatus(status) if status else None
    actions = tracker.get_all(filter_status)
    return {
        "count": len(actions),
        "actions": [a.to_dict() for a in actions[:100]],
    }


@router.post("/auto-rule")
async def set_auto_rule(req: AutoRuleRequest, current_user: dict = Depends(require_user)):
    """设置自动审批规则"""
    autonomous = _get_autonomous(current_user["user_id"])
    autonomous.set_auto_rule(req.action_type, req.auto_approve)
    return {
        "status": "updated",
        "action_type": req.action_type,
        "auto_approve": req.auto_approve,
        "all_rules": autonomous.get_auto_rules(),
    }


@router.get("/auto-rules")
async def get_auto_rules(current_user: dict = Depends(require_user)):
    """获取所有自动审批规则"""
    autonomous = _get_autonomous(current_user["user_id"])
    return {"rules": autonomous.get_auto_rules()}
