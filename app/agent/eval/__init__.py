"""
CrabRes Agent Evaluation System — 三层评估框架

L1: Unit Tests (单元测试)
  - scenarios.py — 28+ 评估场景定义（routing/understand/research/expert/deliver/compaction/error/e2e/regression）
  - assertions.py — 断言引擎（50+ 内置断言函数，支持 expression/custom/LLM 三种类型）
  - runner.py — Eval Runner（DRY/FULL 两种模式，CI 友好）
  - tests/eval/ — pytest 测试套件

L2: Model & Human Evaluation (模型+人工评估)
  - llm_judge.py — LLM-as-Judge（5 维度评分 + LLM-Human 一致性追踪）
  - traces.py — Trace Logging（20 种事件类型的会话轨迹记录与回放）
  - api/v2/eval_annotations.py — 人工标注 API

L3: A/B Test (A/B 测试)
  - ab_test.py — A/B Test 框架（创建/分组/分析/自动回滚/Welch's t-test）

基础设施:
  - collector.py — MetricsCollector（L1/L2 指标收集，JSONL 持久化）
  - api/v2/eval.py — Eval Summary & Health API
"""

from app.agent.eval.collector import MetricsCollector, get_collector
from app.agent.eval.scenarios import (
    EvalScenario, ScenarioCategory, Assertion,
    SCENARIO_REGISTRY, get_scenarios_by_tag, get_scenarios_by_category,
    get_critical_scenarios, get_active_scenarios,
)
from app.agent.eval.assertions import (
    AssertionEngine, AssertResult, AssertionOutcome,
    ScenarioResult, EvalRunSummary,
)
from app.agent.eval.runner import (
    EvalRunner, EvalMode, run_eval_dry, run_eval_full,
)
from app.agent.eval.llm_judge import (
    LLMJudge, JudgeResult, DimensionScore, ScoreDimension,
    ConsistencyTracker, HumanAnnotation,
)
from app.agent.eval.traces import (
    TraceCollector, TraceEvent, EventType, SessionSummary,
    get_tracer, clear_tracer,
)
from app.agent.eval.ab_test import (
    ABTestManager, ABTestConfig, ABTestResult, Observation,
    TestStatus,
)

__all__ = [
    # L1
    "MetricsCollector", "get_collector",
    "EvalScenario", "ScenarioCategory", "Assertion",
    "SCENARIO_REGISTRY", "get_active_scenarios", "get_critical_scenarios",
    "AssertionEngine", "ScenarioResult", "EvalRunSummary",
    "EvalRunner", "EvalMode", "run_eval_dry", "run_eval_full",

    # L2
    "LLMJudge", "JudgeResult", "DimensionScore", "ScoreDimension",
    "ConsistencyTracker", "HumanAnnotation",
    "TraceCollector", "TraceEvent", "EventType", "SessionSummary",
    "get_tracer", "clear_tracer",

    # L3
    "ABTestManager", "ABTestConfig", "ABTestResult", "Observation", "TestStatus",
]
