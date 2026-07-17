"""
CrabRes L1 Eval — 集成测试

运行完整的 DRY mode eval 场景，验证端到端的评估流程：
- 场景加载 → 执行 → 断言 → 报告生成
"""

import pytest
from pathlib import Path


class TestEvalSystemIntegration:
    """Eval 系统集成测试"""

    @pytest.mark.asyncio
    async def test_dry_run_all_scenarios(self):
        """DRY 模式下所有场景应能执行完毕不崩溃"""
        from app.agent.eval.runner import run_eval_dry

        summary = await run_eval_dry()
        assert summary is not None
        assert summary.total_scenarios > 0
        # 应该有场景通过（至少路由类场景应该全过）
        assert summary.passed_scenarios > 0
        print(f"\n[Eval Integration] {summary.passed_scenarios}/{summary.total_scenarios} passed")

    @pytest.mark.asyncio
    async def test_dry_run_routing_only(self):
        """只跑 routing 分类"""
        from app.agent.eval.runner import EvalRunner, EvalMode

        runner = EvalRunner(mode=EvalMode.DRY, category_filter="ROUTING")
        summary = await runner.run_all()
        assert summary.total_scenarios > 0
        # 路由场景在 DRY 模式下应该全部通过（纯确定性逻辑）
        assert summary.pass_rate >= 0.8

    @pytest.mark.asyncio
    async def test_scenario_registry_loaded(self):
        """场景注册表应包含预期数量的场景"""
        from app.agent.eval.scenarios import SCENARIO_REGISTRY, get_critical_scenarios

        assert len(SCENARIO_REGISTRY) >= 25  # 至少 25 个场景
        critical = get_critical_scenarios()
        assert len(critical) >= 3  # 至少 3 个 critical 场景

    def test_assertion_engine_has_builtin_checks(self):
        """断言引擎应有内置检查函数"""
        from app.agent.eval.assertions import get_assertion_engine

        engine = get_assertion_engine()
        assert len(engine._custom_checks) >= 40  # 至少 40 个内置断言

    @pytest.mark.asyncio
    async def test_report_generation(self):
        """评估报告应能正确生成和保存"""
        from app.agent.eval.runner import EvalRunner, EvalMode
        from pathlib import Path

        runner = EvalRunner(mode=EvalMode.DRY, tags_filter="greeting")
        summary = await runner.run_all()

        # 验证报告文件已创建
        report_dir = Path(".crabres/eval")
        latest = report_dir / "latest_report.json"
        # 注意：DRY 模式可能不会实际写文件如果没有场景匹配
        if summary.total_scenarios > 0:
            assert latest.exists() or any(f.name.startswith("report_") for f in report_dir.glob("*.json"))

    def test_metrics_collector_works(self):
        """MetricsCollector 应能正常记录和汇总"""
        from app.agent.eval.collector import MetricsCollector
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            collector = MetricsCollector(base_dir=tmpdir)

            # 记录几个 session
            collector.record_session("sess-1", {
                "tcr": 1.0, "rdr": 0.8, "ear": 0.9,
                "tpt": 10000, "cpt": 0.03, "ttc": 30.0,
                "pgr": True, "dgr": True,
            })
            collector.record_session("sess-2", {
                "tcr": 0.9, "rdr": 0.6, "ear": 0.85,
                "tpt": 12000, "cpt": 0.04, "ttc": 45.0,
                "pgr": False, "dgr": True,
            })

            summary = collector.get_summary(days=7)
            assert summary["sessions"] == 2
            assert 0 < summary["avg_tcr"] <= 1


class TestLLMJudgeIntegration:
    """LLM Judge 集成测试"""

    def test_mock_judge_returns_result(self):
        """无 LLM 服务时应返回 mock 结果"""
        from app.agent.eval.llm_judge import LLMJudge
        import asyncio

        judge = LLMJudge(llm_service=None)
        result = asyncio.run(judge.evaluate(
            user_message="test",
            assistant_response="test response",
        ))
        assert result is not None
        assert result.overall_score == 3.0  # mock 默认值
        assert result.passed is True


class TestTraceIntegration:
    """Trace Logging 集成测试"""

    def test_trace_lifecycle(self):
        """完整 trace 生命周期：start → record → summary → save"""
        from app.agent.eval.traces import TraceCollector
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = TraceCollector(session_id="test-lifecycle", base_dir=tmpdir)

            tracer.start_session(product_name="TestProduct")
            tracer.record_route("pipeline", "product_request_default")
            tracer.record_phase_enter("understand")
            tracer.record_phase_exit("understand")
            tracer.record_output("Hello! Here's my analysis.", output_type="response")
            tracer.end_session()

            summary = tracer.get_summary()
            assert summary.session_id == "test-lifecycle"
            assert summary.total_events >= 4
            assert summary.route_mode == "pipeline"

            path = tracer.save()
            assert Path(path).exists()


class TestABTestIntegration:
    """A/B Test 集成测试"""

    def test_ab_lifecycle(self):
        """完整 A/B Test 生命周期：create → assign → record → analyze"""
        from app.agent.eval.ab_test import ABTestManager
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ABTestManager(base_dir=tmpdir)

            # 创建
            test = mgr.create_test(
                name="test_compaction",
                config_a={"mode": "truncate"},
                config_b={"mode": "llm"},
                primary_metric="user_satisfaction",
            )
            mgr.start_test(test.id)

            # 分组
            g1 = mgr.assign_group("user-1", test.id)
            g2 = mgr.assign_group("user-2", test.id)
            g1_again = mgr.assign_group("user-1", test.id)  # 一致性
            assert g1 == g1_again  # 同一用户总是同组
            assert g1 in ("A", "B")
            assert g2 in ("A", "B")

            # 记录数据
            for i, uid in enumerate(["user-1", "user-2", "user-3", "user-4"] * 10):
                group = mgr.assign_group(uid, test.id)
                value = 4.0 if group == "B" else 3.5  # B 稍好
                mgr.record_observation(test_id=test.id, session_id=uid,
                                       group=group, metric_value=value,
                                       metric_name="user_satisfaction")

            # 分析
            result = mgr.get_test_result(test.id)
            assert result.sample_a > 0
            assert result.sample_b > 0
            assert result.test_id == test.id

            # 清理
            mgr.complete_test(test.id)


class TestConsistencyTrackerIntegration:
    """一致性追踪集成测试"""

    def test_consistency_tracking(self):
        """人工标注和一致性计算"""
        from app.agent.eval.llm_judge import ConsistencyTracker
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConsistencyTracker(base_dir=tmpdir)

            # 模拟几条配对标注
            tracker.record_human_annotation(
                session_id="s1", human_score=4.0, human_passed=True,
                llm_score=4.2, llm_passed=True,
            )
            tracker.record_human_annotation(
                session_id="s2", human_score=2.0, human_passed=False,
                llm_score=4.5, llm_passed=True,  # 不一致！
            )
            tracker.record_human_annotation(
                session_id="s3", human_score=3.5, human_passed=True,
                llm_score=3.3, llm_passed=True,
            )

            report = tracker.get_consistency_report()
            assert report["total_annotations"] == 3
            assert report["paired_annotations"] == 3
            assert 0.0 <= report["agreement_rate"] <= 1.0
