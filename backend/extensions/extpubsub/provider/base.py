from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional


class PubSubProvider(ABC):

    @property
    def _inbox(self) -> Dict[str, List[dict]]:
        # Ne dépend pas d'un appel à __init__ : les adaptateurs concrets
        # (Redis/HiveMQ/Memory) ne rappellent pas systématiquement super().__init__().
        store = self.__dict__.get("_inbox_store")
        if store is None:
            store = {}
            self.__dict__["_inbox_store"] = store
        return store

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def publish(self, channel: str, event: dict) -> None:
        pass

    @abstractmethod
    async def stream(
        self,
        channel: str,
        user_id: Optional[str] = None,
        filter_key: str = "user_id"
    ) -> AsyncGenerator[str, None]:
        pass

    # ── Inbox (offline delivery) ────────────────────────────────────────
    # Défaut en mémoire process-local ; RedisAdapter surcharge avec un
    # stockage persistant/partagé entre instances.

    async def push_inbox(self, user_id: str, event: dict) -> None:
        self._inbox.setdefault(user_id, []).append(event)

    async def flush_inbox(self, user_id: str) -> List[dict]:
        return self._inbox.pop(user_id, [])

    async def inbox_count(self, user_id: str) -> int:
        return len(self._inbox.get(user_id, []))
