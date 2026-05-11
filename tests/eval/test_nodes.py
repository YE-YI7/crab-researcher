"""
CrabRes L1 Eval — Node 节点测试

测试 UNDERSTAND 节点的规则匹配逻辑（不需要 LLM 的部分）：
- @expert 私聊检测
- 自我认知检测
- 纯打招呼检测
- 产品信号检测
- 交付意图检测
- 深度研究模式检测
"""

import pytest
from app.agent.engine.state import AgentState, ExecutionMode, Phase
from app.agent.engine.nodes import node_understand, NodeDeps, _detect_product_info


class TestNodeUnderstandRules:
    """node_understand 中确定性规则的测试"""

    def _make_state(self) -> AgentState:
        return AgentState(session_id="test-node")

    def _make_deps(self) -> NodeDeps:
        return NodeDeps(llm=None, tools=None, experts=None, memory=None, trust=None)

    # ----- 规则 1: @expert 私聊 -----

    @pytest.mark.asyncio
    async def test_expert_chat_sets_direct_reply(self):
        state = self._make_state()
        deps = self._make_deps()
        result = await node_understand(state, deps, "@market_researcher 分析竞品")
        assert result.intent == "expert_chat"
        assert result.direct_reply.startswith("__EXPERT_CHAT__:")
        assert "market_researcher" in result.direct_reply

    # ----- 规则 2: 自我认知 -----

    @pytest.mark.asyncio
    async def test_self_awareness_sets_flag(self):
        state = self._make_state()
        deps = self._make_deps()
        result = await node_understand(state, deps, "What are you?")
        assert result.is_self_awareness is True
        assert result.intent == "self_awareness"
        assert result.has_product_info is True

    @pytest.mark.parametrize("msg", [
        "who are you", "你是什么", "你做什么",
        "what do you do", "介绍一下你", "introduce yourself",
    ])
    @pytest.mark.asyncio
    async def test_all_self_triggers_detected(self, msg):
        state = self._make_state()
        deps = self._make_deps()
        result = await node_understand(state, deps, msg)
        assert result.is_self_awareness

    # ----- 规则 3: 纯打招呼 -----

    @pytest.mark.asyncio
    async def test_greeting_sets_intent(self):
        state = self._make_state()
        deps = self._make_deps()
        result = await node_understand(state, deps, "你好")
        assert result.intent == "greeting"

    # ----- 规则 4: 产品信息检测 -----

    @pytest.mark.asyncio
    async def test_product_signal_detected(self):
        state = self._make_state()
        deps = self._make_deps()
        result = await node_understand(
            state, deps,
            "I built a SaaS tool for developers at $19/mo."
        )
        assert result.has_product_info is True
        assert result.intent == "growth_request"
        assert "raw_description" in result.product_info

    @pytest.mark.asyncio
    async def test_chinese_product_detected(self):
        state = self._make_state()
        deps = self._make_deps()
        result = await node_understand(state, deps, "我做了一个习惯追踪 App")
        assert result.has_product_info is True
        assert result.intent == "growth_request"


class TestProductInfoDetection:
    """_detect_product_info 辅助函数的边界测试"""

    def test_saas_description_detected(self):
        assert _detect_product_info("I built a SaaS at $20/mo") is True

    def test_app_description_detected(self):
        assert _detect_product_info("My app helps users track habits") is True

    def test_tool_description_detected(self):
        assert _detect_product_info("We made a dev tool for APIs") is True

    def test_pricing_mention_detected(self):
        assert _detect_product_info("It costs $9.99 per month") is True

    def test_greeting_not_product(self):
        assert _detect_product_info("hi how are you") is False

    def test_empty_not_product(self):
        assert _detect_product_info("") is False

    def test_short_ambiguous_not_product(self):
        assert _detect_product_info("ok") is False
        assert _detect_product_info("yes") is False

    def test_chinese_product_signals(self):
        assert _detect_product_info("我的产品是") is True
        assert _detect_product_info("我做了") is True
        assert _detect_product_info("帮助用户") is True


class TestDeliverableIntentDetection:
    """交付意图检测（决定 DELIVER 阶段生成哪些产物）"""

    @pytest.mark.asyncio
    async def test_competitor_analysis_intent(self):
        from app.agent.engine.nodes import _detect_deliverable_intent
        intent = _detect_deliverable_intent("Who competes with Notion?")
        assert intent == "competitor_only"

    @pytest.mark.asyncio
    async def test_content_request_intent(self):
        from app.agent.engine.nodes import _detect_deliverable_intent
        intent = _detect_deliverable_intent("Help me write a Reddit post")
        assert intent in ("content_only", "full")

    @pytest.mark.asyncio
    async def test_full_plan_intent(self):
        from app.agent.engine.nodes import _detect_deliverable_intent
        intent = _detect_deliverable_intent("Give me a complete growth plan")
        assert intent == "full"


class TestDeepResearchDetection:
    """深度研究模式触发检测"""

    @pytest.mark.asyncio
    async def test_deep_research_trigger(self):
        from app.agent.engine.nodes import _detect_deep_research
        result = _detect_deep_research("深入分析 AI agent 市场")
        assert result is True

    @pytest.mark.asyncio
    async def test_normal_request_no_deep(self):
        from app.agent.engine.nodes import _detect_deep_research
        result = _detect_deep_research("Help me with marketing")
        assert result is not True  # 可能是 False 或 None


class TestAgentStateDataModel:
    """AgentState 数据模型完整性测试"""

    def test_default_state(self):
        state = AgentState(session_id="test")
        assert state.mode == ExecutionMode.PIPELINE
        assert state.phase == Phase.UNDERSTAND
        assert state.turn_count == 0
        assert state.token_budget == 100_000
        assert state.max_pipeline_steps == 20
        assert state.max_loop_iterations == 10

    def test_message_history(self):
        state = AgentState(session_id="test")
        state.add_message("user", "hello")
        state.add_message("assistant", "hi there")
        assert len(state.message_history) == 2
        recent = state.recent_messages(1)
        assert len(recent) == 1
        assert recent[0]["role"] == "assistant"

    def test_checkpoint_serialization(self):
        state = AgentState(session_id="ckpt-test")
        state.product_info = {"name": "Test"}
        state.expert_outputs = {"a": "x" * 100}
        ckpt = state.to_checkpoint()
        assert ckpt["session_id"] == "ckpt-test"
        assert ckpt["product_info"]["name"] == "Test"
        assert len(ckpt["expert_outputs"]["a"]) <= 3000  # 截断

    def test_execution_mode_values(self):
        assert ExecutionMode.PIPELINE.value == "pipeline"
        assert ExecutionMode.REACT.value == "react"
        assert ExecutionMode.QUICK.value == "quick"

    def test_phase_values(self):
        phases = [p.value for p in Phase]
        assert "understand" in phases
        assert "research" in phases
        assert "expert" in phases
        assert "synthesize" in phases
        assert "deliver" in phases
        assert "think" in phases
        assert "observe" in phases
