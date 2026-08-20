"""app/api/base.py - 基座激活模型接口。

可插拔大模型基座：左侧是一个固定的「基座 Agent」节点，右侧模型仓库里选一个
模型拖上去、点「保存」后即为当前基座激活模型（active_model）。业务运行时只需
读 GET /base/active 就能拿到当前真正要调用的模型，换模型不改业务代码。

沿用项目统一的响应包裹：{"code": 200, "message": "", "data": ...}
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from llm_core.store import ConfigStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/base", tags=["base"])


def _ok(data, message=""):
    return {"code": 200, "message": message, "data": data}


def _err(message, code=500):
    return {"code": code, "message": message, "data": None}


class SetActiveRequest(BaseModel):
    model_id: str


class SetActiveSummaryRequest(BaseModel):
    model_id: str


@router.get("/active")
def get_active():
    """读当前基座激活模型（脱敏）。未激活时 data=None。"""
    logger.info("GET /base/active")
    try:
        active_id = ConfigStore.get_active_model_id()
        if not active_id:
            return _ok(None, "尚未挂载基座模型")
        try:
            model = ConfigStore.get_basic(active_id)
        except ValueError:
            # 激活的模型已被删除：顺带清掉脏状态
            ConfigStore.clear_active_model()
            return _ok(None, "激活模型已被删除，已自动拔出")
        return _ok(model)
    except Exception as e:
        logger.error(f"读取基座激活模型失败: {e}")
        return _err(f"读取基座激活模型失败: {e}")


@router.post("/active")
def set_active(req: SetActiveRequest):
    """把某个模型设为基座激活模型（保存即生效）。"""
    logger.info(f"POST /base/active model_id={req.model_id}")
    try:
        try:
            model = ConfigStore.get_basic(req.model_id)
        except ValueError as e:
            return _err(str(e), code=404)
        ConfigStore.set_active_model_id(req.model_id)
        return _ok(model, f"已挂载 {model['name']}")
    except Exception as e:
        logger.error(f"设置基座激活模型失败: {e}")
        return _err(f"设置基座激活模型失败: {e}")


@router.delete("/active")
def clear_active():
    """拔出基座模型，解除挂载。"""
    logger.info("DELETE /base/active")
    try:
        ConfigStore.clear_active_model()
        return _ok({"status": "cleared"}, "已拔出基座模型")
    except Exception as e:
        logger.error(f"拔出基座激活模型失败: {e}")
        return _err(f"拔出基座激活模型失败: {e}")


# ===== 摘要模型接口（用于上下文管理） =====

@router.get("/active/summary")
def get_active_summary():
    """读当前摘要模型（脱敏）。未激活时 data=None。"""
    logger.info("GET /base/active/summary")
    try:
        active_id = ConfigStore.get_active_summary_model_id()
        if not active_id:
            return _ok(None, "尚未挂载摘要模型")
        try:
            model = ConfigStore.get_basic(active_id)
        except ValueError:
            # 激活的模型已被删除：顺带清掉脏状态
            ConfigStore.clear_active_summary_model()
            return _ok(None, "摘要模型已被删除，已自动拔出")
        return _ok(model)
    except Exception as e:
        logger.error(f"读取摘要模型失败: {e}")
        return _err(f"读取摘要模型失败: {e}")


@router.post("/active/summary")
def set_active_summary(req: SetActiveSummaryRequest):
    """把某个模型设为摘要模型（保存即生效）。"""
    logger.info(f"POST /base/active/summary model_id={req.model_id}")
    try:
        try:
            model = ConfigStore.get_basic(req.model_id)
        except ValueError as e:
            return _err(str(e), code=404)
        ConfigStore.set_active_summary_model_id(req.model_id)
        return _ok(model, f"已挂载摘要模型 {model['name']}")
    except Exception as e:
        logger.error(f"设置摘要模型失败: {e}")
        return _err(f"设置摘要模型失败: {e}")


@router.delete("/active/summary")
def clear_active_summary():
    """拔出摘要模型，解除挂载。"""
    logger.info("DELETE /base/active/summary")
    try:
        ConfigStore.clear_active_summary_model()
        return _ok({"status": "cleared"}, "已拔出摘要模型")
    except Exception as e:
        logger.error(f"拔出摘要模型失败: {e}")
        return _err(f"拔出摘要模型失败: {e}")
