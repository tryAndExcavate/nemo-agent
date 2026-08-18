"""llm_core.registry - 可插拔的关键：装饰器自动注册表。

新增/更换模型平台的核心思想：写一个新的 Adapter 类并用
@AdapterRegistry.register("xxx") 装饰，即可被系统识别，无需改任何业务代码。
"""
from typing import Type

from llm_core.base import BaseLLMAdapter


class AdapterRegistry:
    """provider_type -> AdapterClass 的注册表。"""

    _registry: dict[str, Type[BaseLLMAdapter]] = {}

    @classmethod
    def register(cls, provider_type: str):
        """装饰器：把适配器类注册到指定的 provider_type 名下。"""

        def wrapper(adapter_cls: Type[BaseLLMAdapter]):
            cls._registry[provider_type] = adapter_cls
            return adapter_cls

        return wrapper

    @classmethod
    def get(cls, provider_type: str) -> Type[BaseLLMAdapter]:
        if provider_type not in cls._registry:
            raise ValueError(f"未注册的模型类型: {provider_type}")
        return cls._registry[provider_type]

    @classmethod
    def list_types(cls) -> list[str]:
        return list(cls._registry.keys())
