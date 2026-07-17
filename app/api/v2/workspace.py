"""
Workspace API — 文件管理接口

让前端能查看 Agent 生成的所有文件（报告/草稿/计划等）
"""

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace", tags=["Workspace"])

# workspace 根目录
# 优先使用 Render Disk 持久化路径（部署后文件不丢失）
# 如果没有 Render Disk，降级到容器内路径（部署后会丢失）
import os as _os
_render_disk = _os.environ.get("RENDER_DISK_PATH", "")
if _render_disk:
    WORKSPACE_ROOT = Path(_render_disk) / "workspace"
    WORKSPACE_FALLBACK_ROOT = Path(".crabres/memory")
else:
    WORKSPACE_ROOT = Path(".crabres/memory")
    WORKSPACE_FALLBACK_ROOT = None

WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def _workspace_base(user_id: int) -> Path:
    base = WORKSPACE_ROOT / str(user_id)
    if not _render_disk:
        base = base / "workspace"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _workspace_fallback(user_id: int) -> Optional[Path]:
    if not WORKSPACE_FALLBACK_ROOT:
        return None
    return WORKSPACE_FALLBACK_ROOT / str(user_id) / "workspace"


def _safe_path(user_id: int, rel_path: str) -> Path:
    """防止路径穿越攻击"""
    base = _workspace_base(user_id).resolve()
    resolved = (base / rel_path).resolve()
    if os.path.commonpath((base, resolved)) != str(base):
        raise HTTPException(status_code=403, detail="Access denied")
    return resolved


@router.get("/files")
async def list_files(
    path: str = Query("", description="子目录路径"),
    current_user: dict = Depends(require_user),
):
    """列出 workspace 中的文件和目录"""
    user_id = current_user["user_id"]
    workspace_base = _workspace_base(user_id)
    target = _safe_path(user_id, path)
    if not target.exists():
        # 尝试从容器内路径恢复（Render Disk 可能还没同步）
        fallback = _workspace_fallback(user_id)
        if fallback:
            fallback_target = (fallback / path).resolve()
            if fallback_target.exists():
                import shutil
                target.parent.mkdir(parents=True, exist_ok=True)
                if fallback_target.is_dir():
                    shutil.copytree(fallback_target, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(fallback_target, target)
        if not target.exists():
            return {"files": [], "path": path}

    items = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            stat = entry.stat()
            items.append({
                "name": entry.name,
                "path": str(entry.relative_to(workspace_base)),
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size if entry.is_file() else None,
                "modified": stat.st_mtime,
                "extension": entry.suffix.lstrip(".") if entry.is_file() else None,
            })
    except Exception as e:
        logger.warning(f"Failed to list workspace: {e}")

    return {"files": items, "path": path}


@router.get("/files/tree")
async def file_tree(current_user: dict = Depends(require_user)):
    """递归获取完整文件树"""
    workspace_base = _workspace_base(current_user["user_id"])
    if not workspace_base.exists():
        return {"tree": []}

    def _walk(dir_path: Path, depth: int = 0) -> list:
        if depth > 5:
            return []
        result = []
        try:
            for entry in sorted(dir_path.iterdir()):
                if entry.name.startswith("."):
                    continue
                node = {
                    "name": entry.name,
                    "path": str(entry.relative_to(workspace_base)),
                    "type": "directory" if entry.is_dir() else "file",
                }
                if entry.is_file():
                    node["size"] = entry.stat().st_size
                    node["extension"] = entry.suffix.lstrip(".")
                elif entry.is_dir():
                    node["children"] = _walk(entry, depth + 1)
                result.append(node)
        except Exception:
            pass
        return result

    return {"tree": _walk(workspace_base)}


@router.get("/files/read")
async def read_file(
    path: str = Query(..., description="文件相对路径"),
    current_user: dict = Depends(require_user),
):
    """读取单个文件内容（支持从 memory 备份恢复）"""
    user_id = current_user["user_id"]
    target = _safe_path(user_id, path)
    
    # 如果文件不存在，尝试从 memory 备份恢复
    if not target.exists() or not target.is_file():
        recovered = await _try_recover_from_memory(user_id, path)
        if recovered:
            # 恢复成功，重新读取
            target = _safe_path(user_id, path)
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")

    # 文本文件
    text_ext = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".py", ".js", ".ts"}
    # 图片文件（返回 base64 或直接二进制）
    image_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    
    ext = target.suffix.lower()
    if ext not in text_ext and ext not in image_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {target.suffix}")

    try:
        if ext in image_ext:
            # 图片文件 → 返回二进制流
            from fastapi.responses import FileResponse
            media_types = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
            }
            return FileResponse(
                path=str(target),
                media_type=media_types.get(ext, "application/octet-stream"),
                filename=target.name,
            )
        
        content = target.read_text(encoding="utf-8")
        return {
            "path": path,
            "name": target.name,
            "content": content,
            "size": target.stat().st_size,
            "extension": target.suffix.lstrip("."),
            "modified": target.stat().st_mtime,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")


@router.delete("/files")
async def delete_file(
    path: str = Query(..., description="文件相对路径"),
    current_user: dict = Depends(require_user),
):
    """删除单个文件"""
    target = _safe_path(current_user["user_id"], path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        if target.is_file():
            target.unlink()
        return {"deleted": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")


async def _try_recover_from_memory(user_id: int, rel_path: str) -> bool:
    """尝试从 memory 备份中恢复文件"""
    try:
        user_dir = Path(".crabres/memory") / str(user_id)
        if not user_dir.exists():
            return False

        backup_file = user_dir / "workspace_backup" / f"{rel_path.replace('/', '_')}.json"
        if backup_file.exists():
            import json
            data = json.loads(backup_file.read_text(encoding="utf-8"))
            content = data.get("content", "")
            if content:
                target = _safe_path(user_id, rel_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                logger.info(f"Recovered workspace file from memory backup: {rel_path}")
                return True
    except Exception as e:
        logger.warning(f"Failed to recover file from memory: {e}")
    return False


@router.get("/stats")
async def workspace_stats(current_user: dict = Depends(require_user)):
    """workspace 统计信息"""
    workspace_base = _workspace_base(current_user["user_id"])
    if not workspace_base.exists():
        return {"total_files": 0, "total_size": 0, "categories": {}}

    total_files = 0
    total_size = 0
    categories: dict = {}

    for f in workspace_base.rglob("*"):
        if f.is_file() and not f.name.startswith("."):
            total_files += 1
            total_size += f.stat().st_size
            # 按父目录分类
            cat = f.parent.name if f.parent != workspace_base else "root"
            categories[cat] = categories.get(cat, 0) + 1

    return {
        "total_files": total_files,
        "total_size": total_size,
        "categories": categories,
    }
