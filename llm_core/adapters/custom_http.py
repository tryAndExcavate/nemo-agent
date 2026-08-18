"""llm_core.adapters.custom_http - 完全私有的 HTTP 兜底适配器。

当平台完全不兼容 OpenAI 格式时的兜底方案。配置里额外包含:
  request_template: dict  (支持 {{message}} {{model}} 占位符)
  response_path: str      (JMESPath, 从响应中提取文本, 如 'data.text')
  headers: dict           (可选，自定义请求头)
这样前端"新增模型"时选择 custom_http 类型，可以手工填写映射规则，
完全不需要改后端代码。
"""
import json
import logging

import httpx
import jmespath

from llm_core.base import BaseLLMAdapter, ChatRequest, ChatResponse
from llm_core.registry import AdapterRegistry

logger = logging.getLogger(__name__)


@AdapterRegistry.register("custom_http")
class CustomHTTPAdapter(BaseLLMAdapter):
    """JMESPath + 模板占位符，支持完全私有协议的平台。"""

    def _render(self, template, **kwargs):
        s = json.dumps(template, ensure_ascii=False)
        for k, v in kwargs.items():
            s = s.replace(f"{{{{{k}}}}}", str(v))
        return json.loads(s)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        last_user_msg = next(
            (m.content for m in reversed(request.messages) if m.role == "user"),
            "",
        )
        payload = self._render(
            self.config.get("request_template", {"message": "{{message}}"}),
            message=last_user_msg,
            model=self.config.get("model_name", ""),
        )
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self.config["base_url"],
                json=payload,
                headers=self.config.get("headers") or {},
            )
            resp.raise_for_status()
            data = resp.json()
            path = self.config.get("response_path", "data.text")
            text = jmespath.search(path, data)
            if isinstance(text, (list, dict)):
                text = json.dumps(text, ensure_ascii=False)
            return ChatResponse(content=str(text or ""), raw=data)

    async def stream_chat(self, request: ChatRequest):
        raise NotImplementedError("自定义接口暂不支持流式")
