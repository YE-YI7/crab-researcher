# CrabRes Agent Evaluation Framework

> How do we know if CrabRes is actually good?

## Philosophy

Most AI agent benchmarks measure **can it do the task** (SWE-bench, HumanEval).
CrabRes needs a different lens: **does it actually help users grow?**

We measure three layers, from basic to impactful:

```
Layer 3: GROWTH IMPACT   ← Does the user's product actually grow?
Layer 2: EFFICIENCY       ← How well does the agent work?
Layer 1: CAPABILITY       ← Can it do the job at all?
```

---

## Layer 1: Capability Metrics

These answer: "Does the agent function correctly?"

| Metric | ID | Definition | How to Measure | Target |
|--------|-----|-----------|----------------|--------|
| Task Completion Rate | `TCR` | % of user messages that receive a substantive response (not error/fallback) | `successful_responses / total_messages` | ≥ 95% |
| Research Data Rate | `RDR` | % of search queries that return useful data | `useful_results / total_search_calls` where `useful = content_len > 200 && !error` | ≥ 50% |
| Expert Activation Rate | `EAR` | % of experts that produce valid analysis (not timeout/error) | `valid_outputs / activated_experts` | ≥ 80% |
| Language Consistency | `LCR` | % of responses matching the user's chosen language | `correct_language_responses / total_responses` | 100% |
| Deliverable Generation Rate | `DGR` | % of full-pipeline runs that produce at least 1 deliverable file | `sessions_with_deliverables / full_pipeline_sessions` | ≥ 70% |
| Playbook Generation Rate | `PGR` | % of full-pipeline runs that create a structured Playbook | `sessions_with_playbook / full_pipeline_sessions` | ≥ 50% |

### Automated Test Suite

```python
# tests/eval/test_capability.py

CAPABILITY_SCENARIOS = [
    {
        "name": "basic_saas_analysis",
        "input": "I'm building an AI resume optimizer at $9.99/mo. Goal: 1000 users in 3 months.",
        "language": "en",
        "assertions": [
            "response is not empty",
            "response language is English",
            "pipeline reached Step 4 (RESPOND)",
            "at least 1 search query executed",
            "at least 2 experts activated",
            "response mentions at least 1 competitor by name",
            "response includes specific numbers (pricing, traffic, etc)",
        ],
    },
    {
        "name": "chinese_consumer_app",
        "input": "我做了一个习惯追踪 App，还没有用户，零预算。",
        "language": "zh",
        "assertions": [
            "response is in Chinese",
            "all expert outputs are in Chinese",
            "response acknowledges zero budget constraint",
            "response suggests free channels (Reddit, community, etc)",
        ],
    },
    {
        "name": "followup_question",
        "input_sequence": [
            "I'm building a B2B SaaS for HR teams",
            "What about LinkedIn specifically?",
        ],
        "assertions": [
            "second response uses prior research data (no re-search)",
            "second response is focused on LinkedIn",
            "second response is shorter than first",
        ],
    },
    {
        "name": "greeting_handling",
        "input": "hi",
        "assertions": [
            "response is ≤ 3 sentences",
            "response asks about user's product",
            "no search tools called",
            "no experts activated",
        ],
    },
    {
        "name": "deep_strategy_trigger",
        "input": "I need a deep strategy rethink for my product",
        "assertions": [
            "deep strategy job created",
            "response mentions background processing",
            "job status is RESEARCHING or later",
        ],
    },
]
```

---

## Layer 2: Efficiency Metrics

These answer: "How well does the agent use resources?"

| Metric | ID | Definition | How to Measure | Target |
|--------|-----|-----------|----------------|--------|
| Tokens Per Task | `TPT` | Total tokens consumed for one full analysis | `llm.usage.total_tokens` after pipeline completes | ≤ 15,000 |
| Cost Per Task | `CPT` | USD cost for one full analysis | `llm.usage.total_cost_usd` | ≤ $0.05 |
| Time to First Response | `TTFR` | Seconds from user message to first SSE event | `first_event_timestamp - request_timestamp` | ≤ 3s |
| Time to Complete | `TTC` | Seconds from user message to final response | `last_event_timestamp - request_timestamp` | ≤ 60s |
| Fallback Rate | `FBR` | % of LLM calls that fell back to a cheaper model | `fallback_calls / total_llm_calls` | ≤ 20% |
| Knowledge Injection Efficiency | `KIE` | % of knowledge selectively loaded vs full dump | `selective_loads / total_knowledge_loads` | ≥ 60% |
| Memory Hit Rate | `MHR` | % of sessions where prior memory was successfully loaded and used | `sessions_with_memory_hit / total_sessions` | ≥ 50% (returning users) |

### Cost Budget Rules

```
Per-session budget:  $1.00 (default)
Per-daemon-tick:     $0.10
Per-deep-strategy:   $2.00

Monthly per user:    $100.00
Monthly daemon:      $15.00 (30min × 48 ticks/day × 30 days × $0.01/tick)
```

---

## Layer 3: Growth Impact Metrics

These answer: "Does CrabRes actually help users grow?"

| Metric | ID | Definition | How to Measure | Target |
|--------|-----|-----------|----------------|--------|
| Advice Adoption Rate | `AAR` | % of strategy suggestions the user acts on | Track Playbook step completion rate | ≥ 30% |
| Deliverable Usage Rate | `DUR` | % of generated content (posts, emails) the user actually publishes | User marks deliverable as "published" in UI | ≥ 20% |
| Session Return Rate | `SRR` | % of users who return within 7 days | `returning_users_7d / total_users` | ≥ 40% |
| Growth Signal Rate | `GSR` | % of users who report measurable growth (signups, revenue, traffic) | Growth Loop result entries with positive metrics | ≥ 10% |
| Net Promoter Score | `NPS` | Would you recommend CrabRes? (0-10) | In-app survey after 3rd session | ≥ 40 |
| Time to First Value | `TTFV` | Minutes from signup to first actionable insight | Track onboarding → first full analysis completion | ≤ 5 min |

---

## Automated Evaluation Pipeline

### Architecture

```
┌─────────────────────────────────────────────────┐
│                  Eval Runner                     │
│                                                  │
│  1. Load scenario from CAPABILITY_SCENARIOS      │
│  2. Send message to /api/agent/chat              │
│  3. Collect all SSE events                       │
│  4. Run assertions                               │
│  5. Measure L1/L2 metrics                        │
│  6. Generate report                              │
│                                                  │
│  Runs: on every PR + nightly full suite          │
└─────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│              Metrics Collector                    │
│                                                  │
│  - Hooks into AgentLLM._track_usage()            │
│  - Hooks into PipelineRunner._persist()          │
│  - Hooks into PlaybookStore.save_playbook()      │
│  - Writes to .crabres/eval/metrics.jsonl         │
│                                                  │
│  Runs: on every user interaction (production)    │
└─────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│              Eval Dashboard                      │
│                                                  │
│  Frontend: /eval page (admin only)               │
│  Shows: TCR, RDR, EAR, TPT, CPT trends          │
│  Alerts: when any metric drops below target      │
│                                                  │
│  Runs: always available                          │
└─────────────────────────────────────────────────┘
```

### Implementation Plan

```python
# app/agent/eval/collector.py

class MetricsCollector:
    """
    Lightweight metrics collection that hooks into existing code.
    No new dependencies. Just writes JSONL.
    """
    
    def __init__(self, base_dir: str = ".crabres/eval"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def record_session(self, session_id: str, metrics: dict):
        """Record metrics for a completed session"""
        entry = {
            "timestamp": time.time(),
            "session_id": session_id,
            **metrics,
        }
        path = self.base_dir / "metrics.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def record_event(self, event_type: str, data: dict):
        """Record individual events (LLM call, search, expert activation)"""
        entry = {
            "timestamp": time.time(),
            "event": event_type,
            **data,
        }
        path = self.base_dir / "events.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def get_summary(self, days: int = 7) -> dict:
        """Generate summary metrics for the last N days"""
        cutoff = time.time() - days * 86400
        metrics = []
        path = self.base_dir / "metrics.jsonl"
        if path.exists():
            for line in path.read_text().strip().split("\n"):
                if line:
                    entry = json.loads(line)
                    if entry.get("timestamp", 0) > cutoff:
                        metrics.append(entry)
        
        if not metrics:
            return {"period_days": days, "sessions": 0}
        
        return {
            "period_days": days,
            "sessions": len(metrics),
            "avg_tcr": sum(m.get("tcr", 0) for m in metrics) / len(metrics),
            "avg_tpt": sum(m.get("tpt", 0) for m in metrics) / len(metrics),
            "avg_cpt": sum(m.get("cpt", 0) for m in metrics) / len(metrics),
            "avg_ttc": sum(m.get("ttc", 0) for m in metrics) / len(metrics),
        }
```

---

## Comparison: How Others Evaluate

| System | Primary Metric | Our Equivalent |
|--------|---------------|----------------|
| Claude Code | SWE-bench pass rate (72.7%) | TCR + DGR |
| Hermes | Skill document creation rate | Playbook Generation Rate (PGR) |
| Devin | Task completion + cost | TCR + CPT |
| AutoGPT | End-to-end task success | TCR + AAR |
| SWE-bench | Code patch correctness | N/A (we don't write code) |

**Key difference**: CrabRes is not a coding agent. Our "correctness" is measured by **whether the user's product actually grows** — which is harder to measure but more meaningful.

---

## Current Baseline (Honest Assessment)

Based on code review (not production data):

| Metric | Estimated Current | Target | Gap |
|--------|:---:|:---:|:---:|
| TCR | ~85% | 95% | Fallback paths exist but some edge cases miss |
| RDR | ~40% | 50% | Tavily results quality varies |
| EAR | ~70% | 80% | Timeout at 60s is generous but Moonshot can be slow |
| LCR | ~60% | 100% | **Critical gap** — experts have Chinese system prompts but no language enforcement |
| DGR | ~50% | 70% | Deliverable step exists but errors are silently swallowed |
| PGR | 0% | 50% | **Not connected** — pipeline never calls PlaybookStore.save_playbook() |
| TPT | ~12K | 15K | Within budget |
| CPT | ~$0.03 | $0.05 | Within budget (Moonshot is cheap) |
| MHR | ~10% | 50% | **Critical gap** — memory exists but is rarely injected into conversation |

---

## Implementation Status (Updated)

> **Status: IMPLEMENTED (2026-05-11)**
>
> The three-layer eval system has been built and is operational.

### Architecture

```
app/agent/eval/
├── __init__.py              # 统一导出（L1/L2/L3 全部公共 API）
├── collector.py             # L1/L2: MetricsCollector（JSONL 持久化）
├── scenarios.py             # L1: 28+ 评估场景定义（9 个分类）
├── assertions.py            # L1: 断言引擎（50+ 内置断言函数）
├── runner.py                # L1: Eval Runner（DRY/FULL 模式，CI 集成）
├── llm_judge.py             # L2: LLM-as-Judge + 一致性追踪
├── traces.py                # L2: Trace Logging（20 种事件类型）
└── ab_test.py               # L3: A/B Test 框架

tests/eval/
├── test_router.py           # Router 路由决策测试（8 条规则全覆盖）
├── test_nodes.py            # Node 节点规则测试
├── test_context_engine.py   # 专家调度逻辑测试
├── test_compaction.py       # Compaction 压缩逻辑测试
└── test_eval_integration.py # 端到端集成测试

app/api/v2/
├── eval.py                  # Eval Summary & Health API
└── eval_annotations.py      # L2/L3: 标注/Judge/A/B Test API

.github/workflows/
└── eval-ci.yml              # CI: L1 per-PR, L2 nightly, health gate
```

### Layer 1: Unit Tests (S1+S2+S3)

| Component | File | Scenarios | Status |
|-----------|------|-----------|--------|
| Scenario Definitions | `scenarios.py` | 28+ across 9 categories | Done |
| Assertion Engine | `assertions.py` | 50+ builtin checks | Done |
| Eval Runner (DRY) | `runner.py` | Zero-token, CI-friendly | Done |
| Router Tests | `test_router.py` | 8 rules, parametrized | Done |
| Node Tests | `test_nodes.py` | Understand rules, data model | Done |
| ContextEngine Tests | `test_context_engine.py` | Expert selection, knowledge injection | Done |
| Compaction Tests | `test_compaction.py` | Cache, fallback, prompt quality | Done |
| Integration Tests | `test_eval_integration.py` | Full DRY run, all subsystems | Done |

### Layer 2: Model & Human Evaluation

| Component | File | Capability | Status |
|-----------|------|------------|--------|
| LLM Judge | `llm_judge.py` | 5-dim scoring, structured output parsing | Done |
| Consistency Tracker | `llm_judge.py` | Human-LLM agreement tracking, correlation | Done |
| Trace Collector | `traces.py` | 20 event types, session replay, persistence | Done |
| Annotation API | `eval_annotations.py` | REST endpoints for human review | Done |
| Trace Viewer API | `eval_annotations.py` | List/load/search traces | Done |

### Layer 3: A/B Test

| Component | File | Capability | Status |
|-----------|------|------------|--------|
| ABTest Manager | `ab_test.py` | Create/run/analyze/auto-rollback | Done |
| Consistent Hashing | `ab_test.py` | Same user → same group always | Done |
| Welch's t-test | `ab_test.py` | Statistical significance testing | Done |
| AB API | `eval_annotations.py` | CRUD + assignment + results | Done |

### How to Run

```bash
# L1: Quick dry run (no LLM needed, <10s)
python -c "import asyncio; from app.agent.eval.runner import run_eval_dry; asyncio.run(print(asyncio.run(run_eval_dry())))"

# L1: Run specific category
python -c "import asyncio; from app.agent.eval.runner import EvalRunner, EvalMode; \
  r = EvalRunner(mode=EvalMode.DRY, category_filter='ROUTING'); \
  asyncio.run(r.run_all())"

# L1: Run with pytest
pytest tests/eval/ -v

# L2: Run with LLM Judge (needs OPENAI_API_KEY)
OPENAI_API_KEY=xxx python -c "
import asyncio
from app.agent.eval.runner import run_eval_full
from app.agent.engine.llm_adapter import AgentLLM
asyncio.run(run_eval_full(llm_service=AgentLLM()))
"
```

### Next Steps (Remaining)

1. **FULL mode integration** — Wire AgentLoop into runner.py for real LLM calls
2. **Trace hooks in production** — Add get_tracer() calls to loop.py key points
3. **Dashboard** — Frontend /eval page for trace visualization and annotation UI
4. **Expand scenario coverage** — Add more edge cases based on production failures
5. **Calibrate LLM Judge** — Collect initial human annotations to establish baseline correlation
