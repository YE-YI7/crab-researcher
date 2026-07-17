"""Persistent product-research jobs and evidence-backed scan results."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    """Naive UTC for compatibility with the project's existing DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ScanJob(Base):
    """A durable unit of research that can later be claimed by a worker."""

    __tablename__ = "scan_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_scan_job_user_idempotency"),
        Index("ix_scan_jobs_user_created", "user_id", "created_at"),
        Index("ix_scan_jobs_status_created", "status", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("user_products.id", ondelete="CASCADE"), nullable=False)
    scan_type = Column(String(50), nullable=False, default="market_landscape")
    status = Column(String(24), nullable=False, default="queued")
    progress = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String(128), nullable=True)
    request_config = Column(JSON, default=dict, nullable=False)
    result_summary = Column(JSON, default=dict, nullable=False)
    error_message = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    product = relationship("UserProduct", back_populates="scan_jobs")
    citations = relationship("SourceCitation", back_populates="scan_job", cascade="all, delete-orphan")
    competitor_evidence = relationship("CompetitorEvidence", back_populates="scan_job", cascade="all, delete-orphan")
    market_signals = relationship("MarketSignal", back_populates="scan_job", cascade="all, delete-orphan")
    opportunities = relationship("GrowthOpportunity", back_populates="scan_job", cascade="all, delete-orphan")


class SourceCitation(Base):
    """Normalized provenance for every claim surfaced by a scan."""

    __tablename__ = "source_citations"
    __table_args__ = (
        UniqueConstraint("scan_job_id", "url", name="uq_scan_citation_url"),
        Index("ix_source_citations_scan", "scan_job_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_job_id = Column(String(36), ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(50), nullable=False, default="web")
    platform = Column(String(50), nullable=True)
    title = Column(String(500), nullable=False, default="")
    url = Column(String(1000), nullable=False)
    excerpt = Column(Text, nullable=False, default="")
    relevance_score = Column(Float, nullable=False, default=0.0)
    source_metadata = Column(JSON, default=dict, nullable=False)
    retrieved_at = Column(DateTime, default=_utcnow, nullable=False)

    scan_job = relationship("ScanJob", back_populates="citations")


class CompetitorEvidence(Base):
    """A competitor hypothesis backed by a concrete citation."""

    __tablename__ = "competitor_evidence"
    __table_args__ = (Index("ix_competitor_evidence_scan", "scan_job_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_job_id = Column(String(36), ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False)
    source_citation_id = Column(Integer, ForeignKey("source_citations.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    positioning = Column(Text, nullable=False, default="")
    evidence_summary = Column(Text, nullable=False, default="")
    confidence = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    scan_job = relationship("ScanJob", back_populates="competitor_evidence")
    source = relationship("SourceCitation")


class MarketSignal(Base):
    """An observed customer, market, or channel signal with provenance."""

    __tablename__ = "market_signals"
    __table_args__ = (Index("ix_market_signals_scan", "scan_job_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_job_id = Column(String(36), ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False)
    source_citation_id = Column(Integer, ForeignKey("source_citations.id", ondelete="SET NULL"), nullable=True)
    signal_type = Column(String(50), nullable=False, default="customer_discussion")
    title = Column(String(500), nullable=False)
    evidence_summary = Column(Text, nullable=False, default="")
    relevance_score = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    scan_job = relationship("ScanJob", back_populates="market_signals")
    source = relationship("SourceCitation")


class GrowthOpportunity(Base):
    """A prioritized action derived from evidence rather than free-form chat."""

    __tablename__ = "growth_opportunities"
    __table_args__ = (Index("ix_growth_opportunities_scan_rank", "scan_job_id", "rank"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_job_id = Column(String(36), ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=False)
    rationale = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    channel = Column(String(50), nullable=False, default="product")
    rank = Column(Integer, nullable=False, default=1)
    confidence = Column(Float, nullable=False, default=0.0)
    effort = Column(String(20), nullable=False, default="medium")
    expected_impact = Column(String(20), nullable=False, default="medium")
    evidence_source_ids = Column(JSON, default=list, nullable=False)
    status = Column(String(20), nullable=False, default="proposed")
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    scan_job = relationship("ScanJob", back_populates="opportunities")
