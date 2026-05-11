"""
CrabRes Agent Engine — 统一状态定义

合并 LoopState / PipelineState / OrchestratorContext 为单一状态类，
消除三套引擎之间的状态重复和格式不一致问题。
"""

import time
from dataclasses import dataclass, field
from enum import Enum


class ExecutionMode(str, Enum):
    """Agent 执行模式"""
    PIPELINE = "pipeline"       # 确定性流水线（默认）
    REACT = "react"             # ReAct 自主循环（高信任用户）
    QUICK = "quick"             # 快速回复（打招呼、闲聊）


class Phase(str, Enum):
    """统一阶段枚举（兼容 LoopPhase + Stage）"""
    UNDERSTAND = "understand"
    RESEARCH = "research"
    EXPERT = "expert"
    SYNTHESIZE = "synthesize"
    DELIVER = "deliver"
    
    # ReAct 特有阶段（仅在 REACT 模式下使用）
    THINK = "think"
    OBSERVE = "observe"


@dataclass
class AgentState:
    """
    统一 Agent 状态 — 所有模式共享
    
    替代:
      - LoopState (loop.py)
      - PipelineState (pipeline.py)  
      - OrchestratorContext (orchestrator.py)
    """
    # === 基础标识 ===
    session_id: str
    mode: ExecutionMode = ExecutionMode.PIPELINE
    phase: Phase = Phase.UNDERSTAND
    
    # === 计数器 ===
    turn_count: int = 0
    total_tokens_used: int = 0
    token_budget: int = 100_000
    tool_call_count: int = 0
    ask_count: int = 0
    
    # === 时间 ===
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    
    # === 用户交互 ===
    language: str = "en"
    is_waiting_for_user: bool = False
    _message_history: list[dict] = field(default_factory=list)
    
    # === 产品信息（UNDERSTAND 阶段产出）===
    product_info: dict = field(default_factory=dict)
    has_product_info: bool = False
    intent: str = ""                    # "greeting" | "product_intro" | "growth_request" | ...
    is_self_awareness: bool = False
    direct_reply: str = ""              # 不走完整流程的直接回复

    # 细分交付意图 — 决定 DELIVER 阶段生成哪些产物
    # "full" | "competitor_only" | "content_only" | "plan_only" | "none"
    deliverable_intent: str = "full"

    # 深度研究模式 — node_research 会追加 1 轮 LLM 引导的扩展查询
    deep_research_mode: bool = False

    # === Pipeline 步数预算（防止异常路径无限循环）===
    pipeline_step_count: int = 0
    max_pipeline_steps: int = 20
    
    # === 研究数据（RESEARCH 阶段产出）===
    search_results: list[dict] = field(default_factory=list)
    scraped_pages: list[dict] = field(default_factory=list)
    browse_results: list[dict] = field(default_factory=list)
    scraped_urls: set[str] = field(default_factory=set)
    searched_queries: set[str] = field(default_factory=set)
    
    # === 专家数据（EXPERT 阶段产出）===
    expert_outputs: dict[str, object] = field(default_factory=dict)
    expert_ids_used: list[str] = field(default_factory=list)
    
    # === 综合输出（SYNTHESIZE 阶段产出）===
    synthesis: str = ""
    
    # === 交付物（DELIVER 阶段产出）===
    deliverables: list[dict] = field(default_factory=list)
    
    # === ReAct 模式特有 ===
    actions_history: list[object] = field(default_factory=list)
    pending_user_tasks: list[dict] = field(default_factory=list)
    consecutive_errors: int = 0
    max_loop_iterations: int = 10
    
    # === 目标平台（从 onboarding 提取）===
    target_platforms: list[str] = field(default_factory=list)
    
    @property
    def message_history(self) -> list[dict]:
        return self._message_history
    
    def add_message(self, role: str, content: str):
        self._message_history.append({"role": role, "content": content})
    
    def recent_messages(self, n: int = 12) -> list[dict]:
        return self._message_history[-n:]
    
    def to_checkpoint(self) -> dict:
        """序列化为检查点（用于持久化恢复）"""
        expert_outputs_serialized = {}
        for k, v in self.expert_outputs.items():
            expert_outputs_serialized[k] = v[:3000] if isinstance(v, str) else str(v)[:3000]
        
        return {
            "session_id": self.session_id,
            "mode": self.mode.value,
            "phase": self.phase.value,
            "turn_count": self.turn_count,
            "tokens_used": self.total_tokens_used,
            "token_budget": self.token_budget,
            "tool_call_count": self.tool_call_count,
            "product_info": self.product_info,
            "intent": self.intent,
            "expert_outputs": expert_outputs_serialized,
            "expert_outputs_keys": list(self.expert_outputs.keys()),
            "is_waiting": self.is_waiting_for_user,
            "target_platforms": self.target_platforms,
            "message_history": self._message_history[-50:],
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "checkpoint_version": 3,
        }
