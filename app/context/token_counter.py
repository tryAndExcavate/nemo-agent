"""Token 计数器 - 支持 OpenAI tiktoken 精确计数和非 OpenAI 的粗略估算。"""
import re


class TokenCounter:
    """Token 计数器，支持多种 provider 的计数策略。"""

    _encoder = None

    @classmethod
    def _get_encoder(cls):
        """延迟加载 tiktoken encoder。"""
        if cls._encoder is None:
            try:
                import tiktoken
                cls._encoder = tiktoken.get_encoding("cl100k_base")
            except Exception:
                cls._encoder = None
        return cls._encoder

    @classmethod
    def count(cls, text: str, provider: str = "openai") -> int:
        """计算文本的 token 数。

        - OpenAI 系列：使用 tiktoken 精确计数
        - 非 OpenAI：使用粗略估算（CJK 1.3 字符/token，其他 3.5 字符/token）
        """
        if not text:
            return 0

        if provider in ("openai", "azure_openai"):
            encoder = cls._get_encoder()
            if encoder:
                return len(encoder.encode(text))

        # 非 OpenAI 系列的粗略估算，保守偏高，防止实际超预算
        cjk_count = sum(1 for ch in text if '一' <= ch <= '鿿')
        other_count = len(text) - cjk_count
        return int(cjk_count / 1.3 + other_count / 3.5)

    @classmethod
    def count_messages(cls, messages: list, provider: str = "openai") -> int:
        """计算消息列表的总 token 数（含角色/格式开销）。"""
        total = sum(cls.count(m.get("content", ""), provider) for m in messages)
        return total + len(messages) * 4  # 每条消息的角色/格式开销，经验值
