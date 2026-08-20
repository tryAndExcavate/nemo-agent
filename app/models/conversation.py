"""会话 ORM 模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Conversation(Base):
    """活跃会话表，存储当前活跃的会话。"""
    __tablename__ = "conversations"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新对话")
    agent_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="false")  # true=最后活跃, false=非活跃
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_conversations_user_status', 'user_id', 'status', 'last_message_at'),
    )


class ArchivedConversation(Base):
    """归档会话表，存储归档的会话。"""
    __tablename__ = "archived_conversations"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime)
    original_session_id: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        Index('ix_archived_conversations_user', 'user_id', 'archived_at'),
    )
