from __future__ import annotations

import json
from typing import AsyncIterator

import openai
from xcore.sdk import get_logger

from .base import ProviderUnavailableError

logger = get_logger("chat.providers.openai_compat")


class OpenAICompatProvider:
    """
    Client OpenAI générique — sert à la fois OpenAI et Grok (xAI), dont
    l'API est compatible OpenAI : seule l'URL de base change.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        # Sans ceci, le SDK openai retombe sur son défaut (600s) — un
        # provider qui traîne bloque le flux SSE entier ce temps-là, sans
        # jamais émettre d'événement "error" (constaté : un appel resté
        # bloqué après "start", aucun texte, aucune erreur, juste un flux
        # muet — voir l'incident ask_user qui n'affichait jamais sa question).
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model
        self._system_prompt = system_prompt

    def _build_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        full_messages = list(messages)
        if self._system_prompt:
            full_messages = [{"role": "system", "content": self._system_prompt}, *full_messages]
        return full_messages

    async def chat(
        self,
        messages: list[dict[str, str]],
        images_b64: list[str] | None = None,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model, messages=self._build_messages(messages)
            )
        except openai.RateLimitError as exc:
            raise ProviderUnavailableError(
                f"{self._model} : limite de débit atteinte, réessaie dans un instant."
            ) from exc
        except openai.AuthenticationError as exc:
            raise ProviderUnavailableError(
                f"{self._model} : clé API invalide ou absente."
            ) from exc
        except openai.APIStatusError as exc:
            logger.warning("réponse %s (%s) : %s", self._model, exc.status_code, exc.response.text)
            raise ProviderUnavailableError(
                f"{self._model} a répondu une erreur ({exc.status_code})."
            ) from exc
        except openai.APIConnectionError as exc:
            logger.warning("connexion à %s échouée : %r (cause: %r)", self._model, exc, exc.__cause__)
            raise ProviderUnavailableError(f"Impossible de joindre {self._model}.") from exc
        except openai.APIError as exc:
            # Filet générique : toute autre erreur SDK non couverte ci-dessus
            # (ex. validation d'arguments d'outil côté SDK) ne doit jamais
            # planter le flux ASGI en silence — voir chat_routes.py::event_stream.
            logger.warning("erreur %s non catégorisée : %r", self._model, exc)
            raise ProviderUnavailableError(f"{self._model} a rencontré une erreur.") from exc

        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        images_b64: list[str] | None = None,
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._model, messages=self._build_messages(messages), stream=True
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except openai.RateLimitError as exc:
            raise ProviderUnavailableError(
                f"{self._model} : limite de débit atteinte, réessaie dans un instant."
            ) from exc
        except openai.AuthenticationError as exc:
            raise ProviderUnavailableError(f"{self._model} : clé API invalide ou absente.") from exc
        except openai.APIStatusError as exc:
            logger.warning("réponse %s (%s) : %s", self._model, exc.status_code, exc.response.text)
            raise ProviderUnavailableError(
                f"{self._model} a répondu une erreur ({exc.status_code})."
            ) from exc
        except openai.APIConnectionError as exc:
            logger.warning("connexion à %s échouée : %r (cause: %r)", self._model, exc, exc.__cause__)
            raise ProviderUnavailableError(f"Impossible de joindre {self._model}.") from exc
        except openai.APIError as exc:
            logger.warning("erreur %s non catégorisée : %r", self._model, exc)
            raise ProviderUnavailableError(f"{self._model} a rencontré une erreur.") from exc

    def _to_wire_messages(self, turns: list[dict]) -> list[dict]:
        """Traduit les tours génériques (voir chat/src/tools.py) vers le
        format OpenAI : arguments d'appel d'outil en JSON string (pas un
        dict), résultat d'outil corrélé par tool_call_id (pas par nom) —
        les ids sont générés ici, à la volée, puisque les tours génériques
        n'en portent pas (round-trip garanti par l'ordre, jamais rompu :
        tools.py ajoute toujours un message 'tool' par appel, dans le même
        ordre que les tool_calls qui les précèdent)."""
        out: list[dict] = []
        pending_ids: list[str] = []
        for msg in turns:
            role = msg["role"]
            if role == "assistant" and msg.get("tool_calls"):
                calls = msg["tool_calls"]
                pending_ids = [f"call_{i}" for i in range(len(calls))]
                out.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or None,
                        "tool_calls": [
                            {
                                "id": pending_ids[i],
                                "type": "function",
                                "function": {
                                    "name": c["name"],
                                    "arguments": json.dumps(c["arguments"], ensure_ascii=False),
                                },
                            }
                            for i, c in enumerate(calls)
                        ],
                    }
                )
            elif role == "tool":
                tool_call_id = pending_ids.pop(0) if pending_ids else "call_0"
                out.append(
                    {"role": "tool", "tool_call_id": tool_call_id, "content": msg.get("content", "")}
                )
            else:
                out.append({"role": role, "content": msg.get("content", "")})
        return out

    @staticmethod
    def _parse_tool_calls(raw_calls: list) -> list[dict]:
        calls = []
        for c in raw_calls or []:
            fn = c.function
            try:
                arguments = json.loads(fn.arguments) if fn.arguments else {}
            except json.JSONDecodeError:
                arguments = {}
            calls.append({"name": fn.name, "arguments": arguments})
        return calls

    async def chat_with_tools(
        self, messages: list[dict[str, str]], tools: list[dict] | None = None, images_b64=None
    ) -> dict:
        kwargs: dict = {
            "model": self._model,
            "messages": self._to_wire_messages(self._build_messages(messages)),
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.RateLimitError as exc:
            raise ProviderUnavailableError(
                f"{self._model} : limite de débit atteinte, réessaie dans un instant."
            ) from exc
        except openai.AuthenticationError as exc:
            raise ProviderUnavailableError(f"{self._model} : clé API invalide ou absente.") from exc
        except openai.APIStatusError as exc:
            logger.warning("réponse %s (%s) : %s", self._model, exc.status_code, exc.response.text)
            raise ProviderUnavailableError(
                f"{self._model} a répondu une erreur ({exc.status_code})."
            ) from exc
        except openai.APIConnectionError as exc:
            logger.warning("connexion à %s échouée : %r (cause: %r)", self._model, exc, exc.__cause__)
            raise ProviderUnavailableError(f"Impossible de joindre {self._model}.") from exc
        except openai.APIError as exc:
            logger.warning("erreur %s non catégorisée : %r", self._model, exc)
            raise ProviderUnavailableError(f"{self._model} a rencontré une erreur.") from exc

        message = response.choices[0].message
        return {"content": message.content, "tool_calls": self._parse_tool_calls(message.tool_calls)}

    async def chat_stream_with_tools(
        self, messages: list[dict[str, str]], tools: list[dict] | None = None, images_b64=None
    ) -> AsyncIterator[dict]:
        kwargs: dict = {
            "model": self._model,
            "messages": self._to_wire_messages(self._build_messages(messages)),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        # L'API OpenAI fragmente un appel d'outil sur plusieurs chunks
        # (name/arguments arrivent en morceaux, indexés) — on accumule par
        # index jusqu'à la fin du flux avant de reconstituer l'appel complet.
        fragments: dict[int, dict] = {}
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield {"type": "delta", "content": delta.content}
                for tc in delta.tool_calls or []:
                    slot = fragments.setdefault(tc.index, {"name": None, "arguments": ""})
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
        except openai.RateLimitError as exc:
            raise ProviderUnavailableError(
                f"{self._model} : limite de débit atteinte, réessaie dans un instant."
            ) from exc
        except openai.AuthenticationError as exc:
            raise ProviderUnavailableError(f"{self._model} : clé API invalide ou absente.") from exc
        except openai.APIStatusError as exc:
            logger.warning("réponse %s (%s) : %s", self._model, exc.status_code, exc.response.text)
            raise ProviderUnavailableError(
                f"{self._model} a répondu une erreur ({exc.status_code})."
            ) from exc
        except openai.APIConnectionError as exc:
            logger.warning("connexion à %s échouée : %r (cause: %r)", self._model, exc, exc.__cause__)
            raise ProviderUnavailableError(f"Impossible de joindre {self._model}.") from exc
        except openai.APIError as exc:
            # C'est ici qu'atterrit par exemple une validation d'arguments
            # d'outil rejetée côté SDK (ex. un champ requis renvoyé à null
            # par le modèle) — jusqu'ici non catégorisée, ça remontait comme
            # exception Python brute et tuait le flux ASGI entier sans
            # jamais envoyer d'event "error" au client (constaté avec
            # mcp_word_create_document sur Groq : /author, /title = null).
            logger.warning("erreur %s non catégorisée : %r", self._model, exc)
            raise ProviderUnavailableError(f"{self._model} a rencontré une erreur.") from exc

        if fragments:
            calls = []
            for idx in sorted(fragments):
                slot = fragments[idx]
                try:
                    arguments = json.loads(slot["arguments"]) if slot["arguments"] else {}
                except json.JSONDecodeError:
                    arguments = {}
                calls.append({"name": slot["name"] or "", "arguments": arguments})
            yield {"type": "tool_calls", "calls": calls}
