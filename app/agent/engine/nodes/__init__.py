"""
CrabRes Agent Engine — 共享节点包

每个节点函数对应一个处理阶段，被 Pipeline 和 ReAct 两种模式复用。
所有节点签名统一: (state, deps) -> AsyncIterator[Event]
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator

from app.agent.engine.state import AgentState, ExecutionMode, Phase
from app.agent.engine.errors import ToolError, ExpertError

logger = logging.getLogger(__name__)


# ===== 节点依赖注入容器 =====

@dataclass
class NodeDeps:
    """节点依赖 — 所有节点需要的共享服务。

    必须保留类型注解 — 没有注解的话 @dataclass 不会把它们当作字段，
    NodeDeps(llm=..., tools=...) 会抛 TypeError。
    """
    llm: object = None         # LLMService / AgentLLM
    tools: object = None       # ToolRegistry
    experts: object = None     # ExpertPool
    memory: object = None      # GrowthMemory / DBGrowthMemory
    trust: object = None       # TrustManager (optional)


# ===== Node 1: UNDERSTAND（意图理解 + 产品信息提取）=====

async def node_understand(state: AgentState, deps: NodeDeps, user_message: str) -> AgentState:
    """
    理解用户意图，提取产品信息。
    
    合并了 orchestrator._stage_understand 和 pipeline._step_understand 的逻辑：
    - 确定性规则优先（自我认知、打招呼、产品信号）
    - LLM 兜底做结构化信息提取
    - 输出: state.intent, state.product_info, state.has_product_info, state.direct_reply
    """
    msg = user_message.strip()
    msg_lower = msg.lower()
    if re.search(r"[\u4e00-\u9fff]", msg):
        state.language = "zh"
    lang = state.language
    
    # --- 规则 1: @expert 私聊 ---
    at_match = re.match(r'^@(\w+)\s+(.+)', msg, re.DOTALL)
    if at_match:
        expert_id = at_match.group(1).lower()
        expert_task = at_match.group(2).strip()
        expert = deps.experts.get(expert_id) if deps.experts else None
        if deps.experts is None or expert:
            state.intent = "expert_chat"
            state.direct_reply = f"__EXPERT_CHAT__:{expert_id}:{expert_task}"
            return state
    
    # --- 规则 2: 自我认知 ---
    self_triggers = [
        "what are you", "who are you", "你是什么", "你是谁",
        "what do you do", "你做什么", "介绍一下你", "introduce yourself",
    ]
    if any(t in msg_lower for t in self_triggers):
        state.is_self_awareness = True
        state.intent = "self_awareness"
        state.product_info = _CRABRES_PRODUCT_INFO.copy()
        state.product_info["raw_description"] = msg
        state.product_info["is_self"] = True
        state.has_product_info = True
        return state
    
    # --- 规则 3: 纯打招呼 ---
    greetings = ["hi", "hello", "hey", "你好", "嗨", "yo", "sup", "在吗"]
    if msg_lower.rstrip("!！.。，,") in greetings:
        state.intent = "greeting"
        return state
    
    # --- 规则 4: 产品信息检测 ---
    if _detect_product_info(msg):
        state.has_product_info = True
        state.intent = "growth_request"
        state.deliverable_intent = _detect_deliverable_intent(msg)
        state.deep_research_mode = _detect_deep_research(msg)
        
        # 自我引用检测
        is_self_ref = _is_self_referencing(msg)
        if is_self_ref:
            state.product_info = _CRABRES_PRODUCT_INFO.copy()
            state.product_info["raw_description"] = msg
            state.product_info["is_self"] = True
        else:
            state.product_info["raw_description"] = msg
            if not state.product_info.get("name"):
                inferred_name = _infer_product_name(msg)
                if inferred_name:
                    state.product_info["name"] = inferred_name
            
            # LLM 提取结构化信息（仅当消息足够长时）
            if len(msg) > 30:
                try:
                    from app.agent.engine.llm_adapter import TaskTier
                    response = await deps.llm.generate(
                        system_prompt="Extract product info. Return JSON: {name, description, type, audience, goal, budget, search_keywords}. Return ONLY JSON.",
                        messages=[{"role": "user", "content": msg}],
                        tier=TaskTier.PARSING,
                        max_tokens=300,
                    )
                    info = json.loads(response.content)
                    if isinstance(info, dict):
                        state.product_info.update(info)
                except Exception:
                    pass
        
        # 提取目标平台
        state.target_platforms = _detect_target_platforms(msg)
        return state
    
    # --- 规则 5: 工具请求 ---
    tool_triggers = [
        "browser", "浏览器", "browse", "搜索", "search",
        "发帖", "post", "发布", "publish", "分析", "analyze",
    ]
    url_in_msg = "http" in msg_lower or ".com" in msg_lower or ".io" in msg_lower
    if any(t in msg_lower for t in tool_triggers) or url_in_msg:
        state.intent = "tool_request"
        if state.product_info.get("name"):
            state.has_product_info = True
        return state
    
    # --- 规则 6: 有历史上下文 → followup ---
    has_existing = bool(state.product_info.get("name")) or any(
        _is_self_referencing(m.get("content", ""))
        for m in state.recent_messages(6) if m.get("role") == "user"
    )
    if has_existing or len(msg) > 20:
        state.has_product_info = True
        state.intent = "followup"
        state.deliverable_intent = _detect_deliverable_intent(msg)
        state.deep_research_mode = _detect_deep_research(msg)
        if not state.product_info:
            state.product_info["raw_description"] = msg
        return state
    
    # --- 兜底: 当作 chitchat ---
    state.intent = "chitchat"
    return state


# ===== Node 2: RESEARCH（市场研究）=====

async def node_research(state: AgentState, deps: NodeDeps) -> AsyncIterator[dict]:
    """
    搜索竞品/市场/用户讨论数据。
    
    合并 pipeline._step_research 和 orchestrator._stage_research 的逻辑：
    - 基于产品描述构建多角度搜索查询
    - 并行执行 web_search + social_search
    - 代码控制调用次数上限
    - yield status/browser_event 事件给前端
    """
    if not state.has_product_info and state.intent not in ("tool_request", "followup"):
        return
    
    yield {"type": "status", "content": "Researching your product market..."}
    
    t0 = time.time()
    product_desc = state.product_info.get("raw_description", "")
    product_name = state.product_info.get("name", "")
    audience = state.product_info.get("audience", "")
    ptype = state.product_info.get("type", "")
    keywords = state.product_info.get("search_keywords", [])
    
    # 构建搜索查询
    search_base = ""
    if keywords and isinstance(keywords, list) and len(keywords) >= 2:
        search_base = " ".join(keywords[:4])
    elif len(product_desc) > 10:
        search_base = product_desc[:100]
    else:
        search_base = product_desc[:150] or "software product"
    
    if audience and audience.lower() not in search_base.lower():
        search_base = f"{search_base} for {audience}"
    
    queries = [
        f"{search_base} competitors pricing comparison 2026",
        f"{search_base} user acquisition channels best practices",
    ]
    
    # 有竞品名 → 直接搜竞品对比
    competitors_list = state.product_info.get("competitors", [])
    if competitors_list and isinstance(competitors_list, list):
        comp_names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in competitors_list[:3]]
        comp_names = [n for n in comp_names if n]
        if comp_names:
            queries.append(f"{' vs '.join(comp_names)} comparison review pricing 2026")
    
    # 社媒搜索
    social_tool = deps.tools.get("social_search")
    if social_tool:
        queries.append(f"{audience or 'developers'} {product_desc[:50] or search_base[:50]} recommendation")
    else:
        queries.append(f"site:reddit.com {search_base[:60]} recommendation")
    
    # 去重
    queries = [q for q in queries if q not in state.searched_queries]
    for q in queries:
        state.searched_queries.add(q)
    
    # 并行执行（最多 3 个）
    search_tool = deps.tools.get("web_search")
    tasks = []
    for q in queries[:3]:
        if "reddit" in q and social_tool:
            tasks.append(_exec_tool(social_tool, query=q, platforms=["reddit", "hackernews"]))
        elif search_tool:
            tasks.append(_exec_tool(search_tool, query=q))
    
    import asyncio
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for i, r in enumerate(raw_results):
        query = queries[i] if i < len(queries) else ""
        if isinstance(r, Exception):
            logger.warning(f"Search failed for '{query}': {r}")
            continue
        elif isinstance(r, dict):
            content_len = len(json.dumps(r, default=str))
            result_entry = {"tool": "web_search", "query": query, "result": r, "useful": content_len > 200 and not r.get("error")}
            state.search_results.append(result_entry)
            state.tool_call_count += 1
    
    # 自动保存竞品
    try:
        tool_results_for_auto_save = [{"tool": sr["tool"], "result": sr["result"]} for sr in state.search_results if sr.get("useful")]
        await _auto_save_competitors(deps.memory, tool_results_for_auto_save)
    except Exception as e:
        logger.debug(f"Auto-save competitors failed: {e}")
    
    elapsed = int((time.time() - t0) * 1000)
    useful_count = sum(1 for sr in state.search_results if sr.get("useful"))
    logger.info(f"RESEARCH done (base): {state.tool_call_count} calls, {useful_count} useful results, {elapsed}ms")

    # === LLM 引导的扩展轮（P1.3 + P2.1）===
    # 触发条件：
    #   (A) 用户显式要求深度研究 — state.deep_research_mode
    #   (B) 基础查询召回率太低（useful_count < 2），扩展 1 轮抢救
    # 任一命中且 LLM 可用 → 让 LLM 看现有结果，提出 1-2 个新角度的查询
    should_expand = state.deep_research_mode or (useful_count < 2 and len(state.search_results) > 0)
    if should_expand and deps.llm is not None and search_tool:
        yield {"type": "status", "content": "Expanding research with follow-up queries..."}

        # 构造给 LLM 的现状摘要
        existing = "\n".join(
            f"- '{r.get('query','')}': useful={r.get('useful', False)}, "
            f"snippet={json.dumps(r.get('result',{}), default=str)[:250]}"
            for r in state.search_results[:5]
        )
        reason = "user requested deep research" if state.deep_research_mode else "initial results were thin"

        try:
            from app.agent.engine.llm_adapter import TaskTier
            resp = await deps.llm.generate(
                system_prompt=(
                    "You are a research analyst. Given a product and what was already searched, "
                    "propose 1-2 NEW search queries that explore angles the existing queries missed. "
                    "Good follow-ups: pricing/willingness-to-pay, user complaints/churn reasons, "
                    "channel-specific tactics, regulatory/legal considerations, niche communities.\n"
                    f"Reason for expansion: {reason}.\n\n"
                    "Return ONLY a JSON array of 1-2 strings. Example: "
                    '["RankFlow user complaints reddit", "indie SEO tool willingness to pay"]'
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Product: {json.dumps(state.product_info, ensure_ascii=False, default=str)[:400]}\n\n"
                        f"Already searched ({useful_count} useful / {len(state.search_results)} total):\n{existing}"
                    ),
                }],
                tier=TaskTier.PARSING,
                max_tokens=200,
            )
            raw = (getattr(resp, "content", "") or "").strip()
            if "```" in raw:
                if "```json" in raw:
                    raw = raw.split("```json", 1)[1]
                else:
                    raw = raw.split("```", 1)[1]
                raw = raw.split("```", 1)[0].strip()
            if "[" in raw and "]" in raw:
                raw = raw[raw.index("["): raw.rindex("]") + 1]
            new_queries = json.loads(raw)
            if isinstance(new_queries, list):
                # 去重 + 截到 2 个 + 过滤已搜过的
                new_queries = [
                    q.strip() for q in new_queries
                    if isinstance(q, str) and q.strip() and q.strip() not in state.searched_queries
                ][:2]
                if new_queries:
                    logger.info(f"RESEARCH expansion: {new_queries}")
                    expand_tasks = [_exec_tool(search_tool, query=q) for q in new_queries]
                    expand_results = await asyncio.gather(*expand_tasks, return_exceptions=True)
                    for i, r in enumerate(expand_results):
                        q = new_queries[i]
                        state.searched_queries.add(q)
                        if isinstance(r, Exception) or not isinstance(r, dict):
                            continue
                        content_len = len(json.dumps(r, default=str))
                        state.search_results.append({
                            "tool": "web_search", "query": q, "result": r,
                            "useful": content_len > 200 and not r.get("error"),
                            "source": "llm_expansion",
                        })
                        state.tool_call_count += 1
                    new_useful = sum(1 for sr in state.search_results if sr.get("source") == "llm_expansion" and sr.get("useful"))
                    logger.info(f"RESEARCH expansion done: +{new_useful} useful from {len(new_queries)} new queries")
        except Exception as e:
            logger.debug(f"RESEARCH expansion failed (non-fatal): {e}")


# ===== Node 3: EXPERT（专家圆桌）=====

async def node_expert(state: AgentState, deps: NodeDeps) -> AsyncIterator[dict]:
    """
    专家圆桌分析。
    
    合并 loop._run_roundtable / pipeline._step_analyze / orchestrator._stage_expert：
    - 根据产品类型选择专家（代码控制）
    - 分批并行执行（考虑专家间依赖）
    - CGO 综合输出
    """
    useful_results = [r for r in state.search_results if r.get("useful")]
    
    min_expert = 1
    if len(useful_results) < min_expert:
        logger.info(f"EXPERT skipped: only {len(useful_results)} useful results (need {min_expert})")
        return
    
    yield {"type": "status", "content": "Assembling expert roundtable..."}
    
    from app.agent.engine.context_engine import (
        select_experts_with_llm_refinement,
        get_expert_execution_order,
    )
    from app.agent.engine.llm_adapter import TaskTier

    product_type = state.product_info.get("type", "default")
    max_experts = 4
    # 轴外产品（type=default）会触发 LLM 兜底；其它走查表快路径
    expert_ids = await select_experts_with_llm_refinement(
        product_type=product_type,
        product_info=state.product_info,
        task=state.product_info.get("raw_description", ""),
        max_experts=max_experts,
        llm_service=deps.llm,
    )
    state.expert_ids_used = expert_ids
    
    # 构建研究摘要
    research_summary = "\n".join(
        f"- {r['query']}: {json.dumps(r['result'], ensure_ascii=False, default=str)[:500]}"
        for r in useful_results[:5]
    )
    
    lang = "Chinese" if state.language == "zh" else "English"
    task = (
        f"Analyze this product and create a growth strategy.\n\n"
        f"Product: {json.dumps(state.product_info, ensure_ascii=False, default=str)[:800]}\n\n"
        f"Research data:\n{research_summary}\n"
    )
    
    context = {
        "product": state.product_info,
        "tool_results": useful_results,
        "user_message": state.product_info.get("raw_description", ""),
        "expert_outputs": {},
        "language": state.language,
    }
    
    batches = get_expert_execution_order(expert_ids)
    expert_results = {}
    
    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0:
            yield {"type": "status", "content": f"Round {batch_idx + 1}: {len(batch)} experts analyzing with prior insights..."}
        
        async def _consult_one(eid: str) -> tuple[str, str]:
            expert = deps.experts.get(eid)
            if not expert:
                return eid, f"Expert {eid} not available"
            try:
                enriched_task = task
                if expert_results:
                    enriched_task += "\n\n## Other experts' views:\n"
                    for ok, ov in expert_results.items():
                        if ok != eid:
                            enriched_task += f"- {ok}: {ov[:300]}\n"
                
                result = await asyncio.wait_for(expert.analyze(context, enriched_task), timeout=90.0)
                return eid, result
            except asyncio.TimeoutError:
                return eid, f"[{eid}] Timed out"
            except Exception as e:
                return eid, f"[{eid}] Error: {str(e)[:100]}"
        
        batch_tasks = [_consult_one(eid) for eid in batch]
        for coro in asyncio.as_completed(batch_tasks):
            eid, result = await coro
            expert_results[eid] = result
            state.expert_outputs[eid] = result
            context["expert_outputs"][eid] = result
            
            expert = deps.experts.get(eid)
            expert_name = expert.name if expert else eid
            yield {"type": "expert_thinking", "expert_id": eid, "content": f"{expert_name} is analyzing..."}
            yield {"type": "expert_thinking", "expert_id": eid, "content": result}
    
    # CGO 综合
    yield {"type": "status", "content": "CGO synthesizing expert insights..."}
    
    def _expert_name(eid: str) -> str:
        e = deps.experts.get(eid)
        return getattr(e, "name", eid) if e else eid

    expert_summary = "\n".join(
        f"### {_expert_name(eid)} ({eid}):\n{output[:1500]}\n"
        for eid, output in expert_results.items()
    )
    
    synthesis_prompt = f"""You are CrabRes's Chief Growth Officer. You just held a roundtable with {len(expert_results)} experts.

## CRITICAL LANGUAGE RULE
**You MUST respond ONLY in {lang}.** No exceptions.

## ROUNDTABLE THREE-PHASE STRUCTURE

### Phase 1: Market Intelligence
Open with 2-3 SPECIFIC data points from the research.

### Phase 2: Expert Debate  
Highlight the KEY DISAGREEMENT between experts.

### Phase 3: Execution Playbooks
Present 2-3 Playbooks ranked by priority.

## MANDATORY ELEMENTS
1. **Hard Truth**: One uncomfortable truth.
2. **Quick Win**: One thing they can do TODAY.
3. **CGO Verdict**: Your #1 priority.

## Expert Outputs
{expert_summary}

## Original Question
{task}"""

    response = await deps.llm.generate(
        system_prompt=synthesis_prompt,
        messages=context.get("messages", [])[-5:] if context.get("messages") else [],
        tier=TaskTier.CRITICAL,
        max_tokens=4096,
    )
    
    state.synthesis = response.content
    yield {"type": "message", "content": state.synthesis}
    
    # 保存到记忆
    try:
        await deps.memory.save(f"growth_plan_{state.session_id}", {
            "content": state.synthesis,
            "turn": state.turn_count,
            "updated_at": time.time(),
        }, category="strategy")
    except Exception:
        pass


# ===== Node 4: DELIVER（生成交付物）=====

async def node_deliver(state: AgentState, deps: NodeDeps) -> AsyncIterator[dict]:
    """
    生成交付物：竞品报告、内容草稿、30天计划、Playbook。
    
    复用 loop._generate_deliverables / pipeline._step_deliver 的核心逻辑，
    但基于统一的 state 对象。
    """
    useful_results = [r for r in state.search_results if r.get("useful")]
    if len(useful_results) < 2 and not state.synthesis:
        return
    
    product_info = state.product_info
    product_name = product_info.get("name", "product")
    
    # 质量门控
    has_real_name = product_name not in ("product", "unknown", "")
    has_real_desc = bool(product_info.get("description") and len(product_info.get("description", "")) > 20)
    if not has_real_name and not has_real_desc and len(product_info.get("raw_description", "")) < 30:
        logger.info("DELIVER skipped: product info too vague")
        return
    
    yield {"type": "status", "content": "Preparing deliverables..."}
    
    from pathlib import Path
    import os
    from app.agent.engine.llm_adapter import TaskTier
    
    render_disk = os.environ.get("RENDER_DISK_PATH", "")
    workspace = Path(render_disk) / "workspace" if render_disk else Path(str(deps.memory.base_dir)).parent / "workspace"
    for sub in ["drafts", "reports", "plans"]:
        (workspace / sub).mkdir(parents=True, exist_ok=True)
    
    lang = "Chinese" if state.language == "zh" else "English"
    product_desc = json.dumps(product_info, ensure_ascii=False, default=str)[:500]
    deliverables = []
    
    research_text = "\n".join(
        f"- {r.get('tool','')}: {json.dumps(r.get('result',{}), ensure_ascii=False, default=str)[:600]}"
        for r in state.search_results[:5] if isinstance(r.get("result"), dict) and not r["result"].get("error")
    )

    # 按 deliverable_intent 决定生成哪些产物（避免无脑跑全套）
    intent = state.deliverable_intent or "full"
    want_report = intent in ("full", "competitor_only")
    want_drafts = intent in ("full", "content_only")
    want_plan = intent in ("full", "plan_only")
    want_playbook = intent == "full"  # Playbook 仅在完整方案时生成
    logger.info(f"DELIVER intent={intent} report={want_report} drafts={want_drafts} plan={want_plan} playbook={want_playbook}")

    def _wrap_deliverable(name: str, desc: str, content: str) -> dict:
        """统一封装：附带 safety warnings 给前端展示"""
        warnings = _check_output_safety(content)
        if warnings:
            logger.warning(f"Deliverable '{name}' safety hits: {warnings}")
        return {"name": name, "desc": desc, "warnings": warnings}

    # 并行生成 3 个交付物
    async def _gen_report():
        if not research_text:
            return None
        r = await deps.llm.generate(
            system_prompt=f"Generate competitor analysis report in {lang}. Be specific. 500-800 words.",
            messages=[{"role": "user", "content": f"Product: {product_desc}\n\nResearch:\n{research_text}"}],
            tier=TaskTier.THINKING, max_tokens=1500,
        )
        path = workspace / "reports" / f"competitor_analysis_{product_name.lower().replace(' ','_')}.md"
        path.write_text(f"# Competitor Analysis: {product_name}\n\n{r.content}", encoding="utf-8")
        return _wrap_deliverable("Competitor Analysis", f"reports/{path.name}", r.content)

    async def _gen_drafts():
        d = await deps.llm.generate(
            system_prompt=f"Write ready-to-post drafts in {lang}. Reddit post + Twitter thread.",
            messages=[{"role": "user", "content": f"Product: {product_desc}\nStrategy: {(state.synthesis or '')[:800]}"}],
            tier=TaskTier.WRITING, max_tokens=1200,
        )
        path = workspace / "drafts" / f"first_posts_{product_name.lower().replace(' ','_')}.md"
        path.write_text(f"# Content Drafts: {product_name}\n\n{d.content}", encoding="utf-8")
        return _wrap_deliverable("Content Drafts (Reddit + X)", f"drafts/{path.name}", d.content)

    async def _gen_plan():
        p = await deps.llm.generate(
            system_prompt=f"Create 30-day growth plan in {lang}. Week 1/2/3/4 format.",
            messages=[{"role": "user", "content": f"Product: {product_desc}\nStrategy: {(state.synthesis or '')[:800]}"}],
            tier=TaskTier.THINKING, max_tokens=1500,
        )
        path = workspace / "plans" / f"30day_growth_{product_name.lower().replace(' ','_')}.md"
        path.write_text(f"# 30-Day Growth Plan: {product_name}\n\n{p.content}", encoding="utf-8")
        return _wrap_deliverable("30-Day Growth Plan", f"plans/{path.name}", p.content)
    
    parallel_tasks = []
    if want_report:
        parallel_tasks.append(_gen_report())
    if want_drafts:
        parallel_tasks.append(_gen_drafts())
    if want_plan:
        parallel_tasks.append(_gen_plan())

    if parallel_tasks:
        results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, dict):
                deliverables.append(result)

    # Playbook (仅完整方案场景)
    if want_playbook:
        try:
            from app.agent.memory.playbooks import PlaybookStore, parse_playbook_from_llm
            from app.agent.knowledge.channel_playbooks import get_channels_for_product, get_channel_sop

            channels = get_channels_for_product(product_info.get("type", "saas"))
            channel_sops = ""
            for ch_key in channels[:3]:
                sop = get_channel_sop(ch_key)
                if sop:
                    channel_sops += f"\n### {sop.get('name', ch_key)}\nQuick start: {', '.join(sop.get('quick_start', [])[:3])}\n"

            pb = await deps.llm.generate(
                system_prompt=f"""Generate structured growth playbook JSON. Language: {lang}.
Budget $0 per step, duration under 4 hours, specific platforms.
Return ONLY valid JSON with: name, description, phases[].""",
                messages=[{"role": "user", "content": f"Product: {product_desc}\nStrategy: {(state.synthesis or '')[:1000]}"}],
                tier=TaskTier.CRITICAL, max_tokens=4000,
            )
            raw = pb.content
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            playbook = parse_playbook_from_llm(raw.strip())
            if playbook:
                store = PlaybookStore(base_dir=str(deps.memory.base_dir))
                await store.save_playbook(playbook)
                deliverables.append({"name": f"Growth Playbook: {playbook.name}", "desc": "playbook"})
        except Exception as e:
            logger.warning(f"Playbook generation failed: {e}")
    
    state.deliverables = deliverables
    if deliverables:
        files_msg = "\n".join(f"- {d['name']}: {d['desc']}" for d in deliverables)
        # 收集所有交付物的 safety warnings
        all_warnings = []
        for d in deliverables:
            for w in d.get("warnings", []) or []:
                all_warnings.append(f"  - [{d['name']}] {w}")
        warning_block = ""
        if all_warnings:
            warning_block = (
                "\n\n⚠️ Pre-publish safety check flagged the following — review before sharing:\n"
                + "\n".join(all_warnings)
            )
        yield {
            "type": "message",
            "content": f"I've prepared these for you:\n\n{files_msg}\n\nYou can find them in your workspace.{warning_block}",
        }


# ===== 辅助函数 =====

# CrabRes 自身产品信息（硬编码，用于自我认知场景）
_CRABRES_PRODUCT_INFO: dict = {
    "name": "CrabRes",
    "description": "AI growth strategy agent that helps indie developers and small teams research markets, analyze competitors, and execute actionable growth plans",
    "type": "saas",
    "audience": "indie developers, solo founders, small SaaS teams (1-5 people)",
    "goal": "acquire first 1000 users through organic channels",
    "budget": "$0",
    "url": "https://crab-researcher.vercel.app",
    "features": [
        "13 AI expert advisors (market researcher, content strategist, social media, etc.)",
        "Real-time web research and competitor analysis",
        "Automated content drafting (Reddit, Twitter/X, email)",
        "Structured Growth Playbooks with step-by-step execution",
        "Browser automation for deep scraping",
        "Execution engine that actually posts/sends (not just suggests)",
    ],
    "competitors": [
        {"name": "GrowthBook", "focus": "A/B testing and feature flags"},
        {"name": "Jasper", "focus": "AI copywriting"},
        {"name": "Copy.ai", "focus": "AI marketing copy"},
        {"name": "Writesonic", "focus": "AI content generation"},
    ],
    "differentiator": "Not just AI copywriting — full research + strategy + execution pipeline.",
}


def _detect_product_info(message: str) -> bool:
    """检测消息是否包含足够的产品信息（纯代码，0 token）"""
    msg = message.lower()
    
    greetings = ['hi', 'hello', 'hey', '你好', '嗨', 'yo', 'sup']
    if msg.strip() in greetings:
        return False
    
    # 竞品信号
    competitor_signals = [
        '竞品', '竞争对手', '对手', '竞争者', '类似的产品',
        'competitor', 'competing', 'rival', 'alternative', 'vs ', ' vs',
        '比较', '对比',
    ]
    if any(kw in msg for kw in competitor_signals):
        return True
    
    # 产品描述信号
    product_signals = [
        'my product', 'i built', 'i made', "i'm building", 'i have a',
        "it's a", 'it is a', 'we built', 'our product', 'we made',
        '我的产品', '我做了', '我们做了', '我在做', '我开发了', '帮助用户',
    ]
    if any(kw in msg for kw in product_signals):
        return True
    
    # 类型信号（需要 >10 chars）
    if len(msg) > 10:
        type_signals = [
            'saas', 'app', 'tool', 'platform', 'service', 'marketplace',
            'plugin', 'extension', 'bot', 'agent', 'api',
            'helps', 'for users', 'for developers', 'for teams',
            '$', '/mo', '/month', 'pricing', 'free', 'freemium',
            'users', 'customers', 'target', 'audience',
            'growth', 'marketing', 'launch', 'mvp',
            '帮助', '用户', '增长', '营销', '独立开发', '产品',
            'vibecoder', 'indie', 'hacker', 'startup', 'founder',
        ]
        if any(kw in msg for kw in type_signals):
            return True
    
    # URL 检测
    if 'http' in msg or '.com' in msg or '.io' in msg or '.app' in msg or '.ai' in msg:
        return True
    
    # 长消息且非问句
    if len(msg) > 20 and not msg.endswith('?') and not msg.endswith('？'):
        return True
    
    return False


def _infer_product_name(message: str) -> str:
    """Best-effort, zero-token extraction for common product introductions."""
    patterns = [
        r"(?:we built|we made|i built|i made)\s+([A-Z][A-Za-z0-9_-]{1,40})(?=[,.:]|\s+(?:an?|the)\s)",
        r"(?:i'm building|i am building|my product is|called)\s+(?:an?\s+)?(.+?)(?=\s+(?:at|for|that|which|with)\b|[,.:]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1).strip(" -–—\"'")
            if 1 < len(name) <= 60:
                return name
    return ""


def _detect_deep_research(message: str) -> str:
    """
    检测用户是否显式要求深度研究（纯代码，0 token）。

    命中时 node_research 会在基础模板查询之后追加 1 轮 LLM 引导的扩展查询，
    扩展 1-2 个新角度。其它情况走基础流程，避免不必要的成本。
    """
    msg = message.lower()
    triggers = [
        # CN
        "深入", "深度研究", "详细研究", "彻底调研", "深挖", "深度调研",
        "全面分析", "深入分析",
        # EN
        "deep research", "deep dive", "investigate", "thorough research",
        "in-depth", "in depth", "deeply analyze", "comprehensive analysis",
        "explore in detail",
    ]
    return any(t in msg for t in triggers)


def _detect_deliverable_intent(message: str) -> str:
    """
    检测用户想要哪类交付物（纯代码，0 token）。

    返回 "competitor_only" | "content_only" | "plan_only" | "full"
    用于 node_deliver 阶段裁剪生成内容，避免无脑全跑三件套。
    """
    msg = message.lower()

    competitor_kw = [
        "竞品", "竞争对手", "对手", "竞争者", "对比",
        "competitor", "competes", "competing", "rival", "alternative", " vs ", "vs.",
        "competitive analysis", "市场分析",
    ]
    content_kw = [
        "写一篇", "帮我写", "写个", "写帖子", "写推文", "文案", "草稿",
        "draft", "write a post", "write me a", "write me", "tweet", "copy ",
        "landing page", "落地页", "标题",
    ]
    plan_kw = [
        "30天", "30 day", "30-day", "计划", "路线图", "roadmap",
        "plan", "schedule", "timeline", "周计划", "月计划", "阶段",
    ]
    full_kw = [
        "全套", "完整", "增长方案", "整体策略", "综合",
        "full plan", "full strategy", "growth strategy", "complete plan", "complete growth plan",
    ]

    has_competitor = any(kw in msg for kw in competitor_kw)
    has_content = any(kw in msg for kw in content_kw)
    has_plan = any(kw in msg for kw in plan_kw)
    has_full = any(kw in msg for kw in full_kw)

    # 显式要全套 → full
    if has_full:
        return "full"

    # 单一意图（且其他类型未出现）→ 单一交付
    if has_competitor and not has_content and not has_plan:
        return "competitor_only"
    if has_content and not has_competitor and not has_plan:
        return "content_only"
    if has_plan and not has_competitor and not has_content:
        return "plan_only"

    # 多意图叠加 / 模糊请求 → full（默认）
    return "full"


# ===== 输出安全检查 =====

# 显式 PII / 高风险声明的正则与关键词
# 不追求完美召回（间接 PII 需要 classifier），只抓"会让用户当场出事"的显式情况
_PII_PATTERNS = [
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "phone-like number"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "email address"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "card-number-like sequence"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN-like number"),
]

# 高风险声明（合规/广告法相关）
_RISKY_CLAIMS = [
    "fda approved", "fda-approved", "clinically proven", "doctor recommended",
    "guaranteed results", "100% effective", "no side effects", "risk-free",
    "guaranteed roi", "make $", "earn $", "passive income guaranteed",
    "fda 批准", "临床证实", "百分百有效", "无副作用", "保证收益",
]


def _check_output_safety(content: str) -> list[str]:
    """
    扫描交付物文本里的合规/隐私风险。

    Returns: 命中条目列表（人类可读字符串）。空列表表示通过。
    设计为软警告而非硬阻断：
    - 用户可能就是要写"价格 $99"这种内容，硬过滤会误伤
    - 命中项写进 deliverable.warnings 让前端展示给用户决定怎么处理
    """
    if not content:
        return []
    hits = []
    for pattern, label in _PII_PATTERNS:
        if pattern.search(content):
            hits.append(f"PII risk: {label}")
    text_lower = content.lower()
    for kw in _RISKY_CLAIMS:
        if kw in text_lower:
            hits.append(f"risky claim: {kw!r}")
    # 去重保序
    return list(dict.fromkeys(hits))


def _is_self_referencing(msg: str) -> bool:
    """检测用户是否在说 CrabRes 自身"""
    msg_lower = msg.lower()
    triggers = [
        "crabres", "crab-res", "crab res", "你自己", "你本身",
        "你是一个产品", "你是产品", "给你自己", "为你自己",
        "for yourself", "about yourself", "your own", "you are a product",
        "my project is you", "the product is you",
    ]
    return any(t in msg_lower for t in triggers)


def _detect_target_platforms(message: str) -> list[str]:
    """从用户消息中提取目标平台"""
    msg_lower = message.lower()
    platforms = []
    
    platform_map = {
        "twitter": "X/Twitter", "x平台": "X/Twitter", "推特": "X/Twitter",
        "reddit": "Reddit",
        "小红书": "小红书", "xiaohongshu": "小红书", "xhs": "小红书",
        "product hunt": "Product Hunt", "producthunt": "Product Hunt", "ph": "Product Hunt",
        "hacker news": "Hacker News", "hackernews": "Hacker News", "hn": "Hacker News",
        "linkedin": "LinkedIn", "领英": "LinkedIn",
        "微博": "微博", "weibo": "微博",
        "知乎": "知乎", "zhihu": "知乎",
        "youtube": "YouTube", "油管": "YouTube",
        "抖音": "抖音/TikTok", "tiktok": "抖音/TikTok", "douyin": "抖音/TikTok",
    }
    
    for keyword, platform in platform_map.items():
        if keyword in msg_lower and platform not in platforms:
            platforms.append(platform)
    
    return platforms


async def _exec_tool(tool, **kwargs):
    """执行工具调用，带超时和错误处理"""
    import asyncio
    try:
        return await asyncio.wait_for(tool.execute(**kwargs), timeout=30.0)
    except asyncio.TimeoutError:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)[:200]}


async def _auto_save_competitors(memory, tool_results: list[dict]):
    """从搜索结果中自动提取竞品并保存到记忆"""
    from urllib.parse import urlparse
    
    competitors = []
    seen_domains = set()
    
    for tr in tool_results:
        result = tr.get("result", {})
        if not isinstance(result, dict):
            continue
        
        for r in result.get("results", []):
            url = r.get("url", "")
            title = r.get("title", "")
            content = r.get("content", "")
            if not url:
                continue
            
            try:
                domain = urlparse(url).netloc.replace("www.", "")
            except Exception:
                continue
            
            skip_domains = {
                "google.com", "bing.com", "reddit.com", "twitter.com", "x.com",
                "youtube.com", "linkedin.com", "facebook.com", "instagram.com",
                "github.com", "medium.com", "quora.com", "wikipedia.org",
                "news.ycombinator.com", "producthunt.com", "crunchbase.com",
                "techcrunch.com", "forbes.com", "bloomberg.com",
                "futurepedia.io", "alternativeto.net", "g2.com", "capterra.com",
            }
            if any(skip in domain for skip in skip_domains):
                continue
            
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            
            name = title.split(" - ")[0].split(" | ")[0].split(" — ")[0].strip()
            if len(name) > 50:
                name = name[:50]
            
            competitors.append({
                "name": name,
                "url": f"https://{domain}",
                "description": content[:200] if content else title,
            })
    
    if competitors:
        existing = await memory.load("competitors", category="research")
        if not isinstance(existing, list):
            existing = []
        
        existing_urls = {c.get("url", "").lower() for c in existing}
        new_comps = []
        for c in competitors[:5]:
            if c["url"].lower() not in existing_urls:
                c["discovered_at"] = time.time()
                c["status"] = "active"
                c["source"] = "auto_discovery"
                new_comps.append(c)
        
        if new_comps:
            existing.extend(new_comps)
            await memory.save("competitors", existing, category="research")
