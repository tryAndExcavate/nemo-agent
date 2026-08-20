"""上下文摘要 ORM 模型。"""
from datetime import datetime
from sqlalchemy import BigInteger, Text, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ContextSummary(Base):
    """上下文摘要表，存储对话的历史摘要。"""
    __tablename__ = "context_summaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    covered_up_to_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    summary_model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
