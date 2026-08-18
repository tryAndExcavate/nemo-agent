"""llm_core.base - 所有大模型适配器必须实现的统一契约。

OpenAI 兼容（/v1/chat/completions）已是目前大模型领域的事实标准，
通过抽象基类把"调用哪个平台、怎么调用"全部隔离在 Adapter 层，
业务代码只认 model_id。
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # system / user / assistant / tool
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    extra: dict = {}  # 透传自定义参数，如 top_p, tools 等


class ChatResponse(BaseModel):
    content: str
    raw: dict = {}  # 保留原始返回，便于排查
    usage: dict = {}


class BaseLLMAdapter(ABC):
    """所有大模型适配器必须实现的统一契约"""

    def __init__(self, config: dict):
        self.config = config  # 来自数据库的模型配置（api_key 已解密）

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """普通（非流式）对话。"""

    @abstractmethod
    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        """流式对话，逐段 yield 文本增量。"""

    async def test_connection(self) -> bool:
        """新增模型时用于「测试连接」按钮。

        默认实现：发一条极短的 user 消息，只要能拿到响应就算连通。
        """
        try:
            resp = await self.chat(ChatRequest(
                messages=[ChatMessage(role="user", content="ping")],
                max_tokens=5,
            ))
            # 有 content，或虽然为空但请求整体成功了，都视为连通
            return bool(resp.content) or True
        except Exception:
            return False
