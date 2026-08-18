"""llm_core.manager - ModelManager 全局单例。

业务层唯一入口：@classmethod get_adapter(model_id) 返回一个可直接调用的
adapter 实例，自带缓存；配置变更后调用 invalidate(model_id) 即可强制重载，
实现「换模型不改业务代码」。
"""
import logging

logger = logging.getLogger(__name__)

from llm_core.registry import AdapterRegistry
from llm_core.store import ConfigStore
from llm_core.base import BaseLLMAdapter


class ModelManager:
    """全局单例：负责实例化、缓存 adapter。"""

    _cache: dict[str, BaseLLMAdapter] = {}

    @classmethod
    def get_adapter(cls, model_id: str) -> BaseLLMAdapter:
        if model_id in cls._cache:
            return cls._cache[model_id]
        config = ConfigStore.get_decrypted(model_id)
        adapter_cls = AdapterRegistry.get(config["provider_type"])
        adapter = adapter_cls(config)
        cls._cache[model_id] = adapter
        logger.info(f"实例化 adapter: {model_id} -> {config['provider_type']}")
        return adapter

    @classmethod
    def invalidate(cls, model_id: str):
        """修改模型配置后调用，强制下次重新加载。"""
        cls._cache.pop(model_id, None)
