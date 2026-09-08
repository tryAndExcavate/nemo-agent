"""消息类型系统。这是 QueryEngineState.messages 字段的类型，
必须满足：
  1. 能被 dataclasses.asdict() 完整序列化（用于 snapshot 持久化）
  2. 能从 dict 精确还原回正确子类型（用于 restore 加载历史会话）
  3. 能被转换成 OpenAI Chat Completions API 需要的格式（用于真正调用模型）
"""
from __future__ import annotations

import time
import uuid as uuid_lib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional, Union


def new_uuid() -> str:
    return str(uuid_lib.uuid4())


# =========================================================
# StreamEvent —— 流式输出事件（与消息类型独立）
# =========================================================

class StreamEventType(str, Enum):
    TEXT_DELTA = "text_delta"
    TOOL_USE_START = "tool_use_start"
    TOOL_RESULT = "tool_result"
    MESSAGE_COMPLETE = "message_complete"
    LLM_INPUT = "llm_input"          # 发送给 LLM 的消息摘要
    LLM_OUTPUT = "llm_output"        # LLM 返回的完整内容摘要
    TURN_LIMIT_EXCEEDED = "turn_limit_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    SYSTEM_INFO = "system_info"
    ERROR = "error"
    DONE = "done"


@dataclass
class StreamEvent:
    type: StreamEventType
    data: Any = None
    timestamp: float = field(default_factory=time.time)


# =========================================================
# Content Block —— AssistantMessage 内部的"块"
# =========================================================

@dataclass
class TextBlock:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass
class ThinkingBlock:
    """思考块（部分兼容模型通过 reasoning_content 承载），仅本地展示，不回传给模型"""
    type: Literal["thinking"] = "thinking"
    thinking: str = ""


@dataclass
class RedactedThinkingBlock:
    """被编辑/加密的思考块，内容不可读，只做占位保留"""
    type: Literal["redacted_thinking"] = "redacted_thinking"
    data: str = ""


@dataclass
class ToolUseBlock:
    type: Literal["tool_use"] = "tool_use"
    id: str = field(default_factory=new_uuid)
    name: str = ""
    input: dict = field(default_factory=dict)


ContentBlock = Union[TextBlock, ThinkingBlock, RedactedThinkingBlock, ToolUseBlock]

_BLOCK_TYPE_MAP: dict[str, type] = {
    "text": TextBlock,
    "thinking": ThinkingBlock,
    "redacted_thinking": RedactedThinkingBlock,
    "tool_use": ToolUseBlock,
}


# =========================================================
# Message —— 六种消息类型
# =========================================================

@dataclass
class UserMessage:
    type: Literal["user"] = "user"
    uuid: str = field(default_factory=new_uuid)
    content: Any = ""  # str，或多模态 blocks 列表


@dataclass
class AssistantMessage:
    """
    注：相比原 TS 定义去掉了 `message: {content}` 这层嵌套，直接摊平为 content。
    如果以后需要保留 API 原始响应用于调试，可以加一个可选字段：
        raw_response: Optional[dict] = None
    现在先不加，避免序列化体积膨胀。
    """
    type: Literal["assistant"] = "assistant"
    uuid: str = field(default_factory=new_uuid)
    content: list[ContentBlock] = field(default_factory=list)
    api_error: Optional[str] = None


@dataclass
class SystemMessage:
    """工具结果 / 错误 / 提示信息"""
    type: Literal["system"] = "system"
    uuid: str = field(default_factory=new_uuid)
    subtype: Literal["tool_result", "error", "info"] = "info"
    content: Any = ""
    tool_use_id: Optional[str] = None
    is_error: bool = False


@dataclass
class AttachmentMessage:
    type: Literal["attachment"] = "attachment"
    uuid: str = field(default_factory=new_uuid)
    attachment_type: Literal["image", "file"] = "file"
    path: Optional[str] = None
    mime_type: Optional[str] = None
    data_base64: Optional[str] = None


@dataclass
class ToolUseSummaryMessage:
    """给 UI 用的折叠摘要，不参与发给模型的上下文"""
    type: Literal["tool_use_summary"] = "tool_use_summary"
    uuid: str = field(default_factory=new_uuid)
    tool_name: str = ""
    summary: str = ""
    tool_use_id: Optional[str] = None


@dataclass
class TombstoneMessage:
    """消息被删除/替换后的占位符，保留 uuid 引用链完整性"""
    type: Literal["tombstone"] = "tombstone"
    uuid: str = field(default_factory=new_uuid)
    original_type: Optional[str] = None


Message = Union[
    UserMessage,
    AssistantMessage,
    SystemMessage,
    AttachmentMessage,
    ToolUseSummaryMessage,
    TombstoneMessage,
]

_MESSAGE_TYPE_MAP: dict[str, type] = {
    "user": UserMessage,
    "assistant": AssistantMessage,
    "system": SystemMessage,
    "attachment": AttachmentMessage,
    "tool_use_summary": ToolUseSummaryMessage,
    "tombstone": TombstoneMessage,
}


# =========================================================
# 序列化 / 反序列化
# 专门配合 QueryEngineState.snapshot() / restore() 使用
# =========================================================

def message_to_dict(msg: Message) -> dict:
    """
    不用 dataclasses.asdict()，手写转换——
    原因：asdict() 对 Union 类型字段（content: list[ContentBlock]）
    虽然能递归转换，但反序列化时无法知道该还原成哪个 Block 子类，
    所以序列化和反序列化必须配对手写，不能偷懒用自动化工具。
    """
    if isinstance(msg, AssistantMessage):
        return {
            "type": msg.type,
            "uuid": msg.uuid,
            "content": [block_to_dict(b) for b in msg.content],
            "api_error": msg.api_error,
        }
    # 其余消息类型字段都是基础类型，dataclass 自带的 __dict__ 就够用
    return dict(vars(msg))


def dict_to_message(data: dict) -> Message:
    cls = _MESSAGE_TYPE_MAP.get(data["type"])
    if cls is None:
        raise ValueError(f"未知的消息类型: {data['type']}")

    if cls is AssistantMessage:
        blocks = [dict_to_block(b) for b in data.get("content", [])]
        return AssistantMessage(
            uuid=data["uuid"],
            content=blocks,
            api_error=data.get("api_error"),
        )
    return cls(**{k: v for k, v in data.items() if k != "type"})


def block_to_dict(block: ContentBlock) -> dict:
    return dict(vars(block))


def dict_to_block(data: dict) -> ContentBlock:
    cls = _BLOCK_TYPE_MAP.get(data["type"])
    if cls is None:
        raise ValueError(f"未知的 block 类型: {data['type']}")
    return cls(**{k: v for k, v in data.items() if k != "type"})


def messages_to_list(messages: list[Message]) -> list[dict]:
    return [message_to_dict(m) for m in messages]


def list_to_messages(data: list[dict]) -> list[Message]:
    return [dict_to_message(d) for d in data]


# =========================================================
# ProcessedInput —— 预处理阶段的输出
# =========================================================

@dataclass
class ProcessedInput:
    text: str
    slash_command: Optional[str] = None
    slash_command_args: Optional[str] = None
    attachments: list[dict] = field(default_factory=list)
    injected_memory: Optional[str] = None
    is_command_only: bool = False
