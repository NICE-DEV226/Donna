"""Résilience fournisseurs : retry + circuit breaker.

- RetryMiddleware : pipeline — réessaie l'appel complet (non-streaming) sur
  ProviderUnavailableError avec backoff, un nombre borné de fois. En
  streaming on ne réessaie JAMAIS : un flux déjà partiellement émis au
  client ne peut pas être repris proprement (via le ProviderRouter le repli
  Ollama gère déjà le cas "rien émis").

- CircuitBreakerProvider : wrapper de SLOT (un provider cloud/vision) porté
  par le ProviderRouter — processus : NORMAL → OPEN (N échecs consécutifs)
  → HALF_OPEN (après recovery_timeout, un test call) → NORMAL (succès) ou
  OPEN (échec du test). Quand OPEN, l'appel lève CircuitOpenError — sous-
  classe de ProviderUnavailableError → le repli Ollama du router se
  déclenche naturellement. Le breaker est placé AUTOUR du slot, pas autour
  du router complet, pour connaître la cause exacte d'un échec.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from xcore.sdk import get_logger

from ..base import ProviderUnavailableError
from .base import LLMContext, LLMMiddleware, LLMMiddlewareError

logger = get_logger("chat.middleware.resilience")


class CircuitOpenError(LLMMiddlewareError, ProviderUnavailableError):
    """Circuit breaker ouvert — le slot provider est court-circuité."""


# ── Pipeline : retry ─────────────────────────────────────────────────────────

class RetryMiddleware(LLMMiddleware):
    def __init__(self, max_attempts: int = 2, backoff_base: float = 1.0) -> None:
        super().__init__()
        self._max_attempts = max(1, int(max_attempts))
        self._backoff = float(backoff_base)
        self.name = "retry"

    async def handle(self, ctx: LLMContext) -> Any:
        if ctx.streaming:
            # Jamais de retry sur un flux : la gestion "rien émis → repli"
            # est faite par le ProviderRouter.
            return await ctx.next()

        attempt = 1
        while True:
            try:
                return await ctx.next()
            except ProviderUnavailableError as exc:
                if attempt >= self._max_attempts:
                    raise
                wait = self._backoff * (2 ** (attempt - 1))
                ctx.attempts = attempt + 1
                ctx.tags[f"retry_{attempt}"] = repr(exc)
                logger.warning(
                    "retry llm %s/%s après %ss : %s",
                    attempt,
                    self._max_attempts,
                    round(wait, 2),
                    exc,
                )
                await asyncio.sleep(wait)
                attempt += 1


# ── Slot : circuit breaker ──────────────────────────────────────────────────

class CircuitBreakerProvider:
    """
    Wrapper de slot provider — même interface que les providers (chat,
    chat_stream, chat_with_tools, chat_stream_with_tools, aclose).

    Comportement :
      NORMAL    : chaque échec (ProviderUnavailableError) incrémente les
                  échecs consécutifs ; au-delà du seuil → OPEN.
      OPEN      : tout appel lève immédiatement CircuitOpenError (sans
                  contacter le provider) jusqu'à recovery_timeout.
      HALF_OPEN : un seul test call part ; succès → NORMAL (reset), échec
                  → OPEN (re-nouvelle période).
    """

    def __init__(
        self,
        provider: Any,
        name: str = "provider",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self._provider = provider
        self._name = name
        self._threshold = max(1, int(failure_threshold))
        self._recovery = float(recovery_timeout)
        self._failures = 0
        self._opened_at: float = 0.0
        self._half_open_testing = False

    # ── État ────────────────────────────────────────────────────────────────

    def is_open(self) -> bool:
        if self._failures < self._threshold:
            return False
        return time.monotonic() - self._opened_at < self._recovery

    def state(self) -> str:
        failures = self._failures
        if failures >= self._threshold:
            if time.monotonic() - self._opened_at >= self._recovery:
                return "HALF_OPEN"
            return "OPEN"
        return "NORMAL"

    def _record_success(self) -> None:
        if self._failures:
            self._failures = 0
            self._half_open_testing = False
            logger.info("circuit breaker '%s' rétabli (NORMAL)", self._name)

    def _record_failure(self, exc: Exception) -> None:
        if self._failures == 0:
            self._opened_at = time.monotonic()
        # Échec d'un probe HALF_OPEN : on repart en OPEN avec une nouvelle
        # fenêtre complète (sinon le breaker resterait bloqué en HALF_OPEN,
        # la fenêtre ne se réarmant jamais).
        if self._half_open_testing:
            self._half_open_testing = False
            self._opened_at = time.monotonic()
        self._failures += 1
        if self._failures >= self._threshold:
            logger.warning(
                "circuit breaker '%s' OUVERT (%d échecs consécutifs) — repli Ollama : %s",
                self._name,
                self._failures,
                exc,
            )
        else:
            logger.info(
                "circuit breaker '%s' : %d/%d échecs — %s",
                self._name,
                self._failures,
                self._threshold,
                exc,
            )

    def _maybe_allow(self) -> bool:
        """True si le call peut partir, False s'il est bloqué (OPEN court-
        circuité). En HALF_OPEN, un seul call de test passe."""
        if self._failures < self._threshold:
            return True
        if time.monotonic() - self._opened_at >= self._recovery:
            if self._half_open_testing:
                return False
            self._half_open_testing = True
            return True
        return False

    def _reject(self) -> None:
        raise CircuitOpenError(
            f"circuit breaker '{self._name}' ouvert — provider court-circuité, repli Ollama"
        )

    # ── Interface provider ──────────────────────────────────────────────────

    async def chat(self, messages: list[dict], images_b64: list[str] | None = None) -> str:
        if not self._maybe_allow():
            self._reject()
        try:
            result = await self._provider.chat(messages, images_b64=images_b64)
        except ProviderUnavailableError as exc:
            self._record_failure(exc)
            raise
        self._record_success()
        return result

    async def chat_stream(self, messages: list[dict], images_b64: list[str] | None = None) -> AsyncIterator[str]:
        if not self._maybe_allow():
            self._reject()
        produced = False
        try:
            async for chunk in self._provider.chat_stream(messages, images_b64=images_b64):
                produced = True
                yield chunk
        except ProviderUnavailableError as exc:
            # Un flux déjà partiel ne peut pas être rattrapé par un autre
            # provider — on laisse l'échec remonter (idem ProviderRouter).
            if produced:
                raise
            self._record_failure(exc)
            raise
        self._record_success()

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        images_b64: list[str] | None = None,
    ) -> dict:
        if not self._maybe_allow():
            self._reject()
        try:
            result = await self._provider.chat_with_tools(
                messages, tools=tools, images_b64=images_b64
            )
        except ProviderUnavailableError as exc:
            self._record_failure(exc)
            raise
        self._record_success()
        return result

    async def chat_stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        images_b64: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        if not self._maybe_allow():
            self._reject()
        produced = False
        try:
            async for event in self._provider.chat_stream_with_tools(
                messages, tools=tools, images_b64=images_b64
            ):
                produced = True
                yield event
        except ProviderUnavailableError as exc:
            if produced:
                raise
            self._record_failure(exc)
            raise
        self._record_success()

    async def aclose(self) -> None:
        await self._provider.aclose()