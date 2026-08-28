import asyncio
import json
from typing import AsyncGenerator, Dict, Optional, Set

from .base import PubSubProvider
from .section import MemoryConfig


class MemoryAdapter(PubSubProvider):
    def __init__(self, config: MemoryConfig) -> None:
        self._conf = config
        self._queues: Dict[str, Set[asyncio.Queue]] = {}

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        for channel in self._queues:
            for q in self._queues[channel]:
                await q.put(None)  # Sentinel to close generators
        self._queues.clear()

    async def publish(self, channel: str, event: dict) -> None:
        if channel in self._queues:
            for q in self._queues[channel]:
                await q.put(event)

    async def stream(
        self,
        channel: str,
        user_id: Optional[str] = None,
        filter_key: str = "user_id"
    ) -> AsyncGenerator[str, None]:
        q = asyncio.Queue()
        if channel not in self._queues:
            self._queues[channel] = set()
        self._queues[channel].add(q)

        try:
            while True:
                event = await q.get()
                if event is None:
                    break

                if user_id is None or event.get(filter_key) == user_id:
                    yield f"data: {json.dumps(event)}\n\n"

                await asyncio.sleep(self._conf.heartbeat)
        finally:
            if channel in self._queues:
                self._queues[channel].remove(q)
                if not self._queues[channel]:
                    del self._queues[channel]
