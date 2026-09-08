"""两层状态管理。

第一层 GlobalState：per-workspace，包含工作区信息和跨会话共享的统计数据。
第二层会话状态：每个 QueryEngine 一份，管理单次对话的消息和 token。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# =========================================================
# 第一层：全局状态（per-workspace）
# =========================================================

@dataclass
class GlobalState:
    cwd: str
    model: str = ""
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def record_usage(self, input_tokens: int, output_tokens: int, cost_usd: float = 0.0) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost_usd


# 按 cwd 路径索引，每个工作区一个 GlobalState
_workspace_states: dict[str, GlobalState] = {}


def get_or_create_global_state(cwd: str, model: str = "") -> GlobalState:
    """获取或创建工作区对应的 GlobalState。cwd 相同则复用。"""
    key = cwd.rstrip("/\\")
    if key not in _workspace_states:
        _workspace_states[key] = GlobalState(cwd=cwd, model=model)
    state = _workspace_states[key]
    if model:
        state.model = model
    return state


def get_global_state(cwd: str) -> GlobalState:
    """获取指定工作区的 GlobalState，不存在则创建。"""
    return get_or_create_global_state(cwd)


# =========================================================
# 兼容旧接口（可后续删除）
# =========================================================

def init_global_state(cwd: str, session_id: str = "", model: str = "gpt-4o") -> GlobalState:
    """兼容旧调用，内部转发到 per-workspace 版本。"""
    return get_or_create_global_state(cwd, model)


def ensure_global_state(cwd: str, session_id: str = "", model: str = "gpt-4o") -> GlobalState:
    """兼容旧调用，内部转发到 per-workspace 版本。"""
    return get_or_create_global_state(cwd, model)
