import json
import time
import logging
from typing import AsyncGenerator
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import async_session_factory
from app.models.schemas import AgentResponse, SaveQuestionRequest, UpdateAnswerRequest
from app.prompts.react import get_recommend_prompt

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(self, name: str, llm_client: AsyncOpenAI, model: str, agent_type: str):
        self.name = name
        self.llm_client = llm_client
        self.model = model
        self.agent_type = agent_type
        self.enable_recommendations = True

        # DB — 每个 agent 自己管理会话
        self._db: AsyncSession | None = None

        # Timing
        self.start_time: float = 0
        self.first_response_time: float = 0
        self.used_tools: set[str] = set()
        self.current_session_id: int | None = None
        self.current_conversation_id: str | None = None
        self.current_question: str | None = None
        self.current_recommendations: str | None = None

        # Token usage 累加器（一次 agent session 中所有 LLM 调用的总和）
        self._total_usage: dict = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "call_count": 0,
        }

        # 上下文压缩器（懒加载）
        self._context_compressor = None

    @property
    def context_compressor(self):
        """懒加载上下文压缩器。"""
        if self._context_compressor is None:
            from app.context.compressor import ContextCompressor
            from llm_core.store import ConfigStore
            from llm_core.manager import ModelManager
            from llm_core.base import ChatRequest, ChatMessage

            # 获取摘要模型
            summary_model_id = ConfigStore.get_active_summary_model_id()
            if summary_model_id:
                try:
                    adapter = ModelManager.get_adapter(summary_model_id)

                    class Summarizer:
                        def __init__(self, adapter):
                            self.adapter = adapter

                        async def chat_with_utility_model(self, messages):
                            chat_messages = [ChatMessage(role=m['role'], content=m['content']) for m in messages]
                            request = ChatRequest(messages=chat_messages, temperature=0.7, max_tokens=500)
                            return await self.adapter.chat(request)

                    summarizer = Summarizer(adapter)
                except Exception as e:
                    logger.warning(f"无法加载摘要模型: {e}，摘要功能将被禁用")
                    summarizer = None
            else:
                summarizer = None

            self._context_compressor = ContextCompressor(
                db_session_factory=async_session_factory,
                summarizer=summarizer,
                trigger_ratio=0.7,
                bm25_top_k=5,
            )
        return self._context_compressor

    def _new_db(self) -> AsyncSession:
        """创建新的 DB 会话"""
        if self._db is None:
            self._db = async_session_factory()
        return self._db

    async def _close_db(self):
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _save_question(self, conversation_id: str, question: str, fileid: str | None = None):
        from app.services.session import SessionService
        db = self._new_db()
        svc = SessionService(db)
        saved = await svc.save_question(SaveQuestionRequest(
            session_id=conversation_id, question=question, fileid=fileid,
        ))
        self.current_session_id = saved.id

    async def _save_answer(self, answer: str, thinking: str, references: list | None = None):
        if not self.current_session_id:
            return
        from app.services.session import SessionService
        db = self._new_db()
        svc = SessionService(db)
        ref_json = ""
        if references:
            ref_json = self.reference_response(json.dumps(references, ensure_ascii=False))
        await svc.update_answer(UpdateAnswerRequest(
            id=self.current_session_id, answer=answer, thinking=thinking,
            tools=self.get_used_tools_string(), reference=ref_json,
            recommend=self.current_recommendations,
            first_response_time=int(self.first_response_time),
            total_response_time=self.get_total_response_time(),
        ))

        # 记录 usage 到 JSONL 日志
        if self._total_usage["call_count"] > 0:
            from app.services.usage_logger import usage_logger
            usage_logger.log(
                self._total_usage,
                model_id="",
                model_name=self.model,
                provider="openai_compatible",
                conversation_id=self.current_conversation_id or "",
                agent_type=self.agent_type,
            )

    def _accumulate_usage(self, response):
        """从 OpenAI Completion 对象提取 usage 并累加。"""
        if hasattr(response, 'usage') and response.usage:
            self._total_usage["prompt_tokens"] += getattr(response.usage, 'prompt_tokens', 0) or 0
            self._total_usage["completion_tokens"] += getattr(response.usage, 'completion_tokens', 0) or 0
            self._total_usage["total_tokens"] += getattr(response.usage, 'total_tokens', 0) or 0
            self._total_usage["call_count"] += 1

    def usage_response(self, model_name: str = "", provider: str = "") -> str:
        """生成 TYPE_USAGE SSE 事件，包含整个 session 的汇总 usage。"""
        from llm_core.usage import build_usage
        usage = build_usage(
            self._total_usage,
            model_id="",
            model_name=model_name,
            provider=provider,
        )
        return BaseAgent._make_sse(AgentResponse.TYPE_USAGE, "", data=usage.model_dump())

    def _load_history(self, conversation_id: str) -> list[dict]:
        """返回空的实现，由子类覆盖"""
        return []

    # ===== Response helpers =====
    @staticmethod
    def _make_sse(type: str, content: str, count: int | None = None, data: dict | None = None) -> str:
        obj: dict = {"type": type, "content": content}
        if count is not None:
            obj["count"] = count
        if data is not None:
            obj["data"] = data
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def text_response(content: str) -> str:
        return BaseAgent._make_sse(AgentResponse.TYPE_TEXT, content)

    @staticmethod
    def thinking_response(content: str) -> str:
        return BaseAgent._make_sse(AgentResponse.TYPE_THINKING, content)

    @staticmethod
    def reference_response(content: str, count: int | None = None) -> str:
        if count is None:
            try:
                arr = json.loads(content)
                count = len(arr) if isinstance(arr, list) else None
            except Exception:
                pass
        return BaseAgent._make_sse(AgentResponse.TYPE_REFERENCE, content, count)

    @staticmethod
    def error_response(content: str) -> str:
        return BaseAgent._make_sse(AgentResponse.TYPE_ERROR, content)

    @staticmethod
    def recommend_response(content: str, count: int | None = None) -> str:
        return BaseAgent._make_sse(AgentResponse.TYPE_RECOMMEND, content, count)

    # ===== Timing =====
    def init_timers(self):
        self.start_time = time.time()
        self.first_response_time = 0

    def record_first_response(self):
        if self.first_response_time == 0 and self.start_time > 0:
            self.first_response_time = (time.time() - self.start_time) * 1000

    def get_total_response_time(self) -> int:
        if self.start_time == 0:
            return 0
        return int((time.time() - self.start_time) * 1000)

    def record_used_tool(self, tool_name: str):
        self.used_tools.add(tool_name)

    def get_used_tools_string(self) -> str:
        return ",".join(self.used_tools)

    def clear_used_tools(self):
        self.used_tools.clear()

    # ===== Recommendations =====
    async def generate_recommendations(self, history_messages: list[dict], current_answer: str) -> str | None:
        if not self.enable_recommendations:
            return None

        try:
            msgs = [{"role": "system", "content": get_recommend_prompt()}]
            msgs.extend(history_messages[-20:])
            msgs.append({"role": "user", "content": f"当前会话：\n{self.current_question}\n\n请根据上述对话生成3个推荐问题。输出格式为JSON数组。"})

            response = await self.llm_client.chat.completions.create(
                model=self.model, messages=msgs, temperature=0.7, max_tokens=200,
            )
            text = response.choices[0].message.content
            if text:
                start = text.find("[")
                end = text.rfind("]")
                if start >= 0 and end > start:
                    recommendations = json.loads(text[start:end + 1])
                    if isinstance(recommendations, list) and recommendations:
                        return json.dumps(recommendations, ensure_ascii=False)
        except Exception as e:
            logger.error(f"生成推荐问题异常: {e}")
        return None

    # ===== Stop message =====
    @staticmethod
    def stop_message() -> str:
        return BaseAgent.text_response("⏹ 用户已停止生成\n")
