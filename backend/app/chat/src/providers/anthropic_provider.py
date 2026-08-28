from __future__ import annotations

from typing import AsyncIterator

import anthropic
from xcore.sdk import get_logger

from .base import ProviderUnavailableError

logger = get_logger("chat.providers.anthropic")


class AnthropicProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-5",
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        timeout: float = 30.0,
    ) -> None:
        # Voir le même paramètre sur OpenAICompatProvider : sans lui, un
        # appel qui traîne bloque tout le flux SSE sans jamais renvoyer
        # d'erreur au frontend.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens

    def _split(self, messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
        # L'API Anthropic prend "system" en paramètre top-level, pas comme
        # message role="system" dans la liste (non supporté sur Sonnet 5) —
        # on les extrait et on les fusionne avec le prompt de personnalité.
        system_parts = [self._system_prompt] if self._system_prompt else []
        turns = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                turns.append({"role": m["role"], "content": m["content"]})
        return ("\n\n".join(system_parts) if system_parts else None), turns

    async def chat(
        self,
        messages: list[dict[str, str]],
        images_b64: list[str] | None = None,
    ) -> str:
        system, turns = self._split(messages)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=turns,
            )
        except anthropic.RateLimitError as exc:
            raise ProviderUnavailableError(
                "Anthropic : limite de débit atteinte, réessaie dans un instant."
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderUnavailableError(
                "Anthropic : clé API invalide ou absente."
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailableError(
                f"Anthropic a répondu une erreur ({exc.status_code})."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError(
                "Impossible de joindre l'API Anthropic."
            ) from exc
        except anthropic.APIError as exc:
            logger.warning("erreur Anthropic non catégorisée : %r", exc)
            raise ProviderUnavailableError("Anthropic a rencontré une erreur.") from exc

        if response.stop_reason == "refusal":
            return "Je préfère ne pas répondre à ça."

        return next((b.text for b in response.content if b.type == "text"), "")

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        images_b64: list[str] | None = None,
    ) -> AsyncIterator[str]:
        system, turns = self._split(messages)

        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=turns,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.RateLimitError as exc:
            raise ProviderUnavailableError(
                "Anthropic : limite de débit atteinte, réessaie dans un instant."
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderUnavailableError("Anthropic : clé API invalide ou absente.") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailableError(
                f"Anthropic a répondu une erreur ({exc.status_code})."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError("Impossible de joindre l'API Anthropic.") from exc
        except anthropic.APIError as exc:
            logger.warning("erreur Anthropic non catégorisée : %r", exc)
            raise ProviderUnavailableError("Anthropic a rencontré une erreur.") from exc

    def _to_anthropic_turns(
        self, turns: list[dict]
    ) -> tuple[str | None, list[dict]]:
        """Traduit les tours génériques (voir chat/src/tools.py) vers le
        format Anthropic : un appel d'outil est un bloc de contenu
        'tool_use' (input déjà un dict, pas une string JSON comme OpenAI),
        son résultat un message role=user avec un bloc 'tool_result' —
        corrélation par tool_use_id généré ici, à la volée (voir la même
        note dans openai_compat_provider._to_wire_messages : l'ordre
        garanti par tools.py suffit)."""
        system_parts = [self._system_prompt] if self._system_prompt else []
        out: list[dict] = []
        pending_ids: list[str] = []

        for msg in turns:
            role = msg["role"]
            if role == "system":
                system_parts.append(msg["content"])
            elif role == "assistant" and msg.get("tool_calls"):
                calls = msg["tool_calls"]
                pending_ids = [f"call_{i}" for i in range(len(calls))]
                content = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                content.extend(
                    {"type": "tool_use", "id": pending_ids[i], "name": c["name"], "input": c["arguments"]}
                    for i, c in enumerate(calls)
                )
                out.append({"role": "assistant", "content": content})
            elif role == "tool":
                tool_use_id = pending_ids.pop(0) if pending_ids else "call_0"
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": msg.get("content", ""),
                            }
                        ],
                    }
                )
            else:
                out.append({"role": role, "content": msg["content"]})

        return ("\n\n".join(system_parts) if system_parts else None), out

    @staticmethod
    def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
        out = []
        for t in tools:
            fn = t["function"]
            out.append(
                {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return out

    async def chat_with_tools(
        self, messages: list[dict[str, str]], tools: list[dict] | None = None, images_b64=None
    ) -> dict:
        system, turns = self._to_anthropic_turns(messages)
        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": turns,
        }
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise ProviderUnavailableError(
                "Anthropic : limite de débit atteinte, réessaie dans un instant."
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderUnavailableError("Anthropic : clé API invalide ou absente.") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailableError(
                f"Anthropic a répondu une erreur ({exc.status_code})."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError("Impossible de joindre l'API Anthropic.") from exc
        except anthropic.APIError as exc:
            logger.warning("erreur Anthropic non catégorisée : %r", exc)
            raise ProviderUnavailableError("Anthropic a rencontré une erreur.") from exc

        text = "\n".join(b.text for b in response.content if b.type == "text")
        calls = [
            {"name": b.name, "arguments": b.input} for b in response.content if b.type == "tool_use"
        ]
        return {"content": text or None, "tool_calls": calls}

    async def chat_stream_with_tools(
        self, messages: list[dict[str, str]], tools: list[dict] | None = None, images_b64=None
    ) -> AsyncIterator[dict]:
        system, turns = self._to_anthropic_turns(messages)
        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": turns,
        }
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield {"type": "delta", "content": event.delta.text}
                final = await stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise ProviderUnavailableError(
                "Anthropic : limite de débit atteinte, réessaie dans un instant."
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderUnavailableError("Anthropic : clé API invalide ou absente.") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailableError(
                f"Anthropic a répondu une erreur ({exc.status_code})."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError("Impossible de joindre l'API Anthropic.") from exc
        except anthropic.APIError as exc:
            logger.warning("erreur Anthropic non catégorisée : %r", exc)
            raise ProviderUnavailableError("Anthropic a rencontré une erreur.") from exc

        calls = [{"name": b.name, "arguments": b.input} for b in final.content if b.type == "tool_use"]
        if calls:
            yield {"type": "tool_calls", "calls": calls}
