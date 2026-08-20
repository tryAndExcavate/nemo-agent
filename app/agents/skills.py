import json
import logging
import asyncio
from typing import AsyncGenerator
from openai import AsyncOpenAI
from app.agents.base import BaseAgent
from app.database import async_session_factory
from app.prompts.react import get_skills_prompt
from app.utils.think_parser import ThinkTagParser
from app.services.task_manager import task_manager
from app.services.session import SessionService
from app.tools.skills_tool import format_skills_prompt

logger = logging.getLogger(__name__)


class SkillsReActAgent(BaseAgent):
    def __init__(self, llm_client: AsyncOpenAI, model: str, tools: list[dict],
                 max_rounds: int = 10, max_retries: int = 3,
                 context_compactor=None):
        super().__init__("skills", llm_client, model, "skills")
        self.tools = tools
        self.max_rounds = max_rounds
        self.max_retries = max_retries
        self.context_compactor = context_compactor

    async def stream(self, conversation_id: str, question: str, file_id: str | None = None) -> AsyncGenerator[str, None]:
        task_info = await task_manager.register_task(conversation_id, "skills")
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

            system_prompt = get_skills_prompt()
            skills_text = format_skills_prompt()
            if skills_text:
                system_prompt = system_prompt + "\n\n" + skills_text

            # 使用上下文压缩器智能管理历史消息
            current_input = f"<question>{question}</question>"
            if file_id:
                current_input += f"\n<fileid>{file_id}</fileid>"

            compressed = await self.context_compressor.compress(
                conversation_id=conversation_id,
                system_prompt=system_prompt,
                current_input=current_input,
                model_config={"provider": "openai", "max_context_window": 8000, "reserve_for_reply": 1000}
            )
            messages = compressed.messages

            final_answer_buffer: list[str] = []
            thinking_buffer: list[str] = []
            round_count = 0
            finished = False

            while round_count < self.max_rounds and not finished:
                round_count += 1

                if task_info and task_info.cancel_event.is_set():
                    yield BaseAgent.stop_message()
                    return

                if self.context_compactor:
                    self.context_compactor.compact(messages, question)

                text_buffer = ""
                tool_calls: list[dict] = []
                in_think = False

                try:
                    stream = await self.llm_client.chat.completions.create(
                        model=self.model, messages=messages, tools=self.tools,
                        temperature=0.7, stream=True,
                        stream_options={"include_usage": True},  # 启用 usage 提取
                    )
                    async for chunk in stream:
                        if task_info and task_info.cancel_event.is_set():
                            yield BaseAgent.stop_message()
                            return
                        delta = chunk.choices[0].delta if chunk.choices else None
                        if delta is None:
                            # 检查是否是最后一个带 usage 的 chunk
                            if hasattr(chunk, 'usage') and chunk.usage:
                                self._total_usage["prompt_tokens"] = getattr(chunk.usage, 'prompt_tokens', 0) or 0
                                self._total_usage["completion_tokens"] = getattr(chunk.usage, 'completion_tokens', 0) or 0
                                self._total_usage["total_tokens"] = getattr(chunk.usage, 'total_tokens', 0) or 0
                                self._total_usage["call_count"] += 1
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
                    logger.error(f"LLM stream error: {e}")
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
            yield self.usage_response(model_name=self.model, provider="openai_compatible")
        except Exception as e:
            logger.error(f"Agent 执行异常: {e}")
            yield self.error_response(f"执行出错: {e}")
        finally:
            await self._close_db()
            await task_manager.stop_task(conversation_id)

    async def _execute_tool(self, tool_name: str, args: dict) -> str:
        try:
            if "tavily" in tool_name.lower() or "search" in tool_name.lower():
                from app.services.search_service import tavily_search
                result, _ = await tavily_search(args.get("query", ""))
                return result
            elif tool_name == "loadContent":
                from app.tools.file_content import load_content_tool
                db = async_session_factory()
                try:
                    return await load_content_tool(db, **args)
                finally:
                    await db.close()
            elif tool_name == "load_skill":
                from app.tools.skills_tool import load_skill_tool
                return await load_skill_tool(**args)
            elif tool_name == "read_file":
                from app.tools.file_system import read_file_tool
                return await read_file_tool(**args)
            elif tool_name == "write_file":
                from app.tools.file_system import write_file_tool
                return await write_file_tool(**args)
            elif tool_name == "edit_file":
                from app.tools.file_system import edit_file_tool
                return await edit_file_tool(**args)
            elif tool_name == "list_files":
                from app.tools.file_system import list_files_tool
                return await list_files_tool(**args)
            elif tool_name == "glob_files":
                from app.tools.file_system import glob_files_tool
                return await glob_files_tool(**args)
            elif tool_name == "grep":
                from app.tools.grep_tool import grep_tool
                return await grep_tool(**args)
            elif tool_name == "bash":
                from app.tools.bash_tool import bash_tool
                return await bash_tool(**args)
            return json.dumps({"error": f"未知工具: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": f"工具执行失败: {e}"})
