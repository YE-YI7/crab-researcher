"""
安全认证模块
- JWT Token 认证
- API Key 认证
- 域名白名单校验
"""

from datetime import datetime, timedelta, timezone
import hmac
from typing import Optional
from urllib.parse import urlparse

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

settings = get_settings()

# 安全方案
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ========== JWT Token ==========

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效Token")


# ========== 认证依赖 ==========

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
):
    """支持 Bearer Token 或 API Key 两种认证方式"""
    # 优先检查 API Key
    if api_key and settings.API_KEY and hmac.compare_digest(api_key, settings.API_KEY):
        return {"user_id": 0, "role": "api"}

    # 检查 Bearer Token
    if credentials:
        payload = verify_token(credentials.credentials)
        return payload

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未提供有效的认证凭据",
    )


async def require_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Require an authenticated human tenant, not the shared service API key."""
    user_id = current_user.get("user_id")
    if current_user.get("role") == "api" or not isinstance(user_id, int) or user_id <= 0:
        raise HTTPException(status_code=403, detail="A user-scoped token is required")
    return current_user


async def require_admin(
    admin_key: Optional[str] = Security(APIKeyHeader(name="X-Admin-Key", auto_error=False)),
) -> dict:
    """Protect process-wide operational controls with a dedicated admin key."""
    if (
        admin_key
        and settings.ADMIN_API_KEY
        and hmac.compare_digest(admin_key, settings.ADMIN_API_KEY)
    ):
        return {"role": "admin"}
    raise HTTPException(status_code=403, detail="Administrator credentials required")


# ========== 域名白名单校验 ==========

def validate_domain(url: str) -> bool:
    """检查 URL 是否在允许的爬虫白名单域名中"""
    try:
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower().rstrip(".")
        return any(
            domain == allowed.lower().rstrip(".")
            or domain.endswith(f".{allowed.lower().rstrip('.')}" )
            for allowed in settings.ALLOWED_SCRAPE_DOMAINS
        )
    except Exception:
        return False


def require_allowed_domain(url: str):
    """强制要求 URL 在白名单内，否则抛出异常"""
    if not validate_domain(url):
        raise HTTPException(
            status_code=403,
            detail=f"域名不在白名单中。允许的域名: {settings.ALLOWED_SCRAPE_DOMAINS}",
        )
