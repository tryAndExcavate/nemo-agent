from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AiSession(Base):
    __tablename__ = "ai_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    first_response_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_response_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    fileid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recommend: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
