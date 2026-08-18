"""llm_core - 可插拔大模型基座独立包。

导出核心符号便于业务代码统一 import：
    ModelManager / ConfigStore / AdapterRegistry / BaseLLMAdapter
以及 ChatMessage / ChatRequest / ChatResponse 等基础数据类型。
"""
from llm_core.base import (
    BaseLLMAdapter,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)
from llm_core.registry import AdapterRegistry
from llm_core.store import ConfigStore
from llm_core.manager import ModelManager

# 导入适配器模块，触发 @AdapterRegistry.register 装饰器完成注册
# （openai_compatible / anthropic / custom_http）
from llm_core import adapters  # noqa: E402,F401

__all__ = [
    "ModelManager",
    "ConfigStore",
    "AdapterRegistry",
    "BaseLLMAdapter",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
]
