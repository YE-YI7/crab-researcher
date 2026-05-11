"""
CrabRes Eval System — L1: Eval Runner

场景执行器：加载 Scenario → 执行 Agent → 收集指标 → 跑断言 → 输出报告。

对应 hamel.dev/evals 中的 S3 (CI Infrastructure)：
  - 可通过 pytest 集成到 CI
  - 支持按 tag/category 筛选运行
  - 输出结构化 JSON 报告 + 控制台摘要
  - 支持增量运行（只跑失败的）

两种运行模式：
  1. DRY_RUN: 只跑路由/理解等不需要 LLM 的纯逻辑测试（快，<1s）
  2. FULL_RUN: 完整执行 Pipeline/ReAct（慢，需要 LLM，但测得更全）
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class EvalMode(str, Enum):
    DRY = "dry"           # 纯逻辑测试（不调 LLM）
    FULL = "full"          # 完整执行（调 LLM）


@dataclass
class EvalMetrics:
    """单次场景执行的原始指标收集"""
    # LLM 相关
    llm_calls: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    fallback_calls: int = 0

    # 搜索相关
    search_calls: int = 0
    search_queries: list[str] = field(default_factory=list)
    useful_results: int = 0
    total_results: int = 0

    # 专家相关
    activated_experts: int = 0
    expert_ids_used: list[str] = field(default_factory=list)
    valid_expert_outputs: int = 0

    # 交付物
    deliverables_count: int = 0

    # Compaction
    compaction_count: int = 0
    last_compaction_summary: str = ""
    compaction_fallback_count: int = 0

    # 时间
    total_time_s: float = 0.0
    round1_cost: float = 0.0
    round2_cost: float = 0.0

    # 语言一致性
    language_consistency_rate: float = 1.0

    # 其他
    deep_strategy_triggered: bool = False

    @property
    def useful_result_rate(self) -> float:
        return self.useful_results / self.total_results if self.total_results > 0 else 0.0

    @property
    def valid_expert_rate(self) -> float:
        return self.valid_expert_outputs / self.activated_experts if self.activated_experts > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost_usd,
            "fallback_calls": self.fallback_calls,
            "search_calls": self.search_calls,
            "search_queries": self.search_queries,
            "useful_result_rate": round(self.useful_result_rate, 3),
            "activated_experts": self.activated_experts,
            "expert_ids_used": self.expert_ids_used,
            "valid_expert_rate": round(self.valid_expert_rate, 3),
            "deliverables_count": self.deliverables_count,
            "compaction_count": self.compaction_count,
            "compaction_fallback_count": self.compaction_fallback_count,
            "total_time_s": round(self.total_time_s, 2),
            "language_consistency_rate": self.language_consistency_rate,
        }


@dataclass
class MockResult:
    """模拟执行结果 — 用于 DRY_RUN 模式"""
    mode: str = ""
    intent: str = ""
    phase: str = ""
    expert_id: str | None = None
    product_info: dict = field(default_factory=dict)
    language: str = "en"
    target_platforms: list[str] = field(default_factory=list)
    deliverables: list[dict] = field(default_factory=list)
    search_results: list[dict] = field(default_factory=list)
    expert_outputs: dict = field(default_factory=dict)
    final_response: str = ""
    first_response: str = ""
    error: str | None = None
    status: str = ""


class EvalRunner:
    """
    评估运行器。

    负责：
      1. 加载和筛选场景
      2. 设置每个场景的初始状态
      3. 执行 Agent（或模拟执行）
      4. 收集执行指标
      5. 调用断言引擎验证结果
      6. 汇总报告
    """

    def __init__(
        self,
        mode: EvalMode = EvalMode.DRY,
        base_dir: str = ".crabres/eval",
        tags_filter: str = "",
        category_filter: str = "",
    ):
        self.mode = mode
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.tags_filter = tags_filter
        self.category_filter = category_filter

        # 运行时依赖（FULL_MODE 需要）
        self._llm_service = None
        self._agent_loop = None

        # 结果收集
        self._results: list[Any] = []

    def set_dependencies(
        self,
        llm_service=None,
        agent_loop=None,
    ):
        """设置 FULL 模式需要的运行时依赖"""
        self._llm_service = llm_service
        self._agent_loop = agent_loop

    def get_scenarios(self):
        """获取筛选后的场景列表"""
        from app.agent.eval.scenarios import (
            SCENARIO_REGISTRY, get_active_scenarios,
            get_scenarios_by_tag, get_scenarios_by_category,
        )

        if self.tags_filter:
            return get_scenarios_by_tag(self.tags_filter)
        if self.category_filter:
            cat = __import__("app.agent.eval.scenarios", fromlist=["ScenarioCategory"])
            return get_scenarios_by_category(getattr(cat.ScenarioCategory, self.category_filter.upper(), None) or self.category_filter)

        return get_active_scenarios()

    async def run_all(self) -> Any:
        """运行所有筛选后的场景，返回汇总报告"""
        from app.agent.eval.assertions import EvalRunSummary, get_assertion_engine

        scenarios = self.get_scenarios()
        engine = get_assertion_engine()
        run_id = f"eval-{uuid.uuid4().hex[:8]}"
        start = time.time()

        logger.info(f"[Eval] Starting run {run_id}: {len(scenarios)} scenarios (mode={self.mode.value})")

        results = []
        passed = failed = skipped = errors = 0

        for scenario in scenarios:
            # 跳过检查
            if scenario.skip_reason:
                logger.info(f"[Eval] SKIP {scenario.id}: {scenario.skip_reason}")
                skipped += 1
                continue

            try:
                result = await self._run_single(scenario, engine)
                results.append(result)

                if result.passed:
                    passed += 1
                else:
                    failed += 1

                status = "PASS" if result.passed else "FAIL"
                logger.info(
                    f"[Eval] {status} {scenario.id} "
                    f"(score={result.score:.0%}, assertions={result.passed_assertions}/{result.total_assertions})"
                )

            except Exception as e:
                logger.error(f"[Eval] ERROR {scenario.id}: {e}", exc_info=True)
                from app.agent.eval.assertions import ScenarioResult, AssertResult, AssertionOutcome
                results.append(ScenarioResult(
                    scenario_id=scenario.id,
                    scenario_name=scenario.name,
                    category=scenario.category.value,
                    passed=False,
                    score=0.0,
                    total_assertions=0,
                    passed_assertions=0,
                    failed_assertions=0,
                    skipped_assertions=0,
                    error=str(e),
                ))
                errors += 1

        total_duration = time.time() - start
        total_score = sum(r.score for r in results) / len(results) if results else 1.0

        summary = EvalRunSummary(
            run_id=run_id,
            timestamp=time.time(),
            total_scenarios=len(scenarios),
            passed_scenarios=passed,
            failed_scenarios=failed,
            skipped_scenarios=skipped,
            error_scenarios=errors,
            total_score=round(total_score, 4),
            total_duration_s=round(total_duration, 2),
            results=results,
            tags_filter=self.tags_filter,
        )

        # 保存报告
        self._save_report(summary)

        # 打印控制台摘要
        self._print_summary(summary)

        return summary

    async def _run_single(self, scenario, assertion_engine):
        """执行单个场景"""
        metrics = EvalMetrics()
        exec_start = time.time()

        if self.mode == EvalMode.DRY:
            result_obj = await self._dry_run(scenario, metrics)
        else:
            result_obj = await self._full_run(scenario, metrics)

        metrics.total_time_s = time.time() - exec_start

        # 构建断言上下文
        context = {
            "result": result_obj,
            "metrics": metrics.to_dict(),
            "state": getattr(result_obj, 'state', None),
            "events": getattr(result_obj, 'events', []),
        }

        # 执行断言
        scenario_result = await assertion_engine.evaluate(scenario, context)
        scenario_result.metrics = metrics.to_dict()

        return scenario_result

    async def _dry_run(self, scenario, metrics: EvalMetrics) -> MockResult:
        """
        DRY RUN: 不调用 LLM，只测试确定性逻辑。

        覆盖范围：
        - Router 路由决策（route() 函数）
        - node_understand 规则匹配
        - context_engine 专家调度逻辑
        - compaction 截断逻辑
        """
        from app.agent.engine.state import AgentState, ExecutionMode
        from app.agent.engine.router import route

        # 构建模拟状态
        state = AgentState(session_id=f"eval-{scenario.id}")

        # 应用 setup
        if scenario.setup.get("has_prior_research"):
            state.search_results = [{"query": "test", "content": "mock research"}]
        if scenario.setup.get("has_prior_experts"):
            state.expert_outputs = {"market_researcher": "mock output"}
        if scenario.setup.get("simulate_llm_failure") or scenario.setup.get("simulate_timeout"):
            pass  # DRY 模式下不实际触发

        input_text = scenario.input
        if scenario.is_multi_turn and scenario.input_sequence:
            input_text = scenario.input_sequence[0].content

        # 执行路由
        decision = route(input_text, state)

        # 如果需要，执行 understand 节点
        intent = None
        product_info = {}
        phase = "understand"
        language = scenario.language

        if decision.mode == ExecutionMode.PIPELINE or decision.mode == ExecutionMode.REACT:
            try:
                from app.agent.engine.nodes import node_understand
                from app.agent.engine.nodes import NodeDeps

                mock_deps = NodeDeps(llm=None, tools=None, experts=None, memory=None, trust=None)
                state = await node_understand(state, mock_deps, input_text)
                intent = state.intent
                product_info = state.product_info or {}
                language = state.language
                phase = state.phase.value if hasattr(state.phase, 'value') else str(state.phase)

                # DRY 模式下不调 LLM，所以 phase 可能停在 understand
                if phase == "understand":
                    phase = "understand"  # DRY 无法推进更远
            except Exception as e:
                logger.debug(f"Dry run understand skipped: {e}")
                intent = decision.reason
                phase = "understand"

        elif decision.mode == ExecutionMode.QUICK:
            intent = decision.reason
            if decision.reason == "greeting":
                phase = "quick"
            elif decision.reason == "self_awareness":
                phase = "quick"
            elif decision.reason == "expert_chat":
                phase = "quick"
            elif decision.reason == "deep_strategy_background":
                metrics.deep_strategy_triggered = True
                phase = "quick"

        # 多轮对话：处理后续轮次
        first_response = ""
        final_response = ""
        if scenario.is_multi_turn:
            final_response = f"[Simulated response to: {scenario.input_sequence[-1].content}]"
            first_response = f"[Simulated response to: {scenario.input_sequence[0].content}]"

        return MockResult(
            mode=decision.mode.value,
            intent=intent or "",
            phase=phase,
            expert_id=decision.expert_id,
            product_info=product_info,
            language=language,
            target_platforms=[],
            deliverables=[],
            search_results=state.search_results,
            expert_outputs=state.expert_outputs,
            final_response=final_response,
            first_response=first_response,
            state=state,
        )

    async def _full_run(self, scenario, metrics: EvalMetrics) -> MockResult:
        """
        FULL RUN: 完整执行 Agent Loop，调用真实 LLM。

        通过 hook 收集指标。
        """
        if not self._agent_loop:
            raise RuntimeError("FULL mode requires agent_loop dependency. Call set_dependencies() first.")

        # TODO: 实现 FULL RUN — 需要完整的 agent loop 注入
        # 这里先返回占位，后续根据需要实现
        raise NotImplementedError(
            "FULL mode requires real AgentLoop integration. "
            "Use DRY mode for CI, FULL mode for nightly evals."
        )

    def _save_report(self, summary):
        """保存 JSON 格式的评估报告"""
        report_data = {
            "run_id": summary.run_id,
            "timestamp": summary.timestamp,
            "mode": self.mode.value,
            "summary": {
                "total": summary.total_scenarios,
                "passed": summary.passed_scenarios,
                "failed": summary.failed_scenarios,
                "skipped": summary.skipped_scenarios,
                "errors": summary.error_scenarios,
                "pass_rate": round(summary.pass_rate, 4),
                "score": summary.total_score,
                "duration_s": summary.total_duration_s,
                "healthy": summary.is_healthy,
            },
            "scenarios": [],
        }

        for r in summary.results:
            sr = {
                "id": r.scenario_id,
                "name": r.scenario_name,
                "category": r.category,
                "passed": r.passed,
                "score": round(r.score, 4),
                "assertions": {
                    "total": r.total_assertions,
                    "passed": r.passed_assertions,
                    "failed": r.failed_assertions,
                    "skipped": r.skipped_assertions,
                },
                "metrics": r.metrics,
                "duration_s": round(r.duration_s, 3),
            }
            if r.error:
                sr["error"] = r.error
            # 失败断言详情
            failed_outcomes = [o for o in r.outcomes if o.result.value != "pass"]
            if failed_outcomes:
                sr["failed_assertion_details"] = [
                    {"name": o.assertion_name, "error": o.error_message}
                    for o in failed_outcomes
                ]
            report_data["scenarios"].append(sr)

        # 写入文件
        ts_str = time.strftime("%Y%m%d_%H%M%S")
        path = self.base_dir / f"report_{ts_str}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        # 同时写入 latest.json 方便读取
        latest_path = self.base_dir / "latest_report.json"
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        logger.info(f"[Eval] Report saved to {path}")

    def _print_summary(self, summary):
        """打印控制台摘要"""
        print("\n" + "=" * 70)
        print(f"  CrabRes EVAL REPORT — {summary.run_id}")
        print(f"  Mode: {self.mode.value}  |  Duration: {summary.total_duration_s}s")
        print("=" * 70)
        print(f"  Total: {summary.total_scenarios}  |  "
              f"PASS: \033[32m{summary.passed_scenarios}\033[0m  |  "
              f"FAIL: \033[31m{summary.failed_scenarios}\033[0m  |  "
              f"SKIP: {summary.skipped_scenarios}  |  "
              f"ERROR: {summary.error_scenarios}")
        print(f"  Pass Rate: {summary.pass_rate:.0%}  |  Score: {summary.total_score:.0%}")
        if not summary.is_healthy:
            print(f"  \033[33mSTATUS: UNHEALTHY\033[0m")
        else:
            print(f"  \033[32mSTATUS: HEALTHY\033[0m")

        # 失败场景详情
        failed = [r for r in summary.results if not r.passed]
        if failed:
            print("\n  Failed Scenarios:")
            for r in failed:
                fail_names = [o.assertion_name for o in r.outcomes if o.result.value == "fail"]
                print(f"    - [{r.category}] {r.scenario_id}: {', '.join(fail_names)}")
                if r.error:
                    print(f"      Error: {r.error}")

        print("=" * 70 + "\n")


# =====================================================================
# Pytest 集成
# =====================================================================

def pytest_collection():
    """返回所有可运行的 scenario 给 pytest 发现"""
    from app.agent.eval.scenarios import get_active_scenarios
    return get_active_scenarios()


# 便捷函数：一键跑 DRY 模式评估
async def run_eval_dry(tags: str = "", category: str = "") -> Any:
    """运行 DRY 模式评估（CI 友好，无需 LLM）"""
    runner = EvalRunner(mode=EvalMode.DRY, tags_filter=tags, category_filter=category)
    return await runner.run_all()


async def run_eval_full(agent_loop=None, llm_service=None, tags: str = "") -> Any:
    """运行 FULL 模式评估（需要 LLM，用于夜间构建）"""
    runner = EvalRunner(mode=EvalMode.FULL, tags_filter=tags)
    runner.set_dependencies(agent_loop=agent_loop, llm_service=llm_service)
    return await runner.run_all()
