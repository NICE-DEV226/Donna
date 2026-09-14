"""
Middleware HTTP Starlette pour /app/chat/* — rate limit + request_id.

Deux responsabilités distinctes des middlewares LLM :
- RateLimit : sliding-window approximée sur le cache xcore (Redis), clé par
  user_id (JWT si présent) + IP — sur le modèle de RateLimitMiddleware
  (xauth), avec un prefix de clé distinct pour ne pas se confondre.
- RequestId : injecte/sert un X-Request-Id par requête, puis le pousse dans
  la contextvar des middlewares LLM (providers/middleware/tracing) pour
  corréler toutes les spans d'une même requête HTTP.

Montage : registré en configuration xcore (integration.yaml → middleware:),
donc `app.add_middleware()` est appelé par le noyau au boot.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.chat.src.providers.middleware.tracing import set_request_id

# (limit_par_fenetre, fenetre_secondes)
DEFAULT_CHAT_LIMITS: dict[str, tuple[int, int]] = {
    "/app/chat/messages":  (60, 60),
    "/app/chat/stream":    (60, 60),
    "/app/chat/transcribe": (30, 300),
}

_GLOBAL_CHAT_LIMIT: tuple[int, int] = (240, 60)

_KEY_PREFIX = "chat:rl"


class ChatRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting par user + IP sur les routes chat. Fail-open si le cache
    est indisponible (jamais bloquer un chat pour un souci de Redis).
    Réglages fournis par la config xcore (max_requests / window_seconds /
    limits) ; défauts raisonnables ci-dessous.
    """

    def __init__(
        self,
        app: ASGIApp,
        cache: Any = None,
        # Prototypes à la requête : `cache` est un callable () → service
        # (resolve, cf. xcore.kernel.api.middleware Middlewares) OU une
        # instance directe — on supporte les deux.
        max_requests: int = 60,
        window_seconds: int = 60,
        enabled: bool = True,
        global_limits: dict[str, tuple[int, int]] | None = None,
        **kwargs: Any,
    ) -> None:
        if isinstance(cache, dict):
            cache = cache.get("cache")
        super().__init__(app)
        self._cache_provider = cache
        self._max_requests = int(max_requests)
        self._window = int(window_seconds)
        self._enabled = enabled
        self._limits = global_limits or DEFAULT_CHAT_LIMITS

    # ── résolution du cache (service prototype vs instance) ────────────────

    def _cache(self, request: Request) -> Any:
        cache = self._cache_provider
        if callable(cache) and not hasattr(cache, "get"):
            try:
                cache = cache()
            except Exception:
                return None
        return cache

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @staticmethod
    def _user_id(request: Request) -> str:
        """user_id depuis le JWT, sans le valider lourdement — le vrai check
        est fait par get_current_user sur les routes. Ici c'est juste la clé
        de rate-limit : on veut un identifiant stable, pas une autorisation."""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
            # décodage minimal du payload (segment 2, base64url) — tolérant
            # aux tokens invalides (rate-limit tombé sur l'IP)
            try:
                import base64

                payload = token.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                data = json.loads(base64.urlsafe_b64decode(payload))
                sub = data.get("sub")
                if isinstance(sub, str) and sub:
                    return sub
            except Exception:
                pass
        return ""

    def _get_limit(self, path: str) -> tuple[int, int]:
        for prefix, limit in self._limits.items():
            if path.startswith(prefix):
                return limit
        return self._max_requests, self._window

    async def _check(self, cache: Any, key: str, max_req: int, window: int) -> tuple[bool, int, int]:
        now = int(time.time())
        raw = await cache.get(key)
        if raw is None:
            await cache.set(key, json.dumps({"count": 1, "reset_at": now + window}), ttl=window)
            return False, 1, window
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            data = {"count": 0, "reset_at": now}
        reset_at = int(data.get("reset_at", now))
        if now >= reset_at:
            data = {"count": 1, "reset_at": now + window}
            await cache.set(key, json.dumps(data), ttl=window)
            return False, 1, window
        data["count"] += 1
        remaining = max(1, reset_at - now)
        await cache.set(key, json.dumps(data), ttl=remaining)
        return data["count"] > max_req, data["count"], remaining

    # ── dispatch ────────────────────────────────────────────────────────────

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Request-Id pour la corrélation des spans LLM.
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        set_request_id(request_id)

        path = request.url.path
        if self._enabled and path.startswith("/app/chat"):
            cache = self._cache(request)
            if cache is not None:
                user = self._user_id(request)
                ip = self._client_ip(request)
                max_req, window = self._get_limit(path)
                # Clé : user quand identifié, sinon IP. Un user authentifié
                # ne partage jamais son quota avec d'autres IPs.
                scope = f"u:{user}" if user else f"ip:{ip}"
                key = f"{_KEY_PREFIX}:{scope}:{path.split('?')[0]}"
                try:
                    limited, _, retry_after = await self._check(cache, key, max_req, window)
                    if limited:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Trop de requêtes — patiente un instant puis réessaie."},
                            headers={"Retry-After": str(retry_after), "X-Request-Id": request_id},
                        )
                except Exception:
                    # cache indisponible → fail-open (le chat ne casse pas)
                    pass

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response