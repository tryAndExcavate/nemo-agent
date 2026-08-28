import json
from datetime import datetime
from sqlalchemy import select, desc, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.session import AiSession
from app.models.schemas import SaveQuestionRequest, UpdateAnswerRequest


class SessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_recent_by_session_id(self, session_id: str, max_messages: int = 30) -> list[AiSession]:
        stmt = (
            select(AiSession)
            .where(AiSession.session_id == session_id)
            .order_by(desc(AiSession.create_time))
            .limit(max_messages)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def save_question(self, request: SaveQuestionRequest) -> AiSession:
        # 查找同会话最新的已有消息，作为 parent_id
        parent_id = request.parent_id
        if parent_id is None:
            stmt = (
                select(AiSession.id)
                .where(AiSession.session_id == request.session_id)
                .order_by(AiSession.create_time.desc())
                .limit(1)
            )
            res = await self.db.execute(stmt)
            latest = res.scalar_one_or_none()
            if latest is not None:
                parent_id = latest

        session = AiSession(
            session_id=request.session_id,
            question=request.question,
            fileid=request.fileid,
            first_response_time=request.first_response_time,
            agent_type=None,
            parent_id=parent_id,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def update_answer(self, request: UpdateAnswerRequest) -> bool:
        stmt = select(AiSession).where(AiSession.id == request.id)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        if session is None:
            return False

        session.answer = request.answer
        session.thinking = request.thinking
        session.tools = request.tools
        session.reference = request.reference
        session.recommend = request.recommend
        if request.first_response_time is not None:
            session.first_response_time = request.first_response_time
        if request.total_response_time is not None:
            session.total_response_time = request.total_response_time

        await self.db.commit()
        return True

    async def get_by_session_id(self, session_id: str) -> list[AiSession]:
        stmt = (
            select(AiSession)
            .where(AiSession.session_id == session_id)
            .order_by(AiSession.create_time)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_session_id(self, session_id: str) -> int:
        stmt = delete(AiSession).where(AiSession.session_id == session_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def get_session_list(self, page_num: int = 1, page_size: int = 10) -> tuple[list[AiSession], int]:
        # Get first record per session_id
        subq = (
            select(
                AiSession.session_id,
                func.min(AiSession.id).label("min_id"),
            )
            .group_by(AiSession.session_id)
            .subquery()
        )
        count_stmt = select(func.count()).select_from(subq)
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(AiSession)
            .where(AiSession.id.in_(select(subq.c.min_id)))
            .order_by(desc(AiSession.create_time))
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total
