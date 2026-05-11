"""
CrabRes Memory System

学习自 Claude Code 的多层记忆架构：

Layer 1: Growth Config（最高优先级，用户配置）
Layer 2: Auto Memory（自动记忆，分类存储）
Layer 3: Session Memory（会话记忆，每次对话摘要）
Layer 4: Growth Dream（后台整理，消除矛盾、去重、合并）
Layer 5: External Knowledge（外部引用知识，独立存储+触发条件+版本管理）

记忆分类（学 Claude Code 的 memdir/）：
- product/    产品 DNA
- goals/      增长目标
- research/   研究数据（竞品/用户画像/渠道）
- strategy/   策略文档（增长计划/内容日历/预算）
- execution/  执行效果（KPI/什么有效/什么无效）
- feedback/   用户修正（偏好/约束/否决）
- journal/    增长日志（每日追加）
- knowledge/  外部知识引用（平台规则/行业数据/框架模板）
"""

import json
import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GrowthMemory:
    """CrabRes 记忆系统"""

    CATEGORIES = [
        "product", "goals", "research", "strategy",
        "execution", "feedback", "journal", "knowledge",
    ]

    def __init__(self, base_dir: str = ".crabres/memory"):
        self.base_dir = Path(base_dir)
        self._ensure_dirs()

    def _ensure_dirs(self):
        for cat in self.CATEGORIES:
            (self.base_dir / cat).mkdir(parents=True, exist_ok=True)

    async def save(self, key: str, data: Any, category: str = "product"):
        """
        保存记忆（带版本追踪）
        
        自动记录版本号和更新时间，用于 Dream 去重和知识新鲜度判断。
        """
        path = self.base_dir / category / f"{key}.json"
        
        # 版本追踪：如果文件已存在，递增版本号
        version = 1
        old_data = None
        if path.exists():
            try:
                old_data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(old_data, dict):
                    version = old_data.get("_version", 0) + 1
            except Exception:
                pass
        
        # 如果 data 是 dict，注入元数据
        if isinstance(data, dict):
            data["_version"] = version
            data["_updated_at"] = time.time()
            # 内容 hash 用于 Dream 去重
            content_str = json.dumps({k: v for k, v in data.items() if not k.startswith("_")}, 
                                     ensure_ascii=False, default=str)
            data["_content_hash"] = hashlib.md5(content_str.encode()).hexdigest()[:12]
        
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        logger.debug(f"Memory saved: {category}/{key} (v{version})")

    async def load(self, key: str, category: str = "product") -> Optional[Any]:
        """加载记忆"""
        path = self.base_dir / category / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    async def save_knowledge(self, key: str, content: str, source: str,
                             trigger: str = "", expires_days: int = 0):
        """
        保存外部知识引用（独立于专家知识库的动态知识）
        
        用途：
        - 用户分享的实操经验（小红书/公众号运营心得）
        - 调研获取的最新平台规则
        - 行业基准数据
        
        Args:
            key: 知识标识（如 "xiaohongshu_2026_rules"）
            content: 知识内容
            source: 来源标注
            trigger: 触发条件（什么场景下注入，如 "task contains 小红书"）
            expires_days: 过期天数（0=不过期）
        """
        data = {
            "content": content,
            "source": source,
            "trigger": trigger,
            "created_at": time.time(),
            "expires_at": time.time() + expires_days * 86400 if expires_days > 0 else 0,
        }
        await self.save(key, data, category="knowledge")
        logger.info(f"Knowledge saved: {key} ({len(content)} chars, source={source})")

    async def get_triggered_knowledge(self, task: str) -> list[dict]:
        """
        获取与当前任务匹配的外部知识
        
        遍历 knowledge/ 目录，检查 trigger 条件是否匹配。
        """
        knowledge_dir = self.base_dir / "knowledge"
        if not knowledge_dir.exists():
            return []
        
        results = []
        task_lower = task.lower()
        now = time.time()
        
        for path in knowledge_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # 检查过期
                expires_at = data.get("expires_at", 0)
                if expires_at > 0 and now > expires_at:
                    continue
                
                # 检查触发条件
                trigger = data.get("trigger", "")
                if trigger:
                    # trigger 格式："task contains 小红书" 或 "always"
                    if trigger == "always":
                        results.append(data)
                    elif "contains" in trigger:
                        keyword = trigger.split("contains")[-1].strip()
                        if keyword.lower() in task_lower:
                            results.append(data)
                else:
                    # 无触发条件 = 关键词匹配
                    key_stem = path.stem.replace("_", " ")
                    if any(word in task_lower for word in key_stem.split() if len(word) > 2):
                        results.append(data)
            except Exception:
                continue
        
        return results

    async def append_journal(self, entry: dict):
        """追加增长日志（学 Claude Code 的 Write-Ahead Log）"""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        journal_dir = self.base_dir / "journal"
        path = journal_dir / f"{today}.jsonl"

        entry["timestamp"] = entry.get("timestamp", time.time())
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    async def list_memories(self, category: str) -> list[str]:
        """列出某个类别的所有记忆"""
        cat_dir = self.base_dir / category
        if not cat_dir.exists():
            return []
        return [f.stem for f in cat_dir.glob("*.json")]

    async def search(self, query: str, categories: list[str] = None) -> list[dict]:
        """简单的关键词搜索记忆（后续可改为向量搜索）"""
        results = []
        for cat in (categories or self.CATEGORIES):
            cat_dir = self.base_dir / cat
            if not cat_dir.exists():
                continue
            for path in cat_dir.glob("*.json"):
                try:
                    content = path.read_text(encoding="utf-8")
                    if query.lower() in content.lower():
                        results.append({
                            "category": cat,
                            "key": path.stem,
                            "preview": content[:200],
                        })
                except Exception:
                    continue
        return results

    async def get_memory_stats(self) -> dict:
        """获取记忆系统统计（供 Dream 和 Metrics 使用）"""
        stats = {}
        total_size = 0
        for cat in self.CATEGORIES:
            cat_dir = self.base_dir / cat
            if not cat_dir.exists():
                stats[cat] = {"count": 0, "size_bytes": 0}
                continue
            files = list(cat_dir.glob("*.json")) + list(cat_dir.glob("*.jsonl"))
            size = sum(f.stat().st_size for f in files)
            stats[cat] = {"count": len(files), "size_bytes": size}
            total_size += size
        return {
            "categories": stats,
            "total_files": sum(s["count"] for s in stats.values()),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        }



    # ========== FTS5 Semantic Search Integration ==========

    async def semantic_search(self, query: str, categories: list[str] = None, limit: int = 10) -> list[dict]:
        """
        Search memory using FTS5 BM25 ranking (replaces naive keyword search).
        
        Falls back to simple keyword search if FTS5 is unavailable.
        """
        try:
            from app.agent.memory.semantic_search import SemanticMemorySearch
            searcher = SemanticMemorySearch(base_dir=str(self.base_dir))
            return await searcher.search(query, categories, limit)
        except Exception as e:
            logger.warning(f"FTS5 search failed, falling back to keyword: {e}")
            return await self.search(query, categories)

    async def search_for_prompt(self, query: str, categories: list[str] = None, max_chars: int = 2000) -> str:
        """
        Search and format results as injectable prompt text.
        
        This is what gets prepended to expert/pipeline system prompts
        to give the agent "memory" across sessions.
        """
        try:
            from app.agent.memory.semantic_search import SemanticMemorySearch
            searcher = SemanticMemorySearch(base_dir=str(self.base_dir))
            return await searcher.search_for_prompt(query, categories, max_chars)
        except Exception as e:
            logger.warning(f"Semantic search for prompt failed: {e}")
            # Fallback: use basic search
            results = await self.search(query, categories)
            if not results:
                return ""
            lines = ["## RELEVANT MEMORIES (from past sessions)"]
            for r in results[:5]:
                lines.append(f"- [{r['category']}/{r['key']}] {r['preview'][:200]}")
            return "\n".join(lines)

    async def reindex(self):
        """Force re-index all memory files for FTS5 search"""
        try:
            from app.agent.memory.semantic_search import SemanticMemorySearch
            searcher = SemanticMemorySearch(base_dir=str(self.base_dir))
            return await searcher.index_all(force=True)
        except Exception as e:
            logger.error(f"Reindex failed: {e}")
            return {"error": str(e)}
