"""
CrabRes Autonomous Decision Chain — Agent 自主决策能力

缺失能力 #3 + #4：
- Agent 不能自己决定执行操作（一切都要人确认）
- Agent 不能定时发帖/定时邮件

这是让 Agent 真正"自主"的关键：
- 低风险操作（搜索、分析、写草稿）→ 自动执行
- 中风险操作（发帖到测试账号）→ 需要确认但可预设自动
- 高风险操作（发帖到正式账号、花钱投广告）→ 必须人工确认

基于 Trust Level 动态调整自主权。
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class RiskLevel:
    LOW = "low"           # 搜索、分析、写草稿、保存竞品
    MEDIUM = "medium"     # 发帖到社媒、发邮件
    HIGH = "high"         # 花钱投广告、修改定价、删除内容


# 操作 → 风险等级映射
ACTION_RISK_MAP = {
    # 低风险（Agent 可自主执行）
    "web_search": RiskLevel.LOW,
    "social_search": RiskLevel.LOW,
    "scrape_website": RiskLevel.LOW,
    "browse_website": RiskLevel.LOW,
    "competitor_analyze": RiskLevel.LOW,
    "deep_scrape": RiskLevel.LOW,
    "write_post": RiskLevel.LOW,       # 写草稿是低风险
    "write_email": RiskLevel.LOW,
    "save_competitors": RiskLevel.LOW,
    "rss_check": RiskLevel.LOW,
    "crawl_competitor": RiskLevel.LOW,

    # 中风险（需要确认或 Trust Level >= Trusted）
    "publish_post": RiskLevel.MEDIUM,
    "send_email": RiskLevel.MEDIUM,
    "submit_directory": RiskLevel.MEDIUM,

    # 高风险（必须人工确认）
    "run_ads": RiskLevel.HIGH,
    "change_pricing": RiskLevel.HIGH,
    "delete_content": RiskLevel.HIGH,
}


@dataclass
class PendingAction:
    """等待确认的操作"""
    id: str = ""
    action_type: str = ""
    risk_level: str = ""
    description: str = ""
    details: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending / approved / rejected / auto_approved / executed
    auto_approve_at: Optional[float] = None  # 自动批准时间（如果设置了）


class AutonomousEngine:
    """
    自主决策引擎 — 管理 Agent 的自主权

    核心逻辑：
    1. 每个操作都有风险等级
    2. Trust Level 决定 Agent 可以自主执行哪些操作
    3. 超出自主权的操作进入"待确认"队列
    4. 用户可以设置"自动批准"规则（如"Reddit发帖自动批准"）
    """

    def __init__(self, memory=None, base_dir: str | Path | None = None):
        self.memory = memory
        self._base_dir = Path(base_dir or ".crabres/autonomous")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._pending: list[PendingAction] = []
        self._auto_rules: dict[str, bool] = {}  # action_type → auto_approve
        self._load_rules()
        self._load_pending()

    def can_auto_execute(self, action_type: str, trust_level: str = "cautious") -> bool:
        """判断某个操作是否可以自动执行"""
        risk = ACTION_RISK_MAP.get(action_type, RiskLevel.HIGH)

        # 低风险 → 始终自动执行
        if risk == RiskLevel.LOW:
            return True

        # 检查自动批准规则
        if self._auto_rules.get(action_type):
            return True

        # 中风险 → Trust Level >= trusted 时自动执行
        if risk == RiskLevel.MEDIUM:
            trust_hierarchy = ["cautious", "learning", "trusted", "autonomous"]
            trust_idx = trust_hierarchy.index(trust_level) if trust_level in trust_hierarchy else 0
            return trust_idx >= 2  # trusted 或 autonomous

        # 高风险 → 永远需要确认
        return False

    def request_approval(self, action_type: str, description: str, details: dict = None) -> PendingAction:
        """将操作加入待确认队列"""
        action = PendingAction(
            id=f"pending_{int(time.time()*1000)}",
            action_type=action_type,
            risk_level=ACTION_RISK_MAP.get(action_type, RiskLevel.HIGH),
            description=description,
            details=details or {},
        )
        self._pending.append(action)
        self._save_pending()
        logger.info(f"Approval requested: {action_type} — {description[:60]}")
        return action

    def approve(self, action_id: str) -> Optional[PendingAction]:
        """批准一个待确认操作"""
        for action in self._pending:
            if action.id == action_id:
                action.status = "approved"
                self._save_pending()
                return action
        return None

    def reject(self, action_id: str) -> Optional[PendingAction]:
        """拒绝一个待确认操作"""
        for action in self._pending:
            if action.id == action_id:
                action.status = "rejected"
                self._save_pending()
                return action
        return None

    def get_pending(self) -> list[PendingAction]:
        """获取所有待确认操作"""
        return [a for a in self._pending if a.status == "pending"]

    def get_approved(self) -> list[PendingAction]:
        """获取所有已批准待执行的操作"""
        return [a for a in self._pending if a.status == "approved"]

    def set_auto_rule(self, action_type: str, auto_approve: bool):
        """设置自动批准规则"""
        self._auto_rules[action_type] = auto_approve
        self._save_rules()
        logger.info(f"Auto-approve rule: {action_type} = {auto_approve}")

    def get_auto_rules(self) -> dict:
        return dict(self._auto_rules)

    def _save_pending(self):
        path = self._base_dir / "pending.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "id": a.id, "action_type": a.action_type,
                "risk_level": a.risk_level, "description": a.description,
                "details": a.details, "created_at": a.created_at,
                "status": a.status,
            }
            for a in self._pending[-100:]  # 最多保留100个
        ]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))

    def _save_rules(self):
        path = self._base_dir / "rules.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._auto_rules, indent=2))

    def _load_rules(self):
        path = self._base_dir / "rules.json"
        if path.exists():
            try:
                self._auto_rules = json.loads(path.read_text())
            except Exception:
                pass

    def _load_pending(self):
        path = self._base_dir / "pending.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._pending = [PendingAction(**item) for item in data]
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to load pending approvals from %s: %s", path, exc)
