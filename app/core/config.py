"""
CrabRes 配置管理
"""

import secrets
from pydantic import Field, model_validator
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
    ENVIRONMENT: str = "development"
    API_PREFIX: str = "/api"
    FRONTEND_URL: str = "https://crab-researcher.vercel.app"
    ENABLE_GLOBAL_DAEMON: bool = False
    # Keep publishing/email/browser side effects off until credentials are
    # stored per tenant and a durable audit log is in place.
    ENABLE_REAL_WORLD_EXECUTION: bool = False
    # Browser automation runs in a separate worker. Keep disabled on the
    # shared Render API until an isolated worker/provider is configured.
    BROWSER_WORKER_ENABLED: bool = False
    BROWSER_RUN_INLINE: bool = False
    BROWSER_PROVIDER: str = "local"
    BROWSER_JOB_TIMEOUT_SECONDS: int = 90
    BROWSER_MAX_STEPS: int = 20
    BROWSER_MAX_ACTIVE_JOBS_PER_USER: int = 3
    BROWSER_MAX_ARTIFACT_BYTES: int = 2_000_000
    BROWSER_VERCEL_NODE_BINARY: str = "node"
    BROWSER_VERCEL_VCPUS: int = 1
    VERCEL_SANDBOX_IMAGE: Optional[str] = None
    VERCEL_TEAM_ID: Optional[str] = None
    VERCEL_PROJECT_ID: Optional[str] = None
    VERCEL_TOKEN: Optional[str] = None

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
    # Development gets an ephemeral secret instead of a publicly known default.
    # Production must explicitly provide stable, strong values (validated below).
    JWT_SECRET: str = Field(default_factory=_generate_secret)
    API_KEY: Optional[str] = None
    ADMIN_API_KEY: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # External inbound events use dedicated credentials. They must never share
    # the user-facing JWT or general API key.
    GITHUB_WEBHOOK_SECRET: Optional[str] = None
    GENERIC_WEBHOOK_TOKEN: Optional[str] = None

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

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.ENVIRONMENT.lower() in {"production", "prod"}:
            if len(self.JWT_SECRET) < 32 or self.JWT_SECRET == "change-me-in-production":
                raise ValueError("JWT_SECRET must be an explicit secret of at least 32 characters in production")
            if not self.ADMIN_API_KEY or len(self.ADMIN_API_KEY) < 32:
                raise ValueError("ADMIN_API_KEY must be configured with at least 32 characters in production")
        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()
