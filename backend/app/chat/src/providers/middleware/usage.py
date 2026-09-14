"""Middleware usage : comptage des tokens (entrée → avant l'appel, sortie →
après) pour alimenter le ledger RequestUsage et les métriques.

Réutilise l'heuristique de usage.py (chars/4 uniforme tous providers).
En streaming, le décompte de sortie est cumulé event par event.
"""

from __future__ import annotations

from typing import AsyncIterator

from ...usage import estimate_tokens
from .base import LLMContext, LLMMiddleware


def _extract_content(ctx: LLMContext, result: dict) -> str:
    content = result.get("content")
    return content or ""


def _extract_delta(event: dict | str) -> str:
    if isinstance(event, str):
        return event
    return event.get("content") or ""


class UsageMiddleware(LLMMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self.name = "usage"

    async def before(self, ctx: LLMContext) -> None:
        # BudgetMiddleware calcule déjà input_tokens ; s'il est absent
        # (middleware non monté), on le fait ici par les mêmes helpers.
        if not ctx.input_tokens:
            from ...usage import estimate_messages_tokens

            ctx.input_tokens = estimate_messages_tokens(ctx.messages, ctx.tools)

    async def after(self, ctx: LLMContext, result: dict) -> dict:
        ctx.output_tokens = estimate_tokens(_extract_content(ctx, result))
        return result

    async def stream(self, ctx: LLMContext, stream: AsyncIterator[dict]) -> AsyncIterator[dict]:
        acc = 0
        async for event in stream:
            acc += estimate_tokens(_extract_delta(event))
            yield event
        ctx.output_tokens = acc