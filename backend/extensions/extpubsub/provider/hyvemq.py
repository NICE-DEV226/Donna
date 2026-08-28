import asyncio
import json
import logging
import ssl
import uuid
from typing import AsyncGenerator, Awaitable, Callable, Optional

import aiomqtt

from .base import PubSubProvider
from .section import HivemqConfig

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Types des callbacks                                                 #
# ------------------------------------------------------------------ #

OnMessageCallback = Callable[[str, dict], Awaitable[None]]
OnConnectCallback = Callable[[], Awaitable[None]]
OnDisconnectCallback = Callable[[Exception | None], Awaitable[None]]


class HivemqAdapter(PubSubProvider):
    def __init__(self, config: HivemqConfig) -> None:
        self._conf = config
        self._client_id = str(uuid.uuid4())
        self._client: Optional["aiomqtt.Client"] = None
        self._subscriptions: set[str] = set()
        self._messages: asyncio.Queue = asyncio.Queue()
        self._connected = asyncio.Event()
        self._closing = False
        self._listen_task: Optional[asyncio.Task] = None

        # Callbacks — None par défaut, tous optionnels
        self._on_message:    Optional[OnMessageCallback] = None
        self._on_connect:    Optional[OnConnectCallback] = None
        self._on_disconnect: Optional[OnDisconnectCallback] = None

    # ------------------------------------------------------------------ #
    #  Enregistrement des callbacks                                        #
    # ------------------------------------------------------------------ #

    def on_message(self, fn: OnMessageCallback) -> "HivemqAdapter":
        """
        Appelé pour chaque message reçu sur n'importe quel channel.

        Usage :
            @client.on_message
            async def handler(topic: str, data: dict) -> None:
                print(topic, data)
        """
        self._on_message = fn
        return self

    def on_connect(self, fn: OnConnectCallback) -> "HivemqAdapter":
        """
        Appelé à chaque (re)connexion réussie.

        Usage :
            @client.on_connect
            async def handler() -> None:
                print("connecté")
        """
        self._on_connect = fn
        return self

    def on_disconnect(self, fn: OnDisconnectCallback) -> "HivemqAdapter":
        """
        Appelé à chaque déconnexion. Reçoit l'exception ou None si fermeture propre.

        Usage :
            @client.on_disconnect
            async def handler(exc: Exception | None) -> None:
                print("déconnecté", exc)
        """
        self._on_disconnect = fn
        return self

    # ------------------------------------------------------------------ #
    #  Helpers internes                                                    #
    # ------------------------------------------------------------------ #

    async def _fire_connect(self) -> None:
        if self._on_connect:
            try:
                await self._on_connect()
            except Exception as e:
                logger.error("on_connect callback error: %s", e)

    async def _fire_disconnect(self, exc: Exception | None) -> None:
        if self._on_disconnect:
            try:
                await self._on_disconnect(exc)
            except Exception as e:
                logger.error("on_disconnect callback error: %s", e)

    async def _fire_message(self, topic: str, data: dict) -> None:
        if self._on_message:
            try:
                await self._on_message(topic, data)
            except Exception as e:
                logger.error("on_message callback error: %s", e)

    # ------------------------------------------------------------------ #
    #  Parsing URL                                                         #
    # ------------------------------------------------------------------ #

    def _parse_url(self) -> tuple[str, int]:
        raw = self._conf.url
        is_mqtts = raw.startswith("mqtts://")
        url = raw.replace("mqtts://", "").replace("mqtt://", "")
        parts = url.split(":")
        host = parts[0]
        if len(parts) > 1:
            port = int(parts[1])
        else:
            port = 8883 if is_mqtts else 1883
        return host, port

    def _build_tls_context(self) -> Optional[ssl.SSLContext]:
        _, port = self._parse_url()
        if port == 8883:
            return ssl.create_default_context()
        return None

    # ------------------------------------------------------------------ #
    #  Task background — écoute + reconnexion automatique                 #
    # ------------------------------------------------------------------ #

    async def _listen(self) -> None:
        host, port = self._parse_url()
        tls_ctx = self._build_tls_context()
        reconnect_delay = 1.0

        while not self._closing:
            try:
                kwargs: dict = dict(
                    hostname=host,
                    port=port,
                    identifier=self._client_id,
                    keepalive=60,
                )
                if self._conf.username:
                    kwargs["username"] = self._conf.username
                    kwargs["password"] = self._conf.password
                if tls_ctx is not None:
                    kwargs["tls_context"] = tls_ctx

                async with aiomqtt.Client(**kwargs) as client:
                    self._client = client
                    self._connected.set()
                    reconnect_delay = 1.0
                    logger.info(
                        "Connected to HiveMQ at %s:%d (TLS: %s)",
                        host, port, tls_ctx is not None,
                    )
                    await self._fire_connect()

                    for channel in self._subscriptions:
                        await client.subscribe(channel)
                        logger.info("Re-subscribed to '%s'", channel)

                    async for message in client.messages:
                        try:
                            data = json.loads(message.payload.decode())
                            topic = str(message.topic)
                            await self._messages.put((topic, data))
                            await self._fire_message(topic, data)
                        except Exception as e:
                            logger.error("Message parse error: %s", e)

            except aiomqtt.MqttError as e:
                if self._closing:
                    break
                self._connected.clear()
                self._client = None
                logger.warning(
                    "Disconnected from HiveMQ: %s. Reconnexion dans %.0fs…",
                    e, reconnect_delay,
                )
                await self._fire_disconnect(e)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30.0)

            except Exception as e:
                if self._closing:
                    break
                self._connected.clear()
                self._client = None
                logger.error("Erreur inattendue HiveMQ: %s", e)
                await self._fire_disconnect(e)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30.0)

        # Fermeture propre → on_disconnect avec None
        await self._fire_disconnect(None)

    # ------------------------------------------------------------------ #
    #  Interface PubSubProvider                                            #
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        self._closing = False
        self._listen_task = asyncio.create_task(self._listen())

        try:
            await asyncio.wait_for(self._connected.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            self._closing = True
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            raise RuntimeError(
                "Timeout de connexion HiveMQ — vérifiez l'URL, le port et les credentials"
            )

    async def close(self) -> None:
        self._closing = True
        self._connected.clear()

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        self._client = None
        logger.info("HiveMQ déconnecté proprement")

    async def publish(self, channel: str, event: dict) -> None:
        if not self._client or not self._connected.is_set():
            raise RuntimeError("HiveMQ non connecté — publish impossible")
        await self._client.publish(channel, json.dumps(event), qos=1)

    async def stream(
        self,
        channel: str,
        user_id: Optional[str] = None,
        filter_key: str = "user_id",
    ) -> AsyncGenerator[str, None]:
        if not self._connected.is_set():
            raise RuntimeError("HiveMQ non connecté — stream impossible")

        self._subscriptions.add(channel)
        if self._client:
            await self._client.subscribe(channel)

        try:
            while True:
                if not self._connected.is_set():
                    logger.info(
                        "Stream '%s' en attente de reconnexion…", channel)
                    await self._connected.wait()

                try:
                    topic, event = await asyncio.wait_for(
                        self._messages.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                if topic == channel:
                    if user_id is None or event.get(filter_key) == user_id:
                        yield f"data: {json.dumps(event)}\n\n"

                await asyncio.sleep(self._conf.heartbeat)

        finally:
            self._subscriptions.discard(channel)
            if self._client and self._connected.is_set():
                await self._client.unsubscribe(channel)
