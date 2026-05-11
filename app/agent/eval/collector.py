"""
CrabRes Eval — MetricsCollector

L1/L2 评估指标收集器。把每次 session 的关键指标（TCR / RDR / EAR / TPT / CPT
/ TTC / DGR / PGR 等，定义见 EVALUATION.md）落盘成 JSONL，便于按天聚合、
对外暴露 /api/eval/summary 与 /api/eval/health。

设计原则：
- **写路径零阻塞**：record_session 任何异常都 swallow + log.debug，决不影响主流程。
- **读路径只在请求时聚合**：JSONL 单文件 per day，按 days 参数倒推扫描，
  数量级在万行内的话开销可忽略；超过再考虑加索引。
- **无依赖**：纯标准库（pathlib + json + datetime），不引入额外服务。

数据布局：
    .crabres/eval/
    └── sessions/
        ├── 2026-05-11.jsonl
        ├── 2026-05-12.jsonl
        └── ...
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _default_eval_dir() -> Path:
    """评估数据目录 — 走 Render 持久盘（如有），否则本地 .crabres/eval。"""
    render_disk = os.environ.get("RENDER_DISK_PATH", "")
    base = Path(render_disk) / "eval" if render_disk else Path(".crabres/eval")
    (base / "sessions").mkdir(parents=True, exist_ok=True)
    return base


class MetricsCollector:
    """JSONL-backed session metrics collector. Thread-safe enough for asyncio."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or _default_eval_dir()
        (self.base_dir / "sessions").mkdir(parents=True, exist_ok=True)

    # ===== write path =====

    def record_session(self, session_id: str, metrics: dict) -> None:
        """
        追加一条 session 指标。

        metrics dict 至少包含 EVALUATION.md 定义的 Layer-1/2 指标：
        - tcr / rdr / ear / lcr / dgr / pgr  (capability)
        - tpt / cpt / ttc / ttfr / fbr / kie / mhr  (efficiency)
        - 任意其它附加字段都会原样保留。

        失败时只记 debug 日志，不抛异常 — 评估系统绝不能影响主流程。
        """
        try:
            row = {
                "session_id": session_id,
                "ts": time.time(),
                "ts_iso": datetime.now(timezone.utc).isoformat(),
                **(metrics or {}),
            }
            path = self._path_for_today()
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.debug(f"MetricsCollector.record_session failed (non-fatal): {e}")

    def record_assertion(self, scenario: str, passed: bool, detail: str = "") -> None:
        """L1 评估时记录单条断言结果（runner.py 内调用）。"""
        try:
            row = {
                "type": "assertion", "scenario": scenario,
                "passed": bool(passed), "detail": detail[:500],
                "ts": time.time(), "ts_iso": datetime.now(timezone.utc).isoformat(),
            }
            path = self.base_dir / "sessions" / f"assertions-{self._today_str()}.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.debug(f"MetricsCollector.record_assertion failed: {e}")

    # ===== read path =====

    def get_summary(self, days: int = 7) -> dict:
        """
        聚合最近 N 天的 session 指标。

        Returns:
            {
              "sessions"      : 总会话数,
              "avg_tcr/ear...": 各指标的平均值（无数据则缺省）,
              "p50_ttc/cpt"   : 中位数,
              "p95_ttc/cpt"   : 95 百分位,
              "by_day"        : {"YYYY-MM-DD": count, ...},
              "language_mix"  : {"en": N, "zh": M, ...},
              "window_days"   : 时间窗口（输入回显）,
            }
        """
        rows = list(self._iter_recent_rows(days))
        n = len(rows)
        if n == 0:
            return {"sessions": 0, "window_days": days}

        def _avg(key: str) -> Optional[float]:
            vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
            return round(sum(vals) / len(vals), 4) if vals else None

        def _percentile(key: str, p: float) -> Optional[float]:
            vals = sorted(r[key] for r in rows if isinstance(r.get(key), (int, float)))
            if not vals:
                return None
            k = max(0, min(len(vals) - 1, int(p * (len(vals) - 1))))
            return round(vals[k], 4)

        # daily counts
        by_day: dict[str, int] = {}
        lang_mix: dict[str, int] = {}
        for r in rows:
            day = (r.get("ts_iso") or "")[:10]
            if day:
                by_day[day] = by_day.get(day, 0) + 1
            lang = r.get("language") or "?"
            lang_mix[lang] = lang_mix.get(lang, 0) + 1

        return {
            "sessions": n,
            "window_days": days,
            "avg_tcr": _avg("tcr"),
            "avg_rdr": _avg("rdr"),
            "avg_ear": _avg("ear"),
            "avg_dgr": _avg("dgr"),
            "avg_pgr": _avg("pgr"),
            "avg_tpt": _avg("tpt"),
            "avg_cpt": _avg("cpt"),
            "avg_ttc": _avg("ttc"),
            "p50_ttc": _percentile("ttc", 0.50),
            "p95_ttc": _percentile("ttc", 0.95),
            "p50_cpt": _percentile("cpt", 0.50),
            "p95_cpt": _percentile("cpt", 0.95),
            "by_day": by_day,
            "language_mix": lang_mix,
        }

    # ===== helpers =====

    def _today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _path_for_today(self) -> Path:
        return self.base_dir / "sessions" / f"{self._today_str()}.jsonl"

    def _iter_recent_rows(self, days: int):
        """Yield session rows from the last N days (UTC)."""
        sessions_dir = self.base_dir / "sessions"
        if not sessions_dir.exists():
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        for path in sorted(sessions_dir.glob("*.jsonl")):
            # 文件名带 "assertions-" 前缀的是 L1 断言数据，不混入 session 聚合
            if path.name.startswith("assertions-"):
                continue
            try:
                day_str = path.stem  # "2026-05-11"
                day = datetime.strptime(day_str, "%Y-%m-%d").date()
                if day < cutoff:
                    continue
            except ValueError:
                continue  # 文件名不是日期格式 → 跳过
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue


# ===== module-level singleton =====

_singleton: Optional[MetricsCollector] = None


def get_collector() -> MetricsCollector:
    """Lazy singleton — first call creates the collector + ensures dirs exist."""
    global _singleton
    if _singleton is None:
        _singleton = MetricsCollector()
    return _singleton
