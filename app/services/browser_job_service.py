"""Durable execution service for browser jobs."""

from __future__ import annotations

from datetime import datetime, timezone

from async_timeout import timeout
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.browser import BrowserArtifact, BrowserJob, BrowserStep
from app.services.browser_provider import ApprovalRequired, BrowserSession, create_browser_session


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _load_job(session_factory, job_id: str) -> BrowserJob | None:
    async with session_factory() as db:
        result = await db.execute(
            select(BrowserJob)
            .where(BrowserJob.id == job_id)
            .options(selectinload(BrowserJob.steps), selectinload(BrowserJob.artifacts))
        )
        return result.scalar_one_or_none()


async def _mark_failed(session_factory, job_id: str, message: str, step_id: int | None = None) -> None:
    async with session_factory() as db:
        job = await db.get(BrowserJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = message[:2000]
            job.completed_at = _utcnow()
        if step_id:
            step = await db.get(BrowserStep, step_id)
            if step:
                step.status = "failed"
                step.error_message = message[:2000]
                step.completed_at = _utcnow()
        await db.commit()


async def run_browser_job(
    job_id: str,
    *,
    session_factory: async_sessionmaker = AsyncSessionLocal,
    browser_session: BrowserSession | None = None,
) -> bool:
    """Atomically claim and run a browser job until completion or approval."""
    settings = get_settings()
    async with session_factory() as db:
        claim = await db.execute(
            update(BrowserJob)
            .where(BrowserJob.id == job_id, BrowserJob.status == "queued")
            .values(
                status="running",
                started_at=_utcnow(),
                attempt_count=BrowserJob.attempt_count + 1,
                error_message=None,
            )
        )
        await db.commit()
        if not claim.rowcount:
            return False

    job = await _load_job(session_factory, job_id)
    if job is None:
        return False
    session = browser_session or create_browser_session(
        provider=job.provider,
        allowed_domains=list(job.allowed_domains or []),
        timeout_seconds=settings.BROWSER_JOB_TIMEOUT_SECONDS,
    )
    active_step_id: int | None = None

    try:
        async with timeout(settings.BROWSER_JOB_TIMEOUT_SECONDS):
            await session.start()

            # Approval may happen after the worker has stopped. Rebuild the
            # deterministic page state in a fresh isolated browser session.
            for completed in job.steps:
                if completed.position >= job.current_step:
                    break
                if completed.status == "completed" and completed.action in {"navigate", "click", "fill", "press"}:
                    await session.execute(completed.action, completed.params or {}, approved=True)

            for step_snapshot in job.steps:
                if step_snapshot.position < job.current_step:
                    continue
                active_step_id = step_snapshot.id
                async with session_factory() as db:
                    current_status = (await db.execute(
                        select(BrowserJob.status).where(BrowserJob.id == job_id)
                    )).scalar_one()
                if current_status == "cancelled":
                    return True
                if step_snapshot.requires_approval and step_snapshot.approved_at is None:
                    async with session_factory() as db:
                        job_row = await db.get(BrowserJob, job_id)
                        step_row = await db.get(BrowserStep, step_snapshot.id)
                        job_row.status = "awaiting_approval"
                        step_row.status = "awaiting_approval"
                        await db.commit()
                    return True

                async with session_factory() as db:
                    step_row = await db.get(BrowserStep, step_snapshot.id)
                    step_row.status = "running"
                    step_row.started_at = _utcnow()
                    await db.commit()

                try:
                    action_result = await session.execute(
                        step_snapshot.action,
                        step_snapshot.params or {},
                        approved=step_snapshot.approved_at is not None,
                    )
                except ApprovalRequired as exc:
                    async with session_factory() as db:
                        job_row = await db.get(BrowserJob, job_id)
                        step_row = await db.get(BrowserStep, step_snapshot.id)
                        job_row.status = "awaiting_approval"
                        step_row.status = "awaiting_approval"
                        step_row.requires_approval = True
                        step_row.result = {"approval_reason": str(exc)}
                        await db.commit()
                    return True

                async with session_factory() as db:
                    job_row = await db.get(BrowserJob, job_id)
                    step_row = await db.get(BrowserStep, step_snapshot.id)
                    step_row.status = "completed"
                    step_row.completed_at = _utcnow()
                    step_row.result = {"url": action_result.url, "title": action_result.title, **action_result.data}
                    job_row.current_url = action_result.url
                    job_row.current_step = step_snapshot.position + 1

                    if action_result.artifact_bytes is not None:
                        if len(action_result.artifact_bytes) > settings.BROWSER_MAX_ARTIFACT_BYTES:
                            raise ValueError("Browser artifact exceeds the configured size limit")
                        kind = action_result.artifact_kind or "artifact"
                        content_type = action_result.artifact_content_type or "application/octet-stream"
                        db.add(BrowserArtifact(
                            job_id=job_id,
                            step_id=step_row.id,
                            kind=kind,
                            content_type=content_type,
                            content=action_result.artifact_bytes,
                            size_bytes=len(action_result.artifact_bytes),
                            artifact_metadata={"url": action_result.url, "title": action_result.title},
                        ))
                    await db.commit()

            async with session_factory() as db:
                job_row = await db.get(BrowserJob, job_id)
                artifact_count = len((await db.execute(
                    select(BrowserArtifact.id).where(BrowserArtifact.job_id == job_id)
                )).scalars().all())
                job_row.status = "completed"
                job_row.completed_at = _utcnow()
                job_row.result_summary = {
                    "steps_completed": len(job.steps),
                    "artifact_count": artifact_count,
                    "final_url": job_row.current_url,
                }
                await db.commit()
        return True
    except TimeoutError:
        await _mark_failed(session_factory, job_id, "Browser job exceeded its execution timeout", active_step_id)
        return True
    except Exception as exc:
        await _mark_failed(session_factory, job_id, str(exc), active_step_id)
        return True
    finally:
        try:
            await session.close()
        except Exception:
            pass
