"""分支管理 FastAPI 路由"""
import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.edit_regenerate import EditRegenerateService
from app.models.schemas import (
    EditMessageRequest,
    RegenerateRequest,
    SwitchBranchRequest,
    BranchResponse,
    SiblingsResponse,
)
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/branches", tags=["branches"])


@router.post("/{session_id}/edit", response_model=dict)
async def edit_message(
    session_id: str,
    request: EditMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    编辑用户消息并创建新分支

    支持两种模式：
    - create_branch=True: 分支重新回复（保留原消息）
    - create_branch=False: 不分支重新回复（覆盖原消息）
    """
    logger.info(f"POST /branches/{session_id}/edit message_id={request.message_id}, create_branch={request.create_branch}")
    logger.info(f"Request body: message_id={request.message_id}, new_question={request.new_question[:50] if request.new_question else ''}..., create_branch={request.create_branch}")

    try:
        svc = EditRegenerateService(db)
        result = await svc.edit_message(
            session_id=session_id,
            message_id=request.message_id,
            new_question=request.new_question,
            create_branch=request.create_branch,
        )

        return {
            "code": 200,
            "message": "分支创建成功" if request.create_branch else "消息更新成功",
            "data": result.model_dump(),
        }
    except ValueError as e:
        logger.error(f"编辑消息业务错误: {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"编辑消息失败: {e}", exc_info=True)
        return {"code": 500, "message": f"编辑失败: {str(e)}"}


@router.post("/{session_id}/regenerate", response_model=dict)
async def regenerate_message(
    session_id: str,
    request: RegenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    重新生成AI回复（创建兄弟分支）

    始终创建分支，保留原回复可切换回
    """
    logger.info(f"POST /branches/{session_id}/regenerate message_id={request.message_id}")

    try:
        svc = EditRegenerateService(db)
        result = await svc.regenerate(
            session_id=session_id,
            message_id=request.message_id,
        )

        return {
            "code": 200,
            "message": "分支创建成功",
            "data": result.model_dump(),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"重新生成失败: {e}", exc_info=True)
        return {"code": 500, "message": f"重新生成失败: {str(e)}"}


@router.post("/{session_id}/switch", response_model=dict)
async def switch_branch(
    session_id: str,
    request: SwitchBranchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    切换到指定分支

    更新is_active_branch标记，激活目标分支
    """
    logger.info(f"POST /branches/{session_id}/switch target={request.target_branch_id}")

    try:
        svc = EditRegenerateService(db)
        result = await svc.switch_branch(
            session_id=session_id,
            target_branch_id=request.target_branch_id,
        )

        return {
            "code": 200,
            "message": "分支切换成功",
            "data": result.model_dump(),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"分支切换失败: {e}", exc_info=True)
        return {"code": 500, "message": f"分支切换失败: {str(e)}"}


@router.get("/{session_id}/siblings/{message_id}", response_model=dict)
async def get_sibling_branches(
    session_id: str,
    message_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定消息的所有兄弟分支

    用于分支选择器显示（1/2, 2/2等）
    """
    logger.info(f"GET /branches/{session_id}/siblings/{message_id}")

    try:
        svc = EditRegenerateService(db)
        siblings = await svc.get_siblings(session_id, message_id)

        return {
            "code": 200,
            "message": "",
            "data": {
                "siblings": [s.model_dump() for s in siblings]
            }
        }
    except Exception as e:
        logger.error(f"获取兄弟分支失败: {e}", exc_info=True)
        return {"code": 500, "message": f"获取失败: {str(e)}"}
