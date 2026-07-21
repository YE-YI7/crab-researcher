"""Authenticated API for durable, approval-gated browser jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, undefer

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_user
from app.models.browser import BrowserArtifact, BrowserJob, BrowserStep
from app.models.task import UserProduct
from app.services.browser_job_service import run_browser_job
from app.services.browser_safety import UnsafeBrowserTarget, validate_public_target, validate_target_syntax

router = APIRouter(prefix="/browser-jobs", tags=["Browser Jobs"])

BrowserAction = Literal["navigate", "click", "fill", "press", "extract", "screenshot", "submit"]


class BrowserStepCreate(BaseModel):
    action: BrowserAction
    params: dict = Field(default_factory=dict)


class BrowserJobCreate(BaseModel):
    start_url: str = Field(..., min_length=8, max_length=2000)
    goal: str = Field(default="Inspect this page safely", min_length=3, max_length=1000)
    product_id: Optional[int] = Field(None, gt=0)
    allowed_domains: list[str] = Field(default_factory=list, max_length=10)
    steps: list[BrowserStepCreate] = Field(default_factory=list)


class ApprovalBody(BaseModel):
    confirmation: Literal["approve"]


def _step_payload(step: BrowserStep) -> dict:
    params = dict(step.params or {})
    if step.action == "fill" and "value" in params:
        params["value"] = "••••••••"
    return {
        "id": step.id,
        "position": step.position,
        "action": step.action,
        "status": step.status,
        "params": params,
        "result": step.result or {},
        "requires_approval": step.requires_approval,
        "approved_at": step.approved_at,
        "started_at": step.started_at,
        "completed_at": step.completed_at,
        "error": step.error_message,
    }


def _job_summary(job: BrowserJob) -> dict:
    return {
        "id": job.id,
        "product_id": job.product_id,
        "status": job.status,
        "provider": job.provider,
        "goal": job.goal,
        "start_url": job.start_url,
        "current_url": job.current_url,
        "allowed_domains": job.allowed_domains or [],
        "current_step": job.current_step,
        "summary": job.result_summary or {},
        "error": job.error_message,
        "attempt_count": job.attempt_count,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "updated_at": job.updated_at,
    }


def _job_detail(job: BrowserJob) -> dict:
    payload = _job_summary(job)
    payload["steps"] = [_step_payload(step) for step in job.steps]
    payload["artifacts"] = [
        {
            "id": artifact.id,
            "step_id": artifact.step_id,
            "kind": artifact.kind,
            "content_type": artifact.content_type,
            "size_bytes": artifact.size_bytes,
            "metadata": artifact.artifact_metadata or {},
            "created_at": artifact.created_at,
            "download_url": f"/browser-jobs/{job.id}/artifacts/{artifact.id}",
        }
        for artifact in sorted(job.artifacts, key=lambda item: item.created_at)
    ]
    return payload


async def _owned_job(db: AsyncSession, job_id: str, user_id: int, *, details: bool = False) -> BrowserJob:
    query = select(BrowserJob).where(BrowserJob.id == job_id, BrowserJob.user_id == user_id)
    if details:
        query = query.options(selectinload(BrowserJob.steps), selectinload(BrowserJob.artifacts))
    result = await db.execute(query)
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Browser job not found")
    return job


def _validate_steps(body: BrowserJobCreate, start_url: str, max_steps: int) -> list[BrowserStepCreate]:
    steps = body.steps or [
        BrowserStepCreate(action="navigate", params={"url": start_url}),
        BrowserStepCreate(action="extract", params={"selector": "body"}),
        BrowserStepCreate(action="screenshot", params={}),
    ]
    if len(steps) > max_steps:
        raise HTTPException(status_code=422, detail=f"At most {max_steps} browser steps are allowed")
    if not steps or steps[0].action != "navigate":
        raise HTTPException(status_code=422, detail="The first browser step must be navigate")
    def contains_secret_key(value) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                if any(marker in lowered for marker in ("password", "token", "secret", "cookie", "authorization")):
                    return True
                if contains_secret_key(child):
                    return True
        if isinstance(value, list):
            return any(contains_secret_key(item) for item in value)
        return False

    for step in steps:
        if contains_secret_key(step.params):
            raise HTTPException(status_code=422, detail="Credentials cannot be embedded in browser job steps")
        if step.action == "navigate" and not step.params.get("url"):
            raise HTTPException(status_code=422, detail="Navigate steps require a URL")
        if step.action in {"click", "fill", "press", "submit"} and not step.params.get("selector"):
            raise HTTPException(status_code=422, detail=f"{step.action} steps require a selector")
    return steps


@router.get("/capabilities")
async def browser_capabilities(current_user: dict = Depends(require_user)):
    settings = get_settings()
    provider_ready = settings.BROWSER_PROVIDER != "vercel" or bool(settings.VERCEL_SANDBOX_IMAGE)
    return {
        "enabled": settings.BROWSER_WORKER_ENABLED and provider_ready,
        "provider": settings.BROWSER_PROVIDER,
        "isolation": "firecracker-microvm" if settings.BROWSER_PROVIDER == "vercel" else "worker-process",
        "actions": ["navigate", "click", "fill", "press", "extract", "screenshot", "submit"],
        "approval_required_for": ["fill", "submit", "Enter", "form controls"],
        "max_steps": settings.BROWSER_MAX_STEPS,
        "credentials_supported": False,
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_browser_job(
    body: BrowserJobCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=128),
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    if not settings.BROWSER_WORKER_ENABLED:
        raise HTTPException(status_code=503, detail="Browser worker is not configured for this environment")
    if settings.BROWSER_PROVIDER == "vercel" and not settings.VERCEL_SANDBOX_IMAGE:
        raise HTTPException(status_code=503, detail="Vercel Sandbox image is not configured")

    user_id = current_user["user_id"]
    if body.product_id is not None:
        product = await db.execute(select(UserProduct.id).where(
            UserProduct.id == body.product_id,
            UserProduct.user_id == user_id,
        ))
        if product.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Product not found")

    if idempotency_key:
        existing = await db.execute(select(BrowserJob).where(
            BrowserJob.user_id == user_id,
            BrowserJob.idempotency_key == idempotency_key,
        ))
        existing_job = existing.scalar_one_or_none()
        if existing_job:
            return _job_summary(existing_job)

    active_count = (await db.execute(select(func.count()).select_from(BrowserJob).where(
        BrowserJob.user_id == user_id,
        BrowserJob.status.in_(["queued", "running", "awaiting_approval"]),
    ))).scalar_one()
    if active_count >= settings.BROWSER_MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(status_code=429, detail="Too many active browser jobs")

    try:
        start = await validate_public_target(body.start_url)
        domains = {start.hostname}
        for value in body.allowed_domains:
            candidate = value.strip().lower().rstrip(".")
            if not candidate or "://" in candidate or "*" in candidate:
                raise UnsafeBrowserTarget("Allowed domains must be plain hostnames without wildcards")
            validate_target_syntax(f"https://{candidate}")
            await validate_public_target(f"https://{candidate}")
            domains.add(candidate)
    except UnsafeBrowserTarget as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    steps = _validate_steps(body, start.url, settings.BROWSER_MAX_STEPS)
    for step in steps:
        if step.action == "navigate":
            try:
                await validate_public_target(step.params["url"], sorted(domains))
            except UnsafeBrowserTarget as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = BrowserJob(
        user_id=user_id,
        product_id=body.product_id,
        provider=settings.BROWSER_PROVIDER,
        goal=body.goal,
        start_url=start.url,
        allowed_domains=sorted(domains),
        idempotency_key=idempotency_key,
    )
    job.steps = [
        BrowserStep(
            position=index,
            action=step.action,
            params=step.params,
            requires_approval=(
                step.action in {"fill", "submit"}
                or (step.action == "press" and step.params.get("key") == "Enter")
            ),
        )
        for index, step in enumerate(steps)
    ]
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if not idempotency_key:
            raise
        existing = await db.execute(select(BrowserJob).where(
            BrowserJob.user_id == user_id,
            BrowserJob.idempotency_key == idempotency_key,
        ))
        existing_job = existing.scalar_one_or_none()
        if existing_job is None:
            raise
        return _job_summary(existing_job)
    await db.refresh(job)
    if settings.BROWSER_RUN_INLINE:
        background_tasks.add_task(run_browser_job, job.id)
    return _job_summary(job)


@router.get("")
async def list_browser_jobs(
    job_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BrowserJob).where(BrowserJob.user_id == current_user["user_id"])
    if job_status:
        query = query.where(BrowserJob.status == job_status)
    result = await db.execute(query.order_by(BrowserJob.created_at.desc()).limit(limit))
    return {"items": [_job_summary(job) for job in result.scalars().all()]}


@router.get("/{job_id}")
async def get_browser_job(
    job_id: str,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return _job_detail(await _owned_job(db, job_id, current_user["user_id"], details=True))


@router.post("/{job_id}/approve", status_code=status.HTTP_202_ACCEPTED)
async def approve_browser_step(
    job_id: str,
    body: ApprovalBody,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    job = await _owned_job(db, job_id, current_user["user_id"], details=True)
    if job.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail="This browser job is not awaiting approval")
    step = next((item for item in job.steps if item.status == "awaiting_approval"), None)
    if step is None:
        raise HTTPException(status_code=409, detail="No browser step is awaiting approval")
    step.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    step.status = "pending"
    job.status = "queued"
    await db.commit()
    if settings.BROWSER_RUN_INLINE:
        background_tasks.add_task(run_browser_job, job.id)
    return _job_summary(job)


@router.post("/{job_id}/cancel")
async def cancel_browser_job(
    job_id: str,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _owned_job(db, job_id, current_user["user_id"])
    if job.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Browser job is already terminal")
    job.status = "cancelled"
    await db.commit()
    return _job_summary(job)


@router.get("/{job_id}/artifacts/{artifact_id}")
async def get_browser_artifact(
    job_id: str,
    artifact_id: str,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _owned_job(db, job_id, current_user["user_id"])
    result = await db.execute(
        select(BrowserArtifact)
        .where(BrowserArtifact.id == artifact_id, BrowserArtifact.job_id == job.id)
        .options(undefer(BrowserArtifact.content))
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Browser artifact not found")
    suffix = "png" if artifact.content_type == "image/png" else "txt"
    filename = f"browser-{job.id}-{artifact.kind}.{suffix}"
    return Response(
        content=artifact.content,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )
