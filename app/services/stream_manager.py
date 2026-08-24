"""Redis Stream 流式事件管理器

架构: Agent → Redis Stream → FastAPI SSE → Frontend
支持断线重连: 前端传 lastEventId，后端从 Redis Stream 恢复
"""
import json
import logging
from typing import AsyncGenerator, Optional
import redis.asyncio as redis

logger = logging.getLogger(__name__)

STREAM_PREFIX = "stream:chat:"
STREAM_MAX_LEN = 2000   # 每个会话最多保留 2000 条事件
STREAM_TTL = 3600        # 1 小时过期


class StreamManager:
    """Redis Stream 流式事件管理器"""

    def __init__(self, redis_url: str):
        self._redis: Optional[redis.Redis] = None
        self._redis_url = redis_url
        self._available = False

    async def start(self):
        try:
            self._redis = redis.Redis.from_url(
                self._redis_url,
                decode_responses=True,
                protocol=2,
                socket_connect_timeout=5,
                socket_timeout=65,  # 必须大于 XREAD BLOCK 时长(60s)，否则阻塞读被提前打断
            )
            await self._redis.ping()
            self._available = True
            logger.info("StreamManager connected to Redis")
        except Exception as e:
            logger.warning(f"StreamManager Redis unavailable, fallback to direct SSE: {e}")
            self._available = False
            self._redis = None

    async def close(self):
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass

    @property
    def available(self) -> bool:
        return self._available

    def _key(self, conversation_id: str) -> str:
        return f"{STREAM_PREFIX}{conversation_id}"

    async def publish(self, conversation_id: str, event_data: dict) -> Optional[str]:
        """发布事件到 Redis Stream，返回 stream event ID"""
        if not self._available or not self._redis:
            return None
        try:
            entry_id = await self._redis.xadd(
                self._key(conversation_id),
                {"data": json.dumps(event_data, ensure_ascii=False)},
                maxlen=STREAM_MAX_LEN,
            )
            # 设置 TTL（每次发布刷新）
            await self._redis.expire(self._key(conversation_id), STREAM_TTL)
            return entry_id
        except Exception as e:
            logger.warning(f"Stream publish failed: {e}")
            return None

    async def stream_exists(self, conversation_id: str) -> bool:
        """检查 stream 是否存在"""
        if not self._available or not self._redis:
            return False
        try:
            return bool(await self._redis.exists(self._key(conversation_id)))
        except Exception:
            return False

    async def read_from(
        self,
        conversation_id: str,
        last_event_id: str = "0",
    ) -> AsyncGenerator[dict, None]:
        """从 Redis Stream 读取事件（ last_event_id 之后的所有事件）

        先同步读取已有事件，再 BLOCK 等待新事件，直到流结束。
        """
        if not self._available or not self._redis:
            return

        key = self._key(conversation_id)
        last_id = last_event_id

        try:
            # 阶段1: 同步读取已有事件
            while True:
                entries = await self._redis.xread(
                    {key: last_id},
                    count=100,
                    block=500,
                )
                if not entries or not entries[0][1]:
                    break
                for entry_id, fields in entries[0][1]:
                    last_id = entry_id
                    data = json.loads(fields.get("data", "{}"))
                    data["_stream_event_id"] = entry_id
                    yield data
                    # 收到 done 信号，停止
                    if data.get("type") == "done":
                        return

            # 阶段2: 实时等待新事件（BLOCK 60秒超时）
            while True:
                entries = await self._redis.xread(
                    {key: last_id},
                    count=1,
                    block=60000,
                )
                if not entries or not entries[0][1]:
                    break  # 超时或流不存在
                for entry_id, fields in entries[0][1]:
                    last_id = entry_id
                    data = json.loads(fields.get("data", "{}"))
                    data["_stream_event_id"] = entry_id
                    yield data
                    if data.get("type") == "done":
                        return

        except Exception as e:
            logger.warning(f"Stream read error: {e}")

    async def cleanup(self, conversation_id: str):
        """删除指定会话的 Redis Stream"""
        if not self._available or not self._redis:
            return
        try:
            await self._redis.delete(self._key(conversation_id))
        except Exception as e:
            logger.warning(f"Stream cleanup failed: {e}")


# 全局单例
stream_manager: Optional[StreamManager] = None


def init_stream_manager(redis_url: str) -> StreamManager:
    global stream_manager
    stream_manager = StreamManager(redis_url)
    return stream_manager


def get_stream_manager() -> Optional[StreamManager]:
    return stream_manager
