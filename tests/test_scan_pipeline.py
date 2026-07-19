"""Tests for the durable product scan pipeline."""

import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

import app.models  # noqa: F401
from app.api.v2 import products, scans
from app.api.v2.scans import _owned_job
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models.scan import ScanJob
from app.models.task import User, UserProduct
from app.services.scan_service import run_scan_job


class FakeWebSearch:
    async def execute(self, **kwargs):
        return {
            "results": [{
                "title": "Acme Analytics pricing",
                "url": "https://acme.example/pricing",
                "content": "Acme sells competitor monitoring for $49 per month.",
                "score": 0.91,
            }]
        }


class FakeSocialSearch:
    async def execute(self, **kwargs):
        return {
            "results": [{
                "title": "How do founders track competitor changes?",
                "url": "https://community.example/questions/1",
                "content": "Founders want a weekly, evidence-backed competitor digest.",
                "platform": "reddit",
            }]
        }


def test_scan_persists_evidence_and_opportunities():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessions() as db:
            user = User(company_name="Tenant One", contact_email="one@example.test", hashed_password="x")
            db.add(user)
            await db.flush()
            product = UserProduct(
                user_id=user.id,
                product_name="Crab Researcher",
                industry="SaaS",
                category="market intelligence",
                platforms=["reddit"],
            )
            db.add(product)
            await db.flush()
            job = ScanJob(user_id=user.id, product_id=product.id, request_config={})
            db.add(job)
            await db.commit()
            job_id = job.id
            user_id = user.id

        claimed = await run_scan_job(
            job_id,
            session_factory=sessions,
            web_tool=FakeWebSearch(),
            social_tool=FakeSocialSearch(),
        )
        assert claimed is True
        assert await run_scan_job(job_id, session_factory=sessions) is False

        async with sessions() as db:
            result = await db.execute(
                select(ScanJob)
                .where(ScanJob.id == job_id)
                .options(
                    selectinload(ScanJob.citations),
                    selectinload(ScanJob.competitor_evidence),
                    selectinload(ScanJob.market_signals),
                    selectinload(ScanJob.opportunities),
                )
            )
            completed = result.scalar_one()
            assert completed.status == "completed"
            assert completed.progress == 100
            assert completed.result_summary == {
                "source_count": 2,
                "competitor_count": 1,
                "signal_count": 1,
                "opportunity_count": 2,
                "warnings": [],
            }
            assert {source.url for source in completed.citations} == {
                "https://acme.example/pricing",
                "https://community.example/questions/1",
            }
            assert completed.opportunities[0].evidence_source_ids

            try:
                await _owned_job(db, job_id, user_id + 1)
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("another tenant must not see this scan")

        await engine.dispose()

    asyncio.run(scenario())


def test_scan_failure_is_persisted():
    class BrokenWebSearch:
        async def execute(self, **kwargs):
            raise RuntimeError("provider unavailable")

    class EmptySocialSearch:
        async def execute(self, **kwargs):
            return {"results": []}

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            user = User(company_name="Tenant", contact_email="fail@example.test", hashed_password="x")
            db.add(user)
            await db.flush()
            product = UserProduct(
                user_id=user.id,
                product_name="Product",
                industry="SaaS",
                category="research",
            )
            db.add(product)
            await db.flush()
            job = ScanJob(user_id=user.id, product_id=product.id)
            db.add(job)
            await db.commit()
            job_id = job.id

        await run_scan_job(
            job_id,
            session_factory=sessions,
            web_tool=BrokenWebSearch(),
            social_tool=EmptySocialSearch(),
        )
        async with sessions() as db:
            completed = await db.get(ScanJob, job_id)
            # Provider-level failures are partial results, not lost jobs.
            assert completed.status == "completed"
            assert completed.result_summary["warnings"] == ["web_search_failed", "no_sources_found"]
        await engine.dispose()

    asyncio.run(scenario())


def test_scan_api_is_idempotent_and_tenant_scoped(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            user = User(company_name="Tenant", contact_email="api@example.test", hashed_password="x")
            db.add(user)
            await db.commit()
            return user.id

    user_id = asyncio.run(setup())

    async def override_db():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def skip_background_run(job_id: str):
        return True

    monkeypatch.setattr(scans, "run_scan_job", skip_background_run)
    app = FastAPI()
    app.include_router(products.router, prefix="/api")
    app.include_router(scans.router, prefix="/api")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {create_access_token({'user_id': user_id})}",
        "Idempotency-Key": "same-request",
    }

    product = client.post("/api/products", headers=headers, json={
        "product_name": "Product",
        "industry": "SaaS",
        "category": "research",
        "platforms": ["reddit"],
    })
    assert product.status_code == 201
    product_id = product.json()["id"]
    assert len(client.get("/api/products", headers=headers).json()) == 1

    first = client.post("/api/scans", headers=headers, json={"product_id": product_id})
    second = client.post("/api/scans", headers=headers, json={"product_id": product_id})
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/api/scans", headers=headers).json()["items"]) == 1

    other_headers = {
        "Authorization": f"Bearer {create_access_token({'user_id': user_id + 1})}",
    }
    assert client.get(f"/api/products/{product_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/scans/{first.json()['id']}", headers=other_headers).status_code == 404
    asyncio.run(engine.dispose())
