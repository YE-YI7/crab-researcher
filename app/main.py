"""
CrabRes - AI Growth Strategy Agent
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import engine, Base
from app.models.growth_memory import MemoryRecord, JournalEntry  # 确保 create_all 发现新表
from app.api import auth, tasks, monitoring, reports, rag, system, competitors
from app.api.v2 import agent as agent_v2
from app.api.v2 import growth_data as growth_data_v2
from app.api.v2 import oauth as oauth_v2
from app.api.v2 import share as share_v2
from app.api.v2 import mcp as mcp_v2
from app.api.v2 import skills as skills_v2
from app.api.v2 import brand as brand_v2
from app.api.v2 import creature as creature_v2
from app.api.v2 import simulate as simulate_v2
from app.api.v2 import execute as execute_v2
from app.api.v2 import demo as demo_v2
from app.api.v2 import experiments as experiments_v2
from app.api.v2 import playbooks as playbooks_v2
from app.api.v2 import metrics as metrics_v2
from app.api.v2 import deep_strategy as deep_strategy_v2
from app.api.v2 import eval as eval_v2
from app.api.v2 import daemon as daemon_v2
from app.api.v2 import webhooks as webhooks_v2
from app.api.v2 import real_world as real_world_v2
from app.api.v2 import notifications as notifications_v2
from app.api.v2 import execution as execution_v2
from app.api.v2 import workspace as workspace_v2
from app.channels.feishu_bot import router as feishu_router
from app.channels.openclaw_skill import router as openclaw_router
from app.channels.discord_bot import router as discord_router
from app.channels.telegram_bot import router as telegram_router
import os
from app.services.scheduler import MonitoringScheduler
from app.agent.daemon import GrowthDaemon
from app.agent.notifications import NotificationHub
from app.agent.tools import ToolRegistry
from app.agent.tools.research import WebSearchTool, ScrapeWebsiteTool, SocialSearchTool
from app.agent.tools.browser import BrowseWebsiteTool
from app.agent.memory import GrowthMemory
from app.agent.engine.llm_adapter import AgentLLM

settings = get_settings()

# 日志配置
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期 — 所有子系统容错启动，不阻塞 healthcheck"""

    # 数据库初始化（容错：未配置或连接失败不阻塞启动）
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logging.info("🗄️ Database initialized")
    except Exception as e:
        logging.warning(f"🗄️ Database init failed (will retry on first request): {e}")

    # APScheduler 调度器
    scheduler = MonitoringScheduler()
    scheduler.start()
    app.state.monitoring_scheduler = scheduler

    # Growth Daemon（容错启动）
    daemon = None
    try:
        if not settings.ENABLE_GLOBAL_DAEMON:
            raise RuntimeError("Global daemon disabled; use tenant-scoped jobs")
        tools = ToolRegistry()
        tools.register(WebSearchTool())
        tools.register(ScrapeWebsiteTool())
        tools.register(SocialSearchTool())
        tools.register(BrowseWebsiteTool())
        from app.agent.tools.reddit import RedditPostTool, RedditCommentTool, RedditSearchTool
        from app.agent.tools.email_sender import SendEmailTool
        tools.register(RedditPostTool())
        tools.register(RedditCommentTool())
        tools.register(RedditSearchTool())
        tools.register(SendEmailTool())
        from app.agent.memory.factory import create_memory
        memory = create_memory(user_id="global")
        llm = AgentLLM(budget_limit_usd=0.1)
        daemon = GrowthDaemon(memory=memory, tools=tools, llm=llm, notifier=NotificationHub())
        await daemon.start()
        logging.info("🤖 Growth Daemon started")
    except Exception as e:
        logging.info(f"🤖 Growth Daemon not started: {e}")
    app.state.growth_daemon = daemon

    # EventBus（容错启动）
    try:
        from app.agent.events import get_event_bus
        event_bus = await get_event_bus()
        app.state.event_bus = event_bus
        logging.info("📡 EventBus started")
    except Exception as e:
        logging.warning(f"📡 EventBus init failed: {e}")
        app.state.event_bus = None

    # Telegram 长轮询（仅在配置 token 时启动）
    from app.channels.telegram_polling import TelegramPoller
    tg_poller = TelegramPoller()
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        try:
            await tg_poller.start()
            logging.info("📱 Telegram poller started")
        except Exception as e:
            logging.warning(f"📱 Telegram poller failed: {e}")
    else:
        logging.info("📱 Telegram poller skipped (no TELEGRAM_BOT_TOKEN)")
    app.state.telegram_poller = tg_poller

    # 浏览器不再预热 — 按需启动，用完释放（Render 512MB 限制）
    logging.info("Browser: on-demand mode (will install + launch when needed)")

    logging.info("🦀 CrabRes Agent Engine started!")
    yield

    await tg_poller.stop()
    if daemon:
        await daemon.stop()
    scheduler.shutdown()
    await engine.dispose()
    logging.info("🦀 CrabRes shut down")


async def _warmup_browser():
    """后台预热 Playwright 浏览器（首次启动较慢）"""
    try:
        from app.agent.tools.browser import _get_browser
        browser = await _get_browser()
        if browser:
            logging.info("🌐 Playwright browser warmed up")
        else:
            logging.warning("🌐 Browser not available (install: patchright install chromium)")
    except Exception as e:
        logging.warning(f"🌐 Playwright warmup failed: {e}")


app = FastAPI(
    title="🦀 CrabRes API",
    description="AI Growth Strategy Agent — helps any product find its path to growth",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — 限制为实际前端域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://crab-researcher.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# v1 路由（保留兼容）
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(tasks.router, prefix=settings.API_PREFIX)
app.include_router(monitoring.router, prefix=settings.API_PREFIX)
app.include_router(reports.router, prefix=settings.API_PREFIX)
app.include_router(rag.router, prefix=settings.API_PREFIX)
app.include_router(system.router, prefix=settings.API_PREFIX)
app.include_router(competitors.router, prefix=settings.API_PREFIX)

# v2 路由（Agent Engine）
app.include_router(agent_v2.router, prefix=settings.API_PREFIX)
app.include_router(growth_data_v2.router, prefix=settings.API_PREFIX)
app.include_router(oauth_v2.router, prefix=settings.API_PREFIX)
app.include_router(share_v2.router, prefix=settings.API_PREFIX)
app.include_router(mcp_v2.router, prefix=settings.API_PREFIX)
app.include_router(skills_v2.router, prefix=settings.API_PREFIX)
app.include_router(brand_v2.router, prefix=settings.API_PREFIX)
app.include_router(creature_v2.router, prefix=settings.API_PREFIX)
app.include_router(simulate_v2.router, prefix=settings.API_PREFIX)
app.include_router(execute_v2.router, prefix=settings.API_PREFIX)
app.include_router(demo_v2.router, prefix=settings.API_PREFIX)
app.include_router(experiments_v2.router, prefix=settings.API_PREFIX)
app.include_router(playbooks_v2.router, prefix=settings.API_PREFIX)
app.include_router(metrics_v2.router, prefix=settings.API_PREFIX)
app.include_router(deep_strategy_v2.router, prefix=settings.API_PREFIX)
app.include_router(eval_v2.router, prefix=settings.API_PREFIX)
app.include_router(daemon_v2.router, prefix=settings.API_PREFIX)
app.include_router(webhooks_v2.router, prefix=settings.API_PREFIX)
app.include_router(real_world_v2.router, prefix=settings.API_PREFIX)
app.include_router(notifications_v2.router, prefix=settings.API_PREFIX)
app.include_router(execution_v2.router, prefix=settings.API_PREFIX)
app.include_router(workspace_v2.router, prefix=settings.API_PREFIX)

# 渠道路由
app.include_router(feishu_router, prefix=settings.API_PREFIX)
app.include_router(openclaw_router, prefix=settings.API_PREFIX)
app.include_router(discord_router, prefix=settings.API_PREFIX)
app.include_router(telegram_router, prefix=settings.API_PREFIX)


@app.get("/", tags=["Root"])
async def root():
    # Public root — no version disclosure (use /api/version for an
    # authenticated/admin lookup if needed).
    return {
        "name": "🦀 CrabRes",
        "tagline": "AI Growth Strategy Agent",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Root"])
@app.get("/api/health", tags=["Root"])
async def health():
    """Liveness probe for Render/uptime monitors. No auth, no DB hit."""
    return {"status": "ok", "version": settings.APP_VERSION}
