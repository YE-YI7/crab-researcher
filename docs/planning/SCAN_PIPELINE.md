# Persistent Scan Pipeline

The first productized research slice uses `user_products` as the canonical
Product Profile and adds five additive tables:

- `scan_jobs`: durable state, progress, attempts, idempotency, and errors
- `source_citations`: normalized provenance for every surfaced claim
- `competitor_evidence`: competitor hypotheses tied to citations
- `market_signals`: customer and market observations tied to citations
- `growth_opportunities`: ranked, actionable recommendations with evidence IDs

## API

- `POST /api/scans` creates and queues a scan. Send `Idempotency-Key` when a
  caller might retry the request.
- `GET /api/scans` lists only the authenticated tenant's scans.
- `GET /api/scans/{id}` returns structured evidence and opportunities.
- `POST /api/scans/{id}/retry` requeues a failed scan.

The API triggers a FastAPI background task for low-latency private-beta use, but
the execution contract is the standalone `run_scan_job(job_id)` service. Run
`python -m app.workers.scan_worker` as a separate Render Background Worker for
durable production execution. Both runners use an atomic database claim, so
they cannot execute the same queued job twice. The worker also requeues jobs
left stale by a terminated process.

## Deployment note

This slice only adds new tables, so the existing startup `metadata.create_all`
creates them safely on both a fresh database and the current database. Before
making destructive or column-level schema changes, introduce a versioned
Alembic baseline and run migrations as a deployment step instead of relying on
`create_all`.
