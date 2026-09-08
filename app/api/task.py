"""任务模式 API 端点 — QueryEngine 驱动

前端通过 POST /agent/task/start 提交任务目标，
后端启动 QueryEngine 后台任务，事件通过 Redis Stream 推送。
前端通过 GET /agent/task/stream (复用现有 reconnect 通道) 读取 SSE。
"""
import json
import logging
import asyncio
import time
from pathlib import Path
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.config import settings
from app.services.task_manager import task_manager
from app.services.stream_manager import get_stream_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent/task", tags=["task"])

# 后台任务引用
_background_tasks: dict[str, asyncio.Task] = {}
# 每个会话的任务完成信号（stop 等待它确认旧任务真正结束）
_task_done_events: dict[str, asyncio.Event] = {}
# 每个会话的 QueryEngine 实例（供 /compress 等接口调用）
_engines: dict[str, "QueryEngine"] = {}
# per-conversation 互斥锁：确保同一会话同一时刻只有一个 agent loop 运行
_conversation_locks: dict[str, asyncio.Lock] = {}


def _resolve_llm():
    """复用现有的 LLM 解析逻辑"""
    from llm_core.store import ConfigStore
    from openai import AsyncOpenAI
    active_id = ConfigStore.get_active_model_id()
    if active_id:
        cfg = ConfigStore.get_decrypted(active_id)
        if cfg.get("base_url") and cfg.get("model_name") and cfg.get("api_key"):
            client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
            return client, cfg["model_name"]
    return (
        AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url),
        settings.deepseek_chat_model,
    )


class TaskStartRequest(BaseModel):
    goal: str
    conversation_id: str
    workspace_path: str = "."


class TaskStopRequest(BaseModel):
    conversation_id: str


async def _run_task_to_stream(conversation_id: str, events, lock: asyncio.Lock | None = None):
    """QueryEngine 事件 → Redis Stream（后台任务，持有 per-conversation lock）"""
    sm = get_stream_manager()
    total_input_tokens = 0
    total_output_tokens = 0
    last_context_usage = {}
    _was_cancelled = False
    start_time = time.time()
    try:
        async for event in events:
            # 累积 token 用量
            if event.type.value == "message_complete" and event.data:
                usage = event.data.get("usage") if isinstance(event.data, dict) else None
                if usage:
                    total_input_tokens += usage.get("input_tokens", 0)
                    total_output_tokens += usage.get("output_tokens", 0)
            # 捕获最新的上下文用量
            if event.type.value == "llm_input" and event.data:
                last_context_usage = event.data.get("context_usage", {})
            from app.services.task_stream import _stream_event_to_sse
            sse_data = _stream_event_to_sse(event)
            # 跳过 QueryEngine 的空 DONE —— 由下方发布携带统计的 done 替代
            if event.type.value == "done":
                continue
            if sm and sm.available:
                try:
                    await sm.publish(conversation_id, sse_data)
                except Exception as e:
                    logger.warning(f"Task stream publish failed: {e}")
        # done 标记（正常结束时推送，携带 token 统计和耗时）
        end_time = time.time()
        if sm and sm.available:
            try:
                await sm.publish(conversation_id, {
                    "type": "done",
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                    "elapsed_sec": round(end_time - start_time, 1),
                })
            except Exception:
                pass
    except asyncio.CancelledError:
        # 被 stop 取消时：不推 done，让新任务干净启动
        _was_cancelled = True
        logger.info(f"Task cancelled for {conversation_id}")
    except Exception as e:
        logger.error(f"Task background error: {e}")
        end_time = time.time()
        if sm and sm.available:
            try:
                await sm.publish(conversation_id, {"type": "error", "content": str(e)})
                await sm.publish(conversation_id, {
                    "type": "done",
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                    "elapsed_sec": round(end_time - start_time, 1),
                })
            except Exception:
                pass
    finally:
        # 保存 token 用量与上下文窗口明细到元数据
        # 若刚被手动压缩过，跳过（compress_context 已写入最新值）
        engine = _engines.get(conversation_id)
        was_compressed = engine and getattr(engine.state, 'context_compressed', False)
        end_time_final = time.time()
        try:
            if not was_compressed:
                from app.storage.jsonl_store import JSONLSessionStore
                _store = JSONLSessionStore()
                _store.save_meta(conversation_id, {
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                    "status": "done",
                    "start_time": start_time,
                    "end_time": end_time_final,
                    "duration_sec": round(end_time_final - start_time, 1),
                    "ctx_system_tokens": last_context_usage.get("system_prompt", 0),
                    "ctx_history_tokens": last_context_usage.get("history", 0),
                    "ctx_tool_def_tokens": last_context_usage.get("tool_definitions", 0),
                    "ctx_tool_result_tokens": last_context_usage.get("tool_results", 0),
                    "ctx_input_tokens": last_context_usage.get("current_input", 0),
                })
        except Exception:
            pass
        _background_tasks.pop(conversation_id, None)
        # 通知 stop_task：旧任务已真正结束，可以安全启动新任务了
        done_evt = _task_done_events.pop(conversation_id, None)
        if done_evt:
            done_evt.set()
        # 释放 per-conversation 锁（允许下一个 agent loop 启动）
        if lock and lock.locked():
            lock.release()
        # 注意：不要在这里发布 done 事件！
        # 如果任务被取消（CancelledError），新任务可能已经清理了 Redis Stream，
        # 此时发布 done 会创建新的 Redis Stream，导致前端收到残留 done 事件。


@router.post("/start")
async def start_task(req: TaskStartRequest):
    """启动任务模式 — 启动 QueryEngine，后台运行"""
    from app.agents.query_engine import QueryEngineConfig, QueryEngine
    from app.tools.registry import get_tools
    from app.memory.live_view import LiveMemoryStore
    from app.subagent.policy import AgentExecutionContext

    llm_client, model = _resolve_llm()
    tools = get_tools()

    # 注册表是工作区唯一来源：从这里解析出正式 cwd，
    # GlobalState、QueryEngine 与落盘 meta 全部使用同一 cwd
    from app.services.workspace_registry import resolve_cwd, ensure_registered
    cwd = resolve_cwd(req.workspace_path)
    ensure_registered(cwd, active=True)

    # 获取/创建工作区级 GlobalState
    from app.models.state import ensure_global_state
    ensure_global_state(cwd=cwd, model=model)

    # 注入 dispatch_agent 工具（如果已注册子智能体）
    from app.subagent.registry import list_available as list_subagents
    if list_subagents():
        from app.tools.dispatch_agent_tool import DispatchAgentTool
        tools.append(DispatchAgentTool())

    # 为本次会话创建 live memory store
    live_memory_store = LiveMemoryStore(session_id=req.conversation_id)

    config = QueryEngineConfig(
        tools=tools,
        llm_client=llm_client,
        model=model,
        conversation_id=req.conversation_id,
        cwd=cwd,
        custom_system_prompt=_build_task_system_prompt(),
        max_turns=15,
    )

    engine = QueryEngine(config)

    # 注入子智能体执行上下文（dispatch_agent 工具所需）
    engine._extra_tool_context = {
        "execution_context": AgentExecutionContext.root(req.conversation_id, max_depth=1),
        "live_memory_store": live_memory_store,
        "sessions_root": str(Path(".sessions").resolve()),
        "parent_config": config,
    }
    # 绑定 live memory：主 Agent 每条消息自动同步写入
    engine.live_memory_store = live_memory_store

    # AOP：始终打上记忆切面补丁（通过 config.use_memory_agent 开关控制行为）
    engine.apply_memory_agent_patch()

    # 保存 engine 引用供 /compress 等接口使用
    _engines[req.conversation_id] = engine

    # 保存任务元数据（不覆盖已有的 goal）
    from app.storage.jsonl_store import JSONLSessionStore
    _store = JSONLSessionStore()
    existing_meta = _store.load_meta(req.conversation_id)

    # 从已有 meta 恢复记忆模式偏好
    if existing_meta.get("use_memory_agent"):
        config.use_memory_agent = True

    meta_update = {
        "workspace_path": cwd,
        "model": model,
    }
    if not existing_meta.get("goal"):
        meta_update["goal"] = req.goal
    _store.save_meta(req.conversation_id, meta_update)

    # 等待同会话旧任务彻底结束（如果有的话）
    old_task = _background_tasks.pop(req.conversation_id, None)
    if old_task and not old_task.done():
        old_task.cancel()
        done_evt = _task_done_events.get(req.conversation_id)
        if done_evt:
            try:
                await asyncio.wait_for(done_evt.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning(f"Old task for {req.conversation_id} didn't finish in 5s, forcing on")

    # 获取 per-conversation 锁（阻塞到拿到锁才启动新任务，保证同一会话串行）
    lock = _conversation_locks.setdefault(req.conversation_id, asyncio.Lock())
    await lock.acquire()

    # 清理旧 Redis Stream（保证新任务读不到残留事件）
    sm = get_stream_manager()
    if sm and sm.available:
        try:
            await sm.cleanup(req.conversation_id)
        except Exception:
            pass

    # 启动后台任务（锁由 _run_task_to_stream 的 finally 释放）
    task = asyncio.create_task(
        _run_task_to_stream(req.conversation_id, engine.submit_message(req.goal), lock=lock)
    )
    _background_tasks[req.conversation_id] = task

    return {"success": True, "conversation_id": req.conversation_id}


@router.post("/stop")
async def stop_task(req: TaskStopRequest):
    """停止任务 — 等旧任务真正结束再返回（避免与新任务的 Redis Stream 竞争）"""
    task = _background_tasks.get(req.conversation_id)
    if task and not task.done():
        # 创建完成信号，等旧任务在 finally 里 set()
        done_evt = asyncio.Event()
        _task_done_events[req.conversation_id] = done_evt
        task.cancel()
        try:
            await asyncio.wait_for(done_evt.wait(), timeout=8)
        except asyncio.TimeoutError:
            logger.warning(f"Stop timeout for {req.conversation_id}, proceeding anyway")
        _task_done_events.pop(req.conversation_id, None)
    await task_manager.stop_task(req.conversation_id)
    _engines.pop(req.conversation_id, None)
    return {"success": True}


class TaskCompressRequest(BaseModel):
    conversation_id: str


def _get_or_rebuild_engine(conversation_id: str):
    """获取引擎引用；若不在内存中则从 JSONL + 元数据重建"""
    engine = _engines.get(conversation_id)
    if engine:
        return engine
    # 从元数据恢复 cwd/model 等信息
    from app.storage.jsonl_store import JSONLSessionStore
    store = JSONLSessionStore()
    meta = store.load_meta(conversation_id)
    if not meta:
        return None
    from app.agents.query_engine import QueryEngineConfig, QueryEngine
    from app.tools.registry import get_tools
    from app.subagent.policy import AgentExecutionContext
    from app.memory.live_view import LiveMemoryStore
    llm_client, fallback_model = _resolve_llm()
    cwd = meta.get("workspace_path", ".")
    model = fallback_model
    tools = get_tools()
    # 注入 dispatch_agent 工具
    from app.subagent.registry import list_available as list_subagents
    if list_subagents():
        from app.tools.dispatch_agent_tool import DispatchAgentTool
        tools.append(DispatchAgentTool())
    config = QueryEngineConfig(
        tools=tools,
        llm_client=llm_client,
        model=model,
        conversation_id=conversation_id,
        cwd=cwd,
        custom_system_prompt=_build_task_system_prompt(),
        max_turns=15,
    )
    engine = QueryEngine(config)
    # 注入 extras
    live_mem = LiveMemoryStore(session_id=conversation_id)
    engine._extra_tool_context = {
        "execution_context": AgentExecutionContext.root(conversation_id, max_depth=1),
        "live_memory_store": live_mem,
        "sessions_root": str(Path(".sessions").resolve()),
        "parent_config": config,
    }
    engine.live_memory_store = live_mem
    # AOP：打记忆切面 + 从 meta 恢复偏好
    engine.apply_memory_agent_patch()
    if meta.get("use_memory_agent"):
        config.use_memory_agent = True
    _engines[conversation_id] = engine
    return engine


@router.post("/compress")
async def compress_task_context(req: TaskCompressRequest):
    """手动压缩任务上下文：调 LLM 生成摘要，重置 context 为摘要+最近3条"""
    engine = _get_or_rebuild_engine(req.conversation_id)
    if not engine:
        return {"error": "找不到该任务"}
    result = await engine.compress_context()
    return result


@router.get("/list")
async def list_tasks():
    """列出所有任务会话（从 JSONL 文件读取）"""
    from app.storage.jsonl_store import JSONLSessionStore
    from app.models.query_engine import UserMessage, AssistantMessage

    store = JSONLSessionStore()
    tasks = []
    for conv_id in store.list_conversation_ids():
        msgs = store.load_all(conv_id)
        if not msgs:
            continue
        meta = store.load_meta(conv_id)
        goal = meta.get("goal", "")
        if not goal:
            for m in msgs:
                if isinstance(m, UserMessage):
                    goal = m.content if isinstance(m.content, str) else str(m.content)
                    break
        status = meta.get("status", "done")
        if status == "done":
            last_types = [type(m).__name__ for m in msgs[-3:]]
            if any(t == "AssistantMessage" for t in last_types) and len(msgs) < 4:
                status = "running"
        tasks.append({
            "conversation_id": conv_id,
            "goal": goal[:80],
            "message_count": len(msgs),
            "status": status,
            "workspace_path": meta.get("workspace_path", ""),
            "total_input_tokens": meta.get("total_input_tokens", 0),
            "total_output_tokens": meta.get("total_output_tokens", 0),
        })
    tasks.sort(key=lambda t: t["conversation_id"], reverse=True)
    return {"tasks": tasks[:50]}


@router.get("/load")
async def load_task(conversationId: str = Query(...)):
    """加载单个任务的完整消息历史 + 元数据"""
    from app.storage.jsonl_store import JSONLSessionStore
    from app.models.query_engine import message_to_dict

    store = JSONLSessionStore()
    msgs = store.load_all(conversationId)
    meta = store.load_meta(conversationId)
    has_meta_ctx = (
        meta.get("total_input_tokens") or meta.get("total_output_tokens")
        or any(meta.get(k, 0) for k in (
            "ctx_system_tokens", "ctx_history_tokens", "ctx_tool_def_tokens",
            "ctx_tool_result_tokens", "ctx_input_tokens",
        ))
    )
    if msgs and not has_meta_ctx:
        try:
            from app.context.context import Context
            from app.tools.registry import get_tools
            ctx = Context(
                system_prompt=_build_task_system_prompt(),
                tools=get_tools(),
                messages=msgs,
            )
            u = ctx.estimate_usage()
            meta = {
                **meta,
                "ctx_system_tokens": u.system_prompt_tokens,
                "ctx_history_tokens": u.history_tokens,
                "ctx_tool_def_tokens": u.tool_definitions_tokens,
                "ctx_tool_result_tokens": u.tool_results_tokens,
                "ctx_input_tokens": u.current_input_tokens,
                "_ctx_estimated": True,
            }
        except Exception:
            pass
    return {
        "conversation_id": conversationId,
        "messages": [message_to_dict(m) for m in msgs],
        "meta": meta,
    }


class TaskDeleteRequest(BaseModel):
    conversation_id: str


@router.post("/delete")
async def delete_task(req: TaskDeleteRequest):
    """删除任务会话（删除 JSONL 文件）"""
    from app.storage.jsonl_store import JSONLSessionStore
    store = JSONLSessionStore()
    store.delete(req.conversation_id)
    return {"success": True}


@router.get("/stream")
async def task_stream(
    conversationId: str = Query(...),
    lastEventId: str = Query("0"),
):
    """任务模式 SSE 流 — 复用 Redis Stream 读取通道"""
    sm = get_stream_manager()
    if not sm or not sm.available:
        async def empty():
            yield "data: {\"type\": \"done\"}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    async def read_sse():
        last_id = lastEventId
        try:
            while True:
                entries = await sm._redis.xread(
                    {sm._key(conversationId): last_id},
                    count=50,
                    block=60000,
                )
                if not entries or not entries[0][1]:
                    # XREAD 超时无新事件 — 检查任务是否仍在运行
                    bg_task = _background_tasks.get(conversationId)
                    if bg_task and not bg_task.done():
                        # 发送 SSE 注释心跳保活，防止代理/浏览器断开
                        yield ": heartbeat\n\n"
                        continue
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
            logger.warning(f"Task stream read error: {e}")

    return StreamingResponse(read_sse(), media_type="text/event-stream")


# ===== 记忆模式 Toggle（AOP 切面，不触碰主逻辑） =====

class MemoryAgentToggleRequest(BaseModel):
    conversation_id: str
    enabled: bool


@router.post("/memory-agent-toggle")
async def toggle_memory_agent(req: MemoryAgentToggleRequest):
    """切换记忆模式：启用后 QueryEngine 使用 memory-retriever 子智能体检索记忆。"""
    # 1. 更新 meta 持久化
    from app.storage.jsonl_store import JSONLSessionStore
    _store = JSONLSessionStore()
    _store.save_meta(req.conversation_id, {"use_memory_agent": req.enabled})

    # 2. 热更新内存中的引擎 config（如果存在）
    engine = _engines.get(req.conversation_id)
    if engine is not None:
        engine.config.use_memory_agent = req.enabled

    logger.info(f"Memory agent toggle: conv={req.conversation_id} enabled={req.enabled}")
    return {"code": 200, "message": f"记忆模式已{'启用' if req.enabled else '关闭'}", "data": {"use_memory_agent": req.enabled}}


def _build_task_system_prompt() -> str:
    """任务模式的 system prompt"""
    return """你是一个任务执行助手。用户会给你一个目标，你需要：
1. 分析目标，拆解为可执行的步骤
2. 使用可用工具逐步完成每个步骤
3. 每完成一个步骤，清晰地汇报进展
4. 遇到错误时分析原因并尝试修复
5. 最终给出任务完成的总结

结束协议（严格遵守）：
- 每次回复后，如果你判断任务已经全部完成，在回复末尾另起一行单独输出"结束"两个字
- 如果任务还没完成，不要输出"结束"，而是继续规划下一步操作并调用工具执行
- 如果你只是想给用户看一个中间方案但还没执行完，不要输出"结束"
- 只有当你确认所有目标都已达成时，才输出"结束"

工作准则：
- 主动使用工具完成任务，不要只给出建议
- 每次工具调用后检查结果是否符合预期
- 如果某步失败，分析原因后重试或换方案
- 保持回复简洁清晰，重点突出进展和结果"""
