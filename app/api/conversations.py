"""会话管理 FastAPI 路由。"""
import logging
from fastapi import APIRouter, HTTPException, Query
from app.schemas.conversation import (
    ConversationListResponse, CreateConversationRequest,
    RenameConversationRequest, ConversationActionResponse
)
from app.repositories.conversation_repo import ConversationRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_repo() -> ConversationRepository:
    """获取会话仓库实例。"""
    return ConversationRepository()


async def generate_title_from_message(message: str) -> str:
    """调用总结基座模型生成标题（异步，失败则返回默认值）。"""
    try:
        from llm_core.store import ConfigStore
        from llm_core.manager import ModelManager
        from llm_core.base import ChatRequest, ChatMessage

        summary_model_id = ConfigStore.get_active_summary_model_id()
        if not summary_model_id:
            return None

        adapter = ModelManager.get_adapter(summary_model_id)
        if not adapter:
            return None

        # 构建提示词，让模型生成简短标题
        prompt_messages = [
            ChatMessage(role="system", content="你是一个专业的文本摘要助手。请根据用户的消息生成一个简短的标题（10-20字以内），只返回标题，不要任何解释或格式。"),
            ChatMessage(role="user", content=f"请为以下消息生成标题：\n\n{message[:500]}")
        ]
        request = ChatRequest(messages=prompt_messages, temperature=0.5, max_tokens=50)
        response = await adapter.chat(request)

        # 提取标题
        title = response.content.strip()
        # 移除可能的引号或标点
        title = title.strip('"').strip("'").strip("。").strip("，")
        return title[:255] if title else None

    except Exception as e:
        logger.warning(f"生成标题失败: {e}")
        return None


@router.get("/active", response_model=ConversationListResponse)
async def list_active_conversations(
    user_id: int = Query(1),
):
    """获取所有活跃会话列表。"""
    repo = get_repo()
    items = await repo.list_active(user_id)
    return {"items": items, "next_cursor": None, "has_more": False}


@router.get("/archived", response_model=ConversationListResponse)
async def list_archived_conversations(
    user_id: int = Query(1),
):
    """获取所有归档会话列表。"""
    repo = get_repo()
    items = await repo.list_archived(user_id)
    print(items)
    return {"items": items, "next_cursor": None, "has_more": False}


@router.post("", response_model=dict)
async def create_conversation(
    req: CreateConversationRequest,
    user_id: int = Query(1),
):
    """创建新活跃会话。"""
    repo = get_repo()

    # 如果提供了初始消息，尝试调用总结模型生成标题
    title = req.title
    if req.initial_message and len(req.initial_message.strip()) > 0:
        generated_title = await generate_title_from_message(req.initial_message)
        if generated_title:
            title = generated_title
            logger.info(f"已为会话生成标题: {title}")

    conv = await repo.create(user_id, req.session_id, title, req.agent_type)
    return conv


@router.post("/{session_id}/generate-title", response_model=dict)
async def generate_title_for_conversation(
    session_id: str,
    body: dict,
    user_id: int = Query(1),
):
    """根据用户消息异步生成会话标题。"""
    message = body.get("message", "")
    if not message or len(message.strip()) == 0:
        return {"title": None}

    title = await generate_title_from_message(message)
    if title:
        # 更新会话标题
        repo = get_repo()
        await repo.rename(user_id, session_id, title)
        return {"title": title}

    return {"title": None}


@router.patch("/{session_id}/rename", response_model=ConversationActionResponse)
async def rename_conversation(
    session_id: str,
    req: RenameConversationRequest,
    user_id: int = Query(1),
):
    """重命名会话。"""
    title = req.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    repo = get_repo()
    ok = await repo.rename(user_id, session_id, title)
    if not ok:
        raise HTTPException(404, "会话不存在或无权限")
    return {"status": "ok"}


@router.post("/{session_id}/activate", response_model=ConversationActionResponse)
async def activate_conversation(
    session_id: str,
    user_id: int = Query(1),
):
    """设置会话为活跃状态（其他会话设为非活跃）。"""
    repo = get_repo()
    ok = await repo.set_active(user_id, session_id)
    if not ok:
        raise HTTPException(404, "会话不存在或无权限")
    return {"status": "ok", "message": "已激活"}


@router.patch("/{session_id}/archive", response_model=ConversationActionResponse)
async def archive_conversation(
    session_id: str,
    user_id: int = Query(1),
):
    """归档会话（从活跃移到归档）。"""
    repo = get_repo()
    ok = await repo.archive(user_id, session_id)
    if not ok:
        raise HTTPException(404, "会话不存在或无权限")
    return {"status": "ok", "message": "已归档"}


@router.patch("/{session_id}/restore", response_model=ConversationActionResponse)
async def restore_conversation(
    session_id: str,
    user_id: int = Query(1),
):
    """恢复会话（从归档移到活跃）。"""
    repo = get_repo()
    ok = await repo.restore(user_id, session_id)
    if not ok:
        raise HTTPException(404, "会话不存在或无权限")
    return {"status": "ok", "message": "已恢复"}


@router.delete("/{session_id}", response_model=ConversationActionResponse)
async def delete_conversation(
    session_id: str,
    user_id: int = Query(1),
):
    """硬删除会话（从归档表删除，不可恢复）。"""
    repo = get_repo()
    ok = await repo.hard_delete(user_id, session_id)
    if not ok:
        raise HTTPException(404, "会话不存在或无权限")
    return {"status": "ok", "message": "已永久删除"}
