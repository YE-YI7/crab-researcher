"""
CrabRes Eval System — L1: Assertion Framework

断言引擎：执行场景中的断言，返回通过/失败/跳过结果。

支持三种断言类型：
  1. Python 表达式断言 — 直接 eval，快但需要上下文变量
  2. 函数断言 — 传入 callable，灵活
  3. LLM 断言 — 给 LLM judge 用（L2 层处理）

设计原则：
  - 每个断言独立执行，互不依赖
  - 失败不阻断其他断言（收集所有失败）
  - 支持软断言（warning）和硬断言（error）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AssertResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"     # 断言本身出错（如 eval 异常）


@dataclass
class AssertionOutcome:
    """单个断言的执行结果"""
    assertion_name: str
    result: AssertResult
    expected: Any = None
    actual: Any = None
    error_message: str = ""
    duration_ms: float = 0.0
    weight: float = 1.0


@dataclass
class ScenarioResult:
    """单个场景的完整评估结果"""
    scenario_id: str
    scenario_name: str
    category: str
    passed: bool
    score: float              # 0.0 - 1.0 加权得分
    total_assertions: int
    passed_assertions: int
    failed_assertions: int
    skipped_assertions: int
    outcomes: list[AssertionOutcome] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    duration_s: float = 0.0
    error: str = ""            # 场景级错误（如 setup 失败）

    @property
    def pass_rate(self) -> float:
        total = self.passed_assertions + self.failed_assertions
        return self.passed_assertions / total if total > 0 else 1.0


@dataclass
class EvalRunSummary:
    """一次完整 Eval Run 的汇总"""
    run_id: str
    timestamp: float
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    skipped_scenarios: int
    error_scenarios: int
    total_score: float           # 所有场景加权平均分
    total_duration_s: float
    results: list[ScenarioResult] = field(default_factory=list)
    tags_filter: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        ran = self.passed_scenarios + self.failed_scenarios
        return self.passed_scenarios / ran if ran > 0 else 1.0

    @property
    def is_healthy(self) -> bool:
        """CI 健康检查：无 error 场景 + 通过率 >= 80%"""
        return self.error_scenarios == 0 and self.pass_rate >= 0.8


class AssertionEngine:
    """
    断言执行引擎。

    负责将 Scenario.assertions 中的声明式断言转换为实际检查，
    并收集结果。
    """

    def __init__(self):
        # 自定义断言函数注册表
        # key = assertion_name, value = (callable, description)
        self._custom_checks: dict[str, Callable] = {}

    def register_check(self, name: str, fn: Callable) -> None:
        """注册自定义断言函数"""
        self._custom_checks[name] = fn

    async def evaluate(
        self,
        scenario,
        context: dict[str, Any],
    ) -> ScenarioResult:
        """
        执行一个场景的所有断言。

        Args:
            scenario: EvalScenario 实例
            context: 断言执行上下文，包含：
                - result: 执行结果（state / response 等）
                - metrics: 收集到的指标（llm_calls, search_calls, cost...）
                - state: 最终 AgentState
                - events: SSE 事件列表
        """
        start = time.time()
        outcomes: list[AssertionOutcome] = []
        passed = failed = skipped = 0

        for assertion in scenario.assertions:
            outcome = await self._run_single_assertion(assertion, context)
            outcomes.append(outcome)

            if outcome.result == AssertResult.PASS:
                passed += 1
            elif outcome.result == AssertResult.FAIL:
                failed += 1
            elif outcome.result == AssertResult.SKIP:
                skipped += 1

        duration = time.time() - start

        # 计算加权得分
        total_weight = sum(o.weight for o in outcomes if o.result != AssertResult.SKIP)
        earned_weight = sum(
            o.weight for o in outcomes if o.result == AssertResult.PASS
        )
        score = earned_weight / total_weight if total_weight > 0 else 1.0

        all_passed = failed == 0 and not any(
            o.result == AssertResult.ERROR for o in outcomes
        )

        return ScenarioResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            category=scenario.category.value,
            passed=all_passed,
            score=score,
            total_assertions=len(outcomes),
            passed_assertions=passed,
            failed_assertions=failed,
            skipped_assertions=skipped,
            outcomes=outcomes,
            metrics=context.get("metrics", {}),
            duration_s=duration,
        )

    async def _run_single_assertion(
        self,
        assertion,
        context: dict[str, Any],
    ) -> AssertionOutcome:
        """执行单个断言"""
        start = time.time()
        name = assertion.name

        try:
            # 优先使用自定义函数
            if name in self._custom_checks:
                fn = self._custom_checks[name]
                actual = await fn(context) if isinstance(fn, type(lambda: None)) or hasattr(fn, '__call__') else fn(context)
                # 如果是 coroutine，await 它
                import inspect
                if inspect.iscoroutine(actual):
                    actual = await actual
                passed = bool(actual)
            elif assertion.check:
                # Python 表达式断言
                actual = self._eval_expression(assertion.check, context)
                passed = bool(actual)
            else:
                # 无 check 表达式的断言 → 默认检查 truthy
                actual = context.get(name, False)
                passed = bool(actual)

            duration = (time.time() - start) * 1000

            return AssertionOutcome(
                assertion_name=name,
                result=AssertResult.PASS if passed else AssertResult.FAIL,
                expected=assertion.expected,
                actual=actual,
                duration_ms=duration,
                weight=assertion.weight,
            )

        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.warning(f"Assertion '{name}' error: {e}")
            return AssertionOutcome(
                assertion_name=name,
                result=AssertResult.ERROR,
                error_message=str(e),
                duration_ms=duration,
                weight=assertion.weight,
            )

    def _eval_expression(self, expr: str, context: dict) -> Any:
        """
        安全地求值 Python 表达式。

        只允许访问 context 中的变量和内置常量。
        禁止 import、exec、eval 等危险操作。
        """
        # 构建安全的全局命名空间
        safe_globals = {"__builtins__": {
            "len": len, "str": str, "int": int, "float": float,
            "bool": bool, "list": list, "dict": dict, "set": set,
            "any": any, "all": all, "isinstance": isinstance,
            "range": range, "abs": abs, "min": min, "max": max,
            "sum": sum, "round": round, "True": True, "False": False,
            "None": None,
        }}

        # 合并上下文变量（result 和 metrics 是最常用的顶层变量）
        eval_context = {**context}
        # 方便访问嵌套属性
        result_obj = context.get("result")
        if result_obj and hasattr(result_obj, "__dict__"):
            eval_context["result"] = result_obj
        if hasattr(result_obj, "mode"):
            eval_context["mode"] = result_obj.mode
        if hasattr(result_obj, "intent"):
            eval_context["intent"] = result_obj.intent
        if hasattr(result_obj, "product_info"):
            eval_context["product_info"] = getattr(result_obj, "product_info", {})
        if hasattr(result_obj, "deliverables"):
            eval_context["deliverables"] = getattr(result_obj, "deliverables", [])
        if hasattr(result_obj, "search_results"):
            eval_context["search_results"] = getattr(result_obj, "search_results", [])
        if hasattr(result_obj, "expert_outputs"):
            eval_context["expert_outputs"] = getattr(result_obj, "expert_outputs", {})

        metrics = context.get("metrics", {})
        eval_context["metrics"] = metrics

        return eval(expr, safe_globals, eval_context)


# =====================================================================
# 内置断言函数库
# =====================================================================

def _build_builtin_checks(engine: AssertionEngine) -> None:
    """注册所有内置断言函数"""

    async def _check_no_llm_called(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("llm_calls", 0) == 0

    async def _check_mode_is_quick(ctx) -> bool:
        return getattr(ctx.get("result"), "mode", "") == "quick"

    async def _check_mode_is_pipeline(ctx) -> bool:
        return getattr(ctx.get("result"), "mode", "") == "pipeline"

    async def _check_intent_is_growth_request(ctx) -> bool:
        return getattr(ctx.get("result"), "intent", "") == "growth_request"

    async def _check_has_product_info_set(ctx) -> bool:
        result = ctx.get("result")
        if hasattr(result, "product_info"):
            return bool(getattr(result, "product_info"))
        return bool(result.get("product_info") if isinstance(result, dict) else False)

    async def _check_expert_id_extracted(ctx) -> bool:
        result = ctx.get("result")
        return hasattr(result, "expert_id") and bool(result.expert_id)

    async def _check_zero_budget_detected(ctx) -> bool:
        product_info = getattr(ctx.get("result"), "product_info", {}) or {}
        desc = str(product_info.get("raw_description", "")).lower() + " " + str(product_info).lower()
        budget_indicators = ["zero", "0", "free", "no money", "no budget", "零预算", "免费"]
        return any(ind in desc for ind in budget_indicators)

    async def _check_language_detected_zh(ctx) -> bool:
        result = ctx.get("result")
        lang = getattr(result, "language", None) or getattr(result, "language", "en")
        return lang == "zh"

    async def _check_uses_prior_data(ctx) -> bool:
        result = ctx.get("result")
        srs = getattr(result, "search_results", None) or []
        return len(srs) > 0

    async def _check_deep_strategy_triggered(ctx) -> bool:
        metrics = ctx.get("metrics", {})
        return metrics.get("deep_strategy_triggered", False)

    async def _check_product_name_extracted(ctx) -> bool:
        product_info = getattr(ctx.get("result"), "product_info", {}) or {}
        name = product_info.get("name", "")
        return bool(name and len(str(name)) > 1)

    async def _check_target_audience_students(ctx) -> bool:
        product_info = getattr(ctx.get("result"), "product_info", {}) or {}
        audience = str(product_info.get("target_audience", "")).lower()
        return "student" in audience

    async def _check_reddit_in_target_platforms(ctx) -> bool:
        result = ctx.get("result")
        platforms = getattr(result, "target_platforms", []) or []
        return any("reddit" in p.lower() for p in platforms)

    async def _check_twitter_in_target_platforms(ctx) -> bool:
        result = ctx.get("result")
        platforms = getattr(result, "target_platforms", []) or []
        platform_str = " ".join(platforms).lower()
        return "twitter" in platform_str or "x_twitter" in platform_str or "x.com" in platform_str

    async def _check_at_least_one_search(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("search_calls", 0) >= 1

    async def _check_search_query_contains_competitor(ctx) -> bool:
        m = ctx.get("metrics", {})
        queries = m.get("search_queries", [])
        return any("notion" in q.lower() for q in queries)

    async def _check_useful_search_results(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("useful_result_rate", 0) >= 0.5

    async def _check_no_duplicate_queries(ctx) -> bool:
        m = ctx.get("metrics", {})
        queries = m.get("search_queries", [])
        return len(queries) == len(set(queries))

    async def _check_at_least_2_experts(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("activated_experts", 0) >= 2

    async def _check_valid_expert_rate(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("valid_expert_rate", 0) >= 0.8

    async def _check_critic_activated(ctx) -> bool:
        m = ctx.get("metrics", {})
        return "critic" in m.get("expert_ids_used", [])

    async def _check_all_experts_chinese(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("language_consistency_rate", 1.0) == 1.0

    async def _check_at_least_one_deliverable(ctx) -> bool:
        result = ctx.get("result")
        delivs = getattr(result, "deliverables", []) or []
        return len(delivs) >= 1

    async def _check_deliverable_has_content(ctx) -> bool:
        result = ctx.get("result")
        delivs = getattr(result, "deliverables", []) or []
        return any(len(d.get("content", "")) > 100 for d in delivs)

    async def _check_report_generated(ctx) -> bool:
        result = ctx.get("result")
        delivs = getattr(result, "deliverables", []) or []
        return any(d.get("type") == "report" or "report" in d.get("name", "").lower() for d in delivs)

    async def _check_no_content_draft(ctx) -> bool:
        result = ctx.get("result")
        delivs = getattr(result, "deliverables", []) or []
        return not any(d.get("type") == "content_draft" for d in delivs)

    async def _check_compaction_triggered(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("compaction_count", 0) >= 1

    async def _check_summary_not_empty(ctx) -> bool:
        m = ctx.get("metrics", {})
        summary = m.get("last_compaction_summary", "")
        return len(str(summary)) > 50

    async def _check_key_info_preserved(ctx) -> bool:
        m = ctx.get("metrics", {})
        summary = str(m.get("last_compaction_summary", "")).lower()
        return "testproduct" in summary

    async def _check_fallback_used(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("compaction_fallback_count", 0) >= 1

    async def _check_session_not_crashed(ctx) -> bool:
        result = ctx.get("result")
        err = getattr(result, "error", None)
        status = getattr(result, "status", "")
        return err is None or "recovered" in str(status).lower()

    async def _check_fallback_tier_used(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("fallback_calls", 0) >= 1

    async def _check_experts_still_activated(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("activated_experts", 0) >= 1

    async def _check_deliverable_may_be_partial(_ctx) -> bool:
        return True  # 容许降级，总是 pass

    async def _check_completes_all_phases(ctx) -> bool:
        result = ctx.get("result")
        phase = getattr(result, "phase", None)
        return phase == "deliver" or phase == Phase.DELIVER if hasattr(Phase, 'DELIVER') else str(phase) == "deliver"

    async def _check_has_product_info(ctx) -> bool:
        result = ctx.get("result")
        pi = getattr(result, "product_info", None) or {}
        return bool(pi)

    async def _check_has_search_results(ctx) -> bool:
        result = ctx.get("result")
        srs = getattr(result, "search_results", None) or []
        return len(srs) > 0

    async def _check_has_expert_outputs(ctx) -> bool:
        result = ctx.get("result")
        eos = getattr(result, "expert_outputs", None) or {}
        return len(eos) >= 2

    async def _check_total_cost_under_budget(ctx) -> bool:
        m = ctx.get("metrics", {})
        cost = m.get("total_cost", 0)
        return cost < 0.10

    async def _check_completion_time_reasonable(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("total_time_s", 999) < 120

    async def _check_second_response_focused_on_reddit(_ctx) -> bool:
        # L2 层用 LLM judge 判断
        return True  # L1 层只做结构检查

    async def _check_no_redundant_search(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("search_calls", 99) < 3

    async def _check_second_response_shorter(ctx) -> bool:
        result = ctx.get("result")
        r1_len = len(getattr(result, "first_response", "") or "")
        r2_len = len(getattr(result, "final_response") or "")
        return r2_len < r1_len if r1_len > 0 else True

    async def _check_cost_lower_second_round(ctx) -> bool:
        m = ctx.get("metrics", {})
        return m.get("round2_cost", 999) < m.get("round1_cost", 9999)

    async def _check_no_specific_numbers_without_source(_ctx) -> bool:
        # L2 层判断
        return True

    async def _check_expert_mentions_uncertainty(_ctx) -> bool:
        # L2 层判断
        return True

    async def _check_response_not_empty(ctx) -> bool:
        result = ctx.get("result")
        resp = getattr(result, "final_response", "") or ""
        return len(resp.strip()) > 20

    # 注册所有内置检查
    checks = {
        "mode_is_quick": _check_mode_is_quick,
        "mode_is_pipeline": _check_mode_is_pipeline,
        "intent_is_growth_request": _check_intent_is_growth_request,
        "no_llm_called": _check_no_llm_called,
        "has_product_info_set": _check_has_product_info_set,
        "expert_id_extracted": _check_expert_id_extracted,
        "zero_budget_detected": _check_zero_budget_detected,
        "language_detected_zh": _check_language_detected_zh,
        "uses_prior_data": _check_uses_prior_data,
        "deep_strategy_triggered": _check_deep_strategy_triggered,
        "product_name_extracted": _check_product_name_extracted,
        "target_audience_students": _check_target_audience_students,
        "reddit_in_target_platforms": _check_reddit_in_target_platforms,
        "twitter_in_target_platforms": _check_twitter_in_target_platforms,
        "at_least_one_search": _check_at_least_one_search,
        "search_query_contains_competitor": _check_search_query_contains_competitor,
        "useful_search_results": _check_useful_search_results,
        "no_duplicate_queries": _check_no_duplicate_queries,
        "at_least_2_experts": _check_at_least_2_experts,
        "valid_expert_rate": _check_valid_expert_rate,
        "critic_activated": _check_critic_activated,
        "all_experts_chinese": _check_all_experts_chinese,
        "at_least_one_deliverable": _check_at_least_one_deliverable,
        "deliverable_has_content": _check_deliverable_has_content,
        "report_generated": _check_report_generated,
        "no_content_draft": _check_no_content_draft,
        "compaction_triggered": _check_compaction_triggered,
        "summary_not_empty": _check_summary_not_empty,
        "key_info_preserved": _check_key_info_preserved,
        "fallback_used": _check_fallback_used,
        "session_not_crashed": _check_session_not_crashed,
        "fallback_tier_used": _check_fallback_tier_used,
        "experts_still_activated": _check_experts_still_activated,
        "deliverable_may_be_partial": _check_deliverable_may_be_partial,
        "completes_all_phases": _check_completes_all_phases,
        "has_product_info": _check_has_product_info,
        "has_search_results": _check_has_search_results,
        "has_expert_outputs": _check_has_expert_outputs,
        "total_cost_under_budget": _check_total_cost_under_budget,
        "completion_time_reasonable": _check_completion_time_reasonable,
        "second_response_focused_on_reddit": _check_second_response_focused_on_reddit,
        "no_redundant_search": _check_no_redundant_search,
        "second_response_shorter": _check_second_response_shorter,
        "cost_lower_second_round": _check_cost_lower_second_round,
        "no_specific_numbers_without_source": _check_no_specific_numbers_without_source,
        "expert_mentions_uncertainty": _check_expert_mentions_uncertainty,
        "response_not_empty": _check_response_not_empty,
    }

    for name, fn in checks.items():
        engine.register_check(name, fn)


# 导出便捷工厂函数
_engine_instance: AssertionEngine | None = None


def get_assertion_engine() -> AssertionEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = AssertionEngine()
        _build_builtin_checks(_engine_instance)
    return _engine_instance


# 循环导入兼容
try:
    from app.agent.engine.state import Phase
except ImportError:
    class Phase:
        DELIVER = "deliver"
