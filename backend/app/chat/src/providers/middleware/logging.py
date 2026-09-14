"""Middleware logging : ligne structurée par appel LLM (provider, durée,
tokens, replis). L'observabilité brute (spans détaillées) est ailleurs
(tracing) — ici c'est la trace readable pour les logs du serveur.
"""

from __future__ import annotations

from xcore.sdk import get_logger

from .base import LLMContext, LLMMiddleware

logger = get_logger("chat.middleware.logging")


class LoggingMiddleware(LLMMiddleware):
    def __init__(self, level: str = "info") -> None:
        super().__init__()
        self._level = level
        self.name = "logging"

    def _emit(self, ctx: LLMContext) -> None:
        span = ctx.to_span()
        rec = {
            "event": "llm_call",
            "provider": span["provider"],
            "model": span["model"] or None,
            "request_id": span["request_id"] or None,
            "streaming": span["streaming"],
            "elapsed_ms": span["elapsed_ms"],
            "input_tokens": span["input_tokens"],
            "output_tokens": span["output_tokens"],
            "cached": span["cached"],
            "attempts": span["attempts"],
            "error": span["error"],
            "tags": span["tags"] or None,
            "nb_messages": span["nb_messages"],
        }
        if self._level == "debug":
            logger.debug("%s", rec)
        else:
            logger.info("%s", rec)

    async def after(self, ctx: LLMContext, result: dict) -> dict:
        # Le output_tokens est déjà compté par UsageMiddleware (avant/after).
        self._emit(ctx)
        return result

    async def after_stream(self, ctx: LLMContext) -> None:
        self._emit(ctx)

    async def on_error(self, ctx: LLMContext, exc: Exception) -> dict:
        ctx.error = exc
        self._emit(ctx)
        raise exc