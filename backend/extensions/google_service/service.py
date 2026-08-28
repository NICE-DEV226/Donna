"""
Extension Xcore — point d'entrée `ext.google` : gestion complète Gmail +
Google Calendar au nom d'un utilisateur ayant lié son compte Google (voir
app/auth/src/providers/google.py pour les scopes demandés).

`GoogleServiceClient` ne fait que composer les deux API (gmail.py, calendar.py)
et gérer le cycle de vie `BaseService` (client HTTP partagé) — voir ces deux
modules pour le détail de chaque méthode.

Ce service est volontairement STATELESS et ne connaît ni les utilisateurs ni
la base de données : chaque appel reçoit un access_token déjà valide. La
résolution de l'utilisateur → OAuthAccount → access_token (avec
rafraîchissement si expiré) est la responsabilité du plugin auth (actions IPC
`xauth.google.*`), qui est le seul à posséder les jetons chiffrés.

Configuration dans integration.yaml :
    extensions:
      google:
        module: extensions.googleService.service:GoogleServiceClient
        config:
          timeout: 10

Accès depuis un plugin (normalement seulement depuis auth lui-même) :
    google = self.get_service("ext.google")
    await google.send_email(access_token, to="a@b.com", subject="Hi", body_text="...")
    await google.create_event(access_token, {"summary": "Réunion", "start": {...}, "end": {...}})
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from xcore.services.base import BaseService, ServiceStatus
from xcore.sdk import get_logger

from .services.calendar import CalendarMixin
from .errors import GoogleAPIError
from .services.gmail import GmailMixin

logger = get_logger("ext.google")

__all__ = ["GoogleServiceClient", "GoogleAPIError"]


class GoogleServiceClient(GmailMixin, CalendarMixin, BaseService):
    """Wrapper HTTP autour de l'API Gmail (`GmailMixin`, gmail.py) et de
    l'API Google Calendar (`CalendarMixin`, calendar.py)."""

    name = "google"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._timeout = float(config.get("timeout", 10))
        self._client: Optional[httpx.AsyncClient] = None

    async def init(self) -> None:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._status = ServiceStatus.READY

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
        self._status = ServiceStatus.STOPPED

    async def health_check(self) -> tuple[bool, str]:
        return (self._client is not None), "ok" if self._client else "not initialized"

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "status": self._status.value}
