"""llm_core.adapters - 各类平台适配器。

导入本包即导入全部内置适配器，触发 @AdapterRegistry.register 完成注册。
"""
from llm_core.adapters.openai_compatible import OpenAICompatibleAdapter  # noqa: F401
from llm_core.adapters.anthropic_adapter import AnthropicAdapter  # noqa: F401
from llm_core.adapters.custom_http import CustomHTTPAdapter  # noqa: F401
