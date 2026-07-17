"""
CrabRes Context Engine — 上下文工程核心

三大职责：
1. 知识选择性注入：根据任务/渠道只注入相关知识，不全量 580 行
2. Sub-agent 上下文隔离：每个专家只看到自己需要的上下文
3. Harness 专家权重矩阵：不同产品类型有不同的专家调度优先级和发言顺序
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ===== 知识选择性注入 =====

# 渠道关键词检测 → 只注入对应渠道的知识
CHANNEL_KEYWORDS = {
    "x_twitter": [
        "twitter", "x.com", "tweet", "thread", "x 平台", "推特",
        "build in public", "reply guy",
    ],
    "xiaohongshu": [
        "小红书", "xiaohongshu", "red note", "rednote", "xhs",
        "种草", "笔记", "封面", "流量池",
    ],
    "reddit": [
        "reddit", "subreddit", "r/", "karma", "upvote",
        "hacker news", "hackernews",
    ],
    "linkedin": ["linkedin", "领英"],
    "youtube": ["youtube", "视频", "shorts", "yt"],
    "tiktok": ["tiktok", "抖音", "短视频"],
    "instagram": ["instagram", "ig", "reels"],
    "email": ["email", "邮件", "newsletter", "outreach", "cold email"],
    "seo": ["seo", "搜索引擎", "关键词", "aeo", "geo", "programmatic"],
    "paid_ads": ["广告", "ads", "paid", "投放", "cpc", "cpm", "roas"],
    "product_hunt": ["product hunt", "ph launch", "producthunt"],
}


def detect_relevant_channels(text: str) -> list[str]:
    """从文本中检测涉及的渠道（含扩展渠道）"""
    text_lower = text.lower()
    channels = []

    # 原有渠道检测
    for channel, keywords in CHANNEL_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            channels.append(channel)

    # 扩展渠道检测（7 个新增知识模块对应的渠道）
    try:
        from app.agent.knowledge.knowledge_expansion import EXPANDED_CHANNEL_KEYWORDS
        for channel, keywords in EXPANDED_CHANNEL_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                if channel not in channels:
                    channels.append(channel)
    except ImportError:
        pass

    return channels


def select_knowledge_for_task(expert_id: str, task: str, user_message: str = "") -> list[str]:
    """
    根据任务内容选择要注入的知识模块名
    
    代替全量注入，只返回需要的知识模块 name 列表。
    例如用户问 Reddit 策略 → social_media 专家只注入 reddit_deep_knowledge，
    不注入 x_twitter_deep_knowledge 和 xiaohongshu_deep_knowledge。
    
    Returns:
        需要注入的知识模块 name 列表（对应 skills_registry 中的 name 字段）
    """
    combined_text = f"{task} {user_message}".lower()
    channels = detect_relevant_channels(combined_text)
    
    # 特殊映射：expert_id + 检测到的渠道 → 知识模块
    if expert_id == "social_media":
        modules = []
        if "x_twitter" in channels or not channels:
            modules.append("x_twitter_deep_knowledge")
        if "xiaohongshu" in channels or not channels:
            modules.append("xiaohongshu_deep_knowledge")
        if "reddit" in channels or not channels:
            modules.append("reddit_deep_knowledge")
        # 如果没检测到任何渠道，全部注入（fallback）
        return modules if modules else ["x_twitter_deep_knowledge", "xiaohongshu_deep_knowledge", "reddit_deep_knowledge"]
    
    # 其他专家：检查扩展知识是否有匹配
    try:
        from app.agent.knowledge.knowledge_expansion import EXPANDED_KNOWLEDGE, EXPANDED_CHANNEL_KEYWORDS
        # 检查是否有扩展知识需要注入
        expanded_items = EXPANDED_KNOWLEDGE.get(expert_id, [])
        if expanded_items:
            # 如果检测到相关渠道，返回对应的扩展知识模块名
            for channel in channels:
                if channel in EXPANDED_CHANNEL_KEYWORDS:
                    for item in expanded_items:
                        if channel in item["name"].lower() or any(kw in item["description"].lower() for kw in EXPANDED_CHANNEL_KEYWORDS[channel]):
                            modules.append(item["name"]) if "modules" in dir() else None
    except (ImportError, Exception):
        pass

    # 返回空列表表示注入该专家的所有知识（保持现有行为）
    return []


def get_selective_knowledge(expert_id: str, task: str, user_message: str = "") -> str:
    """
    获取选择性注入的知识文本
    
    替代原来的 get_expert_knowledge(expert_id) 全量注入
    """
    from app.agent.knowledge.skills_registry import EXPERT_KNOWLEDGE, ADVANCED_TACTICS_2026
    
    knowledge_items = EXPERT_KNOWLEDGE.get(expert_id, [])
    selected_names = select_knowledge_for_task(expert_id, task, user_message)
    
    parts = []
    
    if knowledge_items:
        if selected_names:
            # 选择性注入
            filtered = [item for item in knowledge_items if item["name"] in selected_names]
            if filtered:
                parts.append("\n## Your Professional Frameworks (task-relevant selection)\n")
                for item in filtered:
                    parts.append(f"### {item['name']} ({item['source']})")
                    parts.append(item["framework"])
                    parts.append("")
                
                # 记录被跳过的模块
                skipped = [item["name"] for item in knowledge_items if item["name"] not in selected_names]
                if skipped:
                    parts.append(f"\n[Also available but not loaded for this task: {', '.join(skipped)}]\n")
                    logger.info(f"Knowledge selection for {expert_id}: loaded {len(filtered)}, skipped {len(skipped)}")
            else:
                # 没匹配到 → 全量 fallback
                parts.append("\n## Your Professional Frameworks\n")
                for item in knowledge_items:
                    parts.append(f"### {item['name']} ({item['source']})")
                    parts.append(item["framework"])
                    parts.append("")
        else:
            # 非 social_media 专家 → 全量注入（保持现有行为）
            parts.append("\n## Your Professional Frameworks\n")
            for item in knowledge_items:
                parts.append(f"### {item['name']} ({item['source']})")
                parts.append(item["framework"])
                parts.append("")
    
    # 所有专家都获取 2026 高级战术
    parts.append(ADVANCED_TACTICS_2026)
    
    return "\n".join(parts)


# ===== Sub-agent 上下文隔离 =====

def build_expert_context(expert_id: str, full_context: dict, task: str) -> dict:
    """
    为特定专家构建隔离的上下文
    
    不是把整个 context 扔给专家，而是只给它需要的部分：
    - 产品信息（所有专家都需要）
    - 与任务相关的工具结果（不是全部）
    - 其他专家的摘要（不是完整输出）
    - 排除无关的消息历史
    """
    # 产品信息：所有专家都需要
    product = full_context.get("product", {})
    
    # 工具结果：只选择与当前专家相关的
    all_tool_results = full_context.get("tool_results", [])
    relevant_results = _filter_relevant_results(expert_id, all_tool_results)
    
    # 其他专家输出：只给摘要，不给全文
    expert_outputs = full_context.get("expert_outputs", {})
    summarized_outputs = {}
    for eid, output in expert_outputs.items():
        if eid != expert_id:
            # 截断到 300 字符作为摘要
            summarized_outputs[eid] = output[:300] if isinstance(output, str) else str(output)[:300]
    
    return {
        "product": product,
        "tool_results": relevant_results,
        "expert_outputs": summarized_outputs,
        "user_message": full_context.get("user_message", ""),
        # 不传递 messages（专家不需要完整对话历史）
        # 不传递 trust（专家不需要权限信息）
        # 不传递 mood_injection（只有 Coordinator 需要）
    }


def _filter_relevant_results(expert_id: str, tool_results: list) -> list:
    """根据专家类型过滤相关的工具结果"""
    # 专家 → 感兴趣的工具类型
    EXPERT_TOOL_AFFINITY = {
        "market_researcher": ["web_search", "competitor_analyze", "scrape_website"],
        "economist": ["web_search"],
        "social_media": ["social_search", "web_search"],
        "content_strategist": ["web_search", "scrape_website"],
        "psychologist": ["web_search", "scrape_website"],
        "paid_ads": ["web_search"],
        "copywriter": ["web_search", "social_search"],
        "data_analyst": ["web_search"],
        "product_growth": ["web_search", "scrape_website"],
        "partnerships": ["social_search", "web_search"],
        "ai_distribution": ["web_search"],
        "critic": [],  # Critic 看所有结果
        "designer": ["scrape_website", "browse_website"],
    }
    
    interested_tools = EXPERT_TOOL_AFFINITY.get(expert_id)
    if interested_tools is None or not interested_tools:
        return tool_results  # Critic 等看全部
    
    return [
        r for r in tool_results
        if r.get("tool") in interested_tools
    ]


# ===== Harness：专家权重矩阵 =====

# 产品类型 → 专家优先级排序
# 数字越小越优先，不在列表中的专家默认优先级 99
PRODUCT_EXPERT_PRIORITY: dict[str, dict[str, int]] = {
    # ── ToB / 工具类 ──
    "saas": {
        "market_researcher": 1, "economist": 2, "product_growth": 3,
        "social_media": 4, "content_strategist": 5, "psychologist": 6,
        "data_analyst": 7, "copywriter": 8,
    },
    "tool": {
        "product_growth": 1, "market_researcher": 2, "ai_distribution": 3,
        "social_media": 4, "content_strategist": 5, "economist": 6,
    },
    # ── ToC / 消费者产品 ──
    "consumer_app": {
        # 消费级 App: 心理学驱动获客 + 病毒传播 + 留存
        "psychologist": 1, "product_growth": 2, "social_media": 3,
        "designer": 4, "data_analyst": 5, "copywriter": 6,
        "paid_ads": 7, "market_researcher": 8,
    },
    "game": {
        # 游戏: 留存 > 获客, 社区 > 广告
        "psychologist": 1, "product_growth": 2, "social_media": 3,
        "data_analyst": 4, "designer": 5, "copywriter": 6,
        "paid_ads": 7, "partnerships": 8,
    },
    "lifestyle": {
        # 生活方式/消费品牌: 视觉 + 种草 + KOL
        "social_media": 1, "designer": 2, "psychologist": 3,
        "partnerships": 4, "copywriter": 5, "market_researcher": 6,
        "paid_ads": 7, "economist": 8,
    },
    "education": {
        # 教育产品: 信任 > 流量, 内容 > 广告
        "content_strategist": 1, "psychologist": 2, "product_growth": 3,
        "social_media": 4, "copywriter": 5, "market_researcher": 6,
        "partnerships": 7, "data_analyst": 8,
    },
    "subscription": {
        # 订阅服务(非SaaS): 留存 = 一切
        "product_growth": 1, "psychologist": 2, "economist": 3,
        "content_strategist": 4, "social_media": 5, "copywriter": 6,
        "data_analyst": 7, "market_researcher": 8,
    },
    # ── 通用 ──
    "ecommerce": {
        "market_researcher": 1, "psychologist": 2, "social_media": 3,
        "paid_ads": 4, "designer": 5, "economist": 6,
        "copywriter": 7, "partnerships": 8,
    },
    "community": {
        "social_media": 1, "content_strategist": 2, "psychologist": 3,
        "product_growth": 4, "market_researcher": 5, "copywriter": 6,
        "partnerships": 7,
    },
    "content": {
        "content_strategist": 1, "social_media": 2, "copywriter": 3,
        "psychologist": 4, "market_researcher": 5, "ai_distribution": 6,
    },
    "default": {
        "market_researcher": 1, "economist": 2, "social_media": 3,
        "psychologist": 4, "product_growth": 5, "content_strategist": 6,
    },
}

# Public compatibility name used by the evaluation and inspection APIs.
HARNESS_WEIGHTS = PRODUCT_EXPERT_PRIORITY

# 专家发言依赖图：某些专家应该在其他专家之后发言
# key 专家在 value 列表中的专家完成后才开始
EXPERT_DEPENDENCIES: dict[str, list[str]] = {
    "economist": ["market_researcher"],        # 经济学家需要市研的数据
    "copywriter": ["social_media", "psychologist"],  # 文案需要知道渠道和心理学
    "critic": ["market_researcher", "economist"],      # Critic 需要看到核心分析
    "designer": ["copywriter", "social_media"],        # 设计需要知道文案和渠道
}


def get_expert_priority(product_type: str, expert_id: str) -> int:
    """获取专家在某产品类型下的优先级（数字越小越优先）"""
    priorities = PRODUCT_EXPERT_PRIORITY.get(product_type, PRODUCT_EXPERT_PRIORITY["default"])
    return priorities.get(expert_id, 99)


def select_roundtable_experts(product_type: str, task: str, max_experts: int = 4) -> list[str]:
    """
    根据产品类型和任务智能选择圆桌专家
    
    这是 harness engineering 的核心：
    不是随机选 4 个，而是基于产品类型选最相关的，并考虑发言依赖
    """
    priorities = PRODUCT_EXPERT_PRIORITY.get(product_type, PRODUCT_EXPERT_PRIORITY["default"])
    
    # 按优先级排序
    sorted_experts = sorted(priorities.items(), key=lambda x: x[1])
    
    # 检测任务是否涉及特定渠道
    channels = detect_relevant_channels(task)
    
    # 基础选择：取前 max_experts 个
    selected = [eid for eid, _ in sorted_experts[:max_experts]]
    
    # 渠道特化调整：如果任务明确涉及社媒/广告/内容，确保相关专家在列
    channel_expert_boost = {
        "x_twitter": "social_media",
        "xiaohongshu": "social_media",
        "reddit": "social_media",
        "seo": "content_strategist",
        "paid_ads": "paid_ads",
        "email": "copywriter",
        "product_hunt": "partnerships",
    }
    
    for channel in channels:
        boosted = channel_expert_boost.get(channel)
        if boosted and boosted not in selected:
            # 替换优先级最低的
            selected[-1] = boosted
    
    # 确保没有重复
    selected = list(dict.fromkeys(selected))[:max_experts]
    
    logger.info(f"Harness: selected {selected} for product_type={product_type}, channels={channels}")
    return selected


def get_experts_for_product(product_type: str, product_info: dict | None = None) -> list[str]:
    """Stable public wrapper for deterministic product-to-expert selection."""
    info = product_info or {}
    task = " ".join(str(info.get(key, "")) for key in ("description", "audience", "goal"))
    return select_roundtable_experts(product_type or "default", task, max_experts=4)


def get_knowledge_modules_for_query(query: str) -> list[dict]:
    """Return channel-specific knowledge module metadata for a query."""
    channels = detect_relevant_channels(query)
    if not channels:
        return []
    from app.agent.knowledge.skills_registry import EXPERT_KNOWLEDGE

    modules = []
    for items in EXPERT_KNOWLEDGE.values():
        for item in items:
            name = str(item.get("name", "")).lower()
            if any(channel.replace("x_twitter", "twitter") in name for channel in channels):
                modules.append(item)
    return modules


async def select_experts_with_llm_refinement(
    product_type: str,
    product_info: dict,
    task: str,
    max_experts: int,
    llm_service,
) -> list[str]:
    """
    专家选择的混合策略：代码查表为快路径，LLM 在轴外场景兜底。

    触发 LLM 介入的条件：
    - product_type 落到 "default"（查表矩阵未明确分类）
    - 产品描述足够长（>= 30 字符），LLM 有判断依据
    - llm_service 可用

    其它情况直接走 select_roundtable_experts() 查表，零 token。
    """
    base = select_roundtable_experts(product_type, task, max_experts)

    # 非轴外产品 → 直接用查表结果
    if product_type and product_type != "default":
        return base
    if llm_service is None or not hasattr(llm_service, "generate"):
        return base

    desc = (
        product_info.get("raw_description")
        or product_info.get("description")
        or ""
    )[:500]
    if len(desc) < 30:
        return base  # 信息太少，LLM 也判断不出来

    available = [
        "market_researcher", "economist", "social_media", "psychologist",
        "content_strategist", "copywriter", "paid_ads", "partnerships",
        "ai_distribution", "product_growth", "data_analyst", "critic", "designer",
    ]

    try:
        import json as _json
        from app.agent.engine.llm_adapter import TaskTier

        prompt = (
            f"You are picking growth experts for an unusual/niche product.\n"
            f"Pick the {max_experts} MOST RELEVANT expert IDs from this exact list:\n"
            f"{', '.join(available)}\n\n"
            f"Product description:\n{desc}\n\n"
            f"Return ONLY a JSON array of {max_experts} expert IDs from the list above. "
            f"No explanation. Example: [\"market_researcher\", \"social_media\", \"psychologist\", \"content_strategist\"]"
        )
        resp = await llm_service.generate(
            system_prompt=prompt,
            messages=[{"role": "user", "content": "Pick experts."}],
            tier=TaskTier.PARSING,
            max_tokens=120,
        )
        raw = (getattr(resp, "content", "") or "").strip()
        # 清理 ```json``` 围栏
        if "```" in raw:
            if "```json" in raw:
                raw = raw.split("```json", 1)[1]
            else:
                raw = raw.split("```", 1)[1]
            raw = raw.split("```", 1)[0].strip()
        # 抽取 [...] 区段
        if "[" in raw and "]" in raw:
            raw = raw[raw.index("["): raw.rindex("]") + 1]

        picks = _json.loads(raw)
        if isinstance(picks, list):
            valid = [p for p in picks if isinstance(p, str) and p in available]
            valid = list(dict.fromkeys(valid))[:max_experts]  # 去重 + 截断
            if len(valid) >= 2:
                logger.info(
                    f"Expert selection refined by LLM: {valid} (was {base}) for off-axis product"
                )
                return valid
    except Exception as e:
        logger.debug(f"Expert LLM refinement failed, fallback to table: {e}")

    return base


def get_expert_execution_order(expert_ids: list[str]) -> list[list[str]]:
    """
    根据依赖图计算专家的执行顺序（分批）
    
    返回分批列表：同一批内的专家可并行执行
    
    例如：
    输入: ["market_researcher", "economist", "social_media", "copywriter"]
    输出: [["market_researcher", "social_media"], ["economist"], ["copywriter"]]
    
    market_researcher 和 social_media 没有依赖 → 并行
    economist 依赖 market_researcher → 第二批
    copywriter 依赖 social_media → 第三批（如果 psychologist 在列，和 economist 同批）
    """
    remaining = set(expert_ids)
    completed = set()
    batches = []
    
    max_rounds = len(expert_ids) + 1  # 防止无限循环
    for _ in range(max_rounds):
        if not remaining:
            break
        
        # 找出所有依赖已满足的专家
        ready = []
        for eid in remaining:
            deps = EXPERT_DEPENDENCIES.get(eid, [])
            # 依赖的专家要么已完成，要么不在本次调度中
            if all(d in completed or d not in expert_ids for d in deps):
                ready.append(eid)
        
        if not ready:
            # 有循环依赖或所有剩余的都有未满足的依赖 → 强制全放
            ready = list(remaining)
        
        batches.append(ready)
        completed.update(ready)
        remaining -= set(ready)
    
    return batches
