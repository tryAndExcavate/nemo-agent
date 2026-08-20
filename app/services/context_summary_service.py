"""上下文摘要 CRUD 服务。"""
import logging
from typing import Optional
from sqlmodel import select
from app.database import async_session_factory
from app.models.context_summary import ContextSummary

logger = logging.getLogger(__name__)


class ContextSummaryService:
    """上下文摘要的 CRUD 操作。"""

    def __init__(self, db=None):
        self._db = db
        self._owns_session = db is None

    async def get_by_conversation_id(self, conversation_id: str) -> Optional[ContextSummary]:
        """根据会话 ID 获取摘要。"""
        async with async_session_factory() as session:
            stmt = select(ContextSummary).where(ContextSummary.conversation_id == conversation_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_or_update(
        self,
        conversation_id: str,
        summary_text: str,
        covered_up_to_message_id: int,
        token_count: int,
        summary_model_id: str,
    ) -> ContextSummary:
        """创建或更新摘要。"""
        async with async_session_factory() as session:
            existing = await self._get_by_conversation_id(session, conversation_id)
            if existing:
                existing.summary_text = summary_text
                existing.covered_up_to_message_id = covered_up_to_message_id
                existing.token_count = token_count
                existing.summary_model_id = summary_model_id
                await session.commit()
                await session.refresh(existing)
                return existing
            else:
                summary = ContextSummary(
                    conversation_id=conversation_id,
                    summary_text=summary_text,
                    covered_up_to_message_id=covered_up_to_message_id,
                    token_count=token_count,
                    summary_model_id=summary_model_id,
                )
                session.add(summary)
                await session.commit()
                await session.refresh(summary)
                return summary

    async def delete_by_conversation_id(self, conversation_id: int) -> bool:
        """删除摘要。"""
        async with async_session_factory() as session:
            existing = await self._get_by_conversation_id(session, conversation_id)
            if existing:
                await session.delete(existing)
                await session.commit()
                return True
            return False

    async def _get_by_conversation_id(self, session, conversation_id: int) -> Optional[ContextSummary]:
        """内部方法：根据会话 ID 获取摘要。"""
        stmt = select(ContextSummary).where(ContextSummary.conversation_id == conversation_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
