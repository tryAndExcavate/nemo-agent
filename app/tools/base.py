"""工具基类与公共类型。

所有工具继承 Tool 基类，QueryEngine 通过统一接口发现、调用、序列化工具。
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.query_engine import Message


# =========================================================
# ToolResult —— 工具执行结果
# =========================================================

@dataclass
class ToolResult:
    """工具执行结果，output 会被塞进 SystemMessage(subtype='tool_result')"""
    output: Any
    is_error: bool = False


# =========================================================
# ToolUseContext —— 工具执行时的上下文
# =========================================================

@dataclass
class ToolUseContext:
    """每次工具调用时传入的上下文，封装 cwd、中断信号、消息历史"""
    cwd: str
    abort_event: asyncio.Event = field(default_factory=asyncio.Event)
    messages: tuple = ()
    extras: dict = field(default_factory=dict)

    def is_aborted(self) -> bool:
        return self.abort_event.is_set()


# =========================================================
# Tool —— 工具抽象基类
# =========================================================

class Tool(ABC):
    """
    每个工具都继承这个基类。三个抽象属性 + 一个抽象方法，
    对应 TS 版本里最核心的四个字段（name/description/inputSchema/execute）。
    """

    name: str
    description: str
    input_schema: dict  # JSON Schema，双重用途：参数校验 + 给模型看的文档

    @abstractmethod
    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        """所有工具执行都是异步的，支持 I/O、网络请求等"""
        ...

    def needs_permission(self, input: dict) -> bool:
        """
        默认不需要用户确认。危险操作（写文件、执行命令）的子类应覆盖此方法，
        返回 True 触发上层的 canUseTool 权限检查。
        """
        return False

    def render_result(self, result: ToolResult) -> str:
        """
        CLI/日志场景下的简单文本渲染，替代原设计里的 renderToolUse (React JSX)。
        以后如果做 Web UI，可以在这里返回结构化 dict 而不是字符串。
        """
        return str(result.output)

    def to_openai_schema(self) -> dict:
        """转换成 OpenAI function calling 需要的格式，供 QueryEngine 调用时使用"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
