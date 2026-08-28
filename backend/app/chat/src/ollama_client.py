from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .providers.base import ProviderUnavailableError


class OllamaUnavailableError(ProviderUnavailableError):
    """Ollama est injoignable ou a répondu avec une erreur serveur."""


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        vision_model: str | None = None,
        system_prompt: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._vision_model = vision_model or model
        self._system_prompt = system_prompt
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    def _build_request(
        self, messages: list[dict[str, str]], images_b64: list[str] | None
    ) -> tuple[str, list[dict[str, str]]]:
        model = self._model
        if images_b64:
            model = self._vision_model
            messages = [*messages[:-1], {**messages[-1], "images": images_b64}]

        if self._system_prompt:
            messages = [{"role": "system", "content": self._system_prompt}, *messages]

        return model, messages

    async def chat(
        self,
        messages: list[dict[str, str]],
        images_b64: list[str] | None = None,
    ) -> str:
        model, full_messages = self._build_request(messages, images_b64)

        try:
            resp = await self._client.post(
                "/api/chat",
                json={"model": model, "messages": full_messages, "stream": False},
            )
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                "Impossible de joindre Ollama — vérifie qu'il tourne (ollama serve)."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaUnavailableError(
                "Ollama a mis trop de temps à répondre (timeout)."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaUnavailableError(
                f"Ollama a répondu une erreur ({exc.response.status_code}) — "
                f"modèle manquant ou requête invalide ?"
            ) from exc

        data = resp.json()
        return data["message"]["content"]

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        images_b64: list[str] | None = None,
    ) -> AsyncIterator[str]:
        model, full_messages = self._build_request(messages, images_b64)

        try:
            async with self._client.stream(
                "POST",
                "/api/chat",
                json={"model": model, "messages": full_messages, "stream": True},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                "Impossible de joindre Ollama — vérifie qu'il tourne (ollama serve)."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaUnavailableError(
                "Ollama a mis trop de temps à répondre (timeout)."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaUnavailableError(
                f"Ollama a répondu une erreur ({exc.response.status_code})."
            ) from exc

    @staticmethod
    def _parse_tool_calls(raw_calls: list[dict] | None) -> list[dict]:
        calls = []
        for c in raw_calls or []:
            fn = c.get("function", {})
            arguments = fn.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            calls.append({"name": fn.get("name", ""), "arguments": arguments})
        return calls

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        images_b64: list[str] | None = None,
    ) -> dict:
        model, full_messages = self._build_request(messages, images_b64)
        payload: dict = {"model": model, "messages": full_messages, "stream": False}
        if tools:
            payload["tools"] = tools

        try:
            resp = await self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                "Impossible de joindre Ollama — vérifie qu'il tourne (ollama serve)."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaUnavailableError(
                "Ollama a mis trop de temps à répondre (timeout)."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaUnavailableError(
                f"Ollama a répondu une erreur ({exc.response.status_code})."
            ) from exc

        message = resp.json().get("message", {})
        return {
            "content": message.get("content"),
            "tool_calls": self._parse_tool_calls(message.get("tool_calls")),
        }

    async def chat_stream_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        images_b64: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        model, full_messages = self._build_request(messages, images_b64)
        payload: dict = {"model": model, "messages": full_messages, "stream": True}
        if tools:
            payload["tools"] = tools

        collected_calls: list[dict] = []
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    message = chunk.get("message", {})
                    delta = message.get("content")
                    if delta:
                        yield {"type": "delta", "content": delta}
                    raw_calls = message.get("tool_calls")
                    if raw_calls:
                        collected_calls.extend(self._parse_tool_calls(raw_calls))
                    if chunk.get("done"):
                        break
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                "Impossible de joindre Ollama — vérifie qu'il tourne (ollama serve)."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaUnavailableError(
                "Ollama a mis trop de temps à répondre (timeout)."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaUnavailableError(
                f"Ollama a répondu une erreur ({exc.response.status_code})."
            ) from exc

        if collected_calls:
            yield {"type": "tool_calls", "calls": collected_calls}

    async def aclose(self) -> None:
        await self._client.aclose()
