"""llm_core.adapters.openai_compatible - 通用 OpenAI 兼容适配器。

适用于所有兼容 /v1/chat/completions 格式的平台：OpenAI、DeepSeek、Moonshot、
通义千问兼容模式、OpenRouter、本地 vLLM/Ollama(OpenAI 模式) 等，
只需切换 base_url + api_key + model_name 即可，零代码接入。
"""
import json
import logging

import httpx

from llm_core.base import BaseLLMAdapter, ChatRequest, ChatResponse
from llm_core.registry import AdapterRegistry

logger = logging.getLogger(__name__)


@AdapterRegistry.register("openai_compatible")
class OpenAICompatibleAdapter(BaseLLMAdapter):
    """覆盖绝大多数新平台的事实标准适配器。"""

    def _chat_url(self) -> str:
        return f"{self.config['base_url'].rstrip('/')}/chat/completions"

    def _build_payload(self, request: ChatRequest) -> dict:
        payload = {
            "model": self.config["model_name"],
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
            "stream": request.stream,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        payload.update(request.extra)
        return payload

    def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
        }
        # 允许配置里用 extra_config 覆盖自定义 header（如某些网关需要额外认证头）
        headers.update(self.config.get("headers") or {})
        return headers

    async def chat(self, request: ChatRequest) -> ChatResponse:
        url = self._chat_url()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=self._build_payload(request),
                                     headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                content = ""
                logger.warning(f"OpenAI 兼容接口返回缺少 choices[0].message.content: {data}")
            return ChatResponse(
                content=content or "",
                raw=data,
                usage=data.get("usage", {}),
            )

    async def stream_chat(self, request: ChatRequest):
        request.stream = True
        url = self._chat_url()
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=self._build_payload(request),
                                     headers=self._headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    line = line[6:].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(line)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        logger.debug(f"忽略无法解析的流式分片: {line}")
                        continue
