"""Token 消耗统计与成本计算模块。"""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class TokenUsage(BaseModel):
    """Token 使用量模型。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_id: str = ""
    model_name: str = ""
    provider: str = ""
    estimated_cost: float = 0.0
    is_estimated: bool = False  # True 表示本地估算，非平台返回


class PricingConfig(BaseModel):
    """模型定价配置。"""
    input_per_1k: float  # 每 1000 input tokens 的价格（CNY）
    output_per_1k: float  # 每 1000 output tokens 的价格（CNY）
    currency: str = "CNY"


# 内置主流模型定价表（单位：CNY/1000 tokens）
PRICING_TABLE: dict[str, PricingConfig] = {
    "deepseek-chat": PricingConfig(input_per_1k=0.001, output_per_1k=0.002),
    "deepseek-coder": PricingConfig(input_per_1k=0.001, output_per_1k=0.002),
    "gpt-4o": PricingConfig(input_per_1k=0.035, output_per_1k=0.105),
    "gpt-4o-mini": PricingConfig(input_per_1k=0.0015, output_per_1k=0.006),
    "claude-3-5-sonnet-20241022": PricingConfig(input_per_1k=0.022, output_per_1k=0.11),
    "claude-3-5-haiku-20241022": PricingConfig(input_per_1k=0.004, output_per_1k=0.02),
}


def estimate_cost(usage: TokenUsage) -> float:
    """根据 usage 和定价表估算成本（CNY）。"""
    if usage.prompt_tokens == 0 and usage.completion_tokens == 0:
        return 0.0

    pricing = PRICING_TABLE.get(usage.model_name)
    if not pricing:
        return 0.0

    cost = (
        usage.prompt_tokens / 1000 * pricing.input_per_1k
        + usage.completion_tokens / 1000 * pricing.output_per_1k
    )
    return round(cost, 6)


def build_usage(
    raw_usage: dict,
    model_id: str = "",
    model_name: str = "",
    provider: str = "",
) -> TokenUsage:
    """从原始 usage 字典构建 TokenUsage 对象，并计算成本。"""
    prompt_tokens = raw_usage.get("prompt_tokens", 0) or 0
    completion_tokens = raw_usage.get("completion_tokens", 0) or 0

    usage = TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        model_id=model_id,
        model_name=model_name,
        provider=provider,
    )

    usage.estimated_cost = estimate_cost(usage)
    return usage
