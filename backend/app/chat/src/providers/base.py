from __future__ import annotations

from typing import Protocol


class ProviderUnavailableError(Exception):
    """Le provider LLM est injoignable ou a répondu avec une erreur."""


class LLMProvider(Protocol):
    async def chat(
        self, messages: list[dict[str, str]], images_b64: list[str] | None = None
    ) -> str: ...
