"""
Mixin HTTP partagé entre GmailMixin (gmail.py) et CalendarMixin (calendar.py) —
requête authentifiée Bearer + gestion d'erreur commune aux deux API.

Suppose `self._client: httpx.AsyncClient | None`, posé par `GoogleServiceClient`
(voir service.py) qui compose les deux mixins ; ce module ne s'instancie
jamais seul.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .errors import GoogleAPIError


class GoogleHTTPMixin:
    _client: Optional[httpx.AsyncClient]

    def _headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    async def _request(self, method: str, url: str, access_token: str, **kwargs) -> Any:
        if self._client is None:
            raise RuntimeError("GoogleServiceClient non initialisé")
        resp = await self._client.request(method, url, headers=self._headers(access_token), **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise GoogleAPIError(resp.status_code, detail)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()
