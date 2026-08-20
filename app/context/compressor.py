"""三层压缩器 - 整合 Token计数、触发判断、BM25 召回和摘要生成。"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from app.context.token_counter import TokenCounter
from app.context.compression_trigger import CompressionTrigger
from app.context.bm25_retriever import BM25Retriever

logger = logging.getLogger(__name__)


@dataclass
class CompressedContext:
    """压缩后的上下文。"""
    messages: List[Dict]
    was_compressed: bool
    dropped_message_count: int = 0
    recalled_message_ids: List[int] = field(default_factory=list)
    usage_ratio: float = 0.0


class ContextCompressor:
    """三层上下文压缩器。"""

    def __init__(
        self,
        db_session_factory,
        summarizer,
        trigger_ratio: float = 0.7,
        bm25_top_k: int = 5,
    ):
        self.db_session_factory = db_session_factory
        self.summarizer = summarizer
        self.trigger = CompressionTrigger(trigger_ratio=trigger_ratio)
        self.retriever = BM25Retriever(top_k=bm25_top_k)

    async def compress(
        self,
        conversation_id: str,
        system_prompt: str,
        current_input: str,
        model_config: dict,
    ) -> CompressedContext:
        """压缩上下文，返回压缩后的消息列表。

        Args:
            conversation_id: 会话 ID（字符串格式，如 "chat_xxx"）
            system_prompt: 系统提示
            current_input: 当前用户输入
            model_config: 模型配置

        Returns:
            CompressedContext: 压缩后的上下文
        """
        provider = model_config.get("provider", "openai")

        history = await self._load_history(conversation_id)
        existing_summary = await self._load_summary(conversation_id)

        trigger_result = self.trigger.check(
            history, system_prompt, current_input, existing_summary, model_config
        )

        # ---- 快速通道：占用率没到阈值，直接透传全部历史 ----
        if not trigger_result.should_compress:
            messages = [{"role": "system", "content": system_prompt}]
            if existing_summary:
                messages.append({
                    "role": "system",
                    "content": f"[更早对话的背景摘要]\n{existing_summary['summary_text']}"
                })
            covered_id = existing_summary.get("covered_up_to_message_id", 0) if existing_summary else 0
            for m in history:
                if m.get("id", 0) > covered_id:
                    messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
            messages.append({"role": "user", "content": current_input})

            return CompressedContext(
                messages=messages,
                was_compressed=False,
                usage_ratio=trigger_result.usage_ratio,
            )

        # ---- 触发完整三层压缩 ----
        logger.info(
            f"[ContextCompressor] conversation={conversation_id} "
            f"占用率{trigger_result.usage_ratio}达到阈值，触发压缩"
        )
        return await self._full_compress(
            conversation_id, system_prompt, current_input, model_config,
            history, existing_summary, trigger_result,
        )

    async def _full_compress(
        self, conversation_id, system_prompt, current_input, model_config,
        history, existing_summary, trigger_result,
    ) -> CompressedContext:
        """完整三层压缩。"""
        provider = model_config.get("provider", "openai")
        budget = trigger_result.budget_tokens

        fixed_cost = TokenCounter.count(system_prompt, provider) + TokenCounter.count(current_input, provider)
        if existing_summary:
            fixed_cost += existing_summary.get("token_count", 0)
        remaining_budget = max(budget - fixed_cost, 0)

        covered_id = existing_summary.get("covered_up_to_message_id", 0) if existing_summary else 0
        uncovered = [m for m in history if m.get("id", 0) > covered_id]

        # 预算三分：近期窗口60% / BM25召回25% / 剩余给摘要自然消耗
        recency_budget = int(remaining_budget * 0.6)
        relevance_budget = int(remaining_budget * 0.25)

        # ---- Tier 1: 近期窗口，从最新往前贪心装填 ----
        kept, used, cut_index = [], 0, len(uncovered)
        for i in range(len(uncovered) - 1, -1, -1):
            t = TokenCounter.count(uncovered[i].get("content", ""), provider)
            if used + t > recency_budget:
                cut_index = i + 1
                break
            used += t
            kept.insert(0, uncovered[i])
        else:
            cut_index = 0
        to_compress = uncovered[:cut_index]
        exclude_ids = {m.get("id") for m in kept}

        # ---- Tier 2 (BM25召回) 和 Tier 3 (摘要生成) 并行执行 ----
        relevant_task = asyncio.create_task(
            asyncio.to_thread(
                self.retriever.retrieve,
                uncovered, current_input, exclude_ids, relevance_budget, provider,
            )
        )
        summary_task = (
            asyncio.create_task(self._generate_summary(
                existing_summary.get("summary_text") if existing_summary else None, to_compress
            ))
            if to_compress else None
        )

        relevant_messages = await relevant_task
        final_summary_text = existing_summary.get("summary_text") if existing_summary else None
        was_compressed = False
        if summary_task:
            final_summary_text = await summary_task
            await self._save_summary(conversation_id, final_summary_text, to_compress[-1].get("id", 0), model_config)
            was_compressed = True

        # ---- 组装最终消息 ----
        messages = [{"role": "system", "content": system_prompt}]
        if final_summary_text:
            messages.append({
                "role": "system",
                "content": f"[以下是此对话更早历史的背景摘要，可能存在信息压缩]\n{final_summary_text}"
            })
        if relevant_messages:
            recall_text = "\n".join(
                f"- [{m.get('role', 'user')}]（相关度{m.get('relevance_score', 0)}）: {m.get('content', '')}"
                for m in relevant_messages
            )
            messages.append({
                "role": "system",
                "content": f"[以下是与当前问题相关的历史原文片段，可作为精确依据引用]\n{recall_text}"
            })
        for m in kept:
            messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        messages.append({"role": "user", "content": current_input})

        return CompressedContext(
            messages=messages,
            was_compressed=was_compressed,
            dropped_message_count=len(to_compress),
            recalled_message_ids=[m.get("id") for m in relevant_messages],
            usage_ratio=trigger_result.usage_ratio,
        )

    async def _generate_summary(self, old_summary: Optional[str], new_messages: List[Dict]) -> str:
        """生成对话摘要。"""
        conversation_text = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in new_messages)
        if old_summary:
            prompt = (
                f"这是之前对话的摘要：\n{old_summary}\n\n"
                f"以下是新增的对话内容：\n{conversation_text}\n\n"
                f"请合并生成一份更新后的摘要（300字以内），保留关键事实、数字、用户明确提出的要求。"
            )
        else:
            prompt = (
                f"请将以下对话浓缩为一份摘要（300字以内），保留关键事实、数字、用户明确提出的要求：\n\n"
                f"{conversation_text}"
            )
        try:
            result = await self.summarizer.chat_with_utility_model(
                messages=[{"role": "user", "content": prompt}]
            )
            return result.content
        except Exception as e:
            logger.error(f"摘要生成失败，降级返回旧摘要或空: {e}")
            return old_summary or "（摘要生成失败，早期对话内容暂不可用）"

    async def _load_history(self, conversation_id: str) -> List[Dict]:
        """加载历史消息。"""
        from app.services.session import SessionService
        from app.database import async_session_factory
        async with async_session_factory() as session:
            svc = SessionService(session)
            records = await svc.find_recent_by_session_id(conversation_id, 100)
            history = []
            for record in reversed(records):
                if record.question:
                    history.append({"id": record.id, "role": "user", "content": record.question})
                if record.answer:
                    history.append({"id": record.id + 0.5, "role": "assistant", "content": record.answer})
            return history

    async def _load_summary(self, conversation_id: str) -> Optional[Dict]:
        """加载现有摘要。"""
        from app.services.context_summary_service import ContextSummaryService
        svc = ContextSummaryService()
        summary = await svc.get_by_conversation_id(conversation_id)
        if summary:
            return {
                "summary_text": summary.summary_text,
                "covered_up_to_message_id": summary.covered_up_to_message_id,
                "token_count": summary.token_count,
                "summary_model_id": summary.summary_model_id,
            }
        return None

    async def _save_summary(self, conversation_id: str, summary_text, covered_id, model_config):
        """保存摘要。"""
        from app.context.token_counter import TokenCounter
        from app.services.context_summary_service import ContextSummaryService
        svc = ContextSummaryService()
        token_count = TokenCounter.count(summary_text, model_config.get("provider", "openai"))
        await svc.create_or_update(
            conversation_id=conversation_id,
            summary_text=summary_text,
            covered_up_to_message_id=covered_id,
            token_count=token_count,
            summary_model_id=model_config.get("model_id", ""),
        )
