"""MemoryRetrievalContext — 子智能体拿到的全部记忆访问能力。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.memory.live_view import LiveMemoryReadOnlyView
from app.memory.history_reader import ConversationHistoryReader


@dataclass(frozen=True)
class MemoryRetrievalContext:
    """子智能体拿到的两个只读记忆窗口，仅此而已。"""
    live_memory: Optional[LiveMemoryReadOnlyView] = None
    history: Optional[ConversationHistoryReader] = None
