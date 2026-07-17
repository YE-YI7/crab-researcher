"""Tenant-scoped API for durable product research scans."""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import require_user
from app.models.scan import ScanJob
from app.models.task import UserProduct
from app.services.scan_service import run_scan_job

router = APIRouter(prefix="/scans", tags=["Product Scans"])


class ScanCreate(BaseModel):
    product_id: int = Field(..., gt=0)
    scan_type: Literal["market_landscape", "competitor", "customer_voice"] = "market_landscape"
    platforms: list[str] = Field(default_factory=list, max_length=10)
    locale: str = Field(default="en", min_length=2, max_length=20)


def _job_summary(job: ScanJob) -> dict:
    return {
        "id": job.id,
        "product_id": job.product_id,
        "scan_type": job.scan_type,
        "status": job.status,
        "progress": job.progress,
        "summary": job.result_summary or {},
        "error": job.error_message,
        "attempt_count": job.attempt_count,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "updated_at": job.updated_at,
    }


def _job_detail(job: ScanJob) -> dict:
    payload = _job_summary(job)
    payload.update({
        "product": {
            "id": job.product.id,
            "name": job.product.product_name,
            "industry": job.product.industry,
            "category": job.product.category,
            "keywords": job.product.keywords or [],
        },
        "sources": [
            {
                "id": source.id,
                "type": source.source_type,
                "platform": source.platform,
                "title": source.title,
                "url": source.url,
                "excerpt": source.excerpt,
                "relevance_score": source.relevance_score,
                "retrieved_at": source.retrieved_at,
            }
            for source in job.citations
        ],
        "competitors": [
            {
                "id": item.id,
                "source_id": item.source_citation_id,
                "name": item.name,
                "positioning": item.positioning,
                "evidence_summary": item.evidence_summary,
                "confidence": item.confidence,
            }
            for item in job.competitor_evidence
        ],
        "market_signals": [
            {
                "id": item.id,
                "source_id": item.source_citation_id,
                "type": item.signal_type,
                "title": item.title,
                "evidence_summary": item.evidence_summary,
                "relevance_score": item.relevance_score,
                "confidence": item.confidence,
            }
            for item in job.market_signals
        ],
        "opportunities": [
            {
                "id": item.id,
                "title": item.title,
                "rationale": item.rationale,
                "recommended_action": item.recommended_action,
                "channel": item.channel,
                "rank": item.rank,
                "confidence": item.confidence,
                "effort": item.effort,
                "expected_impact": item.expected_impact,
                "evidence_source_ids": item.evidence_source_ids or [],
                "status": item.status,
            }
            for item in sorted(job.opportunities, key=lambda row: row.rank)
        ],
    })
    return payload


async def _owned_product(db: AsyncSession, product_id: int, user_id: int) -> UserProduct:
    result = await db.execute(
        select(UserProduct).where(UserProduct.id == product_id, UserProduct.user_id == user_id)
    )
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


async def _owned_job(db: AsyncSession, job_id: str, user_id: int, *, details: bool = False) -> ScanJob:
    query = select(ScanJob).where(ScanJob.id == job_id, ScanJob.user_id == user_id)
    if details:
        query = query.options(
            selectinload(ScanJob.product),
            selectinload(ScanJob.citations),
            selectinload(ScanJob.competitor_evidence),
            selectinload(ScanJob.market_signals),
            selectinload(ScanJob.opportunities),
        )
    result = await db.execute(query)
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return job


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_scan(
    body: ScanCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=128),
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["user_id"]
    await _owned_product(db, body.product_id, user_id)

    if idempotency_key:
        existing = await db.execute(
            select(ScanJob).where(
                ScanJob.user_id == user_id,
                ScanJob.idempotency_key == idempotency_key,
            )
        )
        job = existing.scalar_one_or_none()
        if job is not None:
            return _job_summary(job)

    job = ScanJob(
        user_id=user_id,
        product_id=body.product_id,
        scan_type=body.scan_type,
        idempotency_key=idempotency_key,
        request_config={"platforms": body.platforms, "locale": body.locale},
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent retry may pass the pre-check. The database constraint is
        # authoritative, so return the already-created job instead of a 500.
        await db.rollback()
        if not idempotency_key:
            raise
        existing = await db.execute(
            select(ScanJob).where(
                ScanJob.user_id == user_id,
                ScanJob.idempotency_key == idempotency_key,
            )
        )
        existing_job = existing.scalar_one_or_none()
        if existing_job is None:
            raise
        return _job_summary(existing_job)
    await db.refresh(job)
    background_tasks.add_task(run_scan_job, job.id)
    return _job_summary(job)


@router.get("")
async def list_scans(
    scan_status: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ScanJob).where(ScanJob.user_id == current_user["user_id"])
    if scan_status:
        query = query.where(ScanJob.status == scan_status)
    result = await db.execute(query.order_by(ScanJob.created_at.desc()).limit(limit))
    return {"items": [_job_summary(job) for job in result.scalars().all()]}


@router.get("/{job_id}")
async def get_scan(
    job_id: str,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return _job_detail(await _owned_job(db, job_id, current_user["user_id"], details=True))


@router.post("/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_scan(
    job_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _owned_job(db, job_id, current_user["user_id"])
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed scans can be retried")
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    await db.commit()
    background_tasks.add_task(run_scan_job, job.id)
    return _job_summary(job)
