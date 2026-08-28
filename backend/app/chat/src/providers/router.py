from __future__ import annotations

from typing import Any, AsyncIterator

from xcore.sdk import get_logger

from .base import ProviderUnavailableError

logger = get_logger("chat.providers.router")


class ProviderRouter:
    """
    Routage par tâche :
    - texte pur : provider cloud configuré par défaut s'il y en a un, sinon Ollama.
    - vision (images) : provider vision dédié s'il est configuré (ex: un
      modèle Groq différent du modèle texte par défaut — nécessaire, un
      modèle texte-seul ne "voit" rien), sinon repli sur Ollama local.
      Ollama refuse catégoriquement le tool-calling sur ses modèles vision
      (confirmé en pratique sur qwen2.5vl:3b, 400 "does not support tools") :
      un repli vers Ollama désactive donc toujours les tools, même si
      l'appelant en avait demandé.
    """

    def __init__(
        self,
        ollama_provider: Any,
        default_provider: Any | None = None,
        default_name: str = "ollama",
        vision_provider: Any | None = None,
    ) -> None:
        self._ollama = ollama_provider
        self._default = default_provider
        self._default_name = default_name
        self._vision = vision_provider

    @property
    def ollama(self) -> Any:
        """Accès direct au provider Ollama — pour les tâches légères qui
        doivent toujours rester locales (ex : titre de conversation),
        indépendamment du provider par défaut configuré pour la génération."""
        return self._ollama

    @property
    def default_name(self) -> str:
        """Nom du provider actif pour la génération de texte — peut changer
        en cours de route via set_default (endpoint /provider), donc pas
        forcément celui lu au démarrage dans plugin.yaml."""
        return self._default_name

    def set_default(self, provider: Any | None, name: str) -> None:
        """Change le provider de génération EN MÉMOIRE, sans redémarrage —
        voir POST /app/chat/provider. Ne persiste pas dans plugin.yaml : un
        redémarrage du serveur revient à la config configurée au démarrage."""
        self._default = provider
        self._default_name = name

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        images_b64: list[str] | None = None,
        force_ollama: bool = False,
    ) -> dict:
        """
        force_ollama : imposé par l'appelant (voir tools.py) une fois qu'un
        repli a déjà eu lieu dans le même tour d'appels d'outils — évite de
        retenter le cloud (et de reprendre un rate limit en pleine figure) à
        chaque round alors qu'on sait déjà qu'il est indisponible.
        """
        if images_b64 and not force_ollama:
            provider = self._vision or self._ollama
            try:
                return await provider.chat_with_tools(messages, tools=tools, images_b64=images_b64)
            except ProviderUnavailableError as exc:
                if provider is self._ollama:
                    raise
                logger.warning("repli vision vers Ollama (provider vision indisponible) : %s", exc)
                # Ollama ne fait jamais tools+vision ensemble (voir docstring
                # de classe) — le repli force donc tools=None, pas ce que
                # l'appelant avait demandé.
                result = await self._ollama.chat_with_tools(messages, tools=None, images_b64=images_b64)
                result["fell_back_to_ollama"] = True
                return result

        if self._default is None or force_ollama:
            return await self._ollama.chat_with_tools(messages, tools=tools, images_b64=images_b64)
        try:
            return await self._default.chat_with_tools(messages, tools=tools)
        except ProviderUnavailableError as exc:
            logger.warning(
                "repli vers Ollama (%s indisponible) : %s", self._default_name, exc
            )
            result = await self._ollama.chat_with_tools(messages, tools=tools, images_b64=images_b64)
            # Signal consommé par tools.py::run_chat_with_tools pour rester
            # sur Ollama le reste du tour plutôt que retenter le cloud à
            # chaque round d'appels d'outils — jamais persisté ni renvoyé au client.
            result["fell_back_to_ollama"] = True
            return result

    async def chat_stream_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        images_b64: list[str] | None = None,
        force_ollama: bool = False,
    ) -> AsyncIterator[dict]:
        if images_b64 and not force_ollama:
            provider = self._vision or self._ollama
            if provider is self._ollama:
                async for event in self._ollama.chat_stream_with_tools(
                    messages, tools=tools, images_b64=images_b64
                ):
                    yield event
                return

            produced_output = False
            fallback_reason: str | None = None
            try:
                async for event in provider.chat_stream_with_tools(
                    messages, tools=tools, images_b64=images_b64
                ):
                    produced_output = True
                    yield event
                return
            except ProviderUnavailableError as exc:
                if produced_output:
                    raise
                fallback_reason = str(exc)
                logger.warning("repli vision vers Ollama (provider vision indisponible) : %s", exc)

            yield {
                "type": "provider_fallback",
                "from": "vision",
                "to": "ollama",
                "reason": fallback_reason,
            }
            # Ollama ne fait jamais tools+vision ensemble (voir docstring de classe).
            async for event in self._ollama.chat_stream_with_tools(
                messages, tools=None, images_b64=images_b64
            ):
                yield event
            return

        if self._default is None or force_ollama:
            async for event in self._ollama.chat_stream_with_tools(
                messages, tools=tools, images_b64=images_b64
            ):
                yield event
            return

        produced_output = False
        fallback_reason = None
        try:
            async for event in self._default.chat_stream_with_tools(messages, tools=tools):
                produced_output = True
                yield event
            return
        except ProviderUnavailableError as exc:
            # Une réponse déjà partiellement partie au client ne peut pas être
            # reprise proprement par un autre provider — on laisse l'erreur
            # remonter plutôt que de tronquer/dupliquer le message en cours.
            if produced_output:
                raise
            fallback_reason = str(exc)
            logger.warning(
                "repli vers Ollama (%s indisponible) : %s", self._default_name, fallback_reason
            )

        # Signalé au client (voir chat_routes.py::event_stream) avant de
        # reprendre en local, sur le même modèle que les tool_call — de la
        # transparence sur ce qui se passe, pas juste un silence puis du texte.
        yield {
            "type": "provider_fallback",
            "from": self._default_name,
            "to": "ollama",
            "reason": fallback_reason,
        }
        async for event in self._ollama.chat_stream_with_tools(
            messages, tools=tools, images_b64=images_b64
        ):
            yield event

    async def aclose(self) -> None:
        await self._ollama.aclose()
