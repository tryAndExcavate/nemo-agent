"""DispatchAgentTool — 主 Agent 调用子智能体的唯一入口。

硬校验深度/环检测，按需组装双通道记忆只读视图。
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

from app.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from app.tools.base import ToolUseContext

logger = logging.getLogger(__name__)


class DispatchAgentTool(Tool):
    name = "dispatch_agent"
    description = "将任务委派给专门的子智能体处理。"

    def __init__(self, allowed_subagents: Optional[set[str]] = None):
        self._allowed = allowed_subagents
        # 延迟构建 schema 和 description（依赖 registry）
        self._schema: Optional[dict] = None
        self._desc: Optional[str] = None

    def _candidates(self):
        from app.subagent.registry import list_available
        all_defs = list_available()
        if self._allowed is None:
            return all_defs
        return [d for d in all_defs if d.name in self._allowed]

    @property
    def input_schema(self) -> dict:
        if self._schema is None:
            names = [d.name for d in self._candidates()] or ["none"]
            self._schema = {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "enum": names},
                    "task": {"type": "string", "description": "要委派给子智能体的任务描述"},
                },
                "required": ["agent_name", "task"],
            }
        return self._schema

    @property
    def description(self) -> str:
        if self._desc is None:
            available = self._candidates()
            if not available:
                self._desc = "调用一个专门的子智能体处理特定任务（当前无可用子智能体）。"
            else:
                lines = ["将任务委派给专门的子智能体处理。\n可用的子智能体："]
                lines += [f"- {d.name}: {d.description}" for d in available]
                self._desc = "\n".join(lines)
        return self._desc

    async def execute(self, input: dict, context: "ToolUseContext") -> ToolResult:
        from app.subagent.registry import get as get_definition
        from app.memory.retrieval_context import MemoryRetrievalContext
        from app.memory.live_view import LiveMemoryReadOnlyView, LiveMemoryStore
        from app.memory.history_reader import ConversationHistoryReader
        from app.subagent.runner import SubAgentRunner
        from pathlib import Path

        agent_name = input["agent_name"]
        task_text = input["task"]

        definition = get_definition(agent_name)
        if definition is None or (self._allowed is not None and definition.name not in self._allowed):
            return ToolResult(output=f"未找到或无权调用子智能体: {agent_name}", is_error=True)

        # 获取执行上下文
        exec_ctx = (context.extras.get("execution_context") if hasattr(context, "extras") else None)
        if exec_ctx is None:
            return ToolResult(output="执行上下文未初始化（无法派遣）", is_error=True)

        try:
            child_ctx = exec_ctx.derive(
                next_agent=definition.name,
                next_max_depth=definition.budget.max_dispatch_depth,
            )
        except PermissionError as e:
            return ToolResult(output=f"派遣被拒绝: {e}", is_error=True)

        # 按需组装双通道记忆（仅声明需要才给）
        retrieval = None
        if definition.needs_live_memory or definition.needs_history_memory:
            live_view = None
            history_reader = None

            if definition.needs_live_memory:
                live_store = context.extras.get("live_memory_store") if hasattr(context, "extras") else None
                if live_store is not None:
                    live_view = LiveMemoryReadOnlyView(live_store)

            if definition.needs_history_memory:
                sessions_root = Path(context.extras.get("sessions_root", ".sessions")) if hasattr(context, "extras") else Path(".sessions")
                history_reader = ConversationHistoryReader(sessions_root, exec_ctx.root_conversation_id)

            retrieval = MemoryRetrievalContext(
                live_memory=live_view,
                history=history_reader,
            )

        # 获取 LLM 客户端和模型
        parent_config = (context.extras.get("parent_config") if hasattr(context, "extras") else None)
        llm_client = parent_config.llm_client if parent_config else None
        parent_model = parent_config.model if parent_config else ""

        if llm_client is None:
            return ToolResult(output="LLM 客户端未初始化，无法派遣子智能体", is_error=True)

        # 检查是否有子 Agent 模型槽位
        sub_agent_model = None
        try:
            from llm_core.store import ConfigStore
            sub_model_id = ConfigStore.get_active_sub_agent_model_id()
            if sub_model_id:
                sub_model_cfg = ConfigStore.get_basic(sub_model_id)
                sub_agent_model = sub_model_cfg.get("model_name")
        except Exception:
            pass

        runner = SubAgentRunner(
            llm_client=llm_client,
            parent_model=parent_model,
            cwd=context.cwd,
            sub_agent_model=sub_agent_model,
        )

        result = await runner.run(
            definition=definition,
            task=task_text,
            execution_context=child_ctx,
            memory_retrieval=retrieval,
            parent_config=parent_config,
        )

        return ToolResult(output=result.text, is_error=result.is_error)
