"""
CrabRes Action Tracker — Action → Result 闭环追踪

解决的核心问题：
- Agent 给出建议后就忘了——不知道用户是否执行了、效果如何
- 没有闭环数据，Skill 进化系统就是空转

工作流：
1. Agent 给出 action 建议（发帖、发邮件、改定价等）
2. 用户确认执行 → ActionTracker 记录 action
3. Daemon 定期检查 action 的结果（通过 API 或爬虫）
4. 结果好 → SkillWriter 自动提取模式 → 新 Skill 诞生
5. 结果差 → 记录教训 → 下次避免

这是让 Agent "真正学习" 的关键闭环。
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)

ACTION_DIR = Path(".crabres/actions")


class ActionStatus(str, Enum):
    PROPOSED = "proposed"       # Agent 建议了
    CONFIRMED = "confirmed"     # 用户确认要做
    EXECUTING = "executing"     # 正在执行
    COMPLETED = "completed"     # 执行完毕，等待结果
    TRACKED = "tracked"         # 已追踪到结果
    SKILL_EXTRACTED = "skill_extracted"  # 已提取为 Skill


class ActionRecord:
    """单条 Action 记录"""

    def __init__(
        self,
        action_id: str,
        action_type: str,      # post, email, pricing_change, feature_launch, etc.
        platform: str,          # x, hackernews, producthunt, email, etc.
        description: str,       # 人类可读描述
        details: dict = None,   # 具体参数
        status: ActionStatus = ActionStatus.PROPOSED,
    ):
        self.action_id = action_id
        self.action_type = action_type
        self.platform = platform
        self.description = description
        self.details = details or {}
        self.status = status
        self.created_at = time.time()
        self.confirmed_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.result: Optional[dict] = None
        self.result_tracked_at: Optional[float] = None
        self.skill_id: Optional[str] = None

    def confirm(self):
        self.status = ActionStatus.CONFIRMED
        self.confirmed_at = time.time()

    def complete(self, result_url: str = ""):
        self.status = ActionStatus.COMPLETED
        self.completed_at = time.time()
        if result_url:
            self.details["result_url"] = result_url

    def record_result(self, result: dict):
        self.status = ActionStatus.TRACKED
        self.result = result
        self.result_tracked_at = time.time()

    def mark_skill_extracted(self, skill_id: str):
        self.status = ActionStatus.SKILL_EXTRACTED
        self.skill_id = skill_id

    @property
    def is_success(self) -> bool:
        """判断结果是否成功（基于平台指标）"""
        if not self.result:
            return False
        verdict = self.result.get("verdict", "")
        if verdict in ("great", "good"):
            return True
        # 基于数值判断
        engagement = (
            self.result.get("likes", 0)
            + self.result.get("comments", 0)
            + self.result.get("retweets", 0)
            + self.result.get("upvotes", 0)
        )
        return engagement > 50

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "platform": self.platform,
            "description": self.description,
            "details": self.details,
            "status": self.status.value,
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "result_tracked_at": self.result_tracked_at,
            "skill_id": self.skill_id,
            "is_success": self.is_success,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActionRecord":
        record = cls(
            action_id=data["action_id"],
            action_type=data["action_type"],
            platform=data["platform"],
            description=data["description"],
            details=data.get("details", {}),
            status=ActionStatus(data.get("status", "proposed")),
        )
        record.created_at = data.get("created_at", time.time())
        record.confirmed_at = data.get("confirmed_at")
        record.completed_at = data.get("completed_at")
        record.result = data.get("result")
        record.result_tracked_at = data.get("result_tracked_at")
        record.skill_id = data.get("skill_id")
        return record


class ActionTracker:
    """
    Action 追踪器 — 管理所有 action 的生命周期

    用法：
        tracker = ActionTracker()

        # Agent 建议一个 action
        action = tracker.propose("post", "x", "Build in public thread about our launch")

        # 用户确认
        tracker.confirm(action.action_id)

        # 执行完成
        tracker.complete(action.action_id, result_url="https://x.com/...")

        # Daemon 追踪结果
        tracker.record_result(action.action_id, {"likes": 234, "retweets": 67})

        # Skill 自动提取
        tracker.mark_skill_extracted(action.action_id, "skill_bip_thread_001")
    """

    def __init__(self, base_dir: str | Path | None = None):
        self._action_dir = Path(base_dir or ACTION_DIR)
        self._action_dir.mkdir(parents=True, exist_ok=True)
        self._actions: dict[str, ActionRecord] = {}
        self._load()

    def propose(
        self,
        action_type: str,
        platform: str,
        description: str,
        details: dict = None,
    ) -> ActionRecord:
        """Agent 提出一个 action 建议"""
        action_id = f"act_{platform}_{int(time.time()*1000)}"
        record = ActionRecord(
            action_id=action_id,
            action_type=action_type,
            platform=platform,
            description=description,
            details=details or {},
        )
        self._actions[action_id] = record
        self._save()
        logger.info(f"📋 Action proposed: {action_id} — {description[:80]}")
        return record

    def confirm(self, action_id: str) -> Optional[ActionRecord]:
        record = self._actions.get(action_id)
        if record:
            record.confirm()
            self._save()
            logger.info(f"📋 Action confirmed: {action_id}")
        return record

    def complete(self, action_id: str, result_url: str = "") -> Optional[ActionRecord]:
        record = self._actions.get(action_id)
        if record:
            record.complete(result_url)
            self._save()
            logger.info(f"📋 Action completed: {action_id}")
        return record

    def record_result(self, action_id: str, result: dict) -> Optional[ActionRecord]:
        record = self._actions.get(action_id)
        if record:
            record.record_result(result)
            self._save()
            logger.info(f"📋 Action result tracked: {action_id} — success={record.is_success}")
        return record

    def mark_skill_extracted(self, action_id: str, skill_id: str) -> Optional[ActionRecord]:
        record = self._actions.get(action_id)
        if record:
            record.mark_skill_extracted(skill_id)
            self._save()
            logger.info(f"📋 Skill extracted from action: {action_id} → {skill_id}")
        return record

    def get_pending_tracking(self) -> list[ActionRecord]:
        """获取需要追踪结果的 action（已完成但未追踪）"""
        return [
            r for r in self._actions.values()
            if r.status == ActionStatus.COMPLETED
            and (time.time() - (r.completed_at or 0)) > 3600  # 完成 1 小时后再追踪
        ]

    def get_successful_unextracted(self) -> list[ActionRecord]:
        """获取成功但未提取 Skill 的 action"""
        return [
            r for r in self._actions.values()
            if r.status == ActionStatus.TRACKED
            and r.is_success
        ]

    def get_all(self, status: Optional[ActionStatus] = None) -> list[ActionRecord]:
        actions = list(self._actions.values())
        if status:
            actions = [a for a in actions if a.status == status]
        return sorted(actions, key=lambda a: a.created_at, reverse=True)

    def get_stats(self) -> dict:
        """获取统计数据"""
        total = len(self._actions)
        by_status = {}
        by_platform = {}
        success_count = 0
        for a in self._actions.values():
            by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
            by_platform[a.platform] = by_platform.get(a.platform, 0) + 1
            if a.is_success:
                success_count += 1

        tracked = by_status.get("tracked", 0) + by_status.get("skill_extracted", 0)
        return {
            "total": total,
            "by_status": by_status,
            "by_platform": by_platform,
            "success_rate": success_count / tracked if tracked > 0 else 0,
            "skills_extracted": by_status.get("skill_extracted", 0),
        }

    def _save(self):
        data = {k: v.to_dict() for k, v in self._actions.items()}
        with open(self._action_dir / "actions.json", "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _load(self):
        path = self._action_dir / "actions.json"
        if not path.exists():
            return
        try:
            with open(path) as f:
                data = json.load(f)
            self._actions = {k: ActionRecord.from_dict(v) for k, v in data.items()}
            logger.info(f"📋 ActionTracker: loaded {len(self._actions)} actions")
        except Exception as e:
            logger.warning(f"📋 ActionTracker: failed to load: {e}")
