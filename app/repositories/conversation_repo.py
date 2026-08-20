"""会话数据访问层。"""
import logging
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy import text
from app.database import async_session_factory

logger = logging.getLogger(__name__)


class ConversationRepository:
    """会话的 CRUD 操作（支持活跃会话和归档会话两个表）。"""

    def __init__(self):
        pass

    async def create(self, user_id: int, session_id: str, title: str = "新对话", agent_type: str = None) -> Dict:
        """创建新活跃会话。"""
        async with async_session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO conversations (session_id, user_id, title, agent_type, status, last_message_at)
                    VALUES (:sid, :uid, :title, :agent_type, 'false', NOW())
                """),
                {"sid": session_id, "uid": user_id, "title": title, "agent_type": agent_type}
            )
            await session.commit()
            return await self._get_by_id(session, session_id, "active")

    async def list_active(self, user_id: int) -> List[Dict]:
        """列出所有活跃会话（活跃会话优先排序）。"""
        async with async_session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT session_id, title, agent_type, status, last_message_at, created_at
                    FROM conversations
                    WHERE user_id = :uid
                    ORDER BY status DESC, last_message_at DESC
                """),
                {"uid": user_id}
            )
            rows = [dict(r._mapping) for r in result.fetchall()]
            return rows

    async def list_archived(self, user_id: int) -> List[Dict]:
        """列出所有归档会话。"""
        async with async_session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT session_id, title, agent_type, archived_at, created_at
                    FROM archived_conversations
                    WHERE user_id = :uid
                    ORDER BY archived_at DESC
                """),
                {"uid": user_id}
            )
            rows = [dict(r._mapping) for r in result.fetchall()]
            return rows

    async def archive(self, user_id: int, session_id: str) -> bool:
        """归档会话：从 conversations 移到 archived_conversations。"""
        async with async_session_factory() as session:
            async with session.begin():
                # 1. 获取活跃会话信息
                result = await session.execute(
                    text("SELECT * FROM conversations WHERE session_id = :sid AND user_id = :uid"),
                    {"sid": session_id, "uid": user_id}
                )
                conv = result.first()
                if not conv:
                    return False

                conv_dict = dict(conv._mapping)

                # 2. 插入归档表
                await session.execute(
                    text("""
                        INSERT INTO archived_conversations
                            (session_id, user_id, title, agent_type, archived_at, created_at, original_session_id)
                        VALUES
                            (:sid, :user_id, :title, :agent_type, NOW(), :created_at, :original_sid)
                    """),
                    {
                        "sid": conv_dict["session_id"],
                        "user_id": conv_dict["user_id"],
                        "title": conv_dict["title"],
                        "agent_type": conv_dict.get("agent_type"),
                        "created_at": conv_dict["created_at"],
                        "original_sid": conv_dict["session_id"],
                    }
                )

                # 3. 从活跃表删除
                await session.execute(
                    text("DELETE FROM conversations WHERE session_id = :sid"),
                    {"sid": session_id}
                )

            return True

    async def restore(self, user_id: int, session_id: str) -> bool:
        """恢复会话：从 archived_conversations 移到 conversations。"""
        async with async_session_factory() as session:
            async with session.begin():
                # 1. 获取归档会话信息
                result = await session.execute(
                    text("SELECT * FROM archived_conversations WHERE session_id = :sid AND user_id = :uid"),
                    {"sid": session_id, "uid": user_id}
                )
                conv = result.first()
                if not conv:
                    return False

                conv_dict = dict(conv._mapping)

                # 2. 插入活跃表
                await session.execute(
                    text("""
                        INSERT INTO conversations
                            (session_id, user_id, title, agent_type, last_message_at, created_at)
                        VALUES
                            (:sid, :user_id, :title, :agent_type, NOW(), :created_at)
                    """),
                    {
                        "sid": conv_dict["session_id"],
                        "user_id": conv_dict["user_id"],
                        "title": conv_dict["title"],
                        "agent_type": conv_dict.get("agent_type"),
                        "created_at": conv_dict["created_at"],
                    }
                )

                # 3. 从归档表删除
                await session.execute(
                    text("DELETE FROM archived_conversations WHERE session_id = :sid"),
                    {"sid": session_id}
                )

            return True

    async def hard_delete(self, user_id: int, session_id: str) -> bool:
        """硬删除：从 archived_conversations 删除（不可恢复）。"""
        async with async_session_factory() as session:
            async with session.begin():
                # 1. 验证所有权
                owner_check = await session.execute(
                    text("SELECT session_id FROM archived_conversations WHERE session_id = :sid AND user_id = :uid"),
                    {"sid": session_id, "uid": user_id}
                )
                if not owner_check.first():
                    return False

                # 2. 级联删除关联数据
                await session.execute(
                    text("DELETE FROM context_summaries WHERE conversation_id = :sid"),
                    {"sid": session_id}
                )
                await session.execute(
                    text("DELETE FROM ai_session WHERE session_id = :sid"),
                    {"sid": session_id}
                )
                await session.execute(
                    text("DELETE FROM archived_conversations WHERE session_id = :sid"),
                    {"sid": session_id}
                )

            return True

    async def rename(self, user_id: int, session_id: str, new_title: str) -> bool:
        """重命名会话（支持活跃和归档会话）。"""
        async with async_session_factory() as session:
            # 先尝试活跃表
            result = await session.execute(
                text("UPDATE conversations SET title = :title WHERE session_id = :sid AND user_id = :uid"),
                {"title": new_title.strip()[:255], "sid": session_id, "uid": user_id}
            )
            if result.rowcount > 0:
                await session.commit()
                return True

            # 再尝试归档表
            result = await session.execute(
                text("UPDATE archived_conversations SET title = :title WHERE session_id = :sid AND user_id = :uid"),
                {"title": new_title.strip()[:255], "sid": session_id, "uid": user_id}
            )
            await session.commit()
            return result.rowcount > 0

    async def update_last_message(self, session_id: str) -> bool:
        """更新会话的最后消息时间。"""
        async with async_session_factory() as session:
            result = await session.execute(
                text("UPDATE conversations SET last_message_at = NOW() WHERE session_id = :sid"),
                {"sid": session_id}
            )
            await session.commit()
            return result.rowcount > 0

    async def set_active(self, user_id: int, session_id: str) -> bool:
        """设置指定会话为活跃状态，其他会话设为非活跃。"""
        async with async_session_factory() as session:
            async with session.begin():
                # 先把该用户所有会话设为非活跃
                await session.execute(
                    text("UPDATE conversations SET status = 'false' WHERE user_id = :uid"),
                    {"uid": user_id}
                )
                # 再把指定会话设为活跃
                result = await session.execute(
                    text("UPDATE conversations SET status = 'true' WHERE session_id = :sid AND user_id = :uid"),
                    {"sid": session_id, "uid": user_id}
                )
            return result.rowcount > 0

    async def get_by_id(self, session_id: str, table: str = "active") -> Optional[Dict]:
        """根据 ID 获取会话。"""
        async with async_session_factory() as session:
            return await self._get_by_id(session, session_id, table)

    async def _get_by_id(self, session, session_id: str, table: str = "active") -> Optional[Dict]:
        """根据 ID 获取会话。"""
        if table == "active":
            sql = text("""
                SELECT session_id, title, agent_type, last_message_at, created_at
                FROM conversations WHERE session_id = :sid
            """)
        else:
            sql = text("""
                SELECT session_id, title, agent_type, archived_at, created_at
                FROM archived_conversations WHERE session_id = :sid
            """)

        result = await session.execute(sql, {"sid": session_id})
        row = result.first()
        return dict(row._mapping) if row else None
