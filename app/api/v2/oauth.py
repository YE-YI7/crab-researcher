"""
CrabRes OAuth — Google + GitHub 一键登录

用户点击 "Continue with Google/GitHub" → 跳转授权 → 回调 → 自动注册/登录 → 返回 JWT
"""

import logging
from datetime import timedelta
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.security import create_access_token, verify_token
from app.core.database import AsyncSessionLocal
from app.models.task import User
from sqlalchemy import select

settings = get_settings()
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/oauth", tags=["OAuth"])

# 前端回调 URL（从配置读取）
FRONTEND_URL = settings.FRONTEND_URL


def _oauth_state(provider: str) -> str:
    return create_access_token(
        {"scope": "oauth_state", "provider": provider},
        expires_delta=timedelta(minutes=10),
    )


def _verify_oauth_state(state: str | None, provider: str) -> None:
    if not state:
        raise HTTPException(400, "Missing OAuth state")
    payload = verify_token(state)
    if payload.get("scope") != "oauth_state" or payload.get("provider") != provider:
        raise HTTPException(400, "Invalid OAuth state")


# ====== Google OAuth ======

GOOGLE_CLIENT_ID = getattr(settings, 'GOOGLE_CLIENT_ID', None)
GOOGLE_CLIENT_SECRET = getattr(settings, 'GOOGLE_CLIENT_SECRET', None)
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


@router.get("/google")
async def google_login(request: Request):
    """跳转到 Google 登录页"""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(400, "Google OAuth not configured")

    redirect_uri = str(request.url_for("google_callback"))
    client = AsyncOAuth2Client(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri=redirect_uri)
    uri, _ = client.create_authorization_url(
        GOOGLE_AUTH_URL, scope="openid email profile", state=_oauth_state("google")
    )
    return RedirectResponse(uri)


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request):
    """Google 授权回调"""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(400, "Google OAuth not configured")
    _verify_oauth_state(request.query_params.get("state"), "google")

    redirect_uri = str(request.url_for("google_callback"))
    client = AsyncOAuth2Client(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri=redirect_uri)

    token = await client.fetch_token(GOOGLE_TOKEN_URL, authorization_response=str(request.url))
    resp = await client.get(GOOGLE_USERINFO_URL)
    user_info = resp.json()

    email = user_info.get("email")
    name = user_info.get("name", "")

    if not email:
        raise HTTPException(400, "Could not get email from Google")

    jwt_token = await _get_or_create_user(email, name, "google")
    return RedirectResponse(f"{FRONTEND_URL}#token={jwt_token}")


# ====== GitHub OAuth ======

GITHUB_CLIENT_ID = getattr(settings, 'GITHUB_CLIENT_ID', None)
GITHUB_CLIENT_SECRET = getattr(settings, 'GITHUB_CLIENT_SECRET', None)
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAIL_URL = "https://api.github.com/user/emails"


@router.get("/github")
async def github_login(request: Request):
    """跳转到 GitHub 登录页"""
    if not GITHUB_CLIENT_ID:
        raise HTTPException(400, "GitHub OAuth not configured")

    redirect_uri = str(request.url_for("github_callback"))
    client = AsyncOAuth2Client(GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, redirect_uri=redirect_uri)
    uri, _ = client.create_authorization_url(
        GITHUB_AUTH_URL, scope="user:email", state=_oauth_state("github")
    )
    return RedirectResponse(uri)


@router.get("/github/callback", name="github_callback")
async def github_callback(request: Request):
    """GitHub 授权回调"""
    if not GITHUB_CLIENT_ID:
        raise HTTPException(400, "GitHub OAuth not configured")
    _verify_oauth_state(request.query_params.get("state"), "github")

    redirect_uri = str(request.url_for("github_callback"))
    client = AsyncOAuth2Client(GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, redirect_uri=redirect_uri)

    token = await client.fetch_token(
        GITHUB_TOKEN_URL,
        authorization_response=str(request.url),
        headers={"Accept": "application/json"},
    )

    # 获取用户信息
    resp = await client.get(GITHUB_USER_URL)
    user_info = resp.json()
    name = user_info.get("name") or user_info.get("login", "")

    # 获取邮箱（GitHub 可能不在 profile 里公开邮箱）
    email = user_info.get("email")
    if not email:
        email_resp = await client.get(GITHUB_EMAIL_URL)
        emails = email_resp.json()
        primary = next((e for e in emails if e.get("primary")), None)
        email = primary["email"] if primary else None

    if not email:
        raise HTTPException(400, "Could not get email from GitHub")

    jwt_token = await _get_or_create_user(email, name, "github")
    return RedirectResponse(f"{FRONTEND_URL}#token={jwt_token}")


# ====== 公共逻辑 ======

async def _get_or_create_user(email: str, name: str, provider: str) -> str:
    """查找或创建用户，返回 JWT token"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.contact_email == email))
        user = result.scalar_one_or_none()

        if not user:
            import bcrypt
            # OAuth 用户存一个不可能匹配的 bcrypt 哈希（防止密码登录）
            fake_hash = bcrypt.hashpw(f"oauth:{provider}:{email}".encode(), bcrypt.gensalt()).decode()
            user = User(
                company_name=name or "CrabRes User",
                contact_email=email,
                hashed_password=fake_hash,
                subscription_plan="free",
                monthly_budget=100.0,
                monthly_token_used=0.0,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info(f"New OAuth user created: {email} via {provider}")
        else:
            logger.info(f"Existing user logged in via {provider}: {email}")

        return create_access_token({"user_id": user.id, "email": email})
