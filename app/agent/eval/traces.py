"""
CrabRes Eval System — L2: Trace Logging

会话轨迹记录系统。对应 hamel.dev/evals 中的 "Logging Traces"：
- 记录一系列事件日志（用户会话 / Agent 请求流）
- 不依赖 LangSmith，自建轻量级追踪
- 支持回放、可视化、标注

Trace 结构：
  SessionTrace
    ├── Event (每个事件是一个节点)
    │   ├── type: think | tool_call | expert | output | error | ...
    │   ├── timestamp
    │   ├── duration_ms
    │   ├── input / output
    │   └── metadata (tokens, model, cost, ...)
    └── Summary (聚合指标)

用途：
  1. 调试：复现问题场景
  2. 评估：给 LLM Judge 提供完整上下文
  3. 标注：人工审核具体决策点
  4. 分析：发现性能瓶颈和异常模式
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型枚举"""
    # 阶段事件
    SESSION_START = "session_start"
    ROUTE_DECISION = "route_decision"
    PHASE_ENTER = "phase_enter"
    PHASE_EXIT = "phase_exit"

    # LLM 事件
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    LLM_FALLBACK = "llm_fallback"

    # 工具事件
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"

    # 专家事件
    EXPERT_ACTIVATE = "expert_activate"
    EXPERT_OUTPUT = "expert_output"
    EXPERT_TIMEOUT = "expert_timeout"

    # 输出事件
    OUTPUT_GENERATED = "output_generated"
    DELIVERABLE_CREATED = "deliverable_created"

    # Compaction 事件
    COMPACTION_TRIGGERED = "compaction_triggered"
    COMPACTION_SUMMARY = "compaction_summary"
    COMPACTION_FALLBACK = "compaction_fallback"

    # 错误事件
    ERROR_OCCURRED = "error_occurred"
    ERROR_RECOVERY = "error_recovery"

    # 用户事件
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"


@dataclass
class TraceEvent:
    """单个 Trace 事件"""
    event_id: str = ""
    event_type: EventType = EventType.SESSION_START
    timestamp: float = 0.0
    duration_ms: float = 0.0

    # 数据负载
    input_data: Any = None
    output_data: Any = None
    metadata: dict = field(default_factory=dict)

    # 关联信息
    parent_event_id: str | None = None     # 父事件（用于嵌套）
    phase: str = ""                        # 当前阶段
    session_id: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"evt-{uuid.uuid4().hex[:8]}"
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "type": self.event_type.value,
            "timestamp": self.timestamp,
            "duration_ms": round(self.duration_ms, 2),
            "input": self._serialize(self.input_data),
            "output": self._serialize(self.output_data),
            "metadata": self.metadata,
            "parent": self.parent_event_id,
            "phase": self.phase,
        }

    @staticmethod
    def _serialize(data: Any) -> Any:
        """序列化数据，截断过大的字段"""
        if data is None:
            return None
        if isinstance(data, str):
            return data[:2000] if len(data) > 2000 else data
        if isinstance(data, dict):
            return {k: TraceEvent._serialize(v)[:500] if isinstance(v, str) else v for k, v in list(data.items())[:20]}
        if isinstance(data, (list, tuple)):
            items = list(data)[:10]
            return [TraceEvent._serialize(i)[:200] if isinstance(i, str) else i for i in items]
        return str(data)[:500]


@dataclass
class SessionSummary:
    """会话摘要 — 从 trace 中聚合的指标"""
    session_id: str = ""
    total_events: int = 0
    total_duration_s: float = 0.0

    # LLM 指标
    llm_call_count: int = 0
    llm_total_tokens: int = 0
    llm_total_cost_usd: float = 0.0
    llm_fallback_count: int = 0

    # 工具指标
    tool_call_count: int = 0
    tool_error_count: int = 0

    # 专家指标
    expert_count: int = 0
    expert_timeout_count: int = 0

    # Compaction 指标
    compaction_count: int = 0

    # 错误指标
    error_count: int = 0
    recovery_count: int = 0

    # 输出
    output_count: int = 0
    deliverable_count: int = 0

    # 路由
    route_mode: str = ""
    route_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "total_events": self.total_events,
            "duration_s": round(self.total_duration_s, 2),
            "llm": {
                "calls": self.llm_call_count,
                "tokens": self.llm_total_tokens,
                "cost_usd": round(self.llm_total_cost_usd, 6),
                "fallbacks": self.llm_fallback_count,
            },
            "tools": {"calls": self.tool_call_count, "errors": self.tool_error_count},
            "experts": {"activated": self.expert_count, "timeouts": self.expert_timeout_count},
            "compactions": self.compaction_count,
            "errors": {"count": self.error_count, "recoveries": self.recovery_count},
            "outputs": {"responses": self.output_count, "deliverables": self.deliverable_count},
            "route": {"mode": self.route_mode, "reason": self.route_reason},
        }


class TraceCollector:
    """
    会话轨迹收集器。

    使用方式：
        tracer = TraceCollector(session_id="abc")
        tracer.start_session(product_info={...})

        tracer.record(EventType.ROUTE_DECISION, ..., metadata={"mode": "pipeline"})
        tracer.record(EventType.LLM_CALL, input_data=prompt)
        tracer.record(EventType.LLM_RESPONSE, output_data=response, duration_ms=1200)

        tracer.end_session()
        summary = tracer.get_summary()
        tracer.save()  # 写入 .crabres/eval/traces/
    """

    def __init__(self, session_id: str = "", base_dir: str = ".crabres/eval/traces"):
        self.session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.events: list[TraceEvent] = []
        self._start_time: float = 0.0
        self._current_phase: str = ""
        self._session_metadata: dict = {}

    def start_session(self, **metadata):
        """开始一个新会话 trace"""
        self._start_time = time.time()
        self._session_metadata = metadata
        self.record(
            EventType.SESSION_START,
            metadata=metadata,
        )

    def end_session(self):
        """结束会话 trace"""
        duration = time.time() - self._start_time
        self.record(
            EventType.PHASE_EXIT,
            phase="session",
            duration_ms=duration * 1000,
        )
        logger.info(f"[Trace] Session {self.session_id}: {len(self.events)} events, {duration:.1f}s")

    def record(
        self,
        event_type: EventType,
        *,
        input_data: Any = None,
        output_data: Any = None,
        duration_ms: float = 0.0,
        metadata: dict | None = None,
        parent_event_id: str | None = None,
    ) -> TraceEvent:
        """记录一个事件"""
        event = TraceEvent(
            event_type=event_type,
            duration_ms=duration_ms,
            input_data=input_data,
            output_data=output_data,
            metadata=metadata or {},
            parent_event_id=parent_event_id,
            phase=self._current_phase,
            session_id=self.session_id,
        )
        self.events.append(event)
        return event

    # ===== 便捷方法 =====

    def record_route(self, mode: str, reason: str, confidence: float = 1.0):
        """记录路由决策"""
        return self.record(
            EventType.ROUTE_DECISION,
            metadata={"mode": mode, "reason": reason, "confidence": confidence},
        )

    def record_phase_enter(self, phase: str):
        """记录进入新阶段"""
        self._current_phase = phase
        return self.record(EventType.PHASE_ENTER, metadata={"phase": phase})

    def record_llm_call(
        self,
        prompt: str,
        tier: str = "",
        model_hint: str = "",
    ) -> TraceEvent:
        """记录 LLM 调用（返回 event 以便后续匹配 response）"""
        return self.record(
            EventType.LLM_CALL,
            input_data=prompt,
            metadata={"tier": tier, "model_hint": model_hint},
        )

    def record_llm_response(
        self,
        call_event: TraceEvent,
        response: str,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        model_display: str = "",
        is_fallback: bool = False,
    ):
        """记录 LLM 响应"""
        evt_type = EventType.LLM_FALLBACK if is_fallback else EventType.LLM_RESPONSE
        return self.record(
            evt_type,
            output_data=response,
            parent_event_id=call_event.event_id,
            metadata={
                "tokens": tokens_used,
                "cost_usd": cost_usd,
                "model": model_display,
                "is_fallback": is_fallback,
            },
        )

    def record_tool_call(self, tool_name: str, args: dict):
        """记录工具调用"""
        return self.record(
            EventType.TOOL_CALL,
            input_data=args,
            metadata={"tool": tool_name},
        )

    def record_tool_result(self, call_event: TraceEvent, result: Any, success: bool = True):
        """记录工具结果"""
        evt_type = EventType.TOOL_RESULT if success else EventType.TOOL_ERROR
        return self.record(
            evt_type,
            output_data=result,
            parent_event_id=call_event.event_id,
        )

    def record_expert(self, expert_id: str, task: str, output: str = "", timeout: bool = False):
        """记录专家激活/输出"""
        evt_type = EventType.EXPERT_TIMEOUT if timeout else (
            EventType.EXPERT_OUTPUT if output else EventType.EXPERT_ACTIVATE
        )
        meta = {"expert_id": expert_id, "task": task}
        if timeout:
            meta["timeout"] = True
        return self.record(evt_type, output_data=output or None, metadata=meta)

    def record_compaction(self, summary_text: str, msg_count: int, fallback: bool = False):
        """记录 compaction 事件"""
        evt_type = EventType.COMPACTION_FALLBACK if fallback else EventType.COMPACTION_SUMMARY
        return self.record(
            evt_type,
            output_data=summary_text,
            metadata={"msg_compressed": msg_count, "fallback": fallback},
        )

    def record_error(self, error: str, level: str = "L1", recovered: bool = False):
        """记录错误/恢复"""
        evt_type = EventType.ERROR_RECOVERY if recovered else EventType.ERROR_OCCURRED
        return self.record(evt_type, metadata={"error": error, "level": level})

    def record_output(self, content: str, output_type: str = "response"):
        """记录输出"""
        return self.record(
            EventType.OUTPUT_GENERATED,
            output_data=content,
            metadata={"type": output_type},
        )

    def record_deliverable(self, deliverable_type: str, content_preview: str = ""):
        """记录交付物生成"""
        return self.record(
            EventType.DELIVERABLE_CREATED,
            output_data=content_preview,
            metadata={"type": deliverable_type},
        )

    # ===== 聚合与持久化 =====

    def get_summary(self) -> SessionSummary:
        """从 events 聚合出会话摘要"""
        s = SessionSummary(session_id=self.session_id)
        s.total_events = len(self.events)
        s.total_duration_s = time.time() - self._start_time if self._start_time else 0

        for evt in self.events:
            t = evt.event_type
            m = evt.metadata

            if t == EventType.LLM_CALL:
                s.llm_call_count += 1
            elif t == EventType.LLM_RESPONSE:
                s.llm_total_tokens += m.get("tokens", 0)
                s.llm_total_cost_usd += m.get("cost_usd", 0.0)
            elif t == EventType.LLM_FALLBACK:
                s.llm_fallback_count += 1
            elif t == EventType.TOOL_CALL:
                s.tool_call_count += 1
            elif t == EventType.TOOL_ERROR:
                s.tool_error_count += 1
            elif t == EventType.EXPERT_ACTIVATE:
                s.expert_count += 1
            elif t == EventType.EXPERT_TIMEOUT:
                s.expert_timeout_count += 1
            elif t == EventType.COMPACTION_SUMMARY:
                s.compaction_count += 1
            elif t == EventType.ERROR_OCCURRED:
                s.error_count += 1
            elif t == EventType.ERROR_RECOVERY:
                s.recovery_count += 1
            elif t == EventType.OUTPUT_GENERATED:
                s.output_count += 1
            elif t == EventType.DELIVERABLE_CREATED:
                s.deliverable_count += 1
            elif t == EventType.ROUTE_DECISION:
                s.route_mode = m.get("mode", "")
                s.route_reason = m.get("reason", "")

        return s

    def save(self) -> str:
        """保存 trace 到文件，返回文件路径"""
        summary = self.get_summary()

        trace_data = {
            "session_id": self.session_id,
            "start_time": self._start_time,
            "end_time": time.time(),
            "summary": summary.to_dict(),
            "session_metadata": self._session_metadata,
            "events": [e.to_dict() for e in self.events],
        }

        # 保存为 JSON
        filename = f"{self.session_id}.json"
        path = self.base_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, ensure_ascii=False, indent=2)

        # 同时追加到索引文件
        index_path = self.base_dir / "_index.jsonl"
        index_entry = {
            "session_id": self.session_id,
            "timestamp": self._start_time,
            "summary": summary.to_dict(),
            "file": filename,
        }
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(index_entry, ensure_ascii=False) + "\n")

        logger.info(f"[Trace] Saved to {path} ({len(self.events)} events)")
        return str(path)

    @staticmethod
    def load(session_id: str, base_dir: str = ".crabres/eval/traces") -> dict | None:
        """加载历史 trace"""
        path = Path(base_dir) / f"{session_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    @staticmethod
    def list_recent(limit: int = 20, base_dir: str = ".crabres/eval/traces") -> list[dict]:
        """列出最近的 trace 会话"""
        index_path = Path(base_dir) / "_index.jsonl"
        if not index_path.exists():
            return []

        entries = []
        for line in index_path.read_text().strip().split("\n"):
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        entries.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return entries[:limit]


# =====================================================================
# 全局 Trace Hook — 注入到 AgentLoop 中自动收集
# =====================================================================

_global_tracer: TraceCollector | None = None


def get_tracer(session_id: str = "") -> TraceCollector:
    """获取当前线程的 trace 收集器"""
    global _global_tracer
    if _global_tracer is None or (session_id and _global_tracer.session_id != session_id):
        _global_tracer = TraceCollector(session_id=session_id)
    return _global_tracer


def clear_tracer():
    """清除全局 tracer（会话结束时调用）"""
    global _global_tracer
    _global_tracer = None
