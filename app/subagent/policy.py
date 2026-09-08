"""执行模式、预算与派遣上下文。

depth / call_path 不是"建议"，是每次 dispatch 前必须通过的硬校验。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EngineMode(Enum):
    MAIN = "main"          # 主 Agent：可写记忆、可持久化、可 dispatch
    SUBAGENT = "subagent"  # 子 Agent：只读、不持久化、默认不可 dispatch


@dataclass
class ExecutionBudget:
    """单个子 Agent 的执行预算，三层限制防无限循环。"""
    max_llm_turns: int = 5
    max_tool_calls: int = 10
    max_memory_detail_reads: int = 3    # 防子 Agent 疯狂拉全量详情
    max_dispatch_depth: int = 0         # 0 = 不能再往下派遣


@dataclass(frozen=True)
class AgentExecutionContext:
    """每次 dispatch 派生新 context，用于深度 / 环检测。"""
    root_conversation_id: str
    current_agent: str
    depth: int
    call_path: tuple[str, ...]
    max_depth: int

    def derive(self, next_agent: str, next_max_depth: int) -> "AgentExecutionContext":
        if self.depth + 1 > self.max_depth:
            raise PermissionError(
                f"dispatch depth exceeded: depth={self.depth}, max={self.max_depth}"
            )
        if next_agent in self.call_path:
            raise PermissionError(
                f"cyclic subagent call: {self.call_path} -> {next_agent}"
            )
        return AgentExecutionContext(
            root_conversation_id=self.root_conversation_id,
            current_agent=next_agent,
            depth=self.depth + 1,
            call_path=self.call_path + (next_agent,),
            max_depth=next_max_depth,
        )

    @classmethod
    def root(cls, conversation_id: str, max_depth: int = 1) -> "AgentExecutionContext":
        return cls(
            root_conversation_id=conversation_id,
            current_agent="main",
            depth=0,
            call_path=("main",),
            max_depth=max_depth,
        )
