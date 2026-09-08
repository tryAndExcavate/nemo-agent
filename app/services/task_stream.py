"""StreamEvent → Redis Stream 桥接。

QueryEngine 产生的 StreamEvent 通过此模块转换为前端 SSE 格式并推入 Redis Stream，
复用现有的 StreamManager 管道。
"""
import asyncio
import json
import logging
from typing import AsyncIterator

from app.models.query_engine import StreamEvent, StreamEventType
from app.services.stream_manager import get_stream_manager

logger = logging.getLogger(__name__)


def _stream_event_to_sse(event: StreamEvent) -> dict:
    """将 StreamEvent 转换为前端期望的 SSE JSON 格式"""
    if event.type == StreamEventType.TEXT_DELTA:
        return {"type": "text", "content": event.data}

    elif event.type == StreamEventType.TOOL_USE_START:
        name = event.data.get("name", "") if isinstance(event.data, dict) else ""
        return {"type": "tool_start", "tool": name, "data": event.data}

    elif event.type == StreamEventType.TOOL_RESULT:
        return {"type": "tool_result", "data": event.data}

    elif event.type == StreamEventType.MESSAGE_COMPLETE:
        usage = event.data.get("usage") if isinstance(event.data, dict) else None
        return {"type": "message_complete", "data": event.data, "usage": usage}

    elif event.type == StreamEventType.LLM_INPUT:
        return {"type": "llm_input", "data": event.data}

    elif event.type == StreamEventType.LLM_OUTPUT:
        return {"type": "llm_output", "data": event.data}

    elif event.type == StreamEventType.TURN_LIMIT_EXCEEDED:
        return {"type": "error", "content": f"已达最大轮次限制 ({event.data.get('turn', '?')})"}

    elif event.type == StreamEventType.BUDGET_EXCEEDED:
        return {"type": "error", "content": "已超出 token 预算"}

    elif event.type == StreamEventType.SYSTEM_INFO:
        msg = event.data.get("msg", "") if isinstance(event.data, dict) else str(event.data)
        return {"type": "info", "content": msg}

    elif event.type == StreamEventType.ERROR:
        error_msg = event.data.get("error", "") if isinstance(event.data, dict) else str(event.data)
        return {"type": "error", "content": error_msg}

    elif event.type == StreamEventType.DONE:
        return {"type": "done"}

    return {"type": "raw", "content": str(event.data)}


async def publish_query_events(
    conversation_id: str,
    events: AsyncIterator[StreamEvent],
) -> None:
    """将 QueryEngine 的 StreamEvent 流推入 Redis Stream。

    作为后台 asyncio.Task 运行，与 HTTP 连接完全解耦。
    """
    sm = get_stream_manager()
    try:
        async for event in events:
            sse_data = _stream_event_to_sse(event)
            if sm and sm.available:
                try:
                    await sm.publish(conversation_id, sse_data)
                except Exception as e:
                    logger.warning(f"Stream publish failed: {e}")
        # 写入 done 标记
        if sm and sm.available:
            try:
                await sm.publish(conversation_id, {"type": "done"})
            except Exception:
                pass
    except asyncio.CancelledError:
        logger.info(f"Query task cancelled for {conversation_id}")
    except Exception as e:
        logger.error(f"Query background task error: {e}")
        if sm and sm.available:
            try:
                await sm.publish(conversation_id, {"type": "error", "content": str(e)})
                await sm.publish(conversation_id, {"type": "done"})
            except Exception:
                pass
