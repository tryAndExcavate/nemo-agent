"""app/api/blueprint.py - 蓝图版本化管理接口。

把蓝图当成"代码"来管理：每次保存生成一条新版本(draft)，可手动发布(published)，
Agent 运行时只读取已发布版本，与编辑中的草稿完全隔离。支持结构校验与版本回滚。

沿用项目统一的响应包裹：{"code": 200, "message": "", "data": ...}
"""
import json
import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import Session, select, func

from llm_core.store import ConfigStore
from llm_core.blueprint_db import BlueprintVersion, BlueprintPointer, engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/blueprint", tags=["blueprint"])


def _ok(data, message=""):
    return {"code": 200, "message": message, "data": data}


def _err(message, data=None, code=500):
    return {"code": code, "message": message, "data": data}


class SaveDraftRequest(BaseModel):
    graph: dict
    message: str = ""


def validate_graph(graph: dict) -> list[str]:
    """保存/发布前的结构校验，返回错误信息列表（空列表表示通过）。"""
    errors = []
    node_ids = {n["id"] for n in graph.get("nodes", [])}

    for node in graph.get("nodes", []):
        if node.get("type") == "agent/llm_call":
            model_id = (node.get("properties") or {}).get("model_id")
            if not model_id:
                errors.append(f"节点 {node['id']} 未绑定任何模型")
            else:
                try:
                    ConfigStore.get_decrypted(model_id)  # 校验模型是否存在
                except ValueError:
                    errors.append(f"节点 {node['id']} 引用的模型 {model_id} 已被删除")

    # 校验连线是否指向不存在的节点（防止脏数据）
    for link in graph.get("links", []):
        # LiteGraph link 格式: [id, origin_id, origin_slot, target_id, target_slot, type]
        if len(link) >= 4:
            origin_id, target_id = link[1], link[3]
            if origin_id not in node_ids or target_id not in node_ids:
                errors.append("存在指向已删除节点的连线，请检查图结构")

    return errors


def _next_version(s: Session, agent_id: str) -> int:
    cur = s.exec(
        select(func.max(BlueprintVersion.version)).where(BlueprintVersion.agent_id == agent_id)
    ).one()
    return (cur or 0) + 1


@router.post("/{agent_id}/draft")
def save_draft(agent_id: str, req: SaveDraftRequest):
    """保存草稿：新增一条版本记录，不做覆盖。"""
    logger.info(f"POST /blueprint/{agent_id}/draft")
    errors = validate_graph(req.graph)
    if errors:
        return _err("校验失败", data={"errors": errors}, code=400)

    try:
        with Session(engine) as s:
            item = BlueprintVersion(
                agent_id=agent_id,
                version=_next_version(s, agent_id),
                graph_json=json.dumps(req.graph, ensure_ascii=False),
                status="draft",
                message=req.message,
            )
            s.add(item)
            s.commit()
            return _ok({"version_id": item.id, "version": item.version}, "草稿已保存")
    except Exception as e:
        logger.error(f"保存草稿失败 agent={agent_id}: {e}")
        return _err(f"保存草稿失败: {e}")


@router.get("/{agent_id}/draft/latest")
def get_latest_draft(agent_id: str):
    """前端进入编辑页时，默认加载最新的草稿（不管是否发布过）。"""
    logger.info(f"GET /blueprint/{agent_id}/draft/latest")
    try:
        with Session(engine) as s:
            item = s.exec(
                select(BlueprintVersion)
                .where(BlueprintVersion.agent_id == agent_id)
                .order_by(BlueprintVersion.version.desc())
            ).first()
        if not item:
            return _ok({"graph": {"nodes": [], "links": []}, "version": 0})
        return _ok({"graph": json.loads(item.graph_json), "version": item.version})
    except Exception as e:
        logger.error(f"加载最新草稿失败 agent={agent_id}: {e}")
        return _err(f"加载草稿失败: {e}")


@router.post("/{agent_id}/publish/{version_id}")
def publish_version(agent_id: str, version_id: str):
    """把某个草稿版本正式设为运行时使用的版本。"""
    logger.info(f"POST /blueprint/{agent_id}/publish/{version_id}")
    try:
        with Session(engine) as s:
            version = s.get(BlueprintVersion, version_id)
            if not version or version.agent_id != agent_id:
                return _err("版本不存在", code=404)

            errors = validate_graph(json.loads(version.graph_json))
            if errors:
                return _err("发布前校验失败", data={"errors": errors}, code=400)

            version.status = "published"
            pointer = s.get(BlueprintPointer, agent_id)
            if pointer:
                pointer.published_version_id = version_id
            else:
                pointer = BlueprintPointer(agent_id=agent_id, published_version_id=version_id)
            s.add(version)
            s.add(pointer)
            s.commit()
            return _ok({"status": "published", "version": version.version}, f"v{version.version} 已发布")
    except Exception as e:
        logger.error(f"发布失败 agent={agent_id}: {e}")
        return _err(f"发布失败: {e}")


@router.get("/{agent_id}/runtime")
def get_runtime_graph(agent_id: str):
    """Agent 实际运行时读取已发布版本，与编辑草稿隔离。"""
    logger.info(f"GET /blueprint/{agent_id}/runtime")
    try:
        with Session(engine) as s:
            pointer = s.get(BlueprintPointer, agent_id)
            if not pointer:
                return _err("该 agent 尚未发布任何蓝图版本", code=404)
            version = s.get(BlueprintVersion, pointer.published_version_id)
            if not version:
                return _err("发布版本不存在", code=404)
        return _ok(json.loads(version.graph_json))
    except Exception as e:
        logger.error(f"读取运行时蓝图失败 agent={agent_id}: {e}")
        return _err(f"读取运行时蓝图失败: {e}")


@router.get("/{agent_id}/history")
def list_history(agent_id: str):
    """版本历史列表，用于前端"版本回溯"面板。"""
    logger.info(f"GET /blueprint/{agent_id}/history")
    try:
        with Session(engine) as s:
            items = s.exec(
                select(BlueprintVersion)
                .where(BlueprintVersion.agent_id == agent_id)
                .order_by(BlueprintVersion.version.desc())
            ).all()
        return _ok([
            {
                "id": i.id, "version": i.version, "status": i.status,
                "message": i.message,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ])
    except Exception as e:
        logger.error(f"加载版本历史失败 agent={agent_id}: {e}")
        return _err(f"加载版本历史失败: {e}")


@router.post("/{agent_id}/rollback/{version_id}")
def rollback(agent_id: str, version_id: str):
    """回滚：把历史版本内容复制成一条新草稿（保留完整历史链）。"""
    logger.info(f"POST /blueprint/{agent_id}/rollback/{version_id}")
    try:
        with Session(engine) as s:
            old = s.get(BlueprintVersion, version_id)
            if not old:
                return _err("版本不存在", code=404)
            new_item = BlueprintVersion(
                agent_id=agent_id,
                version=_next_version(s, agent_id),
                graph_json=old.graph_json,
                status="draft",
                message=f"回滚自 v{old.version}",
            )
            s.add(new_item)
            s.commit()
            return _ok({"version_id": new_item.id, "version": new_item.version}, f"已回滚，生成新草稿 v{new_item.version}")
    except Exception as e:
        logger.error(f"回滚失败 agent={agent_id}: {e}")
        return _err(f"回滚失败: {e}")
