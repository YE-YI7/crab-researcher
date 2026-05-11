"""
CrabRes 配置管理
"""

import secrets
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional, List


def _generate_secret() -> str:
    return secrets.token_urlsafe(32)


class Settings(BaseSettings):
    # ========== 应用基础 ==========
    APP_NAME: str = "CrabRes"
    APP_VERSION: str = "5.1.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api"
    FRONTEND_URL: str = "https://crab-researcher.vercel.app"

    # ========== 数据库 ==========
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/crab_researcher"
    DATABASE_URL_SYNC: str = "postgresql://postgres:password@localhost:5432/crab_researcher"
    REDIS_URL: str = "redis://localhost:6379"

    # ========== TokenDance 网关 (OpenAI 兼容，多模型聚合) ==========
    # 配置后会成为 4 个 Tier 的首选提供商；未配置时自动回退到 OpenRouter / Moonshot
    TOKENDANCE_API_KEY: Optional[str] = None
    TOKENDANCE_BASE_URL: str = "https://tokendance.space/gateway/v1"

    # ========== OpenRouter (备用 LLM) ==========
    OPENROUTER_API_KEY: Optional[str] = None

    # ========== 备用 LLM API Keys ==========
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    MOONSHOT_API_KEY: Optional[str] = None

    # ========== 搜索 API ==========
    TAVILY_API_KEY: Optional[str] = None
    FIRECRAWL_API_KEY: Optional[str] = None

    # ========== 消息平台（国内）==========
    WECOM_WEBHOOK_URL: Optional[str] = None
    FEISHU_WEBHOOK_URL: Optional[str] = None
    FEISHU_WEBHOOK_SECRET: Optional[str] = None
    FEISHU_APP_ID: Optional[str] = None
    FEISHU_APP_SECRET: Optional[str] = None

    # ========== 消息平台（海外）==========
    DISCORD_WEBHOOK_URL: Optional[str] = None
    DISCORD_BOT_TOKEN: Optional[str] = None
    SLACK_WEBHOOK_URL: Optional[str] = None
    SLACK_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    WHATSAPP_API_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_ID: Optional[str] = None

    # ========== 安全 ==========
    JWT_SECRET: str = "change-me-in-production"
    API_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # ========== OAuth ==========
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None

    # ========== 成本控制 ==========
    MONTHLY_BUDGET_PER_USER: float = 100.0
    TOKEN_USAGE_ALERT_THRESHOLD: float = 0.8

    # ========== X/Twitter API（读写帖子）==========
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[str] = None
    TWITTER_ACCESS_TOKEN: Optional[str] = None
    TWITTER_ACCESS_TOKEN_SECRET: Optional[str] = None
    TWITTER_BEARER_TOKEN: Optional[str] = None


    # ========== Reddit API（发帖/评论）==========
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    REDDIT_USERNAME: Optional[str] = None
    REDDIT_PASSWORD: Optional[str] = None

    # ========== Email（SMTP / Resend）==========
    RESEND_API_KEY: Optional[str] = None
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAIL_FROM: Optional[str] = None

    # ========== LinkedIn API ==========
    LINKEDIN_ACCESS_TOKEN: Optional[str] = None

    # ========== MCP 客户端（调用外部 MCP 服务器）==========
    MCP_SERVERS: str = ""  # 格式: name1:url1|name2:url2 或留空

    # ========== 爬虫安全白名单 ==========
    ALLOWED_SCRAPE_DOMAINS: List[str] = [
        "taobao.com", "tmall.com", "jd.com", "pdd.com", "1688.com",
        "xiaohongshu.com", "douyin.com", "weibo.com",
    ]

    ALLOWED_ACTIONS: List[str] = [
        "fetch_data", "generate_report", "send_notification", "search_rag",
    ]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
