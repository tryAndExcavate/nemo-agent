"""消息树形结构仓储层"""
from typing import List, Dict, Optional
from sqlalchemy import text, select, and_, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.session import AiSession
import logging

logger = logging.getLogger(__name__)


def _to_int(value) -> Optional[int]:
    """将字符串/数字转成int，兼容雪花ID字符串。返回None表示无效。"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class MessageTreeRepository:
    """消息树形结构仓储层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_branch_path(
        self,
        session_id: str,
        message_id
    ) -> List[AiSession]:
        """
        获取从根节点到指定消息的激活路径

        沿着parent_id向上回溯，直到根节点（parent_id=NULL）
        """
        # 兼容字符串雪花ID，转成int
        message_id = _to_int(message_id)
        if message_id is None:
            return []

        stmt = select(AiSession).where(
            and_(
                AiSession.id == message_id,
                AiSession.session_id == session_id
            )
        )
        result = await self.db.execute(stmt)
        current = result.scalar_one_or_none()

        if not current:
            return []

        path = []
        while current:
            path.append(current)
            if current.parent_id is None:
                break
            stmt = select(AiSession).where(AiSession.id == current.parent_id)
            result = await self.db.execute(stmt)
            current = result.scalar_one_or_none()

        return list(reversed(path))

    async def get_active_branch_messages(
        self,
        session_id: str
    ) -> List[AiSession]:
        """
        获取激活分支的所有消息（从根到最新）

        从最新消息开始，沿着is_active_branch=1的节点向上
        """
        # 先找最新的激活消息（叶子节点）
        stmt = (
            select(AiSession)
            .where(
                and_(
                    AiSession.session_id == session_id,
                    AiSession.is_active_branch == True
                )
            )
            .order_by(AiSession.create_time.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        head = result.scalar_one_or_none()

        if not head:
            return []

        # 从叶子节点回溯到根节点
        return await self.get_branch_path(session_id, head.id)

    async def get_sibling_branches(
        self,
        session_id: str,
        parent_id: Optional[int]
    ) -> List[AiSession]:
        """
        获取指定父消息的所有兄弟分支

        查询同一parent_id下的所有消息
        """
        stmt = (
            select(AiSession)
            .where(
                and_(
                    AiSession.session_id == session_id,
                    AiSession.parent_id == parent_id
                )
            )
            .order_by(AiSession.branch_order)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_branch(
        self,
        session_id: str,
        parent_id: Optional[int],
        question: str,
        is_active: bool = True,
        original_message_id: Optional[int] = None,
        agent_type: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> AiSession:
        """
        创建新分支

        插入一条新的AiSession记录，作为parent_id的子节点
        """
        # 获取兄弟分支数量
        stmt = select(func.count(AiSession.id)).where(
            and_(
                AiSession.session_id == session_id,
                AiSession.parent_id == parent_id
            )
        )
        result = await self.db.execute(stmt)
        count = result.scalar() or 0

        new_branch_order = count + 1

        new_msg = AiSession(
            session_id=session_id,
            parent_id=parent_id,
            branch_order=new_branch_order,
            is_active_branch=is_active,
            original_message_id=original_message_id,
            question=question,
            agent_type=agent_type,
            model_id=model_id,
        )
        self.db.add(new_msg)
        await self.db.commit()
        await self.db.refresh(new_msg)

        return new_msg

    async def switch_branch(
        self,
        session_id: str,
        target_branch_id
    ) -> bool:
        """
        切换到指定分支

        1. 找到target_branch_id
        2. 将所有兄弟分支的is_active_branch设为False
        3. 激活目标分支
        4. 更新conversations表的active_head_id
        """
        # 兼容字符串雪花ID，转成int
        target_branch_id = _to_int(target_branch_id)
        if target_branch_id is None:
            return False

        # 1. 获取目标消息
        stmt = select(AiSession).where(
            and_(
                AiSession.id == target_branch_id,
                AiSession.session_id == session_id
            )
        )
        result = await self.db.execute(stmt)
        target_msg = result.scalar_one_or_none()

        if not target_msg:
            return False

        # 2. 获取兄弟分支
        siblings = await self.get_sibling_branches(session_id, target_msg.parent_id)

        # 3. 将所有兄弟分支设为非激活
        async with self.db.begin():
            for sibling in siblings:
                if sibling.id != target_branch_id:
                    stmt = update(AiSession).where(AiSession.id == sibling.id).values(
                        is_active_branch=False
                    )
                    await self.db.execute(stmt)

            # 4. 激活目标分支
            stmt = update(AiSession).where(AiSession.id == target_branch_id).values(
                is_active_branch=True
            )
            await self.db.execute(stmt)

            # 5. 更新conversations表的active_head_id
            from app.models.conversation import Conversation
            stmt = update(Conversation).where(
                Conversation.session_id == session_id
            ).values(active_head_id=target_branch_id)
            await self.db.execute(stmt)

        return True

    async def get_history_for_context(
        self,
        session_id: str,
        until_message_id: int
    ) -> List[dict]:
        """
        获取指定消息之前的历史（用于重建上下文）

        从until_message_id向上回溯，构建完整的历史路径
        """
        path = await self.get_branch_path(session_id, until_message_id)

        history = []
        for msg in path:
            if msg.question:
                history.append({
                    "id": msg.id,
                    "role": "user",
                    "content": msg.question
                })
            if msg.answer:
                history.append({
                    "id": msg.id + 0.5,
                    "role": "assistant",
                    "content": msg.answer
                })

        return history

    async def mark_branch_inactive(self, message_id: int):
        """
        标记分支及其所有子消息为非激活

        从message_id开始，向下查找所有子消息并标记
        """
        stmt = update(AiSession).where(
            AiSession.original_message_id == message_id
        ).values(is_active_branch=False)
        await self.db.execute(stmt)

        # 也标记当前消息
        stmt = update(AiSession).where(AiSession.id == message_id).values(
            is_active_branch=False
        )
        await self.db.execute(stmt)

    async def delete_branch_and_children(self, message_id: int):
        """
        删除分支及其所有子消息

        用于不分支重新回复时，删除该消息之后的所有消息
        """
        # 查找所有子消息
        stmt = select(AiSession).where(
            AiSession.original_message_id == message_id
        )
        result = await self.db.execute(stmt)
        children = result.scalars().all()

        # 删除子消息
        for child in children:
            stmt = text("DELETE FROM ai_session WHERE id = :id")
            await self.db.execute(stmt, {"id": child.id})

        # 删除当前消息
        stmt = text("DELETE FROM ai_session WHERE id = :id")
        await self.db.execute(stmt, {"id": message_id})

    async def update_message_content(self, message_id: int, new_question: str):
        """
        直接更新消息内容

        用于不分支重新回复时，覆盖原消息
        """
        stmt = update(AiSession).where(AiSession.id == message_id).values(
            question=new_question
        )
        await self.db.execute(stmt)

    async def get_message_by_id(self, message_id: int) -> Optional[AiSession]:
        """根据ID获取消息"""
        stmt = select(AiSession).where(AiSession.id == message_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
