import logging
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.services.session import SessionService
from app.models.session import AiSession
from app.models.file_info import AiFileInfo
from app.models.ppt import AiPptInst

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/session", tags=["session"])


# ===== 注意：/list 必须在 /{conversation_id} 前面，否则 FastAPI 会把 "list" 当参数匹配 =====

@router.get("/list")
async def get_session_list(
    pageNum: int = Query(default=1, ge=1),
    pageSize: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询会话列表（分页）"""
    logger.info(f"GET /session/list?pageNum={pageNum}&pageSize={pageSize}")
    try:
        svc = SessionService(db)
        records, total = await svc.get_session_list(pageNum, pageSize)
        logger.info(f"会话列表查询结果: {total} 个会话, 当前页 {len(records)} 条")

        session_list = [
            {
                "session_id": r.session_id,
                "agent_type": r.agent_type,
                "question": r.question,
                "create_time": r.create_time.isoformat() if r.create_time else None,
            }
            for r in records
        ]

        return {
            "code": 200, "message": "",
            "data": {
                "page_num": pageNum,
                "page_size": pageSize,
                "total": total,
                "records": session_list,
            },
        }
    except Exception as e:
        logger.error(f"查询会话列表失败: {e}")
        return {"code": 500, "message": f"查询会话列表失败: {e}", "data": None}


@router.get("/{conversation_id}")
async def get_session(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """查询会话详情"""
    logger.info(f"GET /session/{conversation_id}")
    try:
        svc = SessionService(db)
        sessions = await svc.get_by_session_id(conversation_id)
        logger.info(f"查询到 {len(sessions)} 条消息记录")
        if not sessions:
            return {"code": 500, "message": "会话不存在", "data": None}

        agent_type = sessions[0].agent_type
        file_id = sessions[0].fileid

        messages = []
        for s in sessions:
            messages.append({
                "id": str(s.id),  # 雪花ID超出JS安全整数，必须转字符串
                "question": s.question,
                "answer": s.answer,
                "thinking": s.thinking,
                "tools": s.tools,
                "reference": s.reference,
                "create_time": s.create_time.isoformat() if s.create_time else None,
                "fileid": s.fileid,
                "recommend": s.recommend,
            })

        return {
            "code": 200, "message": "",
            "data": {
                "conversation_id": conversation_id,
                "agent_type": agent_type,
                "fileid": file_id,
                "messages": messages,
            },
        }
    except Exception as e:
        logger.error(f"查询会话详情失败: {e}")
        return {"code": 500, "message": f"查询会话详情失败: {e}", "data": None}


@router.delete("/{conversation_id}")
async def delete_session(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """删除会话及其关联数据"""
    try:
        stmt = select(AiFileInfo).where(AiFileInfo.conversation_id == conversation_id)
        result = await db.execute(stmt)
        for record in result.scalars():
            await db.delete(record)

        stmt = select(AiPptInst).where(AiPptInst.conversation_id == conversation_id)
        result = await db.execute(stmt)
        for record in result.scalars():
            await db.delete(record)

        svc = SessionService(db)
        count = await svc.delete_by_session_id(conversation_id)

        await db.commit()
        return {"code": 200, "message": "会话删除成功", "data": None}
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        return {"code": 500, "message": f"删除会话失败: {e}", "data": None}
