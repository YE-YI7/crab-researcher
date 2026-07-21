# 🦀 CrabRes

> An AI growth strategy agent for indie developers — not just chat, but an agent that actually does the research, shapes the strategy, ships the content, and watches the competition.

[![Live demo](https://img.shields.io/badge/demo-crab--researcher.vercel.app-orange)](https://crab-researcher.vercel.app/)
[![Version](https://img.shields.io/badge/version-v5.1.0-blue)](./CHANGELOG.md)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)

CrabRes is a growth agent I built for indie developers. It works, but not well enough yet — and that gap taught me more about agent design than anything else.

<p align="center">
  <a href="https://crab-researcher.vercel.app/">
    <img src="docs/demo/demo.gif" alt="CrabRes demo: ask a question, watch 13 experts research and respond" width="800" />
  </a>
  <br />
  <sub><em>Ask once. Watch the agent research, run a 13-expert roundtable, and ship deliverables.</em></sub>
</p>

---

## What is this

**CrabRes** is a growth agent that lives in your terminal and browser. Hand it your product, and it will:

1. **Research proactively** — searches for competitors, scrapes landing pages, and reads social media on its own. It won't bombard you with questions before doing any work.
2. **A 13-expert roundtable** — Market Researcher, Economist, Content Strategist, Social Media Expert, Paid Ads, Partnerships, AI Distribution, Consumer Psychologist, Product Growth, Data Analyst, Master Copywriter, Strategy Critic, and Design Expert — dynamically weighted by product type.
3. **Continuous watch** — Growth Daemon runs every 30 minutes: scans competitor changes, captures social mentions, and tracks how the content you shipped is performing.
4. **Dreams every night** — Growth Dream runs at midnight, distilling the day's scattered signals into long-term memory. It wakes up understanding your product a little better each day.
5. **Actually takes action** — not just suggestions. It posts to X via the API, drafts directory submissions, and writes outreach emails.

Core principle: **Research First, Ask Last**. The agent's default action is to search, not to interrogate.

---

## Why I built this

What indie developers lack isn't product chops — it's growth chops. Most "AI marketing tools" on the market are ChatGPT wrappers with templates: ask a question, get an answer. No real research chain, no memory, no autonomous action.

CrabRes is an attempt at an **agent that actually touches the real world**:
- It can **see** (Playwright screenshots + multimodal understanding)
- It can **search** (Tavily deep search + Firecrawl deep scrape)
- It can **publish** (X API v2 with OAuth 1.0a)
- It can **remember** (8 memory categories + vector retrieval)
- It can **think** (4-tier LLM routing — strong models for critical decisions, cheap models for parsing)

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Frontend (Vercel)                                  │
│  React + Tailwind + Zustand                         │
│  Expert roundtable chat / Growth dashboard / Memory │
└──────────────────┬──────────────────────────────────┘
                   │ SSE streaming + REST
┌──────────────────▼──────────────────────────────────┐
│  Backend (Render)                                   │
│  FastAPI + SQLAlchemy + asyncio                     │
│                                                     │
│  ┌─────────────────────────────────────────┐        │
│  │  Agent Engine (GraphBuilder, v5.0)      │        │
│  │  ├─ Router → Quick / Pipeline / ReAct   │        │
│  │  ├─ Shared Nodes                        │        │
│  │  │   understand → research → expert →   │        │
│  │  │   deliver  (intent-aware artifacts)  │        │
│  │  ├─ Expert Pool (13, weighted + LLM    │         │
│  │  │   refinement for off-axis products)  │        │
│  │  ├─ Tool Registry                       │        │
│  │  └─ Memory (8 categories + pgvector)    │        │
│  └─────────────────────────────────────────┘        │
│                                                     │
│  ┌─────────────────────────────────────────┐        │
│  │  Growth Daemon (30-min tick)            │        │
│  │  competitors → social → campaigns → push│        │
│  └─────────────────────────────────────────┘        │
│                                                     │
│  ┌─────────────────────────────────────────┐        │
│  │  Growth Dream (midnight distillation)   │        │
│  │  orient → gather → consolidate → prune  │        │
│  └─────────────────────────────────────────┘        │
└──────────────────┬──────────────────────────────────┘
                   │
         ┌─────────┼─────────┬──────────┬──────────┐
         ▼         ▼         ▼          ▼          ▼
    TokenDance  Moonshot   Tavily   Firecrawl    Neon
    (4-tier:    (fallback) (search) (deep scrape) (PG+pgvector)
     DeepSeek
     /GLM/Kimi
     /Qwen)
```

---

## What's new in v5.1

The biggest lesson from v4 → v5: **don't ask an LLM to do something `if/else` can do.**

| Job | v4.x | v5.1 |
|---|---|---|
| Decide route (Quick / Pipeline / ReAct) | LLM | Regex first, LLM only on low-confidence short messages |
| Pick the 4 experts for this product | LLM, every time | Code lookup; LLM only for off-axis products |
| Generate deliverables | Always 4 artifacts | Intent-aware: "give me a competitor analysis only" → just the report |
| Cost of a single "hi" | ~$0.02 | **$0.0005** |
| Cost of a full strategy session | unbounded | **~$0.025** |

Plus: TokenDance gateway (DeepSeek V4 / GLM 4.7 / Kimi K2.6 / Qwen3) as the primary LLM provider with Moonshot/OpenRouter fallback, output safety check on every deliverable, soft-budget alerts at 80% of session cap, and a 3-layer eval system (`app/agent/eval/`). Full details in [CHANGELOG.md](./CHANGELOG.md).

---

## Core Features

### 1. A Research-First Agent
GraphBuilder's first rule is simple: **if you can search, don't ask.** When a user sends a terse message like "xx is a competitor", the agent immediately:
- Fires `web_search("xx competitor analysis")`
- Scrapes the top result's landing page
- Extracts product info and writes it to memory
- Only then replies — it does not open with "can you tell me more?"

### 2. The 13-Expert Roundtable
Not a simple prompt swap — experts are dynamically weighted by product type (SaaS / tool / community / content). A B2B SaaS surfaces the Economist and Partnerships experts; a consumer tool surfaces Social Media and Psychologist. Every expert has its own thinking style and knowledge base.

### 3. Growth Daemon — Real Background Work
Not a cron job — a continuously running loop:
- **Competitor scan**: reads `research/competitors.json`, diffs each competitor's landing page, pushes alerts on pricing changes or new features
- **Social scan**: searches for mentions of your product and every tracked competitor on X / Reddit / HN
- **Campaign tracking**: if an `active_campaign` is set (e.g. a tweet URL), pulls engagement hourly
- **Discovery push**: new findings land in `pending_discoveries`; the frontend polls and surfaces them

### 4. Automatic Competitor Discovery & Tracking
Search results are auto-filtered (twitter / reddit / search-engine domains are dropped), extracted competitor domains are written to `research/competitors.json`, and the Daemon starts tracking them automatically. Users never have to type a competitor list by hand.

### 5. It Can See and Ship
- **BrowseWebsiteTool**: real browser via Playwright + screenshot, then Gemini 2.0 Flash or GPT-4o-mini reads the image and returns product positioning / value prop / pricing / trust signals / design style
- **TwitterPostTool**: real tweet publishing with OAuth 1.0a signing — not "here's the draft, copy-paste it yourself"

### 6. Memory System
Eight categorized directories plus pgvector semantic search:
```
.crabres/memory/{user_id}/
├── product/      # product essence
├── goals/        # goals & OKRs
├── research/     # competitors, market data
├── strategy/     # strategic decisions
├── execution/    # actions taken
├── feedback/     # outcome signals
├── journal/      # conversation logs
└── knowledge/    # long-term knowledge
```

### 7. Trust Levels
Cautious → Building → Trusted → Autopilot. Early on, the agent confirms every action. As trust grows, it can autonomously post, reach out, and hit external systems on the user's behalf.

### 8. Four-Tier LLM Routing (via TokenDance gateway)
- **CRITICAL** (CGO synthesis): DeepSeek V4 Pro → GLM 4.7 → Kimi K2.6
- **THINKING** (expert analysis): GLM 4.7 → DeepSeek V4 Pro
- **WRITING** (copy generation): GLM 4.7 → DeepSeek V4 Flash
- **PARSING** (router fallback / JSON extraction): Qwen3 8B → DeepSeek V4 Flash

All tiers fall back to Moonshot / OpenRouter when TokenDance is unavailable. Providers without API keys are skipped automatically to avoid wasted retries. Saves money without cutting corners on the decisions that matter — a full growth-strategy session runs ~$0.025; a single greeting runs ~$0.0005 via the Quick path.

---

## Tech Stack

**Backend**
- FastAPI + Pydantic v2 + SQLAlchemy 2.0 async
- PostgreSQL (Neon) + pgvector
- Playwright (browser) + httpx (HTTP)
- TokenDance gateway (DeepSeek V4 / GLM 4.7 / Kimi K2.6 / Qwen3) + Moonshot / OpenRouter fallback
- Tavily (search) + Firecrawl (deep scrape)
- Tweepy / hand-rolled OAuth 1.0a

**Frontend**
- React 18 + TypeScript + Vite
- Tailwind CSS + shadcn/ui
- Zustand (state) + SSE (streaming chat)

**Deployment**
- Frontend: Vercel
- API: Render Web Service
- Browser execution: dedicated Render Background Worker (disabled until explicitly configured)
- Database: Neon PostgreSQL (shared durable job queue and small private artifacts)

---

## Quick Start

**Try it now**: https://crab-researcher.vercel.app/ (heads-up: backend runs on Render's free tier, first request after idle takes 30-60s to wake up — the frontend shows a banner).

Or run locally:

```bash
git clone https://github.com/calebguo007/crab-researcher.git
cd crab-researcher

# Backend
cp .env.example .env          # fill in TOKENDANCE_API_KEY, TAVILY_API_KEY, DATABASE_URL
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8002

# Optional: real browser jobs (separate terminal/process)
python -m patchright install chromium
# Set BROWSER_WORKER_ENABLED=true in .env, then run:
python -m app.workers.browser_worker

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                    # http://localhost:3000
```

**Required env vars**:
- `TOKENDANCE_API_KEY` — primary LLM provider; covers DeepSeek V4 / GLM 4.7 / Kimi K2.6 / Qwen3 8B across all 4 tiers
- `TAVILY_API_KEY` — search backend
- `DATABASE_URL` / `DATABASE_URL_SYNC` — Postgres; sqlite works for local dev with code changes

Optional fallback keys (auto-skipped if missing): `MOONSHOT_API_KEY`, `OPENROUTER_API_KEY`, `FIRECRAWL_API_KEY`.

### Browser worker and sandbox boundary

Browser jobs are durable, tenant-scoped, approval-gated workflows. The API writes jobs to PostgreSQL and a separate worker claims them, launches Chromium, applies an HTTPS/domain/public-IP network policy, and stores bounded screenshots or extracted text back in PostgreSQL. Use `BROWSER_RUN_INLINE=true` only for local development.

For local development, `BROWSER_PROVIDER=local` runs Chromium in the worker process and is **not** a per-job security boundary. Production uses `BROWSER_PROVIDER=vercel`: the Render worker creates one Vercel Firecracker microVM per browser job, boots it from a prebuilt Chromium image, and applies a deny-by-default SNI firewall plus private/reserved CIDR blocks. Vercel credentials stay in the Render worker and are never copied into the microVM.

Build and push the browser runtime to Vercel Container Registry (replace the team/project slugs):

```bash
vercel link
vercel env pull
printf '%s' "$VERCEL_OIDC_TOKEN" | docker login vcr.vercel.com --username oidc --password-stdin
docker buildx build \
  -f Dockerfile.sandbox-image \
  --platform linux/amd64 \
  --output "type=image,name=vcr.vercel.com/TEAM/PROJECT/crab-browser:latest,push=true,oci-mediatypes=true,compression=zstd,compression-level=3,force-compression=true" \
  .
```

Deploy the database worker with `Dockerfile.browser`, give it the same `DATABASE_URL` as the API, and configure `BROWSER_WORKER_ENABLED=true`, `BROWSER_PROVIDER=vercel`, `VERCEL_SANDBOX_IMAGE=crab-browser:latest`, `VERCEL_TEAM_ID`, `VERCEL_PROJECT_ID`, and a sensitive `VERCEL_TOKEN`. Set `BROWSER_WORKER_ENABLED=true`, `BROWSER_PROVIDER=vercel`, and the image name on the API service too, but keep the token only on the worker. Keep `BROWSER_RUN_INLINE=false` in production.

**Other entry points**: Discord / WhatsApp / Feishu bot bindings (`app/channels/`), CLI (`cli/`), MCP plugin (`mcp/`).

---

## Project Structure

```
crab-researcher/
├── app/
│   ├── agent/
│   │   ├── engine/          # GraphBuilder + Router + shared nodes / LLM adapter
│   │   ├── experts/         # 13 expert implementations
│   │   ├── tools/           # research / action / browser / twitter tools
│   │   ├── daemon/          # Growth Daemon
│   │   ├── dream/           # Growth Dream memory distillation
│   │   └── memory/          # 8-category memory system
│   ├── api/v2/              # REST + SSE endpoints
│   ├── core/                # config, security, database
│   └── models/              # SQLAlchemy models
├── frontend/                # React frontend
├── alembic/                 # database migrations
├── docs/planning/           # Chinese planning & research docs
└── tests/                   # pytest
```

---

## Design Philosophy

> "An agent that only asks questions isn't an agent — it's a questionnaire."

Every design decision in CrabRes answers the same question: **does this make the agent feel more like a real growth partner, or more like a chatbot?**

- Search over asking
- Action over advice
- Memory over context
- Multiple expert perspectives over a single answer
- Continuous monitoring over one-shot consulting

---

## Roadmap

**Now (P0)**: connect the agent to the real world
- [x] Research-First loop rewrite
- [x] Automatic competitor discovery & tracking
- [x] X/Twitter API publishing
- [x] Multimodal screenshot understanding
- [ ] Daemon feedback loop (campaign outcomes → expert learning)
- [ ] MCP client (plug in the user's own tools)

**Next**: memory and trust
- [ ] Trust Levels frontend UI
- [ ] Growth Dream long-term insight visualization
- [ ] Expert weights evolving with product type

---

## License

MIT

---

**CrabRes — not just advice, action.**
