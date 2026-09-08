"""目录浏览 API + 工作区注册表路由

工作区注册表是服务端“工作区=QueryEngine.cwd”的单一来源，读写集中在
app/services/workspace_registry.py，本文件只提供 HTTP 暴露。
"""
from pathlib import Path
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.workspace_registry import (
    ensure_registered,
    list_workspaces,
    remove,
)

router = APIRouter(prefix="/api", tags=["directories"])


class DirectoryItem(BaseModel):
    name: str
    path: str
    is_dir: bool


class WorkspaceRequest(BaseModel):
    path: str


@router.get("/workspaces")
async def get_workspaces():
    """返回已连接工作区列表与最近选中（服务端持久化）"""
    return list_workspaces()


@router.post("/workspaces")
async def add_or_select_workspace(req: WorkspaceRequest):
    """注册一个工作区并设为当前选中（幂等，按规范化路径去重）"""
    return ensure_registered(req.path, active=True)


@router.delete("/workspaces")
async def delete_workspace(path: str = Query(...)):
    """从注册表移除一个工作区（若移除的是当前选中，回退到列表第一个）"""
    return remove(path)


@router.get("/directories")
async def list_directories(path: str = Query(".")):
    """列出指定路径下的子目录，用于前端工作区选择器浏览文件系统"""
    target = Path(path).resolve()
    if not target.exists():
        return {"path": str(target), "items": [], "error": "路径不存在"}
    if not target.is_dir():
        return {"path": str(target), "items": [], "error": "不是目录"}

    items = []
    try:
        for entry in sorted(target.iterdir()):
            # 只展示目录，跳过隐藏文件/系统目录
            if entry.name.startswith(".") or entry.name.startswith("__"):
                continue
            if entry.is_dir():
                items.append(DirectoryItem(
                    name=entry.name,
                    path=str(entry),
                    is_dir=True,
                ))
    except PermissionError:
        return {"path": str(target), "items": [], "error": "无权限访问"}

    return {"path": str(target), "items": items[:100]}
