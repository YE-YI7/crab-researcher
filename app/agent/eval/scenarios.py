"""
CrabRes Eval System — L1: Test Scenario Definitions

定义所有评估场景（Scenario），每个场景包含：
- input / input_sequence: 用户输入
- assertions: 断言列表
- expected_route: 预期路由结果
- tags: 标签（用于筛选运行 subset）
- metadata: 场景元数据

设计原则（参考 hamel.dev/evals）：
  S1: 每个场景覆盖一个可测范围（如"列表查找器返回预期数量"）
  S2: 用 LLM 综合生成测试用例输入，不需要 100% 通过率
  S3: CI 基础设施执行测试 + 跟踪一段时间内的结果趋势
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ScenarioCategory(str, Enum):
    """场景分类"""
    ROUTING = "routing"           # 路由决策正确性
    UNDERSTAND = "understand"     # 理解阶段：意图识别、产品提取
    RESEARCH = "research"         # 研究阶段：搜索执行、数据质量
    EXPERT = "expert"             # 专家阶段：调度、输出质量
    SYNTHESIZE = "synthesize"     # 综合阶段：CGO 决策质量
    DELIVER = "deliver"           # 交付阶段：产物生成
    COMPACTION = "compaction"     # 上下文压缩
    ERROR_RECOVERY = "error"      # 错误恢复
    END_TO_END = "e2e"            # 端到端完整流程
    REGRESSION = "regression"     # 回归防护（已知 bug 不复发）


@dataclass
class Assertion:
    """单个断言"""
    name: str                           # 断言名称，如 "response_not_empty"
    check: str | None = None           # 断言表达式（给 LLM judge 用）
    expected: Any = True               # 期望值
    category: str = "functional"       # functional | quality | performance | safety
    weight: float = 1.0                # 权重（加权评分用）


@dataclass
class ScenarioStep:
    """多轮对话中的单步"""
    role: str = "user"                 # user | assistant
    content: str = ""
    wait_seconds: float = 0.0          # 模拟用户思考时间


@dataclass
class EvalScenario:
    """
    评估场景 — eval 系统的最小可执行单元。

    对应 hamel.dev/evals 中 S1 (Scope Test) 的概念：
    每个 scenario 测试一个明确的功能范围。
    """
    id: str                            # 唯一标识，如 "route_greeting_en"
    name: str                          # 可读名称
    category: ScenarioCategory         # 分类

    # 输入
    input: str = ""                    # 单轮输入
    input_sequence: list[ScenarioStep] = field(default_factory=list)  # 多轮输入
    language: str = "en"               # 预期语言

    # 预期行为
    expected_mode: str | None = None   # 预期 ExecutionMode: pipeline/react/quick
    expected_intent: str | None = None # 预期 intent
    expected_phase: str | None = None  # 预期最终到达的 phase
    deliverable_intent: str | None = None  # 预期 deliverable_intent: full / competitor_only / content_only / plan_only

    # 断言
    assertions: list[Assertion] = field(default_factory=list)

    # 元数据
    tags: list[str] = field(default_factory=list)
    priority: int = 0                  # 0=normal, 1=important, 2=critical
    skip_reason: str = ""              # 跳过原因（空=不跳过）
    setup: dict = field(default_factory=dict)  # 额外状态设置

    @property
    def is_multi_turn(self) -> bool:
        return len(self.input_sequence) > 0

    @property
    def effective_input(self) -> str | list[ScenarioStep]:
        return self.input_sequence if self.is_multi_turn else self.input


# =====================================================================
# 场景注册表 — 所有评估场景集中定义
# =====================================================================

SCENARIO_REGISTRY: list[EvalScenario] = []


def register(s: EvalScenario) -> EvalScenario:
    SCENARIO_REGISTRY.append(s)
    return s


# ----- Category: ROUTING -----

register(EvalScenario(
    id="route_greeting_en",
    name="English greeting routes to QUICK",
    category=ScenarioCategory.ROUTING,
    input="hi",
    expected_mode="quick",
    expected_intent="greeting",
    assertions=[
        Assertion(name="mode_is_quick", check="result.mode == 'quick'"),
        Assertion(name="intent_is_greeting", check="result.intent == 'greeting'"),
        Assertion(name="no_llm_called", check="metrics.llm_calls == 0"),
    ],
    tags=["greeting", "fast_path", "zero_token"],
    priority=2,  # critical: 打招呼必须零 token
))

register(EvalScenario(
    id="route_greeting_zh",
    name="Chinese greeting routes to QUICK",
    category=ScenarioCategory.ROUTING,
    input="你好",
    expected_mode="quick",
    expected_intent="greeting",
    assertions=[
        Assertion(name="mode_is_quick"),
        Assertion(name="no_llm_called"),
    ],
    tags=["greeting", "i18n", "zero_token"],
    priority=2,
))

register(EvalScenario(
    id="route_self_awareness",
    name="Self-awareness question routes to QUICK",
    category=ScenarioCategory.ROUTING,
    input="What are you?",
    expected_mode="quick",
    expected_intent="self_awareness",
    assertions=[
        Assertion(name="mode_is_quick"),
        Assertion(name="has_product_info_set"),
    ],
    tags=["self_awareness", "zero_token"],
))

register(EvalScenario(
    id="route_expert_chat",
    name="@expert mention routes to expert_chat",
    category=ScenarioCategory.ROUTING,
    input="@market_researcher 分析一下我的竞品",
    expected_mode="quick",
    expected_intent="expert_chat",
    assertions=[
        Assertion(name="mode_is_quick"),
        Assertion(name="expert_id_extracted", check="result.expert_id == 'market_researcher'"),
    ],
    tags=["expert_chat", "routing"],
    priority=1,
))

register(EvalScenario(
    id="route_product_intro_saas",
    name="SaaS product intro routes to PIPELINE",
    category=ScenarioCategory.ROUTING,
    input="I'm building an AI resume optimizer at $9.99/mo. Goal: 1000 users in 3 months.",
    expected_mode="pipeline",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="mode_is_pipeline", check="result.mode == 'pipeline'"),
        Assertion(name="intent_is_growth_request"),
        Assertion(name="product_name_extracted", check="'name' in result.product_info"),
    ],
    tags=["product_intro", "pipeline"],
    priority=1,
))

register(EvalScenario(
    id="route_product_intro_zh",
    name="Chinese consumer app intro routes to PIPELINE",
    category=ScenarioCategory.ROUTING,
    input="我做了一个习惯追踪 App，还没有用户，零预算。",
    expected_mode="pipeline",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="mode_is_pipeline"),
        Assertion(name="language_detected_zh", check="result.language == 'zh'"),
        Assertion(name="zero_budget_detected"),
    ],
    tags=["product_intro", "i18n", "zh"],
))

register(EvalScenario(
    id="route_followup_with_context",
    name="Follow-up with prior research stays in PIPELINE",
    category=ScenarioCategory.ROUTING,
    input="What about LinkedIn specifically?",
    setup={"has_prior_research": True, "has_prior_experts": True},
    expected_mode="pipeline",
    assertions=[
        Assertion(name="mode_is_pipeline"),
        Assertion(name="uses_prior_data", check="len(result.search_results) > 0"),
    ],
    tags=["followup", "context_reuse"],
))

register(EvalScenario(
    id="route_deep_strategy_trigger",
    name="Deep strategy request triggers background job",
    category=ScenarioCategory.ROUTING,
    input="I need a deep strategy rethink for my product",
    expected_mode="quick",
    assertions=[
        Assertion(name="deep_strategy_triggered"),
    ],
    tags=["deep_strategy"],
))


# ----- Category: UNDERSTAND -----

register(EvalScenario(
    id="understand_extract_saas",
    name="Extracts SaaS product info correctly",
    category=ScenarioCategory.UNDERSTAND,
    input="We built RankFlow, an SEO tool for indie developers. $19/mo, currently 200 users.",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="product_name_is_rankflow", check="result.product_info.get('name').lower() == 'rankflow'"),
        Assertion(name="price_extracted", check='"$19" in str(result.product_info)'),
        Assertion(name="target_audience_indie_devs", check='"indie" in str(result.product_info.get("target_audience", "")).lower()'),
        Assertion(name="current_users_200", check='"200" in str(result.product_info)'),
    ],
    tags=["extraction", "structured_output"],
    priority=1,
))

register(EvalScenario(
    id="understand_detect_zero_budget",
    name="Detects zero-budget constraint",
    category=ScenarioCategory.UNDERSTAND,
    input="I made a free todo app for students. No money for ads.",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="budget_constraint_detected", check="result.product_info.get('budget', '').lower() in ('', '0', 'free', 'none', '$0')"),
        Assertion(name="target_audience_students"),
    ],
    tags=["constraint_detection"],
))

register(EvalScenario(
    id="understand_detect_platform_hint",
    name="Detects target platform from message",
    category=ScenarioCategory.UNDERSTAND,
    input="Help me grow on Reddit and X/Twitter. My tool is a dev analytics dashboard.",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="reddit_in_target_platforms", check="'reddit' in [p.lower() for p in result.target_platforms]"),
        Assertion(name="twitter_in_target_platforms", check='"x_twitter" in " ".join(result.target_platforms).lower() or "twitter" in " ".join(result.target_platforms).lower()'),
    ],
    tags=["platform_detection"],
))


# ----- Category: RESEARCH -----

register(EvalScenario(
    id="research_executes_search",
    name="Executes at least one search query for product intro",
    category=ScenarioCategory.RESEARCH,
    input="Analyze my competitor Notion for me.",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="at_least_one_search", check="metrics.search_calls >= 1"),
        Assertion(name="search_query_contains_competitor", check="any('notion' in q.lower() for q in metrics.search_queries)"),
    ],
    tags=["search_execution"],
    priority=1,
))

register(EvalScenario(
    id="research_returns_data",
    name="Search returns usable data (>200 chars)",
    category=ScenarioCategory.RESEARCH,
    input="Research the AI coding assistant market.",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="useful_search_results", check="metrics.useful_result_rate >= 0.5"),
    ],
    tags=["data_quality"],
))

register(EvalScenario(
    id="research_no_duplicate_queries",
    name="Does not search the same query twice",
    category=ScenarioCategory.RESEARCH,
    input="Tell me about the CRM market for small businesses.",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="no_duplicate_queries", check="len(metrics.search_queries) == len(set(metrics.search_queries))"),
    ],
    tags=["efficiency"],
))


# ----- Category: EXPERT -----

register(EvalScenario(
    id="expert_activates_minimum",
    name="Activates at least 2 experts for standard analysis",
    category=ScenarioCategory.EXPERT,
    input="Help me analyze my SaaS product pricing strategy.",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="at_least_2_experts", check="metrics.activated_experts >= 2"),
        Assertion(name="expert_outputs_valid", check="metrics.valid_expert_rate >= 0.8"),
    ],
    tags=["expert_activation"],
    priority=1,
))

register(EvalScenario(
    id="expert_includes_critic",
    name="Critic expert is always activated for full analysis",
    category=ScenarioCategory.EXPERT,
    input="Give me a full growth plan for my e-commerce store.",
    expected_intent="growth_request",
    deliverable_intent="full",
    assertions=[
        Assertion(name="critic_activated", check="'critic' in metrics.expert_ids_used"),
    ],
    tags=["expert_scheduling", "quality_gate"],
    priority=1,
))

register(EvalScenario(
    id="expert_language_consistency",
    name="All expert outputs match user language",
    category=ScenarioCategory.EXPERT,
    input="帮我分析一下我的中文博客增长策略",
    language="zh",
    expected_intent="growth_request",
    assertions=[
        Assertion(name="all_experts_chinese", check="metrics.language_consistency_rate == 1.0"),
    ],
    tags=["i18n", "language", "quality"],
    priority=2,  # critical per EVALUATION.md baseline
))


# ----- Category: DELIVER -----

register(EvalScenario(
    id="deliver_generates_report",
    name="Full pipeline generates at least 1 deliverable",
    category=ScenarioCategory.DELIVER,
    input="Give me a complete growth analysis for my productivity app.",
    expected_intent="growth_request",
    deliverable_intent="full",
    assertions=[
        Assertion(name="at_least_one_deliverable", check="len(result.deliverables) >= 1"),
        Assertion(name="deliverable_has_content", check="any(len(d.get('content', '')) > 100 for d in result.deliverables)"),
    ],
    tags=["deliverable_generation"],
    priority=1,
))

register(EvalScenario(
    id="deliver_respects_intent",
    name="Competitor-only intent skips content draft generation",
    category=ScenarioCategory.DELIVER,
    input="Who are the main competitors to Figma?",
    expected_intent="competitive_analysis",
    deliverable_intent="competitor_only",
    assertions=[
        Assertion(name="report_generated"),
        Assertion(name="no_content_draft", check="not any(d.get('type') == 'content_draft' for d in result.deliverables)"),
    ],
    tags=["deliverable_filtering"],
))


# ----- Category: COMPACTION -----

register(EvalScenario(
    id="compaction_triggers_on_long_history",
    name="LLM compaction triggers when history exceeds threshold",
    category=ScenarioCategory.COMPACTION,
    input_sequence=[
        ScenarioStep(role="user", content="I'm building a SaaS called TestProduct."),
        ScenarioStep(role="assistant", content="[Long analysis response...]"),
        ScenarioStep(role="user", content="What about pricing?"),
        ScenarioStep(role="assistant", content="[Pricing analysis...]"),
        ScenarioStep(role="user", content="And marketing channels?"),
        ScenarioStep(role="assistant", content="[Channel analysis...]"),
        ScenarioStep(role="user", content="Tell me about competitors too."),
        ScenarioStep(role="assistant", content="[Competitor analysis...]"),
        ScenarioStep(role="user", content="Now give me a 30-day plan."),
        ScenarioStep(role="assistant", content="[Plan generated...]"),
        ScenarioStep(role="user", content="What about Reddit strategy?"),
        ScenarioStep(role="assistant", content="[Reddit strategy...]"),
        ScenarioStep(role="user", content="Finally, help me write a launch post."),
        ScenarioStep(role="assistant", content="[Post drafted...]"),
        ScenarioStep(role="user", content="Summarize everything we discussed."),  # 第13条消息 → 触发 compaction
    ],
    assertions=[
        Assertion(name="compaction_triggered", check="metrics.compaction_count >= 1"),
        Assertion(name="summary_not_empty", check="len(metrics.last_compaction_summary) > 50"),
        Assertion(name="key_info_preserved", check='"testproduct" in metrics.last_compaction_summary.lower()'),
    ],
    tags=["compaction", "long_conversation"],
))

register(EvalScenario(
    id="compaction_fallback_on_failure",
    name="Compaction falls back to hard truncate if LLM fails",
    category=ScenarioCategory.COMPACTION,
    input_sequence=[
        ScenarioStep(role="user", content=f"Question {i}?") for i in range(15)
    ],
    setup={"simulate_llm_failure": True},
    assertions=[
        Assertion(name="no_crash", check="result.error is None"),
        Assertion(name="fallback_used", check="metrics.compaction_fallback_count >= 1"),
    ],
    tags=["compaction", "error_recovery"],
))


# ----- Category: ERROR RECOVERY -----

register(EvalScenario(
    id="error_llm_timeout_recovers",
    name="Recovers from LLM timeout without crashing session",
    category=ScenarioCategory.ERROR_RECOVERY,
    input="Analyze my product.",
    setup={"simulate_timeout": True},
    assertions=[
        Assertion(name="session_not_crashed", check="result.error is None or 'recovered' in str(result.status).lower()"),
        Assertion(name="fallback_tier_used", check="metrics.fallback_calls >= 1"),
    ],
    tags=["resilience"],
    priority=1,
))

register(EvalScenario(
    id="error_tool_failure_continues",
    name="Continues pipeline after tool failure",
    category=ScenarioCategory.ERROR_RECOVERY,
    input="Search the web for my competitors.",
    setup={"simulate_search_failure": True},
    assertions=[
        Assertion(name="experts_still_activated", check="metrics.activated_experts >= 1"),
        Assertion(name="deliverable_may_be_partial"),  # 容许降级
    ],
    tags=["resilience", "graceful_degradation"],
))


# ----- Category: END-TO-END -----

register(EvalScenario(
    id="e2e_full_pipeline_saas",
    name="E2E: Full SaaS analysis pipeline completes successfully",
    category=ScenarioCategory.END_TO_END,
    input="I'm building CrabRes, an AI-powered growth agent for indie hackers. $29/mo. Target: 500 users in 3 months.",
    expected_mode="pipeline",
    expected_phase="deliver",
    assertions=[
        Assertion(name="completes_all_phases", check="result.phase == 'deliver'"),
        Assertion(name="has_product_info"),
        Assertion(name="has_search_results", check="len(result.search_results) > 0"),
        Assertion(name="has_expert_outputs", check="len(result.expert_outputs) >= 2"),
        Assertion(name="has_deliverables", check="len(result.deliverables) >= 1"),
        Assertion(name="total_cost_under_budget", check="metrics.total_cost < 0.10"),
        Assertion(name="completion_time_reasonable", check="metrics.total_time_s < 120"),
    ],
    tags=["e2e", "smoke_test"],
    priority=2,  # critical smoke test
))

register(EvalScenario(
    id="e2e_followup_reuses_context",
    name="E2E: Follow-up question reuses prior context efficiently",
    category=ScenarioCategory.END_TO_END,
    input_sequence=[
        ScenarioStep(role="user", content="I'm building a habit tracker app for students."),
        ScenarioStep(role="assistant", content="[First analysis with research and expert opinions]"),
        ScenarioStep(role="user", content="What specifically should I do on Reddit?"),
    ],
    assertions=[
        Assertion(name="second_response_focused_on_reddit"),
        Assertion(name="no_redundant_search", check="metrics.search_calls < 3"),  # 不应该重新全面搜索
        Assertion(name="second_response_shorter", check="len(result.final_response) < len(result.first_response)"),
        Assertion(name="cost_lower_second_round", check="metrics.round2_cost < metrics.round1_cost"),
    ],
    tags=["e2e", "context_reuse", "efficiency"],
))


# ----- Category: REGRESSION -----

register(EvalScenario(
    id="regress_router_no_false_pipeline_for_greeting",
    name="REGRESS: Greeting never misrouted to PIPELINE",
    category=ScenarioCategory.REGRESSION,
    input="hello there!",
    expected_mode="quick",
    assertions=[
        Assertion(name="mode_is_quick", check="result.mode == 'quick'"),
    ],
    tags=["regression", "routing"],
    priority=2,
))

register(EvalScenario(
    id="regress_no_empty_response",
    name="REGRESS: Never returns empty response for valid request",
    category=ScenarioCategory.REGRESSION,
    input="Help me with marketing.",
    assertions=[
        Assertion(name="response_not_empty", check="len(result.final_response.strip()) > 20"),
    ],
    tags=["regression", "quality"],
    priority=2,
))

register(EvalScenario(
    id="regress_no_expert_hallucination",
    name="REGRESS: Expert outputs don't contain fabricated data",
    category=ScenarioCategory.REGRESSION,
    input="Analyze a fictional product called XYZ123 that doesn't exist.",
    assertions=[
        Assertion(name="no_specific_numbers_without_source"),  # 不能编造具体数字
        Assertion(name="expert_mentions_uncertainty"),  # 应该提到信息有限
    ],
    tags=["regression", "safety", "hallucination"],
))


# =====================================================================
# 辅助函数
# =====================================================================

def get_scenarios_by_tag(tag: str) -> list[EvalScenario]:
    """按标签筛选场景"""
    return [s for s in SCENARIO_REGISTRY if tag in s.tags]

def get_scenarios_by_category(cat: ScenarioCategory) -> list[EvalScenario]:
    """按分类筛选场景"""
    return [s for s in SCENARIO_REGISTRY if s.category == cat]

def get_critical_scenarios() -> list[EvalScenario]:
    """获取所有 critical 优先级的场景（CI 必跑）"""
    return [s for s in SCENARIO_REGISTRY if s.priority == 2 and not s.skip_reason]

def get_active_scenarios() -> list[EvalScenario]:
    """获取所有未跳过的场景"""
    return [s for s in SCENARIO_REGISTRY if not s.skip_reason]
