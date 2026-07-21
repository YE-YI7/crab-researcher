"""Database-backed browser worker. Run only in an isolated worker service."""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.models.browser import BrowserJob
from app.services.browser_job_service import run_browser_job

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def recover_stale_jobs(stale_after_minutes: int = 5) -> int:
    cutoff = _utcnow() - timedelta(minutes=stale_after_minutes)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(BrowserJob)
            .where(BrowserJob.status == "running", BrowserJob.started_at < cutoff)
            .values(status="queued", error_message="Recovered after browser worker interruption")
        )
        await db.commit()
        return result.rowcount or 0


async def process_next_job() -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BrowserJob.id)
            .where(BrowserJob.status == "queued")
            .order_by(BrowserJob.created_at.asc())
            .limit(1)
        )
        job_id = result.scalar_one_or_none()
    return False if job_id is None else await run_browser_job(job_id)


async def worker_loop() -> None:
    settings = get_settings()
    if not settings.BROWSER_WORKER_ENABLED:
        raise RuntimeError("BROWSER_WORKER_ENABLED must be true in the isolated worker service")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.info("Browser worker started; recovered %s jobs", await recover_stale_jobs())
    poll_seconds = max(float(os.getenv("BROWSER_WORKER_POLL_SECONDS", "2")), 0.25)
    while True:
        if not await process_next_job():
            await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(worker_loop())
