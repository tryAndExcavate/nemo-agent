from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AiSession(Base):
    __tablename__ = "ai_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="生成本轮回答的模型ID")
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    first_response_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_response_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    token_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="本轮问答的token总数")
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    fileid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recommend: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 树形结构字段
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True, comment="父轮次ID")
    branch_order: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, comment="分支顺序")
    is_active_branch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否激活分支")
    original_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True, comment="原始轮次ID（用于追溯分支来源）")
