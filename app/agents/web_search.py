import json
import logging
import asyncio
from typing import AsyncGenerator
from openai import AsyncOpenAI
from app.agents.base import BaseAgent
from app.database import async_session_factory
from app.prompts.react import get_web_search_prompt
from app.utils.think_parser import ThinkTagParser
from app.services.task_manager import task_manager
from app.services.session import SessionService

logger = logging.getLogger(__name__)


class WebSearchReActAgent(BaseAgent):
    def __init__(self, llm_client: AsyncOpenAI, model: str, tools: list[dict],
                 max_rounds: int = 5):
        super().__init__("websearch", llm_client, model, "websearch")
        self.tools = tools
        self.max_rounds = max_rounds

    async def stream(self, conversation_id: str, question: str) -> AsyncGenerator[str, None]:
        print("在此处A")
        task_info = await task_manager.register_task(conversation_id, "websearch")
        if task_info is None and await task_manager.has_running_task(conversation_id):
            yield BaseAgent.error_response("该会话中存在正在执行的任务，请稍后再试")
            return

        self.init_timers()
        self.clear_used_tools()
        self.current_conversation_id = conversation_id
        self.current_question = question

        db = self._new_db()

        # 收集搜索结果，最后统一发给前端
        all_references: list[dict] = []

        try:
            await self._save_question(conversation_id, question)
            svc = SessionService(db)

            # 使用上下文压缩器智能管理历史消息
            system_prompt = get_web_search_prompt()
            compressed = await self.context_compressor.compress(
                conversation_id=conversation_id,
                system_prompt=system_prompt,
                current_input=f"<question>{question}</question>",
                model_config={"provider": "openai", "max_context_window": 8000, "reserve_for_reply": 1000}
            )
            messages = compressed.messages

            final_answer: list[str] = []
            thinking_buffer: list[str] = []
            round_count = 0
            finished = False

            while round_count < self.max_rounds and not finished:
                round_count += 1
                logger.info(f"=== Round {round_count} ===")

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

                        # 发送搜索 thinking 消息（Java 原版逻辑）
                        if "search" in tool_name.lower():
                            query = args.get("query", "")
                            yield self.thinking_response(f"🔍 正在搜索信息: {query}\n")

                        self.record_used_tool(tool_name)
                        tool_result, refs = await self._execute_tool(tool_name, args)

                        # 收集引用来源
                        if refs:
                            all_references.extend(refs)

                        messages.append({
                            "role": "tool", "tool_call_id": tc["id"], "content": tool_result,
                        })
                else:
                    final_answer.append(text_buffer)
                    finished = True

                    # 发送参考来源（Java 原版逻辑：最终答案后发送 references）
                    if all_references:
                        ref_json = json.dumps(all_references, ensure_ascii=False)
                        yield self.reference_response(ref_json)

                    # 发送推荐问题
                    if self.enable_recommendations:
                        recs = await self.generate_recommendations(messages, "".join(final_answer))
                        if recs:
                            self.current_recommendations = recs
                            yield self.recommend_response(recs)

            # 保存结果
            await self._save_answer("".join(final_answer), "".join(thinking_buffer), all_references)
            yield self.usage_response(model_name=self.model, provider="openai_compatible")
        except Exception as e:
            logger.error(f"Agent 执行异常: {e}")
            yield self.error_response(f"执行出错: {e}")
        finally:
            await self._close_db()
            await task_manager.stop_task(conversation_id)

    async def _execute_tool(self, tool_name: str, args: dict) -> tuple[str, list[dict]]:
        """执行工具，返回 (tool_response_text, references_list)"""
        try:
            if "tavily" in tool_name.lower() or "search" in tool_name.lower():
                from app.services.search_service import tavily_search
                return await tavily_search(args.get("query", ""))
            elif tool_name == "loadContent":
                from app.tools.file_content import load_content_tool
                db = async_session_factory()
                try:
                    return await load_content_tool(db, **args), []
                finally:
                    await db.close()
            elif tool_name == "read_file":
                from app.tools.file_system import read_file_tool
                return await read_file_tool(**args), []
            elif tool_name == "write_file":
                from app.tools.file_system import write_file_tool
                return await write_file_tool(**args), []
            elif tool_name == "edit_file":
                from app.tools.file_system import edit_file_tool
                return await edit_file_tool(**args), []
            elif tool_name == "list_files":
                from app.tools.file_system import list_files_tool
                return await list_files_tool(**args), []
            elif tool_name == "glob_files":
                from app.tools.file_system import glob_files_tool
                return await glob_files_tool(**args), []
            elif tool_name == "grep":
                from app.tools.grep_tool import grep_tool
                return await grep_tool(**args), []
            elif tool_name == "bash":
                from app.tools.bash_tool import bash_tool
                return await bash_tool(**args), []
            elif tool_name == "load_skill":
                from app.tools.skills_tool import load_skill_tool
                return await load_skill_tool(**args), []
            return json.dumps({"error": f"未知工具: {tool_name}"}), []
        except Exception as e:
            return json.dumps({"error": f"工具执行失败: {e}"}), []
