"""触发判断器 - 判断当前上下文占用是否达到压缩阈值。"""
from dataclasses import dataclass
from typing import List, Dict, Optional
from app.context.token_counter import TokenCounter


@dataclass
class TriggerResult:
    """触发判断结果。"""
    should_compress: bool
    used_tokens: int
    budget_tokens: int
    usage_ratio: float


class CompressionTrigger:
    """只有当上下文占用达到阈值时才触发压缩逻辑。"""

    def __init__(self, trigger_ratio: float = 0.7):
        self.trigger_ratio = trigger_ratio

    def check(
        self,
        history: List[Dict],
        system_prompt: str,
        current_input: str,
        existing_summary: Optional[Dict],
        model_config: dict,
    ) -> TriggerResult:
        """检查是否需要触发压缩。

        Args:
            history: 历史消息列表
            system_prompt: 系统提示
            current_input: 当前用户输入
            existing_summary: 现有摘要（可能为 None）
            model_config: 模型配置（包含 provider、max_context_window、reserve_for_reply）

        Returns:
            TriggerResult: 触发判断结果
        """
        provider = model_config.get("provider", "openai")
        max_window = model_config.get("max_context_window", 8000)
        reserve_for_reply = model_config.get("reserve_for_reply", 1000)
        budget = int((max_window - reserve_for_reply) * 0.9)  # 安全余量打 9 折

        used = TokenCounter.count(system_prompt, provider)
        used += TokenCounter.count(current_input, provider)
        if existing_summary:
            used += existing_summary.get("token_count", 0)

        # 只统计"尚未被摘要覆盖"的历史消息（已覆盖的历史不重复计入原文预算）
        covered_id = existing_summary.get("covered_up_to_message_id", 0) if existing_summary else 0
        uncovered_history = [m for m in history if m.get("id", 0) > covered_id]
        used += TokenCounter.count_messages(uncovered_history, provider)

        ratio = used / budget if budget > 0 else 1.0
        return TriggerResult(
            should_compress=ratio >= self.trigger_ratio,
            used_tokens=used,
            budget_tokens=budget,
            usage_ratio=round(ratio, 3),
        )
