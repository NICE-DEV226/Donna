"""Erreurs partagées par les clients Gmail/Calendar (voir gmail.py, calendar.py)."""

from __future__ import annotations

from typing import Any


class GoogleAPIError(Exception):
    """Erreur renvoyée par l'API Gmail/Calendar (4xx/5xx) — porte le détail brut."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(f"Google API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
