from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Any
from datetime import datetime


def _to_camel(s: str) -> str:
    """snake_case -> camelCase，用于 PPT schema 与 render_ppt.py 契约对齐。"""
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])



# --- BaseResult equivalent ---
class BaseResult(BaseModel):
    code: int = 200
    message: str = ""
    data: Any = None

    @staticmethod
    def success(data: Any = None, message: str = "") -> dict:
        return {"code": 200, "message": message, "data": data}

    @staticmethod
    def error(message: str = "服务器错误", code: int = 500) -> dict:
        return {"code": code, "message": message, "data": None}


# --- Agent SSE Response types ---
class AgentResponse:
    TYPE_TEXT = "text"
    TYPE_THINKING = "thinking"
    TYPE_REFERENCE = "reference"
    TYPE_ERROR = "error"
    TYPE_RECOMMEND = "recommend"


# --- Request schemas ---
class SaveQuestionRequest(BaseModel):
    session_id: str
    question: str
    fileid: Optional[str] = None
    first_response_time: Optional[int] = None


class UpdateAnswerRequest(BaseModel):
    id: int
    answer: str
    thinking: str = ""
    tools: str = ""
    reference: str = ""
    recommend: Optional[str] = None
    first_response_time: Optional[int] = None
    total_response_time: Optional[int] = None


# --- VO schemas ---
class MessageVO(BaseModel):
    id: int
    question: Optional[str] = None
    answer: Optional[str] = None
    thinking: Optional[str] = None
    tools: Optional[str] = None
    reference: Optional[str] = None
    create_time: Optional[datetime] = None
    fileid: Optional[str] = None
    recommend: Optional[str] = None


class SessionDetailVO(BaseModel):
    conversation_id: str
    agent_type: Optional[str] = None
    fileid: Optional[str] = None
    messages: list[MessageVO] = []


class SessionListVO(BaseModel):
    id: int
    session_id: str
    agent_type: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    create_time: Optional[datetime] = None


class PageResult(BaseModel):
    page_num: int
    page_size: int
    total: int
    records: list[Any] = []


# --- Internal records ---
class SearchResult(BaseModel):
    url: str
    title: str
    content: str


class PlanTask(BaseModel):
    id: Optional[str] = None
    instruction: str
    order: int


class TaskResult(BaseModel):
    task_id: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


class CritiqueResult(BaseModel):
    passed: bool
    feedback: str = ""


class FileInfo(BaseModel):
    file_id: str
    file_name: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    minio_path: Optional[str] = None
    extracted_text: Optional[str] = None
    status: Optional[str] = "PENDING"
    conversation_id: Optional[str] = None


class PptIntentResult(BaseModel):
    intent: str  # CREATE_PPT, MODIFY_PPT, RESUME_PPT
    reason: str = ""


class TemplateSelectionResult(BaseModel):
    template_code: str
    reason: str = ""


class FieldData(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    type: str  # text, image, background
    content: str
    font_limit: Optional[int] = None
    url: str = ""


class Slide(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    page_type: str
    page_desc: str
    template_page_index: int
    data: dict[str, FieldData]


class PptSchema(BaseModel):
    slides: list[Slide]
