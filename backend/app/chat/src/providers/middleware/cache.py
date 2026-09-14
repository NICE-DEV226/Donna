"""Middleware cache : sert les appels non-streaming identiques depuis le cache.

Cache en mémoire, clé = hash des messages + schéma d'outils (le contexte
LLM est déjà plafonné en amont par BudgetMiddleware). Streaming exclus :
un flux ne peut pas être repris depuis un cache sans perdre la latence
perçue ni garantir la cohérence des events.
"""

from __future__ import annotations

import hashlib
import json
import time

from .base import LLMContext, LLMMiddleware


class CacheMiddleware(LLMMiddleware):
    def __init__(self, enabled: bool = True, ttl_seconds: int = 300, max_entries: int = 50) -> None:
        super().__init__()
        self._enabled = enabled
        self._ttl = float(ttl_seconds)
        self._max_entries = int(max_entries)
        # key → (expires_at, result)
        self._store: dict[str, tuple[float, dict]] = {}
        self._order: list[str] = []
        self.name = "cache"

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _key(self, ctx: LLMContext) -> str:
        payload = json.dumps(
            {
                "provider": ctx.provider,
                "messages": ctx.messages,
                "tools": ctx.tools,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _get(self, key: str, now: float) -> dict | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, result = entry
        if now >= expires_at:
            self._evict(key)
            return None
        return dict(result)

    def _put(self, key: str, result: dict, now: float) -> None:
        if not self._enabled:
            return
        if key in self._store:
            self._evict(key)
        if len(self._store) >= self._max_entries and self._store:
            stale = self._order.pop(0)
            self._store.pop(stale, None)
        self._store[key] = (now + self._ttl, dict(result))
        self._order.append(key)

    def _evict(self, key: str) -> None:
        self._store.pop(key, None)
        if key in self._order:
            self._order.remove(key)

    # ── Flow ────────────────────────────────────────────────────────────────

    async def handle(self, ctx: LLMContext) -> dict:
        if ctx.streaming or not self._enabled:
            return await ctx.next()

        now = time.monotonic()
        key = self._key(ctx)
        hit = self._get(key, now)
        if hit is not None:
            ctx.cached = True
            ctx.tags["cache"] = "hit"
            return hit

        result = await ctx.next()
        ctx.tags["cache"] = "miss"

        # On ne cache que les réponses "pures" : pas d'appel d'outil dans la
        # réponse et crée dans les dernières secondes — une réponse tombée
        # en panne partielle (ProviderUnavailableError traité en repli) ne
        # doit pas polluer le cache.
        if result and not result.get("tool_calls"):
            self._put(key, result, now)
        return result

    def clear(self) -> None:
        self._store.clear()
        self._order.clear()