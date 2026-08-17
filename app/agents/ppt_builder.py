import json
import logging
from typing import AsyncGenerator
from openai import AsyncOpenAI
from app.agents.base import BaseAgent
from app.prompts.ppt_builder import (
    INTENT_RECOGNITION_PROMPT, REQUIREMENT_PROMPT,
    get_search_info_prompt, get_template_selection_prompt,
    get_outline_prompt, get_schema_generation_prompt,
    get_summary_prompt,
)
from app.services.task_manager import task_manager

logger = logging.getLogger(__name__)


class PptStatus:
    INIT = "INIT"
    SEARCH = "SEARCH"
    TEMPLATE = "TEMPLATE"
    OUTLINE = "OUTLINE"
    SCHEMA = "SCHEMA"
    RENDER = "RENDER"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PPTBuilderAgent(BaseAgent):
    def __init__(self, llm_client: AsyncOpenAI, model: str, tools: list[dict]):
        super().__init__("pptx", llm_client, model, "ppt")
        self.tools = tools

    async def stream(self, conversation_id: str, question: str) -> AsyncGenerator[str, None]:
        task_info = await task_manager.register_task(conversation_id, "pptx")
        if task_info is None and await task_manager.has_running_task(conversation_id):
            yield BaseAgent.error_response("该会话正在执行中，请稍后再试")
            return

        self.init_timers()
        self.clear_used_tools()
        self.current_conversation_id = conversation_id
        self.current_question = question

        db = self._new_db()
        from app.services.ppt_service import PptInstService, PptTemplateService
        from app.models.ppt import AiPptInst

        try:
            await self._save_question(conversation_id, question)
            ppt_svc = PptInstService(db)
            tpl_svc = PptTemplateService(db)

            existing = await ppt_svc.get_by_conversation_id(conversation_id)
            if existing:
                ppt_inst = existing
            else:
                ppt_inst = AiPptInst(conversation_id=conversation_id, status=PptStatus.INIT, query=question)
                ppt_inst = await ppt_svc.create(ppt_inst)

            # ===== Phase 1: 需求澄清 (streaming) =====
            yield self.text_response("📋 正在分析您的需求...\n")
            msgs = [
                {"role": "system", "content": REQUIREMENT_PROMPT},
                {"role": "user", "content": question},
            ]
            stream = await self.llm_client.chat.completions.create(
                model=self.model, messages=msgs, temperature=0.7, stream=True,
            )
            requirement_buffer = ""
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    requirement_buffer += delta.content
                    yield self.text_response(delta.content)

            if "暂停生成" in requirement_buffer:
                yield self.text_response("\n信息不足，暂停生成\n")
                return

            await ppt_svc.update_requirement(ppt_inst.id, requirement_buffer)
            await ppt_svc.update_status(ppt_inst.id, PptStatus.SEARCH)

            # ===== Phase 2: 搜索信息 =====
            yield self.text_response("\n🔍 正在搜索相关信息...\n")
            msgs = [
                {"role": "system", "content": get_search_info_prompt(requirement_buffer or question)},
                {"role": "user", "content": "请开始搜索"},
            ]
            response = await self.llm_client.chat.completions.create(
                model=self.model, messages=msgs, tools=self.tools, temperature=0.7,
            )
            search_text = response.choices[0].message.content or ""
            if response.choices[0].message.tool_calls:
                msgs.append({"role": "assistant", "tool_calls": [tc.model_dump() for tc in response.choices[0].message.tool_calls]})
                for tc in response.choices[0].message.tool_calls:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    result = await self._run_tool(tc.function.name, args)
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                final = await self.llm_client.chat.completions.create(
                    model=self.model, messages=msgs, temperature=0.7,
                )
                search_text = final.choices[0].message.content or ""
            yield self.text_response("✅ 信息收集完成\n")
            await ppt_svc.update_search_info(ppt_inst.id, search_text)

            # ===== Phase 3: 选模板 =====
            yield self.text_response("\n🎨 正在选择PPT模板...\n")
            all_tpl = await tpl_svc.get_all()
            tpl_info = "\n".join([f"- {t.template_code}: {t.template_name} ({t.style_tags or '通用'})" for t in all_tpl])
            msgs = [
                {"role": "system", "content": get_template_selection_prompt(requirement_buffer or question, tpl_info)},
                {"role": "user", "content": "请选择模板"},
            ]
            response = await self.llm_client.chat.completions.create(model=self.model, messages=msgs, temperature=0.7)
            try:
                template_code = json.loads(response.choices[0].message.content or "{}").get("templateCode", "ai")
            except json.JSONDecodeError:
                template_code = "ai"
            template = await tpl_svc.get_by_code(template_code or "ai")
            if not template:
                template = all_tpl[0] if all_tpl else None
            yield self.text_response(f"✅ 已选择模板: {template.template_name if template else '默认'}\n")
            await ppt_svc.update_template_code(ppt_inst.id, template_code)

            # ===== Phase 4: 大纲 =====
            yield self.text_response("\n📝 正在生成PPT大纲...\n")
            tpl_schema = template.template_schema if template else "{}"
            tpl_name = template.template_name if template else ""
            msgs = [{"role": "system", "content": get_outline_prompt(requirement_buffer or question, tpl_schema, tpl_name, search_text)}]
            response = await self.llm_client.chat.completions.create(model=self.model, messages=msgs, temperature=0.7)
            outline = response.choices[0].message.content or ""
            yield self.text_response("✅ 大纲生成完成\n")
            await ppt_svc.update_outline(ppt_inst.id, outline)

            # ===== Phase 5: Schema =====
            yield self.text_response("\n📐 正在生成PPT Schema...\n")
            msgs = [{"role": "system", "content": get_schema_generation_prompt(tpl_schema, outline)}]
            response = await self.llm_client.chat.completions.create(model=self.model, messages=msgs, temperature=0.7)
            schema_text = response.choices[0].message.content or ""
            yield self.text_response("✅ Schema生成完成\n")
            await ppt_svc.update_schema(ppt_inst.id, schema_text)

            # ===== Phase 6: 渲染 =====
            yield self.text_response("\n🎬 正在渲染PPT文件...\n")
            try:
                from app.services.ppt_render import PptPythonRenderService
                from app.models.schemas import PptSchema
                schema_obj = PptSchema.model_validate_json(schema_text or "{}")
                render = PptPythonRenderService()
                file_url = await render.render(ppt_inst, schema_obj)
                await ppt_svc.update_file_url(ppt_inst.id, file_url)
                await ppt_svc.update_status(ppt_inst.id, PptStatus.SUCCESS)
                yield self.text_response("✅ 渲染完成\n\n")
            except Exception as e:
                logger.error(f"PPT渲染失败: {e}")
                await ppt_svc.update_error(ppt_inst.id, str(e))
                await ppt_svc.update_status(ppt_inst.id, PptStatus.FAILED)
                yield self.text_response(f"\n抱歉，PPT渲染时出现错误：{e}\n")
                return

            # ===== Phase 7: 最终总结 (streaming) =====
            prompt = get_summary_prompt(requirement_buffer or question, ppt_inst.file_url or "", 5)
            msgs = [{"role": "system", "content": prompt}]
            stream = await self.llm_client.chat.completions.create(
                model=self.model, messages=msgs, temperature=0.7, stream=True,
            )
            summary_buffer = ""
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    summary_buffer += delta.content
                    yield self.text_response(delta.content)

            await self._save_answer(summary_buffer, "")

        finally:
            await self._close_db()

        await task_manager.stop_task(conversation_id)

    async def _run_tool(self, tool_name: str, args: dict) -> str:
        try:
            if "tavily" in tool_name.lower() or "search" in tool_name.lower():
                from app.services.search_service import tavily_search
                result, _ = await tavily_search(args.get("query", ""))
                return result
            return json.dumps({"error": f"未知工具: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": str(e)})
