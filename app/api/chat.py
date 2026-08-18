import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from llm_core.manager import ModelManager
from llm_core.base import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


def _ok(data, message=""):
    return {"code": 200, "message": message, "data": data}


def _err(message, code=500):
    return {"code": code, "message": message, "data": None}


@router.post("/{model_id}")
async def chat(model_id: str, request: ChatRequest):
    """按 model_id 路由到对应平台执行普通（非流式）对话。"""
    logger.info(f"POST /chat/{model_id} 消息数={len(request.messages)}")
    try:
        adapter = ModelManager.get_adapter(model_id)
        resp = await adapter.chat(request)
        return _ok({
            "model_id": model_id,
            "content": resp.content,
            "usage": resp.usage,
        })
    except ValueError as e:
        return _err(str(e), code=404)
    except Exception as e:
        logger.error(f"对话失败 model={model_id}: {e}")
        return _err(f"对话失败: {e}")


@router.post("/{model_id}/stream")
async def chat_stream(model_id: str, request: ChatRequest):
    """按 model_id 路由到对应平台执行流式对话（SSE）。"""
    logger.info(f"POST /chat/{model_id}/stream 消息数={len(request.messages)}")
    try:
        adapter = ModelManager.get_adapter(model_id)
    except ValueError as e:
        return _err(str(e), code=404)
    except Exception as e:
        return _err(f"创建 adapter 失败: {e}")

    async def generate():
        try:
            async for chunk in adapter.stream_chat(request):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            logger.error(f"流式对话失败 model={model_id}: {e}")
            yield f"event: error\ndata: {e}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
