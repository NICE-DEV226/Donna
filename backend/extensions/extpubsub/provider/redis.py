import asyncio
import json
import logging
from typing import AsyncGenerator, List, Optional

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from .base import PubSubProvider
from .section import RedisConfig

logger = logging.getLogger(__name__)

_INBOX_KEY_PREFIX = "pubsub:inbox:"
_INBOX_MAX_SIZE = 200


class RedisAdapter(PubSubProvider):

    def __init__(self, config: RedisConfig) -> None:
        self._conf = config
        self.svc: Optional[Redis] = None
        self._pool: Optional[ConnectionPool] = None
        self._pubsub_pool: Optional[ConnectionPool] = None

    async def connect(self):
        try:
            self._pool = ConnectionPool.from_url(
                url=self._conf.url,
                decode_responses=True,
                max_connections=self._conf.max_connections,
            )
            self.svc = Redis(connection_pool=self._pool)
            # Pool dédié aux souscriptions pubsub (longues durées)
            self._pubsub_pool = ConnectionPool.from_url(
                url=self._conf.url,
                decode_responses=True,
                max_connections=self._conf.max_connections,
            )
            # Test connection
            await self.svc.ping()
            logger.info(f"Connected to Redis at {self._conf.url}")
        except RedisError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def close(self):
        if self.svc:
            await self.svc.close()
        if self._pool:
            await self._pool.disconnect()
        if self._pubsub_pool:
            await self._pubsub_pool.disconnect()
        return True, "closed"

    async def publish(self, channel: str, event: dict):
        if not self.svc:
            raise RuntimeError(
                "Redis provider not initialized. Call connect() first.")

        try:
            await self.svc.publish(
                channel=channel, message=json.dumps(event)
            )
        except RedisError as e:
            logger.error(f"Error publishing to Redis: {e}")
            raise

    async def stream(
        self,
        channel: str,
        user_id: Optional[str] = None,
        filter_key: str = "user_id",
    ) -> AsyncGenerator[str, None]:
        if not self.svc:
            raise RuntimeError("Redis provider not initialized")

        pubsub_client = Redis(connection_pool=self._pubsub_pool)
        pubsub = pubsub_client.pubsub()
        await pubsub.subscribe(channel)

        try:
            while True:
                try:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0
                    )

                    if msg and msg["type"] == "message":
                        event = json.loads(msg["data"])

                        if user_id is None or event.get(filter_key) == user_id:
                            yield f"data: {json.dumps(event)}\n\n"

                except RedisError as e:
                    logger.error(f"Redis stream error: {e}")
                    await asyncio.sleep(1)  # Backoff

                await asyncio.sleep(self._conf.heartbeat)

        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await pubsub_client.close()

    # ── Inbox (offline delivery) — persisté dans Redis, partagé entre instances ──

    async def push_inbox(self, user_id: str, event: dict) -> None:
        if not self.svc:
            raise RuntimeError("Redis provider not initialized")
        key = f"{_INBOX_KEY_PREFIX}{user_id}"
        try:
            await self.svc.rpush(key, json.dumps(event))
            await self.svc.ltrim(key, -_INBOX_MAX_SIZE, -1)
        except RedisError as e:
            logger.error(f"Error pushing to inbox for {user_id}: {e}")
            raise

    async def flush_inbox(self, user_id: str) -> List[dict]:
        if not self.svc:
            raise RuntimeError("Redis provider not initialized")
        key = f"{_INBOX_KEY_PREFIX}{user_id}"
        try:
            async with self.svc.pipeline(transaction=True) as pipe:
                raw_items, _ = await (
                    pipe.lrange(key, 0, -1).delete(key).execute()
                )
        except RedisError as e:
            logger.error(f"Error flushing inbox for {user_id}: {e}")
            raise
        items = []
        for raw in raw_items:
            try:
                items.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return items

    async def inbox_count(self, user_id: str) -> int:
        if not self.svc:
            raise RuntimeError("Redis provider not initialized")
        key = f"{_INBOX_KEY_PREFIX}{user_id}"
        try:
            return await self.svc.llen(key)
        except RedisError as e:
            logger.error(f"Error counting inbox for {user_id}: {e}")
            raise
