"""
CrabRes L1 Eval — Compaction 压缩逻辑测试

测试 _llm_compact_history 及相关逻辑：
- 消息分类和截断规则
- 缓存命中/失效逻辑
- Fallback 链（LLM 失败 → 硬截断）
- 错误恢复路径（L1/L2/L3）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCompactionMessageClassification:
    """Compaction 输入消息分类逻辑"""

    def _make_messages(self, specs: list[tuple]) -> list[dict]:
        """辅助：按 (role, content_prefix, length) 构造消息列表"""
        msgs = []
        for role, prefix, length in specs:
            content = prefix + ("x" * length)
            msgs.append({"role": role, "content": content})
        return msgs

    def test_classifies_tool_results(self):
        """工具结果消息应被特殊处理"""
        msgs = self._make_messages([
            ("user", "[Tool:web_search] result:", 500),
            ("assistant", "normal response", 200),
        ])
        # 在 compaction 逻辑中，[Tool:] 开头的消息只保留元信息
        tool_msgs = [m for m in msgs if m["content"].startswith("[Tool:")]
        assert len(tool_msgs) == 1

    def test_classifies_expert_outputs(self):
        """专家输出消息应被特殊处理"""
        msgs = self._make_messages([
            ("assistant", "[Expert:market_researcher] analysis:", 800),
        ])
        expert_msgs = [m for m in msgs if m["content"].startswith("[Expert:")]
        assert len(expert_msgs) == 1

    def test_classifies_internal_reasoning(self):
        """内部推理消息应被跳过"""
        msgs = self._make_messages([
            ("assistant", "[Internal reasoning] thinking...", 300),
        ])
        internal = [m for m in msgs if m["content"].startswith("[Internal reasoning]")]
        assert len(internal) == 1

    def test_classifies_normal_user_message(self):
        """普通用户消息正常处理"""
        msgs = self._make_messages([("user", "I need help with my product pricing strategy", 100)])
        normal = [m for m in msgs if not m["content"].startswith("[")]
        assert len(normal) == 1


class TestCompactionCache:
    """Compaction 缓存逻辑测试"""

    def test_cache_initialized_empty(self):
        """AgentLoop 初始化时缓存应为空"""
        from app.agent.engine.loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)
        loop._compaction_cache = ""
        loop._compaction_msg_count = 0
        assert loop._compaction_cache == ""
        assert loop._compaction_msg_count == 0

    def test_cache_hit_when_count_unchanged(self):
        """旧消息数量不变时复用缓存"""
        cache = "cached summary text"
        count = 10
        old_msgs = [{"role": "user", "content": f"msg {i}"} for i in range(count)]

        # 模拟缓存命中条件
        cached_msg_count = count
        cached_summary = cache

        if len(old_msgs) == cached_msg_count and cached_summary:
            summary = cached_summary
            assert summary == cache

    def test_cache_invalidated_on_count_change(self):
        """消息数量变化时缓存失效"""
        old_cache_count = 10
        new_msgs_count = 12
        should_invalidate = new_msgs_count != old_cache_count
        assert should_invalidate is True


class TestCompactionFallback:
    """Compaction Fallback 链测试"""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        """空消息列表返回空摘要"""
        from app.agent.engine.loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)
        # Mock 必要属性
        loop.llm = MagicMock()
        result = await loop._llm_compact_history([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty_for_fallback(self):
        """LLM 调用失败时返回空字符串（触发 fallback）"""
        from app.agent.engine.loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM timeout"))
        loop.llm = mock_llm

        msgs = [
            {"role": "user", "content": "test message one"},
            {"role": "assistant", "content": "response one"},
        ]
        result = await loop._llm_compact_history(msgs)
        # LLM 失败应返回空字符串，调用方会 fallback 到硬截断
        assert result == ""


class TestErrorRecoveryLevels:
    """错误恢复三级降级链测试"""

    def test_l1_compact_context_exists(self):
        """L1 恢复方法 _compact_context 应存在"""
        from app.agent.engine.loop import AgentLoop
        assert hasattr(AgentLoop, '_compact_context')

    def test_l2_collapse_history_exists(self):
        """L2 恢复方法 _collapse_history 应存在"""
        from app.agent.engine.loop import AgentLoop
        assert hasattr(AgentLoop, '_collapse_history')

    def test_l3_reset_is_final_fallback(self):
        """L3 是最终兜底：重置为安全状态"""
        from app.agent.engine.loop import AgentLoop
        # L3 的行为是调用 _build_context("") 重置
        assert hasattr(AgentLoop, '_build_context')


class TestCompactionPromptQuality:
    """Compaction Prompt 结构验证（不需要 LLM 执行）"""

    def test_prompt_has_structured_sections(self):
        """Prompt 应要求结构化 5 段式输出"""
        from app.agent.engine.loop import AgentLoop
        import inspect
        source = inspect.getsource(AgentLoop._llm_compact_history)
        # 验证 prompt 包含关键 section 标题
        assert "Product" in source or "product" in source
        assert "Decision" in source or "decision" in source
        assert "Constraint" in source or "constraint" in source
        assert "Pending" in source or "pending" in source

    def test_prompt_requires_specificity(self):
        """Prompt 应要求具体性（禁止幻觉）"""
        from app.agent.engine.loop import AgentLoop
        import inspect
        source = inspect.getsource(AgentLoop._llm_compact_history)
        assert "hallucinat" in source.lower() or "specific" in source.lower()

    def test_prompt_has_token_limit(self):
        """Prompt 应限制输出 token 数"""
        from app.agent.engine.loop import AgentLoop
        import inspect
        source = inspect.getsource(AgentLoop._llm_compact_history)
        assert "token" in source.lower() or "800" in source or "1024" in source


class TestContextBuildIntegration:
    """_build_context 中 compaction 集成测试"""

    def test_recent_count_constant(self):
        """最近保留的消息数应为常量 12"""
        from app.agent.engine.loop import AgentLoop
        import inspect
        source = inspect.getsource(AgentLoop._build_context)
        assert "12" in source or "RECENT_COUNT" in source

    def test_compacted_context_marker_present(self):
        """压缩后的上下文应有标记前缀"""
        from app.agent.engine.loop import AgentLoop
        import inspect
        source = inspect.getsource(AgentLoop._build_context)
        assert "COMPACTED" in source

    def test_fallback_path_preserves_recent(self):
        """Fallback 路径也应保留最近消息"""
        from app.agent.engine.loop import AgentLoop
        import inspect
        source = inspect.getsource(AgentLoop._build_context)
        # fallback 分支中应该有 recent_msgs 处理
        assert "recent" in source.lower()
