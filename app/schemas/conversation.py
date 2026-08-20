"""会话 Pydantic 模型。"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ConversationOut(BaseModel):
    """会话输出模型。"""
    session_id: str
    title: str
    agent_type: Optional[str] = None
    status: Optional[str] = None  # true=活跃, false=非活跃
    last_message_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    created_at: datetime


class ConversationListResponse(BaseModel):
    """会话列表响应。"""
    items: List[ConversationOut]
    next_cursor: Optional[str] = None
    has_more: bool = False


class CreateConversationRequest(BaseModel):
    """创建会话请求。"""
    session_id: str = Field(..., min_length=1, max_length=255)
    title: str = Field("新对话", min_length=1, max_length=255)
    agent_type: Optional[str] = Field(None, max_length=50)
    initial_message: Optional[str] = Field(None, max_length=2000)  # 用户的初始消息，用于生成标题


class RenameConversationRequest(BaseModel):
    """重命名会话请求。"""
    title: str


class ConversationActionResponse(BaseModel):
    """会话操作响应。"""
    status: str
    message: Optional[str] = None
