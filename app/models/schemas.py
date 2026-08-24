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
    TYPE_USAGE = "usage"      # 新增：Token 消耗统计事件


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


# --- 分支管理 Request/Response schemas ---

class EditMessageRequest(BaseModel):
    """编辑用户消息请求"""
    message_id: str  # 雪花ID用字符串传递，避免JS精度丢失
    new_question: str
    create_branch: bool = True  # True=分支重新回复, False=不分支重新回复


class RegenerateRequest(BaseModel):
    """重新生成AI回复请求"""
    message_id: str  # 雪花ID用字符串


class SwitchBranchRequest(BaseModel):
    """切换分支请求"""
    target_branch_id: str  # 雪花ID用字符串


class BranchResponse(BaseModel):
    """分支响应"""
    branch_id: str  # 雪花ID用字符串
    parent_id: Optional[str] = None  # NULL=根节点
    branch_order: int = 1
    is_active: bool = True
    history: list[dict] = []
    active_head_id: Optional[str] = None


class SiblingsResponse(BaseModel):
    """兄弟分支响应"""
    siblings: list[BranchResponse]
