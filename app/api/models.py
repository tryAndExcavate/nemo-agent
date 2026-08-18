import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from llm_core.store import ConfigStore
from llm_core.manager import ModelManager
from llm_core.registry import AdapterRegistry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/models", tags=["models"])


class ModelUpsertRequest(BaseModel):
    id: str | None = None
    name: str
    provider_type: str
    base_url: str
    model_name: str
    api_key: str
    extra_config: dict = {}
    enabled: bool = True


def _ok(data, message=""):
    return {"code": 200, "message": message, "data": data}


def _err(message, code=500):
    return {"code": code, "message": message, "data": None}


@router.get("/provider_types")
def list_provider_types():
    """前端「新增模型」下拉框数据来源。"""
    logger.info("GET /models/provider_types")
    try:
        return _ok({"types": AdapterRegistry.list_types()})
    except Exception as e:
        logger.error(f"获取 provider 类型失败: {e}")
        return _err(f"获取 provider 类型失败: {e}")


@router.get("")
def list_models():
    """模型仓库列表（脱敏，不含 api_key）。"""
    logger.info("GET /models")
    try:
        return _ok(ConfigStore.list_all())
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}")
        return _err(f"获取模型列表失败: {e}")


@router.get("/{model_id}")
def get_model(model_id: str):
    """获取单个模型配置（脱敏），供前端编辑回填。"""
    logger.info(f"GET /models/{model_id}")
    try:
        return _ok(ConfigStore.get_basic(model_id))
    except ValueError as e:
        logger.warning(f"模型不存在: {model_id}")
        return _err(str(e), code=404)
    except Exception as e:
        logger.error(f"获取模型失败: {e}")
        return _err(f"获取模型失败: {e}")


@router.post("")
def upsert_model(req: ModelUpsertRequest):
    """新增或更新模型配置。传入 id 则更新，否则新建。"""
    logger.info(f"POST /models upsert: name={req.name} provider={req.provider_type}")
    try:
        if req.provider_type not in AdapterRegistry.list_types():
            return _err(f"未注册的模型类型: {req.provider_type}")
        model_id = req.id or str(uuid.uuid4())
        ConfigStore.save(
            model_id, req.name, req.provider_type, req.base_url,
            req.model_name, req.api_key, req.extra_config, req.enabled,
        )
        ModelManager.invalidate(model_id)
        return _ok({"id": model_id, "status": "saved"}, "保存成功")
    except Exception as e:
        logger.error(f"保存模型失败: {e}")
        return _err(f"保存模型失败: {e}")


@router.post("/{model_id}/test")
async def test_model(model_id: str):
    """测试连接：实例化 adapter 并对其发一个 ping。"""
    logger.info(f"POST /models/{model_id}/test")
    try:
        adapter = ModelManager.get_adapter(model_id)
        ok = await adapter.test_connection()
        if not ok:
            return _err("连接测试失败，请检查配置", code=400)
        return _ok({"status": "ok", "model_id": model_id}, "连接成功")
    except ValueError as e:
        return _err(str(e), code=404)
    except Exception as e:
        logger.warning(f"连接测试失败 model={model_id}: {e}")
        return _err(f"连接测试失败: {e}", code=400)


@router.delete("/{model_id}")
def delete_model(model_id: str):
    """删除模型配置并清掉缓存。"""
    logger.info(f"DELETE /models/{model_id}")
    try:
        deleted = ConfigStore.delete(model_id)
        ModelManager.invalidate(model_id)
        if not deleted:
            return _err("模型不存在", code=404)
        return _ok({"status": "deleted", "model_id": model_id}, "删除成功")
    except Exception as e:
        logger.error(f"删除模型失败: {e}")
        return _err(f"删除模型失败: {e}")
