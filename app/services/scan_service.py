"""Execution service for durable, evidence-backed product scans.

The API and the future queue worker both call this module. Keeping research out of
the HTTP route makes replacing the temporary in-process runner straightforward.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select, update

from app.agent.tools.research import SocialSearchTool, WebSearchTool
from app.core.database import AsyncSessionLocal
from app.models.scan import (
    CompetitorEvidence,
    GrowthOpportunity,
    MarketSignal,
    ScanJob,
    SourceCitation,
)
from app.models.task import UserProduct

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _score(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _source_url(value: Any) -> str | None:
    url = str(value or "").strip()[:1000]
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


async def run_scan_job(
    job_id: str,
    *,
    session_factory=AsyncSessionLocal,
    web_tool: WebSearchTool | None = None,
    social_tool: SocialSearchTool | None = None,
) -> bool:
    """Claim and execute one queued scan.

    Returns ``False`` when another runner already claimed the job. All failures
    are persisted on the job so callers never need to infer state from a timeout.
    """

    async with session_factory() as db:
        claim = await db.execute(
            update(ScanJob)
            .where(ScanJob.id == job_id, ScanJob.status == "queued")
            .values(
                status="running",
                progress=10,
                started_at=_utcnow(),
                error_message=None,
                attempt_count=ScanJob.attempt_count + 1,
            )
        )
        await db.commit()
        if claim.rowcount != 1:
            return False

    try:
        async with session_factory() as db:
            row = await db.execute(
                select(ScanJob, UserProduct)
                .join(UserProduct, ScanJob.product_id == UserProduct.id)
                .where(ScanJob.id == job_id)
            )
            pair = row.one_or_none()
            if not pair:
                raise RuntimeError("Scan product no longer exists")
            job, product = pair

            config = job.request_config or {}
            query = " ".join(str(part) for part in [
                product.product_name,
                product.category,
                product.industry,
                " ".join((product.keywords or [])[:5]),
                config.get("locale", ""),
            ] if part)
            platforms = config.get("platforms") or product.platforms or ["reddit", "hackernews"]
            social_platforms = [p for p in platforms if p in {
                "reddit", "x", "hackernews", "producthunt", "linkedin",
                "xiaohongshu", "jike", "bilibili", "zhihu",
            }] or ["reddit", "hackernews"]

        web = web_tool or WebSearchTool()
        social = social_tool or SocialSearchTool()
        search_suffix = {
            "competitor": "direct competitors pricing features alternatives",
            "customer_voice": "customer reviews complaints pain points discussions",
            "market_landscape": "competitors pricing alternatives market trends",
        }.get(job.scan_type, "competitors pricing alternatives")
        web_result, social_result = await asyncio.gather(
            web.execute(query=f"{query} {search_suffix}", num_results=8),
            social.execute(query=query, platforms=social_platforms),
            return_exceptions=True,
        )
        if isinstance(web_result, Exception):
            logger.warning("Web scan failed for %s: %s", job_id, web_result)
            web_result = {"results": [], "error": str(web_result)}
        if isinstance(social_result, Exception):
            logger.warning("Social scan failed for %s: %s", job_id, social_result)
            social_result = {"results": [], "error": str(social_result)}

        await _persist_results(
            job_id,
            web_result,
            social_result,
            scan_type=job.scan_type,
            session_factory=session_factory,
        )
        return True
    except Exception as exc:
        logger.exception("Scan job %s failed", job_id)
        async with session_factory() as db:
            await db.execute(
                update(ScanJob)
                .where(ScanJob.id == job_id)
                .values(
                    status="failed",
                    progress=100,
                    completed_at=_utcnow(),
                    error_message=str(exc)[:2000],
                )
            )
            await db.commit()
        return True


async def _persist_results(
    job_id: str,
    web_result: dict,
    social_result: dict,
    *,
    scan_type: str = "market_landscape",
    session_factory=AsyncSessionLocal,
) -> None:
    async with session_factory() as db:
        citation_by_url: dict[str, SourceCitation] = {}
        competitors: list[CompetitorEvidence] = []
        signals: list[MarketSignal] = []

        for item in (web_result.get("results") or [])[:8]:
            url = _source_url(item.get("url"))
            if not url or url in citation_by_url:
                continue
            citation = SourceCitation(
                scan_job_id=job_id,
                source_type="web",
                title=str(item.get("title") or "")[:500],
                url=url,
                excerpt=str(item.get("content") or "")[:3000],
                relevance_score=_score(item.get("score")),
            )
            db.add(citation)
            await db.flush()
            citation_by_url[url] = citation
            if scan_type != "customer_voice":
                competitor = CompetitorEvidence(
                    scan_job_id=job_id,
                    source_citation_id=citation.id,
                    name=citation.title[:255] or url[:255],
                    evidence_summary=citation.excerpt,
                    confidence=max(0.35, citation.relevance_score),
                )
                db.add(competitor)
                competitors.append(competitor)

        for item in (social_result.get("results") or [])[:8]:
            url = _source_url(item.get("url"))
            if not url:
                continue
            citation = citation_by_url.get(url)
            if citation is None:
                citation = SourceCitation(
                    scan_job_id=job_id,
                    source_type="social",
                    platform=str(item.get("platform") or "other")[:50],
                    title=str(item.get("title") or "")[:500],
                    url=url,
                    excerpt=str(item.get("content") or "")[:3000],
                    relevance_score=0.55,
                )
                db.add(citation)
                await db.flush()
                citation_by_url[url] = citation
            signal = MarketSignal(
                scan_job_id=job_id,
                source_citation_id=citation.id,
                signal_type="customer_discussion",
                title=citation.title or "Customer discussion",
                evidence_summary=citation.excerpt,
                relevance_score=citation.relevance_score,
                confidence=0.55,
            )
            db.add(signal)
            signals.append(signal)

        opportunities = _build_opportunities(job_id, competitors, signals)
        db.add_all(opportunities)

        warnings = []
        if web_result.get("error"):
            warnings.append("web_search_failed")
        if social_result.get("error"):
            warnings.append("social_search_failed")
        if not citation_by_url:
            warnings.append("no_sources_found")

        await db.execute(
            update(ScanJob)
            .where(ScanJob.id == job_id)
            .values(
                status="completed",
                progress=100,
                completed_at=_utcnow(),
                result_summary={
                    "source_count": len(citation_by_url),
                    "competitor_count": len(competitors),
                    "signal_count": len(signals),
                    "opportunity_count": len(opportunities),
                    "warnings": warnings,
                },
            )
        )
        await db.commit()


def _build_opportunities(
    job_id: str,
    competitors: list[CompetitorEvidence],
    signals: list[MarketSignal],
) -> list[GrowthOpportunity]:
    opportunities: list[GrowthOpportunity] = []
    if signals:
        signal = signals[0]
        opportunities.append(GrowthOpportunity(
            scan_job_id=job_id,
            title=f"Answer the demand behind: {signal.title[:180]}",
            rationale="A live customer discussion is direct evidence of an unanswered question or pain point.",
            recommended_action="Publish a concise, source-backed answer and turn it into a free diagnostic tool.",
            channel="content",
            rank=1,
            confidence=signal.confidence,
            effort="low",
            expected_impact="medium",
            evidence_source_ids=[signal.source_citation_id],
        ))
    if competitors:
        competitor = competitors[0]
        opportunities.append(GrowthOpportunity(
            scan_job_id=job_id,
            title=f"Create a comparison page against {competitor.name[:180]}",
            rationale="The competitor appears in current search evidence and can anchor high-intent comparison traffic.",
            recommended_action="Document verifiable differences, pricing, ideal users, and trade-offs; do not invent claims.",
            channel="seo",
            rank=len(opportunities) + 1,
            confidence=competitor.confidence,
            effort="medium",
            expected_impact="medium",
            evidence_source_ids=[competitor.source_citation_id],
        ))
    return opportunities
