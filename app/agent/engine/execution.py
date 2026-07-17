"""
CrabRes Execution Engine — Agent 真正执行操作的核心

这是"给建议"和"做事"的分水岭。

职责：
1. 接收 Pipeline/Daemon 的执行请求
2. 通过 AutonomousEngine 评估风险
3. 低风险 → 直接执行
4. 中/高风险 → 进审批队列 或 自动执行（取决于 Trust Level）
5. 执行完成 → 记录到 ActionTracker → Daemon 追踪结果
6. 结果好 → SkillWriter 提取模式

这是让 Agent 从"顾问"变成"员工"的关键模块。
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

REAL_WORLD_ACTIONS = {
    "reddit_post", "reddit_comment", "twitter_post", "publish_post",
    "send_email", "bulk_email", "browser_action",
}


@dataclass
class ExecutionRequest:
    """一个待执行的操作"""
    action_type: str          # reddit_post, send_email, twitter_post, etc.
    platform: str             # reddit, email, x, linkedin, etc.
    description: str          # 人类可读描述
    params: dict = field(default_factory=dict)  # 执行参数
    draft_content: str = ""   # 草稿内容（给用户确认用）
    source: str = "pipeline"  # pipeline / daemon / user_direct
    priority: str = "normal"  # low / normal / high / urgent


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    status: str               # posted / sent / failed / queued / rejected
    platform: str
    action_id: str = ""
    url: str = ""             # 发布后的 URL（用于追踪）
    details: dict = field(default_factory=dict)
    error: str = ""


class ExecutionEngine:
    """
    执行引擎 — 连接决策层和真实世界

    核心流程：
    request → risk_check → auto_execute / queue_for_approval → execute → track_result
    """

    def __init__(self, tools=None, memory=None, autonomous=None, tracker=None):
        self.tools = tools
        self.memory = memory
        self.autonomous = autonomous
        self.tracker = tracker
        self._execution_log: list[dict] = []

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """
        执行一个操作 — 核心入口

        1. 检查风险等级
        2. 判断是否可以自动执行
        3. 可以 → 直接执行
        4. 不可以 → 进审批队列，返回 queued 状态
        """
        logger.info(f"⚡ ExecutionEngine: {request.action_type} on {request.platform}")

        # 获取当前 trust level
        trust_level = "cautious"
        if self.memory:
            try:
                trust_data = await self.memory.load("trust_level")
                if trust_data and isinstance(trust_data, dict):
                    trust_level = trust_data.get("level", "cautious")
            except Exception:
                pass

        # 风险评估
        can_auto = True
        if self.autonomous:
            can_auto = self.autonomous.can_auto_execute(request.action_type, trust_level)

        if not can_auto:
            # 进审批队列
            if self.autonomous:
                pending = self.autonomous.request_approval(
                    action_type=request.action_type,
                    description=request.description,
                    details={
                        "params": request.params,
                        "draft": request.draft_content[:500],
                        "platform": request.platform,
                    },
                )
                logger.info(f"⚡ Queued for approval: {pending.id}")

                # 也记录到 ActionTracker
                if self.tracker:
                    action = self.tracker.propose(
                        action_type=request.action_type,
                        platform=request.platform,
                        description=request.description,
                        details=request.params,
                    )
                    return ExecutionResult(
                        success=False,
                        status="queued",
                        platform=request.platform,
                        action_id=action.action_id,
                        details={"approval_id": pending.id, "risk": "medium_or_high"},
                    )

            return ExecutionResult(
                success=False,
                status="queued",
                platform=request.platform,
                details={"reason": "requires_approval"},
            )

        # 直接执行
        return await self._do_execute(request)

    async def execute_approved(self, approval_id: str) -> ExecutionResult:
        """执行已审批通过的操作"""
        if not self.autonomous:
            return ExecutionResult(success=False, status="failed", platform="unknown",
                                   error="No autonomous engine")

        action = self.autonomous.approve(approval_id)
        if not action:
            return ExecutionResult(success=False, status="failed", platform="unknown",
                                   error=f"Approval {approval_id} not found")

        # 从 pending action 重建 ExecutionRequest
        request = ExecutionRequest(
            action_type=action.action_type,
            platform=action.details.get("platform", ""),
            description=action.description,
            params=action.details.get("params", {}),
            source="approved",
        )

        return await self._do_execute(request)

    async def _do_execute(self, request: ExecutionRequest) -> ExecutionResult:
        """真正执行操作"""
        if request.action_type in REAL_WORLD_ACTIONS:
            from app.core.config import get_settings
            if not get_settings().ENABLE_REAL_WORLD_EXECUTION:
                return ExecutionResult(
                    success=False,
                    status="disabled",
                    platform=request.platform,
                    error="Real-world execution is disabled until tenant-scoped credentials are configured",
                )

        # 记录到 ActionTracker
        action_record = None
        if self.tracker:
            action_record = self.tracker.propose(
                action_type=request.action_type,
                platform=request.platform,
                description=request.description,
                details=request.params,
            )
            self.tracker.confirm(action_record.action_id)

        # 根据 action_type 路由到具体工具
        result = await self._route_to_tool(request)

        # 更新 ActionTracker
        if action_record and self.tracker:
            if result.success:
                self.tracker.complete(action_record.action_id, result_url=result.url)
                result.action_id = action_record.action_id
            else:
                # 记录失败
                self.tracker.record_result(action_record.action_id, {
                    "verdict": "failed",
                    "error": result.error,
                })

        # 记录执行日志
        self._execution_log.append({
            "action_type": request.action_type,
            "platform": request.platform,
            "success": result.success,
            "status": result.status,
            "url": result.url,
            "timestamp": time.time(),
        })

        # 持久化日志到记忆
        if self.memory:
            try:
                await self.memory.append_journal({
                    "type": "execution",
                    "action_type": request.action_type,
                    "platform": request.platform,
                    "success": result.success,
                    "url": result.url,
                    "timestamp": time.time(),
                })
            except Exception as e:
                logger.debug(f"Journal append failed: {e}")

        # 发布事件
        try:
            from app.agent.events import get_event_bus
            bus = await get_event_bus()
            await bus.publish(f"execution.{'success' if result.success else 'failed'}", {
                "action_type": request.action_type,
                "platform": request.platform,
                "url": result.url,
                "status": result.status,
            })
        except Exception:
            pass

        return result

    async def _route_to_tool(self, request: ExecutionRequest) -> ExecutionResult:
        """根据 action_type 路由到具体的执行工具"""
        action = request.action_type
        params = request.params

        try:
            # ===== Reddit =====
            if action == "reddit_post":
                tool = self.tools.get("reddit_post") if self.tools else None
                if not tool:
                    from app.agent.tools.reddit import RedditPostTool
                    tool = RedditPostTool()
                result = await tool.execute(**params)
                return self._parse_tool_result(result, "reddit")

            # ===== Reddit Comment =====
            elif action == "reddit_comment":
                tool = self.tools.get("reddit_comment") if self.tools else None
                if not tool:
                    from app.agent.tools.reddit import RedditCommentTool
                    tool = RedditCommentTool()
                result = await tool.execute(**params)
                return self._parse_tool_result(result, "reddit")

            # ===== Twitter/X =====
            elif action in ("twitter_post", "publish_post"):
                tool = self.tools.get("twitter_post") if self.tools else None
                if not tool:
                    from app.agent.tools.twitter import TwitterPostTool
                    tool = TwitterPostTool()
                result = await tool.execute(**params)
                return self._parse_tool_result(result, "x")

            # ===== Email =====
            elif action == "send_email":
                tool = self.tools.get("send_email") if self.tools else None
                if not tool:
                    from app.agent.tools.email_sender import SendEmailTool
                    tool = SendEmailTool()
                result = await tool.execute(**params)
                return self._parse_tool_result(result, "email")

            # ===== Bulk Email =====
            elif action == "bulk_email":
                from app.agent.tools.email_sender import BulkEmailTool
                tool = BulkEmailTool()
                result = await tool.execute(**params)
                return self._parse_tool_result(result, "email")

            # ===== 浏览器操作（自动提交到目录等）=====
            elif action == "browser_action":
                from app.agent.tools.browser_crawler import BrowserCrawler
                crawler = BrowserCrawler()
                try:
                    url = params.get("url", "")
                    result = await crawler.crawl(url)
                    return ExecutionResult(
                        success=not result.get("error"),
                        status="completed" if not result.get("error") else "failed",
                        platform="browser",
                        url=url,
                        details=result,
                    )
                finally:
                    await crawler.close()

            # ===== 未知操作 =====
            else:
                return ExecutionResult(
                    success=False,
                    status="unsupported",
                    platform=request.platform,
                    error=f"Unknown action type: {action}. Supported: reddit_post, reddit_comment, twitter_post, send_email, bulk_email, browser_action",
                )

        except Exception as e:
            logger.error(f"Execution failed for {action}: {e}")
            return ExecutionResult(
                success=False,
                status="failed",
                platform=request.platform,
                error=str(e),
            )

    def _parse_tool_result(self, result: dict, platform: str) -> ExecutionResult:
        """将工具返回值转为统一的 ExecutionResult"""
        status = result.get("status", "unknown")
        success = status in ("posted", "sent", "completed")
        return ExecutionResult(
            success=success,
            status=status,
            platform=platform,
            url=result.get("url", ""),
            details=result,
            error=result.get("error", ""),
        )

    async def drain_approved_queue(self) -> list[ExecutionResult]:
        """
        消费审批队列 — Daemon 每次 tick 时调用

        检查所有已审批的操作，逐个执行
        """
        if not self.autonomous:
            return []

        approved = self.autonomous.get_approved()
        results = []

        for action in approved:
            request = ExecutionRequest(
                action_type=action.action_type,
                platform=action.details.get("platform", ""),
                description=action.description,
                params=action.details.get("params", {}),
                source="approved_queue",
            )
            result = await self._do_execute(request)
            results.append(result)

            # 标记为已执行
            action.status = "executed"

            # 间隔执行，避免触发平台限流
            await asyncio.sleep(5)

        if results:
            logger.info(f"⚡ Drained {len(results)} approved actions")

        return results

    def get_execution_log(self, limit: int = 50) -> list[dict]:
        """获取最近的执行日志"""
        return self._execution_log[-limit:]

    def get_stats(self) -> dict:
        """获取执行统计"""
        total = len(self._execution_log)
        success = sum(1 for e in self._execution_log if e.get("success"))
        by_platform = {}
        for e in self._execution_log:
            p = e.get("platform", "unknown")
            by_platform[p] = by_platform.get(p, 0) + 1
        return {
            "total_executions": total,
            "success_count": success,
            "success_rate": round(success / max(total, 1), 2),
            "by_platform": by_platform,
        }
