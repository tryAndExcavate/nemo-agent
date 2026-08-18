import logging
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from app.config import settings
from app.services.task_manager import task_manager
from llm_core.store import ConfigStore
from app.tools.skills_tool import set_skills_directory, SCHEMA as SKILL_SCHEMA
from app.tools.file_content import TOOL_SCHEMA as FILE_CONTENT_SCHEMA
from app.tools.file_system import (
    READ_FILE_SCHEMA, WRITE_FILE_SCHEMA, EDIT_FILE_SCHEMA,
    LIST_FILES_SCHEMA, GLOB_FILES_SCHEMA,
)
from app.tools.grep_tool import SCHEMA as GREP_SCHEMA
from app.tools.bash_tool import SCHEMA as BASH_SCHEMA

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


def _resolve_llm() -> tuple[AsyncOpenAI, str]:
    """返回业务 Agent 真正要用的 (AsyncOpenAI client, model_name)。

    优先使用基座激活模型（可插拔大模型基座里当前挂载的模型）；
    未激活/已失效时回退到 settings 的 DeepSeek，保证业务不中断。
    """
    active_id = ConfigStore.get_active_model_id()
    print(active_id)
    if active_id:
        try:
            cfg = ConfigStore.get_decrypted(active_id)
            if cfg.get("base_url") and cfg.get("model_name"):
                print(cfg.get("model_name"))
                client = AsyncOpenAI(
                    api_key=cfg["api_key"],
                    base_url=cfg["base_url"],
                )
                logger.info(f"Agent 使用基座激活模型: {cfg['name']}({cfg['model_name']})")
                return client, cfg["model_name"]
        except Exception as e:
            logger.warning(f"读取基座激活模型失败，回退深色 fallback: {e}")
    logger.info("Agent 使用默认 DeepSeek 模型")
    return (
        AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url),
        settings.deepseek_chat_model,
    )


# Tool schemas
TAVILY_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "tavily_search",
        "description": "使用 Tavily 搜索引擎搜索互联网信息，获取实时、全面的搜索结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询关键词"},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"], "description": "搜索深度"},
            },
            "required": ["query"],
        },
    },
}

WEB_SEARCH_TOOLS = [TAVILY_SEARCH_SCHEMA]
FILE_TOOLS = [FILE_CONTENT_SCHEMA]
SKILLS_TOOLS = [TAVILY_SEARCH_SCHEMA, FILE_CONTENT_SCHEMA, SKILL_SCHEMA,
                READ_FILE_SCHEMA, WRITE_FILE_SCHEMA, EDIT_FILE_SCHEMA,
                LIST_FILES_SCHEMA, GLOB_FILES_SCHEMA, GREP_SCHEMA, BASH_SCHEMA]


@router.get("/chat/stream")
async def web_search_stream(
    query: str = Query(...),
    conversationId: str = Query(...),
):
    """智能问答 - Web Search Agent"""
    from app.agents.web_search import WebSearchReActAgent
    llm_client, model = _resolve_llm()
    print(llm_client)
    agent = WebSearchReActAgent(
        llm_client=llm_client,
        model=model,
        tools=WEB_SEARCH_TOOLS,
        max_rounds=5,
    )

    async def generate():
        async for event in agent.stream(conversationId, query):
            yield f"data: {event}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/file/stream")
async def file_stream(
    query: str = Query(...),
    conversationId: str = Query(...),
    fileId: str = Query(...),
):
    """文件问答 - File Agent"""
    from app.agents.file_qa import FileReActAgent
    llm_client, model = _resolve_llm()
    agent = FileReActAgent(
        llm_client=llm_client,
        model=model,
        tools=FILE_TOOLS,
        max_rounds=5,
    )

    async def generate():
        async for event in agent.stream(conversationId, query, fileId):
            yield f"data: {event}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/pptx/stream")
async def pptx_stream(
    query: str = Query(...),
    conversationId: str = Query(...),
):
    """PPT 生成 - PPT Builder Agent"""
    from app.agents.ppt_builder import PPTBuilderAgent
    llm_client, model = _resolve_llm()
    agent = PPTBuilderAgent(
        llm_client=llm_client,
        model=model,
        tools=WEB_SEARCH_TOOLS,
    )

    async def generate():
        async for event in agent.stream(conversationId, query):
            yield f"data: {event}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/deep/stream")
async def deep_stream(
    query: str = Query(...),
    conversationId: str = Query(...),
):
    """深度研究 - Plan-Execute Agent"""
    from app.agents.deep_research import PlanExecuteAgent
    llm_client, model = _resolve_llm()
    agent = PlanExecuteAgent(
        llm_client=llm_client,
        model=model,
        tools=WEB_SEARCH_TOOLS,
        max_rounds=3,
    )

    async def generate():
        async for event in agent.stream(conversationId, query):
            yield f"data: {event}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/skills/stream")
async def skills_stream(
    query: str = Query(...),
    conversationId: str = Query(...),
    fileId: str | None = Query(None),
):
    """Skills 智能问答 - Skills Agent"""
    from app.agents.skills import SkillsReActAgent
    if settings.skills_directory:
        set_skills_directory(settings.skills_directory)

    llm_client, model = _resolve_llm()
    agent = SkillsReActAgent(
        llm_client=llm_client,
        model=model,
        tools=SKILLS_TOOLS,
        max_rounds=10,
    )

    async def generate():
        async for event in agent.stream(conversationId, query, fileId):
            yield f"data: {event}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/stop")
async def stop_agent(conversationId: str = Query(...)):
    """停止Agent执行"""
    success = await task_manager.stop_task(conversationId)
    return {
        "success": success,
        "message": "已停止执行" if success else "没有找到正在执行的任务或已停止",
    }
