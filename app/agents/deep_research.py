import json
import logging
import asyncio
from typing import AsyncGenerator
from openai import AsyncOpenAI
from app.agents.base import BaseAgent
from app.prompts.plan_execute import (
    get_current_time, PLAN, EXECUTE, CRITIQUE, COMPRESS, SUMMARIZE,
    REQUIREMENT_CLARIFICATION, RESEARCH_TOPIC_GENERATION,
)
from app.utils.think_parser import ThinkTagParser
from app.services.task_manager import task_manager

logger = logging.getLogger(__name__)


class PlanExecuteAgent(BaseAgent):
    def __init__(self, llm_client: AsyncOpenAI, model: str, tools: list[dict],
                 session_service=None, db=None,
                 max_rounds: int = 3, max_tool_retries: int = 2):
        super().__init__("plan-execute", llm_client, model, "deep")
        self.tools = tools
        # session_service removed — db is self-managed
        self.db = db
        self.max_rounds = max_rounds
        self.max_tool_retries = max_tool_retries
        self.tool_semaphore = asyncio.Semaphore(3)

    async def stream(self, conversation_id: str, question: str) -> AsyncGenerator[str, None]:
        task_info = await task_manager.register_task(conversation_id, "deep")
        if task_info is None and await task_manager.has_running_task(conversation_id):
            yield BaseAgent.error_response("该会话正在执行中，请稍后再试")
            return

        self.init_timers()
        self.clear_used_tools()
        self.current_conversation_id = conversation_id
        self.current_question = question

        # Save question
        if self.db:
            from app.services.session import SessionService
            from app.models.schemas import SaveQuestionRequest
            svc = SessionService(self.db)
            saved = await svc.save_question(SaveQuestionRequest(
                session_id=conversation_id, question=question,
            ))
            self.current_session_id = saved.id

        final_answer: list[str] = []
        thinking: list[str] = []
        all_references: list[dict] = []
        messages: list[dict] = []
        research_topic: str = ""

        def check_cancel():
            return task_info and task_info.cancel_event.is_set()

        # Phase 1: Clarify requirement
        yield self.thinking_response("\n🔍 正在分析您的需求...\n")
        clarify_result = await self._clarify_requirement(question, check_cancel)
        thinking.append(clarify_result)
        if check_cancel():
            yield BaseAgent.stop_message(); return
        if "【需要补充信息】" in clarify_result:
            yield self.text_response(f"⏸【暂停深入研究】{clarify_result.replace('【需要补充信息】', '').strip()}")
            await task_manager.stop_task(conversation_id); return
        yield self.thinking_response("✅ 信息充足，准备生成研究主题\n")

        # Phase 2: Generate research topic
        yield self.thinking_response("📝 正在生成研究主题...\n")
        research_topic = await self._generate_topic(question, check_cancel)
        thinking.append(research_topic)
        yield self.thinking_response("\n✅ 研究主题已生成\n\n")
        if check_cancel():
            yield BaseAgent.stop_message(); return

        # Phase 3: Plan-Execute-Critique loop
        for round_num in range(1, self.max_rounds + 1):
            yield self.thinking_response(f"\n🔄 第 {round_num} 轮研究开始\n")
            if check_cancel():
                yield BaseAgent.stop_message(); return

            # Plan
            yield self.thinking_response("📋 正在生成执行计划...\n")
            plan = await self._generate_plan(question, research_topic, messages, check_cancel)
            if plan is None or all(t.get("id") is None for t in plan):
                break
            yield self.thinking_response(f"\n✅ 执行计划已生成，共 {len(plan)} 个任务\n")
            if check_cancel():
                yield BaseAgent.stop_message(); return

            # Execute
            yield self.thinking_response("\n--- 开始执行任务 ---\n\n")
            results = await self._execute_plan(plan, check_cancel, thinking, all_references)
            yield self.thinking_response("\n--- 任务执行完成 ---\n\n")
            if check_cancel():
                yield BaseAgent.stop_message(); return

            # Critique
            yield self.thinking_response("\n🔍 正在评估当前研究结果...\n")
            critique = await self._critique(question, research_topic, plan, results, check_cancel)
            if critique.get("passed"):
                yield self.thinking_response("\n✅ 研究结果评估通过，准备生成最终报告\n")
                break
            else:
                yield self.thinking_response(f"\n⚠️ 研究结果评估未通过，原因分析：{critique.get('feedback', '')}\n")
                messages.append({"role": "assistant", "content": f"【Critique Feedback】\n{critique.get('feedback', '')}"})

        # Phase 4: Summarize
        yield self.thinking_response("\n✅ 研究阶段完成，准备生成最终报告\n\n")
        yield self.thinking_response("\n📝 正在生成最终研究报告...\n\n")

        final_text = await self._summarize(question, research_topic, messages, check_cancel, all_references)
        final_answer.append(final_text)
        yield self.text_response(final_text)

        if all_references:
            yield self.reference_response(json.dumps(all_references, ensure_ascii=False))

        await self._save_session(conversation_id, "".join(final_answer), "".join(thinking), all_references)
        await task_manager.stop_task(conversation_id)

    async def _clarify_requirement(self, question: str, check_cancel) -> str:
        msgs = [
            {"role": "system", "content": f"{get_current_time()}\n\n{REQUIREMENT_CLARIFICATION}"},
            {"role": "user", "content": question},
        ]
        response = await self.llm_client.chat.completions.create(
            model=self.model, messages=msgs, temperature=0.7,
        )
        return response.choices[0].message.content or ""

    async def _generate_topic(self, question: str, check_cancel) -> str:
        msgs = [
            {"role": "system", "content": f"{get_current_time()}\n\n{RESEARCH_TOPIC_GENERATION}"},
            {"role": "user", "content": f"<original_question>{question}</original_question>"},
        ]
        response = await self.llm_client.chat.completions.create(
            model=self.model, messages=msgs, temperature=0.7,
        )
        return response.choices[0].message.content or ""

    async def _generate_plan(self, question: str, topic: str, context: list[dict], check_cancel) -> list[dict] | None:
        msgs = [
            {"role": "system", "content": f"{get_current_time()}\n\n{PLAN}"},
            {"role": "user", "content": f"【研究主题】\n{topic}\n\n请生成执行计划。输出格式为JSON数组。"},
        ]
        response = await self.llm_client.chat.completions.create(
            model=self.model, messages=msgs, temperature=0.7,
        )
        text = response.choices[0].message.content or ""
        # Try to parse JSON
        try:
            cleaned = ThinkTagParser.strip_think_tags(text)
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass
        return []

    async def _execute_plan(self, plan: list[dict], check_cancel, thinking: list[str], references: list[dict]) -> dict[str, dict]:
        by_order: dict[int, list[dict]] = {}
        for t in plan:
            order = t.get("order", 1)
            by_order.setdefault(order, []).append(t)

        results: dict[str, dict] = {}
        for order in sorted(by_order.keys()):
            if check_cancel():
                break
            tasks = by_order[order]

            async def run_one(task):
                async with self.tool_semaphore:
                    return await self._execute_single_task(task, check_cancel, references)

            order_results = await asyncio.gather(*[run_one(t) for t in tasks])
            for r in order_results:
                if r:
                    results[r["task_id"]] = r

        return results

    async def _execute_single_task(self, task: dict, check_cancel, references: list[dict]) -> dict | None:
        task_id = task.get("id")
        if not task_id:
            return None
        instruction = task.get("instruction", "")

        msgs = [
            {"role": "system", "content": EXECUTE},
            {"role": "user", "content": f"【Current Task】\n{instruction}"},
        ]

        try:
            response = await self.llm_client.chat.completions.create(
                model=self.model, messages=msgs, tools=self.tools,
                temperature=0.7,
            )
            if response.choices[0].message.tool_calls:
                for tc in response.choices[0].message.tool_calls:
                    result = await self._execute_tool(tc.function.name, json.loads(tc.function.arguments))
                    msgs.append({"role": "assistant", "tool_calls": [tc.model_dump()]})
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})

                # Follow-up call for summary
                final_response = await self.llm_client.chat.completions.create(
                    model=self.model, messages=msgs, temperature=0.7,
                )
                answer = final_response.choices[0].message.content or ""
            else:
                answer = response.choices[0].message.content or ""

            return {"task_id": task_id, "success": True, "output": answer, "error": None}
        except Exception as e:
            return {"task_id": task_id, "success": False, "output": None, "error": str(e)}

    async def _critique(self, question: str, topic: str, plan: list[dict], results: dict[str, dict], check_cancel) -> dict:
        msgs = [
            {"role": "system", "content": f"{get_current_time()}\n\n{CRITIQUE}"},
            {"role": "user", "content": json.dumps({
                "question": question, "topic": topic,
                "plan": plan, "results": list(results.values()),
            }, ensure_ascii=False)},
        ]
        response = await self.llm_client.chat.completions.create(
            model=self.model, messages=msgs, temperature=0.7,
        )
        text = response.choices[0].message.content or ""
        try:
            cleaned = ThinkTagParser.strip_think_tags(text)
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass
        return {"passed": True, "feedback": ""}

    async def _summarize(self, question: str, topic: str, context: list[dict], check_cancel, references: list[dict]) -> str:
        msgs = [
            {"role": "system", "content": f"{get_current_time()}\n\n{SUMMARIZE}"},
            {"role": "user", "content": f"【用户原始问题】\n{question}\n\n【研究主题】\n{topic}"},
        ]
        response = await self.llm_client.chat.completions.create(
            model=self.model, messages=msgs, temperature=0.7,
        )
        return response.choices[0].message.content or ""

    async def _execute_tool(self, tool_name: str, args: dict) -> str:
        try:
            if "tavily" in tool_name.lower() or "search" in tool_name.lower():
                from app.services.search_service import tavily_search
                result, _ = await tavily_search(args.get("query", ""))
                return result
            return json.dumps({"error": f"未知工具: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _save_session(self, conversation_id: str, answer: str, thinking: str, references: list[dict]):
        if not self.db or not self.current_session_id:
            return
        try:
            from app.services.session import SessionService
            from app.models.schemas import UpdateAnswerRequest
            svc = SessionService(self.db)
            ref_json = ""
            if references:
                ref_json = self.reference_response(json.dumps(references, ensure_ascii=False))
            await svc.update_answer(UpdateAnswerRequest(
                id=self.current_session_id, answer=answer, thinking=thinking,
                tools=self.get_used_tools_string(), reference=ref_json,
                first_response_time=int(self.first_response_time),
                total_response_time=self.get_total_response_time(),
            ))
        except Exception as e:
            logger.error(f"保存会话失败: {e}")
