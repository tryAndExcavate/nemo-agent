"""工作区注册表（服务端单一来源）。

workspaces 注册表是“工作区”的定义处。QueryEngine 启动任务时，通过
resolve_cwd() 从注册表解析出正式 cwd，GlobalState 与引擎都使用该 cwd，
避免同一目录因写法差异（分隔符 / 结尾斜杠 / 大小写）被当成多个工作区。
"""
from __future__ import annotations

import json
from pathlib import Path

_FILE = Path(__file__).resolve().parent.parent / "storage" / "workspaces.json"
_DEFAULT = {"name": "当前项目", "path": "."}


def _norm(p: str) -> str:
    p = (p or ".").replace("\\", "/").rstrip("/")
    return p if p else "."


def name_of(path: str) -> str:
    p = (path or ".").rstrip("/\\") or (path or ".")
    if p == ".":
        return "当前项目"
    base = p.split("/")[-1].split("\\")[-1]
    return base or p


def load() -> dict:
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
    except Exception:
        pass
    return {"active": ".", "items": [dict(_DEFAULT)]}


def save(data: dict) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def ensure_registered(path: str, *, active: bool = True) -> dict:
    """把 path 作为工作区写入注册表（按规范化路径去重），返回整体数据。"""
    path = (path or ".").strip() or "."
    data = load()
    items = data.get("items") or []
    norm = _norm(path)
    name = name_of(path)
    hit = False
    for it in items:
        if _norm(it.get("path", "")) == norm:
            it["path"] = path
            it["name"] = name
            hit = True
            break
    if not hit:
        items.append({"name": name, "path": path})
    data["items"] = items
    if active:
        data["active"] = path
    save(data)
    return data


def resolve_cwd(raw: str | None) -> str:
    """从注册表解析正式 cwd：
    - 已注册 → 返回注册表里记录的规范写法（统一 GlobalState / 引擎 cwd）
    - 未注册 → 返回输入路径本身（调用方随后 ensure_registered 补记）
    """
    raw = (raw or ".").strip() or "."
    norm = _norm(raw)
    for it in load().get("items") or []:
        if _norm(it.get("path", "")) == norm:
            return it["path"]
    return raw


def list_workspaces() -> dict:
    data = load()
    items = data.get("items") or [_DEFAULT]
    active = data.get("active") or items[0]["path"]
    return {"workspaces": items, "active": active}


def remove(path: str) -> dict:
    data = load()
    norm = _norm(path)
    items = [it for it in (data.get("items") or []) if _norm(it.get("path", "")) != norm]
    data["items"] = items or [_DEFAULT]
    if _norm(data.get("active", "")) == norm:
        data["active"] = data["items"][0]["path"]
    save(data)
    return {"workspaces": data["items"], "active": data["active"]}
