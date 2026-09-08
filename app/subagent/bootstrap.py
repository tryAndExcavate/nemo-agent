"""子智能体注册启动模块 — 在应用启动时调用，注册所有可用子智能体。

当前注册：
- memory-retriever：从当前运行期记忆 + 历史 JSONL 中检索信息
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_registered = False


def register_all_subagents() -> None:
    """注册所有子智能体（幂等，多次调用不会重复注册）。"""
    global _registered
    if _registered:
        return
    _registered = True

    _register_memory_retriever()
    logger.info("[SubAgent] 所有子智能体注册完成")


def _register_memory_retriever() -> None:
    from app.subagent.registry import register
    from app.subagent.definition import SubAgentDefinition
    from app.subagent.policy import ExecutionBudget
    from app.tools.memory_agent_tools import (
        ListCurrentMemoryTool,
        SearchCurrentMemoryTool,
        GetCurrentMemoryDetailTool,
        ListHistoryIndexTool,
        SearchHistoryTool,
        GetHistoryDetailTool,
    )

    register(SubAgentDefinition(
        name="memory-retriever",
        description=(
            "从【当前运行期记忆】和【以往持久化历史记录】中检索相关信息。"
            "当需要参考之前讨论过、但不在当前上下文中的内容时使用。"
        ),
        system_prompt=(
            "你是主 Agent 的隔离记忆检索子智能体。\n"
            "你拥有两个只读信息来源：\n"
            "1. current memory：主 Agent 当前运行阶段已经形成的记忆。\n"
            "2. historical memory：主 Agent 当前 conversation 在以往轮次中持久化的历史记录。\n"
            "根据任务自主判断查哪个来源，必要时交叉验证两者。\n"
            "你只能读取，不能修改任何记忆，不得访问其他 conversation，"
            "不得调用或创建其他 Agent。\n"
            "最终只返回与任务直接相关的简报，并标明信息来自 current、history 或二者。\n"
            "没有找到相关内容时必须明确说明，不要编造。"
        ),
        tools_factory=lambda: [
            ListCurrentMemoryTool(),
            SearchCurrentMemoryTool(),
            GetCurrentMemoryDetailTool(),
            ListHistoryIndexTool(),
            SearchHistoryTool(),
            GetHistoryDetailTool(),
        ],
        budget=ExecutionBudget(
            max_llm_turns=5,
            max_tool_calls=8,
            max_memory_detail_reads=10,
            max_dispatch_depth=0,   # 不能再往下派遣
        ),
        needs_live_memory=True,
        needs_history_memory=True,
        allow_dispatch=False,
    ))
