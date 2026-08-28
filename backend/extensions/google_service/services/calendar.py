"""
Google Calendar — calendarList (agendas souscrits), calendars (les agendas
eux-mêmes), events, freebusy.

`CalendarMixin` est composé dans `GoogleServiceClient` (voir service.py),
jamais instancié seul : il suppose `_request`/`_headers` de `GoogleHTTPMixin`
(_http.py) déjà présents sur `self`.
"""

from __future__ import annotations

from typing import Any, Optional

from .._http import GoogleHTTPMixin

_CALENDAR_ROOT = "https://www.googleapis.com/calendar/v3"
_CALENDAR_BASE_URL = f"{_CALENDAR_ROOT}/calendars"


class CalendarMixin(GoogleHTTPMixin):
    """Nécessite le scope `calendar` (accès complet) accordé au consentement
    OAuth (voir app/auth/src/providers/google.py)."""

    # ── CalendarList (agendas souscrits par l'utilisateur) ──────────────────

    async def list_calendar_list(
        self, access_token: str, *, min_access_role: Optional[str] = None
    ) -> list[dict[str, Any]]:
        params = {"minAccessRole": min_access_role} if min_access_role else {}
        data = await self._request(
            "GET", f"{_CALENDAR_ROOT}/users/me/calendarList", access_token, params=params
        )
        return (data or {}).get("items", [])

    async def get_calendar_list_entry(self, access_token: str, calendar_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"{_CALENDAR_ROOT}/users/me/calendarList/{calendar_id}", access_token
        )

    async def subscribe_calendar(self, access_token: str, calendar_id: str) -> dict[str, Any]:
        """Ajoute un agenda existant (ex. un agenda partagé) à la liste de
        l'utilisateur — ne crée pas un nouvel agenda (voir `create_calendar`)."""
        return await self._request(
            "POST", f"{_CALENDAR_ROOT}/users/me/calendarList", access_token,
            json={"id": calendar_id},
        )

    async def unsubscribe_calendar(self, access_token: str, calendar_id: str) -> None:
        await self._request(
            "DELETE", f"{_CALENDAR_ROOT}/users/me/calendarList/{calendar_id}", access_token
        )

    # ── Calendars (les agendas eux-mêmes) ───────────────────────────────────

    async def create_calendar(
        self, access_token: str, summary: str, *, time_zone: Optional[str] = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"summary": summary}
        if time_zone:
            body["timeZone"] = time_zone
        return await self._request("POST", f"{_CALENDAR_ROOT}/calendars", access_token, json=body)

    async def get_calendar(self, access_token: str, calendar_id: str = "primary") -> dict[str, Any]:
        return await self._request("GET", f"{_CALENDAR_BASE_URL}/{calendar_id}", access_token)

    async def update_calendar(
        self, access_token: str, calendar_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request(
            "PATCH", f"{_CALENDAR_BASE_URL}/{calendar_id}", access_token, json=patch
        )

    async def delete_calendar(self, access_token: str, calendar_id: str) -> None:
        """Supprime un agenda secondaire — un compte ne peut pas supprimer
        son agenda `primary` (Google renvoie 403)."""
        await self._request("DELETE", f"{_CALENDAR_BASE_URL}/{calendar_id}", access_token)

    async def clear_calendar(self, access_token: str, calendar_id: str = "primary") -> None:
        """Vide tous les événements d'un agenda — uniquement valide sur `primary`."""
        await self._request("POST", f"{_CALENDAR_BASE_URL}/{calendar_id}/clear", access_token)

    # ── Events ───────────────────────────────────────────────────────────────

    async def list_events(
        self,
        access_token: str,
        calendar_id: str = "primary",
        *,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        query: Optional[str] = None,
        max_results: int = 50,
        page_token: Optional[str] = None,
        single_events: bool = True,
        order_by: str = "startTime",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "maxResults": max_results,
            "singleEvents": str(single_events).lower(),
            "orderBy": order_by if single_events else None,
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        params = {k: v for k, v in params.items() if v is not None}

        data = await self._request(
            "GET", f"{_CALENDAR_BASE_URL}/{calendar_id}/events", access_token, params=params
        )
        return (data or {}).get("items", [])

    async def get_event(
        self, access_token: str, event_id: str, calendar_id: str = "primary"
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"{_CALENDAR_BASE_URL}/{calendar_id}/events/{event_id}", access_token
        )

    async def create_event(
        self,
        access_token: str,
        event: dict[str, Any],
        calendar_id: str = "primary",
        *,
        send_updates: Optional[str] = None,
    ) -> dict[str, Any]:
        """`event` suit le schéma Google Calendar API (summary, start, end,
        description, attendees, ... — voir la doc officielle de la ressource
        Event) — transmis tel quel, aucune validation applicative ici.
        `send_updates` : "all" | "externalOnly" | "none" (notifie les invités)."""
        params = {"sendUpdates": send_updates} if send_updates else {}
        return await self._request(
            "POST", f"{_CALENDAR_BASE_URL}/{calendar_id}/events", access_token,
            json=event, params=params,
        )

    async def update_event(
        self,
        access_token: str,
        event_id: str,
        event: dict[str, Any],
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Mise à jour partielle (`events.patch`) — seuls les champs fournis
        dans `event` sont modifiés."""
        return await self._request(
            "PATCH", f"{_CALENDAR_BASE_URL}/{calendar_id}/events/{event_id}",
            access_token, json=event,
        )

    async def delete_event(
        self,
        access_token: str,
        event_id: str,
        calendar_id: str = "primary",
    ) -> None:
        await self._request(
            "DELETE", f"{_CALENDAR_BASE_URL}/{calendar_id}/events/{event_id}", access_token
        )

    async def move_event(
        self,
        access_token: str,
        event_id: str,
        destination_calendar_id: str,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Déplace un événement d'un agenda vers un autre (les deux
        appartenant au même compte, ou avec droit d'écriture sur les deux)."""
        return await self._request(
            "POST", f"{_CALENDAR_BASE_URL}/{calendar_id}/events/{event_id}/move",
            access_token, params={"destination": destination_calendar_id},
        )

    async def quick_add_event(
        self, access_token: str, text: str, calendar_id: str = "primary"
    ) -> dict[str, Any]:
        """Crée un événement à partir d'un texte en langage naturel (ex.
        "Déjeuner avec Alice vendredi midi") — Google se charge du parsing."""
        return await self._request(
            "POST", f"{_CALENDAR_BASE_URL}/{calendar_id}/events/quickAdd",
            access_token, params={"text": text},
        )

    # ── Disponibilité ────────────────────────────────────────────────────────

    async def query_freebusy(
        self,
        access_token: str,
        time_min: str,
        time_max: str,
        calendar_ids: list[str],
    ) -> dict[str, Any]:
        """Retourne les créneaux occupés pour chaque agenda de `calendar_ids`
        entre `time_min`/`time_max` (ISO 8601) — ne révèle pas le contenu des
        événements, seulement leur présence."""
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cid} for cid in calendar_ids],
        }
        return await self._request("POST", f"{_CALENDAR_ROOT}/freeBusy", access_token, json=body)
