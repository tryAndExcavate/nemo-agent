"""子智能体定义：把权限设成数据，而不是散落在代码里。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from app.subagent.policy import ExecutionBudget


@dataclass
class SubAgentDefinition:
    name: str
    description: str
    system_prompt: str
    tools_factory: Callable[[], list]
    model: Optional[str] = None
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)

    # 记忆能力开关：默认全部关闭，需要哪个显式打开
    needs_live_memory: bool = False
    needs_history_memory: bool = False

    # 是否允许再往下 dispatch（默认禁止，杜绝递归）
    allow_dispatch: bool = False
