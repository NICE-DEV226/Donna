import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

from xcore.services import BaseService, ServiceStatus

from .provider import (HivemqAdapter, MemoryAdapter, PubSubConf,
                    PubSubProvider, RedisAdapter)


class PubSubClient(BaseService):
    """
    Extension PubSub pour XCore.
    Cette classe est instanciée par le ServiceContainer de XCore
    qui lui passe la section 'pubsub' du fichier xcore.yaml.
    """

    name = "pubsub"

    def __init__(self, config: dict) -> None:
        super().__init__()
        self._status = ServiceStatus.INITIALIZING

        self.conf = PubSubConf(**config)
        self.provider: Optional[PubSubProvider] = None
        self._active_streams = 0

        if self.conf.provider == 'redis':
            self.provider = RedisAdapter(config=self.conf.redis)
        elif self.conf.provider == 'hivemq':
            self.provider = HivemqAdapter(config=self.conf.hivemq)
        elif self.conf.provider == 'memory':
            self.provider = MemoryAdapter(config=self.conf.memory)

        self._status = ServiceStatus.READY

    async def init(self) -> None:
        if self.provider:
            await self.provider.connect()
            self._status = ServiceStatus.READY
        else:
            self._status = ServiceStatus.DEGRADED

    async def shutdown(self) -> None:
        if self.provider:
            await self.provider.close()
        self._status = ServiceStatus.STOPPED

    @property
    def active_streams(self) -> int:
        return self._active_streams

    async def publish(self, channel: str, data: dict) -> bool:
        """Publie un message (dict) sur un channel. Retourne le succès.

        Si `data` porte un `user_id`, le message est aussi déposé dans
        l'inbox de cet utilisateur pour livraison différée (reconnexion SSE).
        """
        if not self.provider:
            raise RuntimeError("PubSub provider non initialisé")
        try:
            await self.provider.publish(channel, data)
        except Exception:
            return False

        user_id = data.get("user_id")
        if user_id:
            try:
                await self.provider.push_inbox(user_id, {**data, "channel": channel})
            except Exception:
                pass
        return True

    async def publish_many(self, channels: List[str], data: dict) -> Dict[str, bool]:
        """Publie le même message sur plusieurs channels."""
        return {channel: await self.publish(channel, data) for channel in channels}

    async def flush_inbox(self, user_id: str) -> List[dict]:
        """Retourne et vide les messages en attente pour un utilisateur (SSE reconnect)."""
        if not self.provider:
            raise RuntimeError("PubSub provider non initialisé")
        return await self.provider.flush_inbox(user_id)

    async def inbox_count(self, user_id: str) -> int:
        if not self.provider:
            raise RuntimeError("PubSub provider non initialisé")
        return await self.provider.inbox_count(user_id)

    async def stream(
        self,
        channels: List[str],
        user_id: str,
        filter_key: str = "user_id",
        unfiltered_channels: Optional[set] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream SSE fusionné sur plusieurs channels, préfixé `event: <channel>`.

        `unfiltered_channels` : canaux pour lesquels aucun filtrage par
        `user_id` n'est appliqué (diffusion globale/tenant, dont les messages
        ne portent jamais ce champ par construction) — l'appelant est
        responsable d'avoir autorisé l'abonné sur ces canaux en amont, cette
        méthode ne fait que transporter le choix (audit XPulse Constat 2).
        """
        if not self.provider:
            raise RuntimeError("PubSub provider non initialisé")

        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        async def _pump(channel: str) -> None:
            try:
                effective_user_id = None if (unfiltered_channels and channel in unfiltered_channels) else user_id
                async for chunk in self.provider.stream(channel, effective_user_id, filter_key):
                    await queue.put(f"event: {channel}\n{chunk}")
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                await queue.put(SENTINEL)

        tasks = [asyncio.create_task(_pump(channel)) for channel in channels]
        self._active_streams += 1
        done_count = 0
        try:
            while done_count < len(tasks):
                item = await queue.get()
                if item is SENTINEL:
                    done_count += 1
                    continue
                yield item
        finally:
            self._active_streams -= 1
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    async def bulk_publish(self, channel: str, identified: List[str], data: dict) -> None:
        """Publie un message à plusieurs destinataires (un envoi par user_id)."""
        for user_id in identified:
            await self.publish(channel, {**data, "user_id": user_id})

    def get_status(self) -> dict[str, Any]:
        return {
            "provider": self.conf.provider,
            "status": self._status,
            "is_ready": self.is_ready,
        }

    async def health_check(self) -> tuple[bool, str]:
        if self.provider:
            return True, "service working"
        return False, "service not working"

    def status(self):

        return {
            "provider": self.conf.provider,
            "status": self._status.value
        }
