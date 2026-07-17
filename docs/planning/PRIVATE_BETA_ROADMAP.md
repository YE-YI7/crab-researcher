# CrabRes private-beta roadmap

Goal: turn CrabRes from a convincing single-process demo into a safe, evidence-first product for 5–10 design partners. The first paid promise is not “autonomous AI CMO”; it is “three to five sourced growth opportunities each week, with human-approved execution and measurable outcomes.”

## Phase 0 — Safe private beta

Exit condition: one user cannot read, approve, trigger, or delete another user's data or actions; external side effects are off unless explicitly and safely configured.

- [x] Require user authentication on Execution and Workspace APIs.
- [x] Store approvals, rules, actions, and Workspace files per tenant.
- [x] Require GitHub signatures and a dedicated token for generic webhooks.
- [x] Require a dedicated admin key for process-wide Daemon controls.
- [x] Sign public share-card URLs and prevent cross-user token reuse.
- [x] Remove known default API/JWT secrets and validate production secrets.
- [x] Disable the global Daemon and real-world execution by default.
- [x] Add security regression tests and restore the complete test suite.
- [x] Stop retrying business-validation errors as “server cold starts.”
- [x] Make onboarding claims reflect when research actually starts.
- [ ] Add database migrations and remove schema creation from web startup.
- [ ] Add account deletion, privacy policy, terms, and retention controls.

## Phase 1 — Durable control plane

Exit condition: a research or execution job survives restarts, runs once, can be inspected, and can be safely retried.

- [ ] Persist sessions and jobs in PostgreSQL.
- [ ] Add a separate worker process and durable queue.
- [ ] Define job states: queued, running, awaiting approval, completed, failed, cancelled.
- [ ] Add idempotency keys, timeouts, bounded retries, and dead-letter handling.
- [ ] Add tenant-scoped encrypted credential storage; never use shared publishing credentials.
- [ ] Store immutable action/approval audit events.
- [ ] Enforce per-user monthly model and tool budgets in the primary Agent path.
- [ ] Add structured logs, error monitoring, traces, and operational alerts.
- [ ] Add CI for backend tests and frontend typecheck/build.

Implemented foundation (not yet deployed): persistent `scan_jobs`, atomic job
claiming, idempotent scan creation, evidence/result tables, tenant-scoped scan
APIs, and a database-polling worker entrypoint with stale-job recovery. Remaining
work includes deploying that worker, bounded retries/dead-letter handling, and
moving all legacy sessions/execution paths onto the same control plane.

## Phase 2 — Evidence-first product loop

Exit condition: a new user receives a specific, sourced opportunity and CrabRes can connect an approved action to an observed result.

- [ ] Replace generic dashboard tasks with opportunity cards containing sources, evidence excerpts, confidence, effort, and expected impact.
- [ ] Make onboarding create a durable product profile instead of sending a synthetic chat message.
- [ ] Show honest research progress and useful partial results.
- [ ] Require approval for every external side effect during private beta.
- [ ] Pull outcome metrics and connect them to the originating action.
- [ ] Track activation, first-value time, weekly retention, approval rate, execution rate, and outcome rate.
- [ ] Add one narrow integration set for the initial ICP instead of more expert personas.

Implemented foundation (UI still pending): canonical source citations,
competitor evidence, market signals, and ranked growth opportunities with
confidence, effort, expected impact, and evidence IDs.

## Phase 3 — Paid design-partner offer

Exit condition: at least three users repeatedly receive value and at least one pays without founder persuasion on every renewal.

- [ ] Recruit 5–10 English-market Micro-SaaS founders with 10–500 users.
- [ ] Deliver a weekly human-reviewed opportunity report and approval queue.
- [ ] Charge a concierge beta price before building broad self-serve automation.
- [ ] Record source-to-action-to-result case studies.
- [ ] Use interviews and retention data to decide whether the paid wedge is research, execution, or outcome tracking.
- [ ] Only then add billing entitlements and a $49–99 self-serve plan.

## Metrics for the private beta

- Activation: product profile completed and first sourced opportunity viewed.
- First value: median time from onboarding completion to first sourced opportunity.
- Weekly retained: user returns in a later week and reviews at least one new opportunity.
- Trust: percentage of proposed actions approved, edited, rejected, and reported as unsafe or irrelevant.
- Execution: percentage of approved actions successfully completed exactly once.
- Outcome: percentage of executed actions with a measurable result attached.
- Unit economics: model/tool cost per activated user and per measured outcome.

## Explicit non-goals until Phase 2 exits

- More expert personas.
- More publishing channels.
- Fully autonomous posting.
- Broad “AI CMO” positioning.
- Optimizing visual polish ahead of evidence quality and reliability.
