"""消息编辑与重新生成服务"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update, text
from app.models.session import AiSession
from app.models.schemas import (
    EditMessageRequest,
    RegenerateRequest,
    SwitchBranchRequest,
    BranchResponse
)
from app.repositories.message_tree_repo import MessageTreeRepository
from app.services.session import SessionService
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class EditRegenerateService:
    """消息编辑与重新生成服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.tree_repo = MessageTreeRepository(db)
        self.session_svc = SessionService(db)

    async def edit_message(
        self,
        session_id: str,
        message_id: str,
        new_question: str,
        create_branch: bool = False,
    ) -> BranchResponse:
        """
        编辑用户消息并创建新分支

        两种模式：
        1. create_branch=False (不分支重新回复)
           - 直接UPDATE原消息的question字段
           - 删除该消息之后的所有子消息（包括assistant回复）
           - 重新生成新回复
           - 不改变parent_id和branch_order

        2. create_branch=True (分支重新回复)
           - 创建新分支（保持原消息不变）
           - 新分支的parent_id指向原消息的parent_id
           - 重新生成新回复
           - 切换到新分支
        """
        # 1. 获取当前消息
        stmt = select(AiSession).where(AiSession.id == message_id)
        result = await self.db.execute(stmt)
        current_msg = result.scalar_one_or_none()

        if not current_msg:
            raise ValueError(f"消息不存在: {message_id}")

        if current_msg.session_id != session_id:
            raise ValueError(f"消息不属于此会话: {message_id}")

        # 2. 获取父消息ID（NULL表示根节点，不转换为0）
        parent_id = current_msg.parent_id

        if not create_branch:
            # 不分支模式：直接更新原消息
            return await self._edit_without_branch(
                session_id,
                current_msg,
                new_question,
                parent_id
            )
        else:
            # 分支模式：创建新分支
            return await self._edit_with_branch(
                session_id,
                current_msg,
                new_question,
                parent_id
            )

    async def _edit_without_branch(
        self,
        session_id: str,
        current_msg: AiSession,
        new_question: str,
        parent_id: Optional[int]
    ) -> BranchResponse:
        """不分支重新回复：覆盖原消息"""
        # 1. 更新原消息 content（保留记录本身）
        await self.tree_repo.update_message_content(current_msg.id, new_question)

        # 2. 提交事务：不分支模式下必须手动 commit，否则 UPDATE 全部回滚
        await self.db.commit()

        # 4. 返回新分支信息，供前端触发AI重新生成
        return BranchResponse(
            branch_id=str(current_msg.id),
            parent_id=str(parent_id),
            branch_order=current_msg.branch_order,
            is_active=True,
            history=await self._get_history_for_regenerate(session_id, parent_id),
        )

    async def _edit_with_branch(
        self,
        session_id: str,
        current_msg: AiSession,
        new_question: str,
        parent_id: Optional[int]
    ) -> BranchResponse:
        """分支重新回复：插入新分支（不修改任何旧记录）"""
        # 1. 插入新分支（parent_id = 当前消息的 parent_id，与原消息同级）
        new_msg = await self.tree_repo.create_branch(
            session_id=session_id,
            parent_id=current_msg.parent_id,  # 与原消息同级（兄弟）
            question=new_question,
            is_active=True,
            agent_type=current_msg.agent_type,
        )

        # 2. 更新会话头指针（只改 conversations 表，不改 ai_session）
        await self._update_head_id(session_id, new_msg.id)

        # 3. 提交事务
        await self.db.commit()

        return BranchResponse(
            branch_id=str(new_msg.id),
            parent_id=str(current_msg.parent_id),
            branch_order=new_msg.branch_order,
            is_active=True,
            history=await self._get_history_for_regenerate(session_id, current_msg.parent_id),
        )

    async def regenerate(
        self,
        session_id: str,
        message_id: str,
    ) -> BranchResponse:
        """
        重新生成AI回复（创建兄弟分支，不修改任何旧记录）

        插入新记录：parent_id = 当前消息的 parent_id（同一层级的兄弟）
        """
        # 1. 获取当前消息
        stmt = select(AiSession).where(AiSession.id == message_id)
        result = await self.db.execute(stmt)
        current_msg = result.scalar_one_or_none()

        if not current_msg:
            raise ValueError(f"消息不存在: {message_id}")

        if current_msg.session_id != session_id:
            raise ValueError(f"消息不属于此会话: {message_id}")

        # 2. 插入新的兄弟分支（parent_id = 当前消息的 parent_id）
        new_msg = await self.tree_repo.create_branch(
            session_id=session_id,
            parent_id=current_msg.parent_id,  # 与当前消息同一层级
            question=current_msg.question,     # 复制原问题
            is_active=True,
            agent_type=current_msg.agent_type,
        )

        # 3. 更新会话头指针（只改 conversations 表）
        await self._update_head_id(session_id, new_msg.id)

        # 4. 提交事务
        await self.db.commit()

        return BranchResponse(
            branch_id=str(new_msg.id),
            parent_id=str(current_msg.parent_id),
            branch_order=new_msg.branch_order,
            is_active=True,
            history=await self._get_history_for_regenerate(session_id, current_msg.parent_id),
        )

    async def create_new_branch(
        self,
        session_id: str,
        parent_id: str,
        question: str,
    ) -> BranchResponse:
        """
        新增并排分支：在指定父节点下创建一个全新的兄弟分支

        父节点不变，新分支的 parent_id 指向父节点，与父节点下已有分支并排
        """
        try:
            parent_int = int(parent_id)
        except (ValueError, TypeError):
            raise ValueError(f"无效的父节点ID: {parent_id}")

        parent_msg = await self.tree_repo.get_message_by_id(parent_int)
        if not parent_msg:
            raise ValueError(f"父节点不存在: {parent_id}")

        # 1. 插入新分支（parent_id = 分叉点），成为活跃分支并停用同级兄弟
        new_msg = await self.tree_repo.create_branch(
            session_id=session_id,
            parent_id=parent_int,
            question=question,
            is_active=True,
            agent_type=parent_msg.agent_type,
        )

        # 2. 更新会话头指针（只改 conversations 表，不改 ai_session）
        await self._update_head_id(session_id, new_msg.id)

        # 3. 提交事务
        await self.db.commit()

        return BranchResponse(
            branch_id=str(new_msg.id),
            parent_id=str(parent_int),
            branch_order=new_msg.branch_order,
            is_active=True,
            history=await self._get_history_for_regenerate(session_id, parent_int),
        )

    async def switch_branch(
        self,
        session_id: str,
        target_branch_id: str,
    ) -> BranchResponse:
        """
        切换到指定分支

        更新is_active_branch标记，激活目标分支
        """
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
            raise ValueError(f"目标分支不存在: {target_branch_id}")

        # 2. 执行切换
        success = await self.tree_repo.switch_branch(session_id, target_branch_id)

        if not success:
            raise ValueError("分支切换失败")

        # 3. 构建返回信息
        branch_path = await self.tree_repo.get_branch_path(session_id, target_branch_id)

        return BranchResponse(
            branch_id=target_branch_id,
            parent_id=str(target_msg.parent_id) if target_msg.parent_id is not None else None,
            branch_order=target_msg.branch_order,
            is_active=True,
            history=await self._get_history_for_switch(session_id, branch_path),
            active_head_id=target_branch_id,
        )

    async def delete_branch(
        self,
        session_id: str,
        message_id: str,
    ) -> dict:
        """
        删除分支及其所有后代

        若被删节点是活跃分支，则恢复其同级兄弟中最新的一个为活跃
        若无同级兄弟，则激活父节点
        """
        try:
            msg_id = int(message_id)
        except (ValueError, TypeError):
            raise ValueError(f"无效的消息ID: {message_id}")

        target_msg = await self.tree_repo.get_message_by_id(msg_id)
        if not target_msg:
            raise ValueError(f"消息不存在: {message_id}")
        if target_msg.session_id != session_id:
            raise ValueError(f"消息不属于此会话: {message_id}")

        was_active = target_msg.is_active_branch
        parent_id = target_msg.parent_id

        # 获取同级兄弟（删除前查询，用于恢复活跃状态）
        siblings = await self.tree_repo.get_sibling_branches(session_id, parent_id)
        remaining = [s for s in siblings if s.id != msg_id]

        # 递归删除所有后代
        await self.tree_repo.delete_branch_and_children(msg_id)

        # 删除自身
        await self.db.execute(text("DELETE FROM ai_session WHERE id = :id"), {"id": msg_id})

        # 恢复活跃状态
        new_active_id = None
        if was_active:
            if remaining:
                # 激活同级兄弟中 branch_order 最大的（最新的）
                last_sibling = max(remaining, key=lambda s: s.branch_order or 0)
                await self.db.execute(
                    update(AiSession).where(AiSession.id == last_sibling.id).values(is_active_branch=True)
                )
                new_active_id = last_sibling.id
            elif parent_id is not None:
                # 无兄弟，激活父节点
                await self.db.execute(
                    update(AiSession).where(AiSession.id == parent_id).values(is_active_branch=True)
                )
                new_active_id = parent_id

        # 更新 active_head_id
        if was_active and new_active_id:
            await self._update_head_id(session_id, new_active_id)

        await self.db.commit()

        return {
            "deleted_id": str(msg_id),
            "new_active_id": str(new_active_id) if new_active_id else None,
        }

    async def get_siblings(
        self,
        session_id: str,
        message_id: str
    ) -> list[BranchResponse]:
        """获取所有兄弟分支（用于前端分支选择器）"""
        stmt = select(AiSession).where(AiSession.id == message_id)
        result = await self.db.execute(stmt)
        current_msg = result.scalar_one_or_none()

        if not current_msg:
            return []

        siblings = await self.tree_repo.get_sibling_branches(
            session_id,
            current_msg.parent_id
        )

        return [
            BranchResponse(
                branch_id=str(s.id),
                parent_id=str(s.parent_id if s.parent_id is not None else 0),
                branch_order=s.branch_order,
                is_active=s.is_active_branch,
            )
            for s in siblings
        ]

    async def _get_history_for_regenerate(
        self,
        session_id: str,
        parent_id: Optional[int]
    ) -> list[dict]:
        """获取重新生成所需的历史消息"""
        if parent_id is None:
            return []

        history = await self.tree_repo.get_history_for_context(
            session_id=session_id,
            until_message_id=parent_id
        )

        return history

    async def _get_history_for_switch(
        self,
        session_id: str,
        branch_path: list
    ) -> list[dict]:
        """获取切换分支后的历史消息"""
        history = []
        for msg in branch_path:
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

    async def _update_head_id(self, session_id: str, new_head_id: int):
        """更新会话的激活头指针"""
        from app.models.conversation import Conversation
        from sqlalchemy import update

        stmt = update(Conversation).where(
            Conversation.session_id == session_id
        ).values(active_head_id=new_head_id)
        await self.db.execute(stmt)
