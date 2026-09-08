"""子智能体专用记忆检索工具 — 两组，语义显式区分。

- current memory：主 Agent 当前运行期已经形成的记忆（LiveMemoryReadOnlyView）
- historical memory：主 Agent 历史 JSONL 持久化记录（ConversationHistoryReader）

工具 schema 里没有任何 conversation_id 字段——刻意设计，安全边界不可出现在模型可控参数里。
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from app.tools.base import ToolUseContext


def _consume_detail_budget(context: "ToolUseContext") -> None:
    """每次调 get_*_detail 都消耗一次预算，超限抛异常中断。"""
    state = context.extras.get("execution_state") if hasattr(context, "extras") else None
    if state is None:
        return
    state.detail_reads += 1
    budget = state.budget
    if hasattr(budget, "max_memory_detail_reads") and state.detail_reads > budget.max_memory_detail_reads:
        raise PermissionError("memory detail read budget exceeded")


# =========================================================
# current / live memory 工具
# =========================================================

class ListCurrentMemoryTool(Tool):
    name = "list_current_memory"
    description = "列出主 Agent【当前这次运行】已经积累的记忆目录（仅摘要）。"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, input: dict, context: "ToolUseContext") -> ToolResult:
        view = context.extras.get("memory_retrieval").live_memory if hasattr(context, "extras") else None
        if view is None:
            return ToolResult(output="当前运行期暂无 live memory（未启用）")
        index = view.list_index()
        if not index:
            return ToolResult(output="当前运行期暂无记忆")
        lines = [f"[{c['id']}] (turn:{c['turn']}, {c['role']}) {c['summary']}" for c in index]
        return ToolResult(output="\n".join(lines))


class SearchCurrentMemoryTool(Tool):
    name = "search_current_memory"
    description = "在【当前运行期】记忆中按关键词搜索。"
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    async def execute(self, input: dict, context: "ToolUseContext") -> ToolResult:
        view = context.extras.get("memory_retrieval").live_memory if hasattr(context, "extras") else None
        if view is None:
            return ToolResult(output="当前运行期暂无 live memory（未启用）")
        results = view.search(input["query"])
        if not results:
            return ToolResult(output="当前运行期未找到匹配内容")
        lines = [f"[{r['id']}] (turn:{r['turn']}, {r['role']}) {r['summary']}" for r in results]
        return ToolResult(output="\n".join(lines))


class GetCurrentMemoryDetailTool(Tool):
    name = "get_current_memory_detail"
    description = "获取【当前运行期】某条记忆的完整内容。chunk_id 必须来自之前工具返回的真实 ID。"
    input_schema = {
        "type": "object",
        "properties": {"chunk_id": {"type": "string"}},
        "required": ["chunk_id"],
    }

    async def execute(self, input: dict, context: "ToolUseContext") -> ToolResult:
        _consume_detail_budget(context)
        view = context.extras.get("memory_retrieval").live_memory if hasattr(context, "extras") else None
        if view is None:
            return ToolResult(output="当前运行期暂无 live memory（未启用）")
        chunk = view.get_detail(input["chunk_id"])
        if chunk is None:
            return ToolResult(output="未找到该记忆片段", is_error=True)
        return ToolResult(output=f"[{chunk.role}] {chunk.full_text}")


# =========================================================
# historical / jsonl memory 工具
# =========================================================

class ListHistoryIndexTool(Tool):
    name = "list_history_index"
    description = "列出主 Agent【以往持久化历史】的目录（仅摘要）。"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, input: dict, context: "ToolUseContext") -> ToolResult:
        reader = context.extras.get("memory_retrieval").history if hasattr(context, "extras") else None
        if reader is None:
            return ToolResult(output="历史记录访问未启用（未绑定会话）")
        index = reader.list_index()
        if not index:
            return ToolResult(output="历史记录中暂无内容")
        lines = [f"[{c['id']}] (turn:{c['turn']}, {c['role']}) {c['content']}" for c in index]
        return ToolResult(output="\n".join(lines))


class SearchHistoryTool(Tool):
    name = "search_history"
    description = "在【以往持久化历史】中按关键词搜索。"
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    async def execute(self, input: dict, context: "ToolUseContext") -> ToolResult:
        reader = context.extras.get("memory_retrieval").history if hasattr(context, "extras") else None
        if reader is None:
            return ToolResult(output="历史记录访问未启用（未绑定会话）")
        results = reader.search(input["query"])
        if not results:
            return ToolResult(output="历史记录中未找到匹配内容")
        lines = [f"[{r['id']}] (turn:{r['turn']}, {r['role']}) {r['content']}" for r in results]
        return ToolResult(output="\n".join(lines))


class GetHistoryDetailTool(Tool):
    name = "get_history_detail"
    description = "获取【历史记录】中某条的完整内容。record_id 必须来自之前工具返回的真实 ID。"
    input_schema = {
        "type": "object",
        "properties": {"record_id": {"type": "string"}},
        "required": ["record_id"],
    }

    async def execute(self, input: dict, context: "ToolUseContext") -> ToolResult:
        _consume_detail_budget(context)
        reader = context.extras.get("memory_retrieval").history if hasattr(context, "extras") else None
        if reader is None:
            return ToolResult(output="历史记录访问未启用（未绑定会话）")
        record = reader.get_detail(input["record_id"])
        if record is None:
            return ToolResult(output="未找到该历史记录", is_error=True)
        return ToolResult(output=f"[{record.role}] {record.full_text}")
