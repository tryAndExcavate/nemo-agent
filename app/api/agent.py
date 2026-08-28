"""Agent API 路由 — Redis Stream 解耦架构

解耦: Agent 后台任务 → Redis Stream ← SSE 读取 ← Frontend
断连: 客户端断开不影响 Agent，重连从 Redis Stream 恢复
"""
import json
import logging
import asyncio
from typing import AsyncGenerator
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from app.config import settings
from app.services.task_manager import task_manager
from app.services.stream_manager import get_stream_manager
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

# 保持后台 agent 任务的引用，防止 GC 回收
_background_tasks: dict[str, asyncio.Task] = {}


def _resolve_llm() -> tuple[AsyncOpenAI, str]:
    active_id = ConfigStore.get_active_model_id()
    if active_id:
        try:
            cfg = ConfigStore.get_decrypted(active_id)
            if cfg.get("base_url") and cfg.get("model_name"):
                client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
                logger.info(f"Agent 使用基座激活模型: {cfg['name']}({cfg['model_name']})")
                return client, cfg["model_name"]
        except Exception as e:
            logger.warning(f"读取基座激活模型失败，回退: {e}")
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


# ===== 后台 Agent 任务：写入 Redis Stream =====

async def _run_agent_to_stream(agent, conversation_id: str, agent_gen):
    """Agent 作为后台任务运行，所有事件写入 Redis Stream。与 HTTP 连接完全解耦。"""
    sm = get_stream_manager()
    try:
        async for event in agent_gen:
            if sm and sm.available:
                try:
                    event_data = json.loads(event) if event.startswith("{") else {"type": "raw", "content": event}
                    await sm.publish(conversation_id, event_data)
                except Exception:
                    pass
        # 写入 done 标记
        if sm and sm.available:
            try:
                await sm.publish(conversation_id, {"type": "done"})
            except Exception:
                pass
    except asyncio.CancelledError:
        logger.info(f"Agent task cancelled for {conversation_id}")
    except Exception as e:
        logger.error(f"Agent background task error: {e}")
        if sm and sm.available:
            try:
                await sm.publish(conversation_id, {"type": "error", "content": str(e)})
                await sm.publish(conversation_id, {"type": "done"})
            except Exception:
                pass
    finally:
        _background_tasks.pop(conversation_id, None)
        await agent._close_db()


async def _start_agent_task(agent, conversation_id: str, agent_gen) -> asyncio.Task:
    """启动后台 agent 任务（await 完成旧 Stream 清理，保证顺序正确）"""
    # 取消同会话的旧任务
    old = _background_tasks.pop(conversation_id, None)
    if old and not old.done():
        old.cancel()

    # 清理旧 Redis Stream，确保 _read_stream_sse("0") 从新任务开始读，不重放旧事件
    sm = get_stream_manager()
    if sm and sm.available:
        try:
            await sm.cleanup(conversation_id)
        except Exception:
            pass

    task = asyncio.create_task(_run_agent_to_stream(agent, conversation_id, agent_gen))
    _background_tasks[conversation_id] = task
    return task


# ===== SSE 读取端点：从 Redis Stream 读取 =====

async def _read_stream_sse(conversation_id: str, last_event_id: str = "0") -> AsyncGenerator[str, None]:
    """从 Redis Stream 读取事件并转为 SSE 格式"""
    sm = get_stream_manager()
    if not sm or not sm.available:
        yield "data: [DONE]\n\n"
        return

    last_id = last_event_id

    try:
        while True:
            entries = await sm._redis.xread(
                {sm._key(conversation_id): last_id},
                count=50,
                block=60000,
            )
            if not entries or not entries[0][1]:
                break
            for entry_id, fields in entries[0][1]:
                last_id = entry_id
                data = json.loads(fields.get("data", "{}"))
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("type") == "done":
                    return
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.warning(f"Stream read error for {conversation_id}: {e}")


# ===== API 端点 =====

@router.get("/chat/stream")
async def web_search_stream(
    query: str = Query(...),
    conversationId: str = Query(...),
    untilMessageId: int | None = Query(None),
    regenerateFromId: str | None = Query(None),
    parentId: str | None = Query(None),
):
    """智能问答 - Agent 后台运行，SSE 从 Redis Stream 读取"""
    from app.agents.web_search import WebSearchReActAgent
    llm_client, model = _resolve_llm()
    agent = WebSearchReActAgent(llm_client=llm_client, model=model, tools=WEB_SEARCH_TOOLS, max_rounds=5)

    # 启动后台 agent 任务（不绑定 HTTP 连接）
    await _start_agent_task(agent, conversationId,
                            agent.stream(conversationId, query, until_message_id=untilMessageId, regenerate_from_id=regenerateFromId,
                                         parent_id=int(parentId) if parentId else None))

    # SSE 从 Redis Stream 读取（客户端断开不影响 agent）
    return StreamingResponse(
        _read_stream_sse(conversationId, last_event_id="0"),
        media_type="text/event-stream",
    )


@router.get("/reconnect/{conversationId}")
async def reconnect_stream(conversationId: str, lastEventId: str = Query("0")):
    """从 Redis Stream 恢复断线的 SSE 流"""
    return StreamingResponse(
        _read_stream_sse(conversationId, last_event_id=lastEventId),
        media_type="text/event-stream",
    )


@router.get("/active/{conversationId}")
async def check_active_stream(conversationId: str):
    """检查 Redis Stream 中是否有该会话的活跃流"""
    sm = get_stream_manager()
    if not sm or not sm.available:
        return {"active": False}
    return {"active": await sm.stream_exists(conversationId)}


@router.get("/file/stream")
async def file_stream(
    query: str = Query(...),
    conversationId: str = Query(...),
    fileId: str = Query(...),
):
    """文件问答"""
    from app.agents.file_qa import FileReActAgent
    llm_client, model = _resolve_llm()
    agent = FileReActAgent(llm_client=llm_client, model=model, tools=FILE_TOOLS, max_rounds=5)
    await _start_agent_task(agent, conversationId, agent.stream(conversationId, query, fileId))
    return StreamingResponse(_read_stream_sse(conversationId), media_type="text/event-stream")


@router.get("/pptx/stream")
async def pptx_stream(query: str = Query(...), conversationId: str = Query(...)):
    """PPT 生成"""
    from app.agents.ppt_builder import PPTBuilderAgent
    llm_client, model = _resolve_llm()
    agent = PPTBuilderAgent(llm_client=llm_client, model=model, tools=WEB_SEARCH_TOOLS)
    await _start_agent_task(agent, conversationId, agent.stream(conversationId, query))
    return StreamingResponse(_read_stream_sse(conversationId), media_type="text/event-stream")


@router.get("/deep/stream")
async def deep_stream(query: str = Query(...), conversationId: str = Query(...)):
    """深度研究"""
    from app.agents.deep_research import PlanExecuteAgent
    llm_client, model = _resolve_llm()
    agent = PlanExecuteAgent(llm_client=llm_client, model=model, tools=WEB_SEARCH_TOOLS, max_rounds=3)
    await _start_agent_task(agent, conversationId, agent.stream(conversationId, query))
    return StreamingResponse(_read_stream_sse(conversationId), media_type="text/event-stream")


@router.get("/skills/stream")
async def skills_stream(
    query: str = Query(...),
    conversationId: str = Query(...),
    fileId: str | None = Query(None),
):
    """Skills 智能问答"""
    from app.agents.skills import SkillsReActAgent
    if settings.skills_directory:
        set_skills_directory(settings.skills_directory)
    llm_client, model = _resolve_llm()
    agent = SkillsReActAgent(llm_client=llm_client, model=model, tools=SKILLS_TOOLS, max_rounds=10)
    await _start_agent_task(agent, conversationId, agent.stream(conversationId, query, fileId))
    return StreamingResponse(_read_stream_sse(conversationId), media_type="text/event-stream")


@router.get("/stop")
async def stop_agent(conversationId: str = Query(...)):
    """停止 Agent 执行"""
    # 取消后台任务
    task = _background_tasks.pop(conversationId, None)
    if task and not task.done():
        task.cancel()
    success = await task_manager.stop_task(conversationId)
    return {"success": success, "message": "已停止执行" if success else "没有找到正在执行的任务或已停止"}
