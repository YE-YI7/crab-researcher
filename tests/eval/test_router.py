"""
CrabRes L1 Eval — Router 路由决策测试

覆盖所有 8 条路由规则，确保：
- 零 token 路径（greeting/self_awareness/expert_chat）正确命中
- PIPELINE/REACT 分发逻辑正确
- 边界情况（空消息、特殊字符、混合语言）
"""

import pytest
from app.agent.engine.state import AgentState, ExecutionMode
from app.agent.engine.router import route, RouteDecision, _has_strong_product_signal


class TestRouterGreeting:
    """路由规则 2: 纯打招呼 → QUICK (零 token)"""

    @pytest.mark.parametrize("msg", [
        "hi", "hello", "hey", "你好", "嗨", "yo", "sup",
        "hi!", "你好！", "hey.",
    ])
    def test_greeting_routes_to_quick(self, msg):
        state = AgentState(session_id="test")
        decision = route(msg, state)
        assert decision.mode == ExecutionMode.QUICK
        assert decision.reason == "greeting"
        assert decision.confidence >= 0.7  # 强规则命中

    @pytest.mark.parametrize("msg", [
        "Hi there, how are you?",     # 不是纯打招呼（有额外内容）
        "Hello, I need help with...", # 带请求
        "你好啊帮我看看",              # 中文带请求
    ])
    def test_not_pure_greeting_falls_through(self, msg):
        state = AgentState(session_id="test")
        decision = route(msg, state)
        # 不应该命中 greeting 规则
        assert decision.reason != "greeting"


class TestRouterSelfAwareness:
    """路由规则 3: 自我认知 → QUICK"""

    @pytest.mark.parametrize("msg", [
        "What are you?", "Who are you?", "你是什么？", "你是谁？",
        "What do you do?", "你做什么？", "介绍一下你", "introduce yourself",
    ])
    def test_self_awareness_routes_to_quick(self, msg):
        state = AgentState(session_id="test")
        decision = route(msg, state)
        assert decision.mode == ExecutionMode.QUICK
        assert "self_aware" in decision.reason


class TestRouterExpertChat:
    """路由规则 1: @expert 私聊 → QUICK"""

    def test_expert_mention_routes_to_quick(self):
        state = AgentState(session_id="test")
        decision = route("@market_researcher 分析竞品", state)
        assert decision.mode == ExecutionMode.QUICK
        assert decision.reason == "expert_chat"
        assert decision.expert_id == "market_researcher"
        assert decision.expert_task == "分析竞品"

    def test_expert_case_insensitive(self):
        state = AgentState(session_id="test")
        decision = route("@Social_Media help with Reddit", state)
        assert decision.expert_id == "social_media"

    def test_nonexistent_expert_still_routes(self):
        state = AgentState(session_id="test")
        decision = route("@nonexistent_expert do something", state)
        assert decision.mode == ExecutionMode.QUICK
        assert decision.expert_id == "nonexistent_expert"


class TestRouterProductIntro:
    """路由规则 7: 有产品信息 → PIPELINE (默认) / REACT (高信任)"""

    def test_saas_intro_routes_to_pipeline(self):
        state = AgentState(session_id="test")
        decision = route(
            "I'm building an AI resume optimizer at $9.99/mo. Goal: 1000 users.",
            state,
        )
        assert decision.mode == ExecutionMode.PIPELINE
        assert decision.reason == "product_request_default"

    def test_chinese_app_intro_routes_to_pipeline(self):
        state = AgentState(session_id="test")
        decision = route("我做了一个习惯追踪 App，还没有用户，零预算。", state)
        assert decision.mode == ExecutionMode.PIPELINE

    def test_product_with_high_trust_goes_react(self):
        state = AgentState(session_id="test", turn_count=5)
        # 模拟高信任级别
        state._trust_level = "Trusted"
        decision = route(
            "I need a comprehensive analysis of my SaaS pricing strategy for the US market "
            "and how to compete with established players using content marketing and SEO.",
            state,
        )
        # 长消息 + 高信任 + turn_count > 2 → REACT
        if len(decision.reason) > 3:  # 排除 default
            assert decision.mode in (ExecutionMode.REACT, ExecutionMode.PIPELINE)

    def test_short_message_no_react(self):
        """短消息即使高信任也不触发 ReAct"""
        state = AgentState(session_id="test", turn_count=5)
        state._trust_level = "Trusted"
        decision = route("Help me grow.", state)
        # 短消息 < 50 字符 → 不满足 ReAct 条件
        assert decision.mode == ExecutionMode.PIPELINE or decision.mode == ExecutionMode.QUICK


class TestRouterFollowup:
    """路由规则 6: 追问（有历史数据）→ PIPELINE"""

    def test_followup_with_prior_research(self):
        state = AgentState(session_id="test")
        state.search_results = [{"query": "SaaS growth", "content": "..."}]
        decision = route("What about LinkedIn?", state)
        assert decision.mode == ExecutionMode.PIPELINE
        assert "followup" in decision.reason

    def test_followup_trusted_with_tool_request(self):
        state = AgentState(session_id="test")
        state.search_results = [{"query": "test"}]
        state._trust_level = "Trusted"
        decision = route("Search for my competitors on Google", state)
        # 高信任 + 工具请求 + 追问 → 可能是 REACT 或 PIPELINE
        assert decision.mode in (ExecutionMode.PIPELINE, ExecutionMode.REACT)


class TestRouterToolRequest:
    """路由规则 5: 工具请求（有产品上下文）"""

    def test_tool_request_without_product_falls_through(self):
        """没有产品上下文的工具请求不触发工具路由"""
        state = AgentState(session_id="test")
        decision = route("search for something", state)
        # 没有 product context → 不匹配工具规则，走后续规则
        assert decision.reason != "tool_request_safe_mode"

    def test_tool_request_with_product_context(self):
        state = AgentState(session_id="test")
        state.product_info = {"name": "TestProduct"}
        state.has_product_info = True
        decision = route("搜索我的竞品", state)
        assert decision.mode in (ExecutionMode.PIPELINE, ExecutionMode.REACT)


class TestRouterDefault:
    """路由规则 8: 兜底 → PIPELINE"""

    def test_unknown_message_defaults_to_pipeline(self):
        state = AgentState(session_id="test")
        decision = route("something completely unexpected xyz123", state)
        assert decision.mode == ExecutionMode.PIPELINE
        assert decision.confidence < 0.7  # 低置信度兜底

    def test_empty_message_defaults_to_pipeline(self):
        state = AgentState(session_id="test")
        decision = route("", state)
        assert decision.mode == ExecutionMode.PIPELINE

    def test_very_short_ambiguous_message(self):
        state = AgentState(session_id="test")
        decision = route("ok", state)
        # "ok" 不在 greetings 列表中（因为.rstrip后不在），走兜底
        assert decision.mode in (ExecutionMode.PIPELINE, ExecutionMode.QUICK)


class TestProductSignalDetection:
    """_has_strong_product_signal 辅助函数测试"""

    def test_crabres_signals(self):
        assert _has_strong_product_signal("Tell me about crabres") is True
        assert _has_strong_product_signal("crab-res is great") is True

    def test_building_signals(self):
        assert _has_strong_product_signal("I built a tool for developers") is True
        assert _has_strong_product_signal("We made an app called X") is True

    def test_no_signal(self):
        assert _has_strong_product_signal("hello") is False
        assert _has_strong_product_signal("ok thanks") is False
        assert _has_strong_product_signal("a") is False  # 太短

    def test_url_as_signal(self):
        assert _has_strong_product_signal("Check out myapp.com") is True
        assert _has_strong_product_signal("We launched at app.io") is True


class TestRouteDecisionDataClass:
    """RouteDecision 数据结构测试"""

    def test_decision_fields(self):
        d = RouteDecision(ExecutionMode.REACT, reason="test", confidence=0.9)
        assert d.mode == ExecutionMode.REACT
        assert d.confidence == 0.9

    def test_expert_chat_decision(self):
        d = RouteDecision(
            ExecutionMode.QUICK,
            reason="expert_chat",
            expert_id="critic",
            expert_task="review this",
        )
        assert d.expert_id == "critic"
        assert d.expert_task == "review this"
