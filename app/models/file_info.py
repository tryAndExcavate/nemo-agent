from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, func, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AiFileInfo(Base):
    __tablename__ = "ai_file_info"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    minio_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), default="PENDING")
    embed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
