"""Context 上下文维护窗口。

管理 QueryEngine 每次 API 调用所需的完整上下文，
包括系统提示、对话历史、工具定义和工具调用结果。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.models.query_engine import (
    AssistantMessage,
    Message,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    UserMessage,
)
from app.tools.base import Tool


# 粗略估算：1 个中文字符 ≈ 2 tokens，1 个英文单词 ≈ 1.3 tokens
# 这里用字符数 / 2 作为 token 估算
_CHARS_PER_TOKEN = 2


@dataclass
class ContextUsage:
    """按类型分类的上下文使用量"""
    system_prompt_tokens: int = 0
    history_tokens: int = 0
    tool_definitions_tokens: int = 0
    tool_results_tokens: int = 0
    current_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (self.system_prompt_tokens + self.history_tokens +
                self.tool_definitions_tokens + self.tool_results_tokens +
                self.current_input_tokens)

    def to_dict(self) -> dict:
        return {
            "system_prompt": self.system_prompt_tokens,
            "history": self.history_tokens,
            "tool_definitions": self.tool_definitions_tokens,
            "tool_results": self.tool_results_tokens,
            "current_input": self.current_input_tokens,
            "total": self.total_tokens,
        }


class Context:
    """QueryEngine 的上下文维护窗口。

    职责：
    1. 分类存储不同类型的上下文（系统提示、历史消息、工具定义）
    2. 提供 to_api_messages() 生成 OpenAI API 格式的消息列表
    3. 提供 estimate_usage() 按类别估算 token 使用量
    """

    def __init__(
        self,
        system_prompt: str = "",
        tools: list[Tool] | None = None,
        messages: list[Message] | None = None,
    ):
        self.system_prompt: str = system_prompt
        self.tools: list[Tool] = tools or []
        self.messages: list[Message] = list(messages) if messages else []

        # 预计算工具 schema（避免每次调用重复转换）
        self._tool_schemas: list[dict] = [t.to_openai_schema() for t in self.tools]

    # =====================================================
    # 消息管理
    # =====================================================

    def add_message(self, msg: Message) -> None:
        """追加一条消息到上下文"""
        self.messages.append(msg)

    def get_messages(self) -> list[Message]:
        """获取当前所有消息（只读视图）"""
        return list(self.messages)

    def reset(self, messages: list[Message]) -> None:
        """重置消息列表（用于新一轮 submit_message）"""
        self.messages = list(messages)

    def clone_messages(self) -> list[Message]:
        """克隆当前消息列表，用于 query() 循环中独立操作"""
        return list(self.messages)

    # =====================================================
    # 生成 API 格式
    # =====================================================

    def to_api_messages(self) -> list[dict]:
        """将完整上下文转换为 OpenAI Chat Completions API 格式。

        返回格式:
        [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "...", "tool_calls": [...]},
            {"role": "tool", "tool_call_id": "...", "content": "..."},
            ...
        ]

        注意：Qwen 等模型要求 system 消息必须在最前面。
        本方法将非 tool_result 的 SystemMessage 提升到消息列表开头，
        保证 [system, system, ..., user, assistant, tool, ...] 的顺序。
        """
        api_messages: list[dict] = []
        pending_system: list[dict] = []  # 需要提升到开头的 system 消息

        # 1. 系统提示（固定在最前）
        if self.system_prompt:
            api_messages.append({"role": "system", "content": self.system_prompt})

        # 2. 对话历史
        for m in self.messages:
            if isinstance(m, UserMessage):
                api_messages.append({"role": "user", "content": m.content})

            elif isinstance(m, AssistantMessage):
                text_parts = [b.text for b in m.content if isinstance(b, TextBlock)]
                text_content = "\n".join(text_parts) if text_parts else None

                tool_calls = []
                for b in m.content:
                    if isinstance(b, ToolUseBlock):
                        tool_calls.append({
                            "id": b.id,
                            "type": "function",
                            "function": {
                                "name": b.name,
                                "arguments": json.dumps(b.input, ensure_ascii=False),
                            },
                        })

                d: dict = {"role": "assistant", "content": text_content or ""}
                if tool_calls:
                    d["tool_calls"] = tool_calls
                api_messages.append(d)

            elif isinstance(m, SystemMessage):
                if m.subtype == "tool_result" and m.tool_use_id:
                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": m.tool_use_id,
                        "content": m.content,
                    })
                else:
                    # 非 tool_result 的 SystemMessage（如压缩摘要）→ 暂存，稍后提升到开头
                    pending_system.append({"role": "system", "content": m.content})

        # 3. 将暂存的 system 消息插入到 api_messages 最前面（系统提示之后）
        if pending_system:
            api_messages[1:1] = pending_system

        return api_messages

    def get_tool_schemas(self) -> list[dict]:
        """获取工具定义（OpenAI format）"""
        return self._tool_schemas

    # =====================================================
    # 使用量估算
    # =====================================================

    def estimate_usage(self) -> ContextUsage:
        """估算当前上下文中各类内容的 token 使用量。

        Returns:
            ContextUsage: 按类型分类的 token 估算值
        """
        usage = ContextUsage()

        # 1. 系统提示
        usage.system_prompt_tokens = self._estimate_tokens(self.system_prompt)

        # 2. 工具定义
        tools_text = json.dumps(self._tool_schemas, ensure_ascii=False)
        usage.tool_definitions_tokens = self._estimate_tokens(tools_text)

        # 3. 对话历史（区分用户输入、助手回复、工具结果）
        for m in self.messages:
            if isinstance(m, UserMessage):
                text = m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)
                usage.history_tokens += self._estimate_tokens(text)

            elif isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, TextBlock):
                        usage.history_tokens += self._estimate_tokens(b.text)
                    elif isinstance(b, ToolUseBlock):
                        usage.history_tokens += self._estimate_tokens(
                            json.dumps(b.input, ensure_ascii=False)
                        )

            elif isinstance(m, SystemMessage):
                text = str(m.content)
                if m.subtype == "tool_result":
                    usage.tool_results_tokens += self._estimate_tokens(text)
                else:
                    usage.history_tokens += self._estimate_tokens(text)

        return usage

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算文本的 token 数（中文字符 / 2）"""
        return max(1, len(text) // _CHARS_PER_TOKEN) if text else 0
