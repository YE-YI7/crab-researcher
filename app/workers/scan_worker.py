"""Database-backed scan worker.

Run separately from the web service with::

    python -m app.workers.scan_worker
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal, Base, engine
from app.models.scan import ScanJob
from app.services.scan_service import run_scan_job

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def recover_stale_jobs(*, session_factory=AsyncSessionLocal, stale_after_minutes: int = 15) -> int:
    """Requeue jobs abandoned by a terminated worker."""
    cutoff = _utcnow() - timedelta(minutes=stale_after_minutes)
    async with session_factory() as db:
        result = await db.execute(
            update(ScanJob)
            .where(ScanJob.status == "running", ScanJob.started_at < cutoff)
            .values(status="queued", progress=0, error_message="Recovered after worker interruption")
        )
        await db.commit()
        return result.rowcount or 0


async def process_next_scan(*, session_factory=AsyncSessionLocal) -> bool:
    """Find the oldest queued job and let the atomic runner claim it."""
    async with session_factory() as db:
        result = await db.execute(
            select(ScanJob.id)
            .where(ScanJob.status == "queued")
            .order_by(ScanJob.created_at.asc())
            .limit(1)
        )
        job_id = result.scalar_one_or_none()
    if job_id is None:
        return False
    return await run_scan_job(job_id, session_factory=session_factory)


async def worker_loop() -> None:
    poll_seconds = max(float(os.getenv("SCAN_WORKER_POLL_SECONDS", "2")), 0.25)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    recovered = await recover_stale_jobs()
    logger.info("Scan worker started; recovered %s stale jobs", recovered)
    while True:
        processed = await process_next_scan()
        if not processed:
            await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(worker_loop())
