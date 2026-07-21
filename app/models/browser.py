"""Durable, tenant-scoped browser automation jobs."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import deferred, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BrowserJob(Base):
    """A browser workflow that can be claimed by an isolated worker."""

    __tablename__ = "browser_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_browser_job_user_idempotency"),
        Index("ix_browser_jobs_user_created", "user_id", "created_at"),
        Index("ix_browser_jobs_status_created", "status", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("user_products.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(32), nullable=False, default="queued")
    provider = Column(String(32), nullable=False, default="local")
    goal = Column(Text, nullable=False, default="Inspect this page safely")
    start_url = Column(String(2000), nullable=False)
    current_url = Column(String(2000), nullable=True)
    allowed_domains = Column(JSON, nullable=False, default=list)
    current_step = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String(128), nullable=True)
    result_summary = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    steps = relationship(
        "BrowserStep",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="BrowserStep.position",
    )
    artifacts = relationship("BrowserArtifact", back_populates="job", cascade="all, delete-orphan")


class BrowserStep(Base):
    """One deterministic browser action in a job."""

    __tablename__ = "browser_steps"
    __table_args__ = (
        UniqueConstraint("job_id", "position", name="uq_browser_step_position"),
        Index("ix_browser_steps_job_position", "job_id", "position"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("browser_jobs.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    action = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    params = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=False, default=dict)
    requires_approval = Column(Boolean, nullable=False, default=False)
    approved_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    job = relationship("BrowserJob", back_populates="steps")
    artifacts = relationship("BrowserArtifact", back_populates="step")


class BrowserArtifact(Base):
    """A private screenshot or extracted text produced by a browser job."""

    __tablename__ = "browser_artifacts"
    __table_args__ = (Index("ix_browser_artifacts_job", "job_id", "created_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    job_id = Column(String(36), ForeignKey("browser_jobs.id", ondelete="CASCADE"), nullable=False)
    step_id = Column(Integer, ForeignKey("browser_steps.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(32), nullable=False)
    content_type = Column(String(100), nullable=False)
    # MVP artifacts live in the shared database so a separate worker and API
    # do not need a shared filesystem. Move large recordings to object storage.
    # Keep binary payloads out of job-list/detail queries; the authenticated
    # artifact endpoint explicitly undefer-loads this field.
    content = deferred(Column(LargeBinary, nullable=False))
    size_bytes = Column(Integer, nullable=False, default=0)
    artifact_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    job = relationship("BrowserJob", back_populates="artifacts")
    step = relationship("BrowserStep", back_populates="artifacts")
