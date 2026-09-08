"""子智能体 Runner：创建全新、隔离的 QueryEngine，执行完即销毁。"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class SubAgentResult:
    text: str
    is_error: bool = False
    cost_usd: float = 0.0


class SubAgentRunner:
    """隔离式子智能体执行器。

    每次 run() 创建全新 QueryEngine（conversation_id=uuid），
    persist=False，不产生任何 .jsonl 残留。
    """

    def __init__(
        self,
        llm_client: Any,
        parent_model: str,
        cwd: str,
        sub_agent_model: Optional[str] = None,
    ):
        self.llm_client = llm_client
        self.parent_model = parent_model
        self.cwd = cwd
        self.sub_agent_model = sub_agent_model

    async def run(
        self,
        definition,  # SubAgentDefinition
        task: str,
        execution_context,  # AgentExecutionContext
        memory_retrieval=None,  # MemoryRetrievalContext | None
        parent_config=None,
    ) -> SubAgentResult:
        from app.agents.query_engine import QueryEngine, QueryEngineConfig, QueryEngineState

        sub_conversation_id = f"subagent-{definition.name}-{uuid.uuid4().hex[:8]}"

        # 子 Agent 用独立 model（如果有），否则继承父级
        model = self.sub_agent_model or self.parent_model

        config = QueryEngineConfig(
            tools=definition.tools_factory(),
            llm_client=self.llm_client,
            model=model,
            conversation_id=sub_conversation_id,
            cwd=self.cwd,
            custom_system_prompt=definition.system_prompt,
            max_turns=definition.budget.max_llm_turns,
        )

        # 标记为子 Agent 模式：不落盘、不写记忆
        config._persist = False

        engine = QueryEngine(config)

        # 注入记忆访问 + 预算执行状态
        from app.subagent.runner import ExecutionState
        exec_state = ExecutionState(definition.budget)

        engine._extra_tool_context = {
            "memory_retrieval": memory_retrieval,
            "execution_context": execution_context,
            "execution_state": exec_state,
            "parent_config": parent_config,
        }

        final_text = ""
        is_error = False
        try:
            async for event in engine.submit_message(task):
                if hasattr(event, "type") and hasattr(event.type, "value"):
                    event_type = event.type.value
                else:
                    event_type = str(event.type) if hasattr(event, "type") else ""

                if event_type == "text_delta" and hasattr(event, "data"):
                    final_text += str(event.data)
                elif event_type == "error":
                    is_error = True
                    final_text = f"子智能体执行出错: {event.data}"
        except Exception as e:
            is_error = True
            final_text = f"子智能体异常: {e}"

        return SubAgentResult(
            text=final_text.strip(),
            is_error=is_error,
            cost_usd=getattr(engine.state, "total_cost_usd", 0.0),
        )


@dataclass
class ExecutionState:
    """子 Agent 执行预算追踪器。"""
    budget: Any  # ExecutionBudget
    detail_reads: int = 0
    tool_calls: int = 0
