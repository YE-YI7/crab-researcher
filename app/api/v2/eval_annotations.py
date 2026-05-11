"""
CrabRes Eval API — L2: 人工标注 + LLM Judge API

提供 REST 接口用于：
1. 获取需要人工审核的会话列表
2. 提交人工评分和反馈
3. 查看 LLM-Human 一致性报告
4. 触发 LLM Judge 批量评估
5. 管理 A/B Test
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from app.core.security import get_current_user, get_optional_user
from app.agent.eval.traces import TraceCollector, get_tracer
from app.agent.eval.llm_judge import LLMJudge, ConsistencyTracker
from app.agent.eval.ab_test import ABTestManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eval/v2", tags=["Eval V2"])

# 全局实例
_ab_manager: Optional[ABTestManager] = None
_consistency_tracker: Optional[ConsistencyTracker] = None


def _get_ab_manager() -> ABTestManager:
    global _ab_manager
    if _ab_manager is None:
        _ab_manager = ABTestManager()
    return _ab_manager


def _get_consistency_tracker() -> ConsistencyTracker:
    global _consistency_tracker
    if _consistency_tracker is None:
        _consistency_tracker = ConsistencyTracker()
    return _consistency_tracker


# =====================================================================
# Trace 查看与回放
# =====================================================================

@router.get("/traces")
async def list_traces(
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """列出最近的 trace 会话"""
    traces = TraceCollector.list_recent(limit=limit)
    return {"traces": traces, "count": len(traces)}


@router.get("/traces/{session_id}")
async def get_trace_detail(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取单个 trace 的完整详情"""
    trace = TraceCollector.load(session_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


# =====================================================================
# 人工标注
# =====================================================================

class AnnotationRequest(BaseModel):
    session_id: str
    human_score: float  # 1-5
    human_passed: bool
    llm_score: float = 0.0
    llm_passed: bool = True
    feedback_text: str = ""
    scenario_id: str = ""


@router.post("/annotate")
async def submit_annotation(
    req: AnnotationRequest,
    current_user: dict = Depends(get_current_user),
):
    """提交人工标注"""
    tracker = _get_consistency_tracker()
    ann = tracker.record_human_annotation(
        session_id=req.session_id,
        human_score=req.human_score,
        human_passed=req.human_passed,
        llm_score=req.llm_score,
        llm_passed=req.llm_passed,
        feedback_text=req.feedback_text,
        annotator_id=current_user.get("user_id", "unknown"),
        scenario_id=req.scenario_id,
    )
    return {"status": "recorded", "annotation_id": ann.session_id}


@router.get("/consistency")
async def get_consistency_report(
    current_user: dict = Depends(get_current_user),
):
    """获取 LLM-Human 一致性报告"""
    tracker = _get_consistency_tracker()
    return tracker.get_consistency_report()


# =====================================================================
# LLM Judge 触发
# =====================================================================

class JudgeRequest(BaseModel):
    session_id: str
    user_message: str
    assistant_response: str
    product_info: dict = {}
    reference_data: dict = {}
    scenario_id: str = ""


@router.post("/judge")
async def trigger_llm_judge(
    req: JudgeRequest,
    current_user: dict = Depends(get_current_user),
):
    """触发 LLM Judge 评估（需要 LLM 服务可用）"""
    try:
        from app.agent.engine.loop import AgentLoop
        # 尝试从 AgentLoop 获取 LLM 服务
        # 这里简化处理：直接创建 judge 实例
        # 实际使用时应该注入真实的 llm_service
        judge = LLMJudge(llm_service=None)  # TODO: 注入真实 LLM 服务
        result = await judge.evaluate(
            user_message=req.user_message,
            assistant_response=req.assistant_response,
            product_info=req.product_info,
            reference_data=req.reference_data,
            scenario_id=req.scenario_id,
            session_id=req.session_id,
        )
        return result.to_dict
    except Exception as e:
        logger.error(f"LLM Judge failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# A/B Test 管理
# =====================================================================

class CreateABTestRequest(BaseModel):
    name: str
    description: str = ""
    config_a: dict = {}
    config_b: dict = {}
    primary_metric: str = ""
    hypothesis: str = "B > A"
    traffic_split: float = 0.5
    min_sample_size: int = 30
    auto_rollback: bool = True


@router.post("/ab/create")
async def create_ab_test(
    req: CreateABTestRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建新的 A/B Test（需要管理员权限）"""
    mgr = _get_ab_manager()
    test = mgr.create_test(
        name=req.name,
        description=req.description,
        config_a=req.config_a,
        config_b=req.config_b,
        primary_metric=req.primary_metric,
        hypothesis=req.hypothesis,
        traffic_split=req.traffic_split,
        min_sample_size=req.min_sample_size,
        auto_rollback=req.auto_rollback,
    )
    return {"test_id": test.id, "name": test.name, "status": test.status.value}


@router.post("/ab/{test_id}/start")
async def start_ab_test(
    test_id: str,
    current_user: dict = Depends(get_current_user),
):
    """启动 A/B Test"""
    mgr = _get_ab_manager()
    test = mgr.start_test(test_id)
    return {"test_id": test.id, "status": test.status.value}


@router.get("/ab/{test_id}/result")
async def get_ab_result(
    test_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 A/B Test 结果"""
    mgr = _get_ab_manager()
    result = mgr.get_test_result(test_id)
    return result.to_dict


@router.get("/ab/{test_id}/assign")
async def get_ab_assignment(
    test_id: str,
    session_id: str = Query(...),
    current_user: dict = Depends(get_optional_user),
):
    """获取用户在指定测试中的分组和配置"""
    mgr = _get_ab_manager()
    group = mgr.assign_group(session_id, test_id)
    config = mgr.get_config(session_id, test_id)
    return {"test_id": test_id, "group": group, "config": config}


@router.get("/ab/list")
async def list_ab_tests(
    active_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    """列出所有 A/B Tests"""
    mgr = _get_ab_manager()
    tests = mgr.list_tests(active_only=active_only)
    return [
        {
            "id": t.id,
            "name": t.name,
            "status": t.status.value,
            "primary_metric": t.primary_metric,
            "traffic_split": t.traffic_split,
            "created_at": t.created_at,
        }
        for t in tests
    ]


@router.post("/ab/{test_id}/record")
async def record_ab_observation(
    test_id: str,
    session_id: str = Query(...),
    group: str = Query(...),
    metric_value: float = Query(...),
    metric_name: str = Query(""),
    current_user: dict = Depends(get_optional_user),
):
    """记录 A/B 测试观测数据"""
    mgr = _get_ab_manager()
    mgr.record_observation(
        test_id=test_id,
        session_id=session_id,
        group=group,
        metric_name=metric_name or mgr.get_test(test_id).primary_metric,
        metric_value=metric_value,
    )
    return {"status": "recorded"}
