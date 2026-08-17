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
