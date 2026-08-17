from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AiPptInst(Base):
    __tablename__ = "ai_ppt_inst"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    template_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(32), default="INIT", index=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    ppt_schema: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AiPptTemplate(Base):
    __tablename__ = "ai_ppt_template"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_schema: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    style_tags: Mapped[str | None] = mapped_column(String(200), nullable=True)
    slide_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
