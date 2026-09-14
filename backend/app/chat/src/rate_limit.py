from __future__ import annotations

import asyncio
import time
from collections import deque

from fastapi import Depends, HTTPException
from xcore.kernel.api import AuthPayload, get_current_user
from xcore.sdk import get_logger

from extensions.donna_settings import (
    CHAT_CALLS_PER_MINUTE,
    MAX_AUDIO_BYTES,
    MAX_FILES_PER_REQUEST,
    STREAM_CALLS_PER_MINUTE,
    TRANSCRIBE_TIMEOUT_S,
    UPLOAD_CALLS_PER_10MIN,
)

logger = get_logger("chat.rate_limit")

# Plafonds par utilisateur — réglages ops centralisés, voir
# extensions/donna_settings.py (DONNA_*). Volontairement généreux : le but
# n'est pas de brider un usage normal (chaque message coûte déjà un appel
# LLM, donc le modèle économique se régule seul) mais de couper les abus
# automatisés et les boucles clientes buguées — un seul user ne doit jamais
# pouvoir saturer Whisper (CPU) ou enchaîner des tours d'outils à N rounds
# en boucle.
#
# Garde-fous /upload : chaque fichier est lu ENTIÈREMENT en RAM (base64 +
# extraction) avant tout contrôle — borner le nombre et la taille côté
# transcription évite les pics mémoire/DoS compute.


class RouteRateLimiter:
    """Fenêtre glissante en mémoire, par (utilisateur, route).

    Suffisant à workers=1 et acceptable en multi-processus (chaque worker
    applique le plafond pour son compte — 4 workers = plafond ×4 au pire,
    toujours un garde-fou, jamais une garantie stricte). Pour une limite
    stricte partagée, passer le compteur sur Redis (Vague 1 MLOps).
    """

    def __init__(self, max_keys: int = 10_000) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def check(self, user_id: str, route: str, calls: int, period_s: float) -> None:
        now = time.monotonic()
        key = (user_id, route)
        async with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = self._hits[key] = deque()
                if len(self._hits) > self._max_keys:
                    # Évite une croissance illimitée (énumération d'user_id) :
                    # on retire une clé arbitraire la plus ancienne.
                    self._hits.pop(next(iter(self._hits)))
            while hits and hits[0] <= now - period_s:
                hits.popleft()
            if len(hits) >= calls:
                retry_after = max(1, int(hits[0] + period_s - now))
                logger.warning(
                    "rate limit dépassée", user_id=user_id, route=route, retry_after_s=retry_after
                )
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Trop de requêtes sur cette action, réessaie dans {retry_after} s."
                    ),
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)


limiter = RouteRateLimiter()


def limit_requests(calls: int, period_s: float, route: str):
    """Fabrique de dépendance FastAPI : `dependencies=[Depends(limit_requests(60, 60.0, "chat"))]`."""

    async def _dep(current_user: AuthPayload = Depends(get_current_user)) -> None:
        await limiter.check(current_user["sub"], route, calls, period_s)

    return _dep
