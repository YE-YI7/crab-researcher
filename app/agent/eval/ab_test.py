"""
CrabRes Eval System — L3: A/B Test Framework

A/B 测试基础设施。对应 hamel.dev/evals 中 "L3: A/B test"：
- LLM 的 AB 测和其他类型产品没有太大不同
- 核心能力：分组、流量分配、指标对比、统计显著性检验

设计原则：
- 轻量级：不需要复杂的基础设施，基于本地文件 + 内存
- 安全：支持自动回滚（当 B 组显著差于 A 时）
- 灵活：可以测试任何可配置的参数（prompt、模型选择、路由策略等）

使用示例：
    ab = ABTestManager()
    test = ab.create_test(
        name="compaction_llm_vs_truncate",
        description="Test LLM compaction vs hard truncate",
        config_a={"compaction_mode": "truncate"},
        config_b={"compaction_mode": "llm"},
        metric="user_satisfaction_score",
        hypothesis="B > A",  # B 应该更好
        min_sample_size=50,
    )

    # 分配用户到组
    group = ab.assign_group(session_id="user-123", test_id=test.id)

    # 记录结果
    ab.record_result(test_id=test.id, session_id="user-123",
                     group=group, metric_value=4.2)

    # 检查是否有显著差异
    result = ab.get_test_result(test.id)
    if result["is_significant"] and result["winner"] == "B":
        print("LLM compaction is significantly better!")
"""

from __future__ import annotations

import json
import logging
import time
import uuid
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TestStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"   # B 显著更差，已回滚


@dataclass
class ABTestConfig:
    """单个 A/B Test 的配置"""
    id: str = ""
    name: str = ""
    description: str = ""

    # 变体配置
    config_a: dict = field(default_factory=dict)     # Control (A) 组配置
    config_b: dict = field(default_factory=dict)     # Treatment (B) 组配置

    # 目标指标
    primary_metric: str = ""          # 主要评估指标（如 "user_satisfaction_score"）
    secondary_metrics: list[str] = field(default_factory=list)

    # 假设
    hypothesis: str = ""              # "B > A" | "B < A" | "B != A"

    # 流量分配
    traffic_split: float = 0.5       # B 组占比 (0.0 - 1.0)，默认 50/50

    # 样本量
    min_sample_size: int = 30         # 每组最小样本量
    max_sample_size: int = 1000       # 最大样本量（到达后自动结束）

    # 统计
    significance_level: float = 0.05  # α = 0.05
    min_detectable_effect: float = 0.1  # 最小可检测效应量

    # 状态
    status: TestStatus = TestStatus.DRAFT
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0

    # 自动回滚
    auto_rollback: bool = True        # 当 B 显著更差时自动回滚
    rollback_threshold: float = -0.1  # B 比 A 差超过此阈值时回滚（负数表示 B 更差）


@dataclass
class ABTestResult:
    """A/B Test 的分析结果"""
    test_id: str = ""
    status: TestStatus = TestStatus.RUNNING

    # 样本量
    sample_a: int = 0
    sample_b: int = 0

    # 指标值
    mean_a: float = 0.0
    mean_b: float = 0.0
    std_a: float = 0.0
    std_b: float = 0.0

    # 统计检验
    effect_size: float = 0.0         # Cohen's d
    p_value: float = 1.0
    is_significant: bool = False
    confidence_interval: tuple = (0.0, 0.0)

    # 结论
    winner: str | None = None        # "A" | "B" | None (no significant diff)
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "status": self.status.value,
            "samples": {"A": self.sample_a, "B": self.sample_b},
            "means": {"A": round(self.mean_a, 4), "B": round(self.mean_b, 4)},
            "effect_size": round(self.effect_size, 4),
            "p_value": round(self.p_value, 4),
            "is_significant": self.is_significant,
            "winner": self.winner,
            "recommendation": self.recommendation,
        }


@dataclass
class Observation:
    """单次观测数据"""
    test_id: str = ""
    session_id: str = ""
    group: str = ""                   # "A" or "B"
    metric_name: str = ""
    metric_value: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class ABTestManager:
    """
    A/B Test 管理器。

    功能：
      1. 创建/管理测试
      2. 一致性哈希分组（同一用户总是分到同一组）
      3. 记录观测数据
      4. 统计显著性检验（Welch's t-test 近似）
      5. 自动回滚
    """

    def __init__(self, base_dir: str = ".crabres/eval/ab_tests"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._tests: dict[str, ABTestConfig] = {}
        _observations: list[Observation] = []
        self._observations = _observations
        self._assignments: dict[str, dict] = {}  # {session_id: {test_id: group}}
        self._load_tests()

    def _load_tests(self):
        """从文件加载已有测试"""
        tests_path = self.base_dir / "_tests.json"
        if tests_path.exists():
            try:
                data = json.loads(tests_path.read_text())
                for tid, tdata in data.items():
                    t = ABTestConfig(**{**tdata, "id": tid})
                    t.status = TestStatus(tdata.get("status", "draft"))
                    self._tests[tid] = t
            except (json.JSONDecodeError, TypeError):
                pass

    def _save_tests(self):
        """持久化测试配置"""
        tests_path = self.base_dir / "_tests.json"
        data = {}
        for tid, t in self._tests.items():
            d = {
                "name": t.name,
                "description": t.description,
                "config_a": t.config_a,
                "config_b": t.config_b,
                "primary_metric": t.primary_metric,
                "secondary_metrics": t.secondary_metrics,
                "hypothesis": t.hypothesis,
                "traffic_split": t.traffic_split,
                "min_sample_size": t.min_sample_size,
                "max_sample_size": t.max_sample_size,
                "significance_level": t.significance_level,
                "auto_rollback": t.auto_rollback,
                "rollback_threshold": t.rollback_threshold,
                "status": t.status.value,
                "created_at": t.created_at,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
            }
            data[tid] = d
        tests_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # ===== CRUD =====

    def create_test(
        self,
        name: str,
        *,
        description: str = "",
        config_a: dict | None = None,
        config_b: dict | None = None,
        primary_metric: str = "",
        hypothesis: str = "B > A",
        traffic_split: float = 0.5,
        min_sample_size: int = 30,
        auto_rollback: bool = True,
    ) -> ABTestConfig:
        """创建新的 A/B Test"""
        test_id = f"ab-{uuid.uuid4().hex[:8]}"
        test = ABTestConfig(
            id=test_id,
            name=name,
            description=description,
            config_a=config_a or {},
            config_b=config_b or {},
            primary_metric=primary_metric,
            hypothesis=hypothesis,
            traffic_split=max(0.0, min(1.0, traffic_split)),
            min_sample_size=min_sample_size,
            auto_rollback=auto_rollback,
        )
        self._tests[test_id] = test
        self._save_tests()
        logger.info(f"[ABTest] Created: {test_id} — {name}")
        return test

    def start_test(self, test_id: str) -> ABTestConfig:
        """启动测试"""
        test = self._get_test(test_id)
        test.status = TestStatus.RUNNING
        test.started_at = time.time()
        self._save_tests()
        logger.info(f"[ABTest] Started: {test_id}")
        return test

    def pause_test(self, test_id: str) -> ABTestConfig:
        """暂停测试"""
        test = self._get_test(test_id)
        test.status = TestStatus.PAUSED
        self._save_tests()
        return test

    def complete_test(self, test_id: str) -> ABTestResult:
        """完成测试并生成最终结果"""
        test = self._get_test(test_id)
        test.status = TestStatus.COMPLETED
        test.completed_at = time.time()
        self._save_tests()
        return self.get_test_result(test_id)

    def get_test(self, test_id: str) -> ABTestConfig | None:
        return self._tests.get(test_id)

    def list_tests(self, active_only: bool = False) -> list[ABTestConfig]:
        tests = list(self._tests.values())
        if active_only:
            tests = [t for t in tests if t.status == TestStatus.RUNNING]
        return sorted(tests, key=lambda t: t.created_at, reverse=True)

    # ===== 分组 =====

    def assign_group(self, session_id: str, test_id: str) -> str:
        """
        为用户分配测试组。

        使用一致性哈希：同一用户在同一测试中总是分到相同组。
        """
        test = self._get_test(test_id)

        # 先检查缓存
        cache_key = f"{session_id}:{test_id}"
        if cache_key in self._assignments:
            return self._assignments[cache_key].get("group", "A")

        # 一致性哈希
        hash_input = f"{test_id}:{session_id}"
        hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        normalized = hash_val / (2 ** 128)  # 归一化到 [0, 1)

        group = "B" if normalized < test.traffic_split else "A"

        # 缓存
        self._assignments[cache_key] = {"group": group, "assigned_at": time.time()}
        return group

    def get_config(self, session_id: str, test_id: str) -> dict:
        """获取用户所在组的配置"""
        test = self._get_test(test_id)
        group = self.assign_group(session_id, test_id)
        return test.config_b if group == "B" else test.config_a

    # ===== 数据记录 =====

    def record_observation(
        self,
        test_id: str,
        session_id: str,
        group: str,
        metric_name: str,
        metric_value: float,
        metadata: dict | None = None,
    ):
        """记录一次观测数据"""
        obs = Observation(
            test_id=test_id,
            session_id=session_id,
            group=group,
            metric_name=metric_name,
            metric_value=metric_value,
            metadata=metadata or {},
        )
        self._observations.append(obs)

        # 追加到文件
        obs_path = self.base_dir / f"{test_id}_observations.jsonl"
        with open(obs_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "session_id": session_id,
                "group": group,
                "metric": metric_name,
                "value": metric_value,
                "timestamp": obs.timestamp,
            }, ensure_ascii=False) + "\n")

        # 检查是否需要自动停止/回滚
        self._check_auto_actions(test_id)

    def record_result(self, **kwargs):
        """record_observation 的别名"""
        self.record_observation(**kwargs)

    # ===== 分析 =====

    def get_test_result(self, test_id: str) -> ABTestResult:
        """计算测试结果和统计显著性"""
        test = self._get_test(test_id)
        metric = test.primary_metric

        # 过滤该测试的观测
        obs = [o for o in self._observations if o.test_id == test_id and o.metric_name == metric]
        obs_a = [o.metric_value for o in obs if o.group == "A"]
        obs_b = [o.metric_value for o in obs if o.group == "B"]

        n_a, n_b = len(obs_a), len(obs_b)

        if n_a == 0 and n_b == 0:
            return ABTestResult(test_id=test_id, status=test.status)

        # 基本统计
        mean_a = sum(obs_a) / n_a if n_a else 0
        mean_b = sum(obs_b) / n_b if n_b else 0
        var_a = sum((x - mean_a) ** 2 for x in obs_a) / (n_a - 1) if n_a > 1 else 0
        var_b = sum((x - mean_b) ** 2 for x in obs_b) / (n_b - 1) if n_b > 1 else 0
        std_a = var_a ** 0.5
        std_b = var_b ** 0.5

        # Welch's t-test 近似（简化版）
        p_value, effect_size, is_sig = self._welch_t_test(obs_a, obs_b, test.significance_level)

        # 判定赢家
        winner = None
        if is_sig:
            if mean_b > mean_a:
                winner = "B"
            else:
                winner = "A"

        # 生成建议
        recommendation = self._generate_recommendation(
            test, n_a, n_b, mean_a, mean_b, p_value, is_sig, winner
        )

        return ABTestResult(
            test_id=test_id,
            status=test.status,
            sample_a=n_a,
            sample_b=n_b,
            mean_a=mean_a,
            mean_b=mean_b,
            std_a=std_a,
            std_b=std_b,
            effect_size=effect_size,
            p_value=p_value,
            is_significant=is_sig,
            winner=winner,
            recommendation=recommendation,
        )

    def _welch_t_test(
        self,
        group_a: list[float],
        group_b: list[float],
        alpha: float = 0.05,
    ) -> tuple[float, float, bool]:
        """
        简化的 Welch's t-test。

        Returns:
            (p_value, effect_size_cohens_d, is_significant)
        """
        n_a, n_b = len(group_a), len(group_b)

        if n_a < 2 or n_b < 2:
            return 1.0, 0.0, False

        mean_a = sum(group_a) / n_a
        mean_b = sum(group_b) / n_b
        var_a = sum((x - mean_a) ** 2 for x in group_a) / (n_a - 1)
        var_b = sum((x - mean_b) ** 2 for x in group_b) / (n_b - 1)

        # Effect size (Cohen's d)
        pooled_std = ((var_a + var_b) / 2) ** 0.5
        effect_size = abs(mean_b - mean_a) / pooled_std if pooled_std > 0 else 0.0

        # t-statistic
        se = (var_a / n_a + var_b / n_b) ** 0.5
        if se == 0:
            return 1.0, effect_size, False

        t_stat = (mean_b - mean_a) / se

        # 自由度 (Welch-Satterthwaite)
        num = (var_a / n_a + var_b / n_b) ** 2
        denom = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
        df = num / denom if denom > 0 else 1

        # 简化的 p-value 近似（对于大样本用正态近似）
        # 这里使用简化的近似方法
        import math
        if df > 30:
            # 正态近似
            p_value = 2 * (1 - self._normal_cdf(abs(t_stat)))
        else:
            # 对于小自由度，使用粗略近似
            p_value = max(0.0, min(1.0, 2 * (1 - self._t_approx(abs(t_stat), df))))

        is_significant = p_value < alpha and n_a >= 2 and n_b >= 2
        return round(p_value, 6), round(effect_size, 4), is_significant

    @staticmethod
    def _normal_cdf(x: float) -> float:
        """标准正态分布 CDF 近似"""
        import math
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    @staticmethod
    def _t_approx(t: float, df: float) -> float:
        """t 分布 CDF 粗略近似"""
        import math
        if df <= 0:
            return 0.5
        x = df / (df + t * t)
        return 1 - 0.5 * (x ** (df / 2)) if t > 0 else 0.5 * (x ** (df / 2))

    def _generate_recommendation(
        self, test, n_a, n_b, mean_a, mean_b, p_value, is_sig, winner
    ) -> str:
        """生成建议文本"""
        total = n_a + n_b
        min_n = test.min_sample_size

        if total < min_n:
            return f"Collecting samples ({total}/{min_n_n}). Not enough data yet."

        if not is_sig:
            return (
                f"No significant difference (p={p_value:.3f}). "
                f"A={mean_a:.3f}, B={mean_b:.3f}. Consider increasing sample size or ending test."
            )

        direction = "better" if winner == "B" else "worse"
        pct_diff = ((mean_b - mean_a) / mean_a * 100) if mean_a != 0 else 0

        if winner == "B":
            return (
                f"B is significantly {direction} than A (p={p_value:.3f}, "
                f"effect={self.get_test_result(test.id).effect_size:.2f}, "
                f"+{abs(pct_diff):.1f}%). Consider rolling out B."
            )
        else:
            if test.auto_rollback and pct_diff < test.rollback_threshold * 100:
                return (
                    f"A is significantly better (p={p_value:.3f}, B is {pct_diff:.1f}% worse). "
                    f"AUTO-ROLLBACK recommended."
                )
            return (
                f"A is significantly better (p={p_value:.3f}, B is {pct_diff:.1f}% worse). "
                f"Keep using A."
            )

    def _check_auto_actions(self, test_id: str):
        """检查是否需要自动操作（停止/回滚）"""
        test = self._get_test(test_id)
        if test.status != TestStatus.RUNNING:
            return

        result = self.get_test_result(test_id)
        total = result.sample_a + result.sample_b

        # 达到最大样本量 → 自动完成
        if total >= test.max_sample_size:
            logger.info(f"[ABTest] {test_id} reached max sample size, completing")
            self.complete_test(test_id)
            return

        # 自动回滚：B 显著更差
        if (test.auto_rollback and result.is_significant and
                result.winner == "A" and
                result.mean_b < result.mean_a * (1 + test.rollback_threshold)):
            logger.warning(
                f"[ABTest] AUTO-ROLLBACK {test_id}: "
                f"A={result.mean_a:.3f} > B={result.mean_b:.3f}"
            )
            test.status = TestStatus.ROLLED_BACK
            self._save_tests()

    def _get_test(self, test_id: str) -> ABTestConfig:
        test = self._tests.get(test_id)
        if not test:
            raise ValueError(f"Test not found: {test_id}")
        return test


# 导入 hashlib（在文件顶部使用）
import hashlib
