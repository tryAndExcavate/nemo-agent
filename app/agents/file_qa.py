"""文件问答 Agent — 对应 Java FileReactAgent"""
import json
import logging
import asyncio
from typing import AsyncGenerator
from openai import AsyncOpenAI
from app.agents.base import BaseAgent
from app.database import async_session_factory
from app.prompts.react import get_file_prompt
from app.utils.think_parser import ThinkTagParser
from app.services.task_manager import task_manager
from app.services.session import SessionService
from app.services.file_info import FileInfoService

logger = logging.getLogger(__name__)


class FileReActAgent(BaseAgent):
    def __init__(self, llm_client: AsyncOpenAI, model: str, tools: list[dict],
                 max_rounds: int = 5):
        super().__init__("file", llm_client, model, "file")
        self.tools = tools
        self.max_rounds = max_rounds
        self.current_file_id: str | None = None

    async def stream(self, conversation_id: str, question: str, file_id: str) -> AsyncGenerator[str, None]:
        self.current_file_id = file_id

        task_info = await task_manager.register_task(conversation_id, "file")
        if task_info is None and await task_manager.has_running_task(conversation_id):
            yield BaseAgent.error_response("该会话正在执行中，请稍后再试")
            return

        self.init_timers()
        self.clear_used_tools()
        self.current_conversation_id = conversation_id
        self.current_question = question

        db = self._new_db()

        try:
            await self._save_question(conversation_id, question, fileid=file_id)
            svc = SessionService(db)

            # 判断文件类型，图片/文本走不同处理
            file_info_svc = FileInfoService(db)
            file_record = await file_info_svc.get_by_file_id(file_id)

            messages: list[dict] = [
                {"role": "system", "content": get_file_prompt()},
            ]
            history = await svc.find_recent_by_session_id(conversation_id, 30)
            for record in reversed(history):
                if record.question:
                    messages.append({"role": "user", "content": record.question})
                if record.answer:
                    messages.append({"role": "assistant", "content": record.answer})

            # 构建用户消息 — 图片/文本不同处理
            if file_record and self._is_image(file_record.file_type):
                user_msg = self._build_image_message(file_record)
            else:
                user_msg = {
                    "role": "user",
                    "content": f"<question>{question}</question>\n<fileid>{file_id}</fileid>"
                }

            messages.append(user_msg)

            final_answer_buffer: list[str] = []
            thinking_buffer: list[str] = []
            round_count = 0
            finished = False

            while round_count < self.max_rounds and not finished:
                round_count += 1

                if task_info and task_info.cancel_event.is_set():
                    yield BaseAgent.stop_message()
                    return

                text_buffer = ""
                tool_calls: list[dict] = []
                in_think = False

                try:
                    stream = await self.llm_client.chat.completions.create(
                        model=self.model, messages=messages, tools=self.tools,
                        temperature=0.7, stream=True,
                    )
                    async for chunk in stream:
                        if task_info and task_info.cancel_event.is_set():
                            yield BaseAgent.stop_message()
                            return
                        delta = chunk.choices[0].delta if chunk.choices else None
                        if delta is None:
                            continue
                        if delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                while len(tool_calls) <= idx:
                                    tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
                                if tc_delta.id:
                                    tool_calls[idx]["id"] = tc_delta.id
                                if tc_delta.function:
                                    if tc_delta.function.name:
                                        tool_calls[idx]["function"]["name"] = tc_delta.function.name
                                    if tc_delta.function.arguments:
                                        tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments
                        if delta.content:
                            self.record_first_response()
                            parsed = ThinkTagParser.parse(delta.content, in_think)
                            in_think = parsed.in_think
                            for seg in parsed.segments:
                                if seg.thinking:
                                    thinking_buffer.append(seg.content)
                                    yield self.thinking_response(seg.content)
                                else:
                                    text_buffer += seg.content
                                    yield self.text_response(seg.content)
                except asyncio.CancelledError:
                    yield BaseAgent.stop_message()
                    return
                except Exception as e:
                    yield self.error_response(f"LLM调用失败: {e}")
                    return

                if tool_calls:
                    assistant_msg = {
                        "role": "assistant",
                        "content": text_buffer if text_buffer else None,
                        "tool_calls": [
                            {"id": tc["id"], "type": "function", "function": tc["function"]}
                            for tc in tool_calls
                        ],
                    }
                    messages.append(assistant_msg)
                    for tc in tool_calls:
                        tool_name = tc["function"]["name"]
                        try:
                            args = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
                            args = {}
                        self.record_used_tool(tool_name)
                        result = await self._execute_tool(tool_name, args)
                        messages.append({
                            "role": "tool", "tool_call_id": tc["id"], "content": result,
                        })
                else:
                    final_answer_buffer.append(text_buffer)
                    finished = True

            await self._save_answer("".join(final_answer_buffer), "".join(thinking_buffer))
        finally:
            await self._close_db()

        await task_manager.stop_task(conversation_id)

    def _build_image_message(self, file_record) -> dict:
        """对应 Java handleImageFile(): 图片文件用描述文字作为上下文"""
        desc = file_record.extracted_text or ""
        if not desc or desc == "[无法识别图片内容]":
            desc = "该图片无法识别内容，请尝试重新上传。"
        return {
            "role": "user",
            "content": (
                f"当前文件是一张图片，以下是图片的内容描述：\n{desc}\n\n"
                f"请根据以上图片内容描述来回答用户问题，禁止透露 fileid。\n"
                f"<question>{self.current_question}</question>\n"
                f"<fileid>{self.current_file_id}</fileid>"
            ),
        }

    async def _execute_tool(self, tool_name: str, args: dict) -> str:
        try:
            if tool_name == "loadContent":
                from app.tools.file_content import load_content_tool
                db = async_session_factory()
                try:
                    return await load_content_tool(db, **args)
                finally:
                    await db.close()
            return json.dumps({"error": f"未知工具: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": f"工具执行失败: {e}"})

    @staticmethod
    def _is_image(file_type: str | None) -> bool:
        return (file_type or "").lower() in ("jpg", "jpeg", "png", "gif", "bmp")
