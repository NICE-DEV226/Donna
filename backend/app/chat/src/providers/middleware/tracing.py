"""Middleware tracing : spans LLM en mémoire + request_id contextvar.

Garde un store in-process des dernières spans (dict), libérable via une
route exposition (GET /app/chat/traces). request_id propagé via contextvar
pour corréler plusieurs appels LLM d'une même requête utilisateur.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid

from xcore.sdk import get_logger

from .base import LLMContext, LLMMiddleware

logger = get_logger("chat.middleware.tracing")

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "chat_request_id", default=""
)


def current_request_id() -> str:
    return _request_id_var.get()


def set_request_id(request_id: str | None) -> str:
    """Injecte (ou génère) un request_id dans le contexte courant — appelé
    par la couche HTTP (chat_routes) à chaque requête, puis réutilisé par
    TraceMiddleware pour corréler les spans."""
    rid = request_id or uuid.uuid4().hex[:12]
    _request_id_var.set(rid)
    return rid


class TraceMiddleware(LLMMiddleware):
    def __init__(self, max_spans: int = 500) -> None:
        super().__init__()
        self._max_spans = int(max_spans)
        self._spans: list[dict] = []
        self._lock = threading.Lock()
        self.name = "tracing"

    def _push(self, ctx: LLMContext) -> None:
        span = ctx.to_span()
        span["ts"] = time.time()
        with self._lock:
            self._spans.append(span)
            if len(self._spans) > self._max_spans:
                self._spans = self._spans[-self._max_spans :]

    async def before(self, ctx: LLMContext) -> None:
        ctx.request_id = _request_id_var.get()

    async def after(self, ctx: LLMContext, result: dict) -> dict:
        self._push(ctx)
        return result

    async def after_stream(self, ctx: LLMContext) -> None:
        self._push(ctx)

    async def on_error(self, ctx: LLMContext, exc: Exception) -> dict:
        ctx.error = exc
        self._push(ctx)
        raise exc

    def spans(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return list(reversed(self._spans))[: int(limit)]

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()