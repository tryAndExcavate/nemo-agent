import asyncio
import uuid
import time
import logging
from typing import Any
import redis.asyncio as redis
from app.config import settings

logger = logging.getLogger(__name__)

TASK_KEY_PREFIX = "agent:task-mode.css:"
STOP_TOPIC_NAME = "agent:stop"
TASK_TTL_SECONDS = 30 * 60  # 30 minutes
TTL_REFRESH_INTERVAL = 5 * 60  # 5 minutes


class TaskInfo:
    def __init__(self, queue: asyncio.Queue, agent_type: str):
        self.queue = queue
        self.agent_type = agent_type
        self.create_time = time.time()
        self.cancel_event = asyncio.Event()


class TaskManager:
    """分布式任务管理器。

    优先使用 Redis 做分布式锁和跨实例停止广播。
    如果 Redis 不可用，自动降级为仅本地内存模式。
    """

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._instance_id = str(uuid.uuid4())[:8]
        self._tasks: dict[str, TaskInfo] = {}
        self._refresh_task: asyncio.Task | None = None
        self._redis_available = False
        logger.info(f"TaskManager initialized, instanceId={self._instance_id}")

    async def start(self):
        try:
            self._redis = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                protocol=2,  # 强制使用 RESP2，兼容低版本 Redis
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self._redis.ping()
            self._redis_available = True

            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(**{STOP_TOPIC_NAME: self._handle_stop_message})
            self._refresh_task = asyncio.create_task(self._refresh_loop())
            # 清理所有残留的 task-mode.css key（防止重启后旧 key 阻塞新实例）
            stale_keys = await self._redis.keys(f"{TASK_KEY_PREFIX}*")
            if stale_keys:
                await self._redis.delete(*stale_keys)
                logger.info(f"Cleaned {len(stale_keys)} stale task-mode.css keys on startup")
            logger.info(f"TaskManager started with Redis, instanceId={self._instance_id}")
        except Exception as e:
            logger.warning(f"Redis 不可用，降级为本地模式: {e}")
            self._redis_available = False
            self._redis = None
            self._pubsub = None

    async def stop(self):
        if self._refresh_task:
            self._refresh_task.cancel()
        for conversation_id in list(self._tasks.keys()):
            await self._local_remove_task(conversation_id)
        if self._pubsub and self._redis_available:
            try:
                await self._pubsub.unsubscribe(STOP_TOPIC_NAME)
            except Exception:
                pass
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass

    async def _handle_stop_message(self, message):
        conversation_id = message["data"]
        task = self._tasks.pop(conversation_id, None)
        if task:
            logger.info(f"Remote stop: conversationId={conversation_id}, instanceId={self._instance_id}")
            task.cancel_event.set()
            await self._local_remove_task(conversation_id)

    async def register_task(self, conversation_id: str, agent_type: str = "unknown") -> TaskInfo | None:
        if conversation_id in self._tasks:
            logger.warning(f"Conversation {conversation_id} already has local task-mode.css")
            return None

        if self._redis_available:
            try:
                key = f"{TASK_KEY_PREFIX}{conversation_id}"
                acquired = await self._redis.set(key, self._instance_id, nx=True, ex=TASK_TTL_SECONDS)
                if not acquired:
                    holder = await self._redis.get(key)
                    logger.warning(f"Conversation {conversation_id} already running on instance {holder}")
                    return None
            except Exception as e:
                logger.warning(f"Redis register failed, using local-only: {e}")

        task_info = TaskInfo(asyncio.Queue(), agent_type)
        self._tasks[conversation_id] = task_info
        logger.info(f"Registered task-mode.css: conversationId={conversation_id}, agentType={agent_type}")
        return task_info

    def get_task(self, conversation_id: str) -> TaskInfo | None:
        return self._tasks.get(conversation_id)

    async def stop_task(self, conversation_id: str) -> bool:
        # 本地停止
        task = self._tasks.pop(conversation_id, None)
        if task:
            logger.info(f"Local stop: conversationId={conversation_id}")
            task.cancel_event.set()
            if self._redis_available:
                try:
                    await self._redis_delete_key(conversation_id)
                except Exception:
                    pass
            return True

        # Redis 广播（仅当本地没有时）
        if self._redis_available:
            try:
                key = f"{TASK_KEY_PREFIX}{conversation_id}"
                exists = await self._redis.exists(key)
                if not exists:
                    return False
                holder = await self._redis.get(key)
                if holder == self._instance_id:
                    return False
                receivers = await self._redis.publish(STOP_TOPIC_NAME, conversation_id)
                logger.info(f"Published stop broadcast: conversationId={conversation_id}, receivers={receivers}")
                return True
            except Exception as e:
                logger.warning(f"Redis stop broadcast failed: {e}")

        return False

    async def has_running_task(self, conversation_id: str) -> bool:
        if conversation_id in self._tasks:
            return True
        if self._redis_available:
            try:
                return await self._redis.exists(f"{TASK_KEY_PREFIX}{conversation_id}") > 0
            except Exception:
                pass
        return False

    async def _redis_delete_key(self, conversation_id: str):
        key = f"{TASK_KEY_PREFIX}{conversation_id}"
        holder = await self._redis.get(key)
        if holder == self._instance_id:
            await self._redis.delete(key)

    async def _local_remove_task(self, conversation_id: str):
        """仅清理本地状态"""
        self._tasks.pop(conversation_id, None)

    async def _refresh_loop(self):
        while True:
            try:
                await asyncio.sleep(TTL_REFRESH_INTERVAL)
                if not self._redis_available:
                    continue
                for conversation_id in list(self._tasks.keys()):
                    key = f"{TASK_KEY_PREFIX}{conversation_id}"
                    holder = await self._redis.get(key)
                    if holder == self._instance_id:
                        await self._redis.expire(key, TASK_TTL_SECONDS)
                    else:
                        logger.warning(f"Task key ownership changed: {conversation_id}")
                        self._tasks.pop(conversation_id, None)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TTL refresh error: {e}")


task_manager = TaskManager()
