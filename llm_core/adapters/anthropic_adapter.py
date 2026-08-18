"""llm_core.adapters.anthropic_adapter - Anthropic 专用适配器。

Anthropic Messages API 使用 x-api-key 头、消息中不能携带 system role
（system 单独作为一个顶层字段），格式与 OpenAI 不同，需单独处理。
"""
import json
import logging

import httpx

from llm_core.base import BaseLLMAdapter, ChatRequest, ChatResponse
from llm_core.registry import AdapterRegistry

logger = logging.getLogger(__name__)


@AdapterRegistry.register("anthropic")
class AnthropicAdapter(BaseLLMAdapter):
    def _url(self) -> str:
        return f"{self.config['base_url'].rstrip('/')}/messages"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        system_msg = next((m.content for m in request.messages if m.role == "system"), None)
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages if m.role != "system"
        ]
        payload = {
            "model": self.config["model_name"],
            "messages": messages,
            "max_tokens": request.max_tokens or 1024,
            **({"system": system_msg} if system_msg else {}),
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        payload.update(request.extra)

        headers = {
            "x-api-key": self.config["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        url = self._url()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            try:
                content = data["content"][0]["text"]
            except (KeyError, IndexError, TypeError):
                content = ""
                logger.warning(f"Anthropic 返回缺少 content[0].text: {data}")
            return ChatResponse(content=content, raw=data,
                                usage=data.get("usage", {}))

    async def stream_chat(self, request: ChatRequest):
        """解析 Anthropic SSE: event: content_block_delta + data: {...}"""
        system_msg = next((m.content for m in request.messages if m.role == "system"), None)
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages if m.role != "system"
        ]
        payload = {
            "model": self.config["model_name"],
            "messages": messages,
            "max_tokens": request.max_tokens or 1024,
            "stream": True,
            **({"system": system_msg} if system_msg else {}),
        }
        headers = {
            "x-api-key": self.config["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        url = self._url()
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for raw_line in resp.aiter_lines():
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    data_json = line[len("data:"):].strip()
                    if not data_json:
                        continue
                    try:
                        chunk = json.loads(data_json)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("delta") or {}
                    text = delta.get("text")
                    if text:
                        yield text
