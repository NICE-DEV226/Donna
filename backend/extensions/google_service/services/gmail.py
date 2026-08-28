"""
Gmail — messages, threads, labels, drafts, profil.

`GmailMixin` est composé dans `GoogleServiceClient` (voir service.py), jamais
instancié seul : il suppose `_request`/`_headers` de `GoogleHTTPMixin`
(_http.py) déjà présents sur `self`.
"""

from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from .._http import GoogleHTTPMixin

_GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


def _build_mime_message(
    to: str,
    subject: str,
    body_text: Optional[str] = None,
    body_html: Optional[str] = None,
    *,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> str:
    if not body_text and not body_html:
        raise ValueError("Un message nécessite body_text et/ou body_html.")

    if body_html and body_text:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body_text, "plain"))
        message.attach(MIMEText(body_html, "html"))
    elif body_html:
        message = MIMEText(body_html, "html")
    else:
        message = MIMEText(body_text, "plain")

    message["to"] = to
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    return base64.urlsafe_b64encode(message.as_bytes()).decode()


class GmailMixin(GoogleHTTPMixin):
    """Nécessite le scope `gmail.modify` (lecture/écriture, hors suppression
    permanente — voir `delete_message`) accordé au consentement OAuth (voir
    app/auth/src/providers/google.py)."""

    # ── Messages ─────────────────────────────────────────────────────────────

    async def send_email(
        self,
        access_token: str,
        to: str,
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        *,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
    ) -> dict[str, Any]:
        """Envoie un email — nécessite le scope gmail.send (inclus dans gmail.modify)."""
        raw = _build_mime_message(to, subject, body_text, body_html, cc=cc, bcc=bcc)
        return await self._request(
            "POST", f"{_GMAIL_BASE_URL}/messages/send", access_token, json={"raw": raw}
        )

    async def list_messages(
        self,
        access_token: str,
        *,
        query: Optional[str] = None,
        label_ids: Optional[list[str]] = None,
        max_results: int = 50,
        page_token: Optional[str] = None,
        include_spam_trash: bool = False,
    ) -> dict[str, Any]:
        """Liste les messages (`q` = syntaxe de recherche Gmail, ex.
        "from:x@y.com is:unread")."""
        params: dict[str, Any] = {
            "maxResults": max_results,
            "includeSpamTrash": str(include_spam_trash).lower(),
        }
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", f"{_GMAIL_BASE_URL}/messages", access_token, params=params)

    async def get_message(
        self, access_token: str, message_id: str, *, format: str = "full"
    ) -> dict[str, Any]:
        """`format` : full | metadata | minimal | raw."""
        return await self._request(
            "GET", f"{_GMAIL_BASE_URL}/messages/{message_id}", access_token,
            params={"format": format},
        )

    async def trash_message(self, access_token: str, message_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"{_GMAIL_BASE_URL}/messages/{message_id}/trash", access_token
        )

    async def untrash_message(self, access_token: str, message_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"{_GMAIL_BASE_URL}/messages/{message_id}/untrash", access_token
        )

    async def delete_message(self, access_token: str, message_id: str) -> None:
        """Suppression PERMANENTE (contourne la corbeille) — irréversible.
        Nécessite le scope restreint `https://mail.google.com/`, non demandé
        par défaut (voir providers/google.py) : 403 tant qu'il n'est pas
        explicitement ajouté et re-consenti. Préférer `trash_message`."""
        await self._request("DELETE", f"{_GMAIL_BASE_URL}/messages/{message_id}", access_token)

    async def modify_message_labels(
        self,
        access_token: str,
        message_id: str,
        *,
        add_label_ids: Optional[list[str]] = None,
        remove_label_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        body = {
            "addLabelIds": add_label_ids or [],
            "removeLabelIds": remove_label_ids or [],
        }
        return await self._request(
            "POST", f"{_GMAIL_BASE_URL}/messages/{message_id}/modify", access_token, json=body
        )

    async def get_attachment(
        self, access_token: str, message_id: str, attachment_id: str
    ) -> dict[str, Any]:
        """Retourne `{"size": int, "data": <base64url>}` — décoder avec
        `base64.urlsafe_b64decode` pour les octets bruts de la pièce jointe."""
        return await self._request(
            "GET", f"{_GMAIL_BASE_URL}/messages/{message_id}/attachments/{attachment_id}",
            access_token,
        )

    # ── Threads ──────────────────────────────────────────────────────────────

    async def list_threads(
        self,
        access_token: str,
        *,
        query: Optional[str] = None,
        label_ids: Optional[list[str]] = None,
        max_results: int = 50,
        page_token: Optional[str] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", f"{_GMAIL_BASE_URL}/threads", access_token, params=params)

    async def get_thread(
        self, access_token: str, thread_id: str, *, format: str = "full"
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"{_GMAIL_BASE_URL}/threads/{thread_id}", access_token, params={"format": format}
        )

    async def trash_thread(self, access_token: str, thread_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"{_GMAIL_BASE_URL}/threads/{thread_id}/trash", access_token
        )

    async def modify_thread_labels(
        self,
        access_token: str,
        thread_id: str,
        *,
        add_label_ids: Optional[list[str]] = None,
        remove_label_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        body = {"addLabelIds": add_label_ids or [], "removeLabelIds": remove_label_ids or []}
        return await self._request(
            "POST", f"{_GMAIL_BASE_URL}/threads/{thread_id}/modify", access_token, json=body
        )

    # ── Labels ───────────────────────────────────────────────────────────────

    async def list_labels(self, access_token: str) -> list[dict[str, Any]]:
        data = await self._request("GET", f"{_GMAIL_BASE_URL}/labels", access_token)
        return (data or {}).get("labels", [])

    async def get_label(self, access_token: str, label_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{_GMAIL_BASE_URL}/labels/{label_id}", access_token)

    async def create_label(
        self,
        access_token: str,
        name: str,
        *,
        label_list_visibility: str = "labelShow",
        message_list_visibility: str = "show",
    ) -> dict[str, Any]:
        body = {
            "name": name,
            "labelListVisibility": label_list_visibility,
            "messageListVisibility": message_list_visibility,
        }
        return await self._request("POST", f"{_GMAIL_BASE_URL}/labels", access_token, json=body)

    async def update_label(
        self, access_token: str, label_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request(
            "PATCH", f"{_GMAIL_BASE_URL}/labels/{label_id}", access_token, json=patch
        )

    async def delete_label(self, access_token: str, label_id: str) -> None:
        await self._request("DELETE", f"{_GMAIL_BASE_URL}/labels/{label_id}", access_token)

    # ── Drafts ───────────────────────────────────────────────────────────────

    async def list_drafts(
        self, access_token: str, *, max_results: int = 50, page_token: Optional[str] = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", f"{_GMAIL_BASE_URL}/drafts", access_token, params=params)

    async def get_draft(self, access_token: str, draft_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{_GMAIL_BASE_URL}/drafts/{draft_id}", access_token)

    async def create_draft(
        self,
        access_token: str,
        to: str,
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
    ) -> dict[str, Any]:
        raw = _build_mime_message(to, subject, body_text, body_html)
        return await self._request(
            "POST", f"{_GMAIL_BASE_URL}/drafts", access_token, json={"message": {"raw": raw}}
        )

    async def update_draft(
        self,
        access_token: str,
        draft_id: str,
        to: str,
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
    ) -> dict[str, Any]:
        raw = _build_mime_message(to, subject, body_text, body_html)
        return await self._request(
            "PUT", f"{_GMAIL_BASE_URL}/drafts/{draft_id}", access_token, json={"message": {"raw": raw}}
        )

    async def send_draft(self, access_token: str, draft_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"{_GMAIL_BASE_URL}/drafts/send", access_token, json={"id": draft_id}
        )

    async def delete_draft(self, access_token: str, draft_id: str) -> None:
        await self._request("DELETE", f"{_GMAIL_BASE_URL}/drafts/{draft_id}", access_token)

    # ── Profil ───────────────────────────────────────────────────────────────

    async def get_profile(self, access_token: str) -> dict[str, Any]:
        """`{"emailAddress", "messagesTotal", "threadsTotal", "historyId"}`."""
        return await self._request("GET", f"{_GMAIL_BASE_URL}/profile", access_token)
