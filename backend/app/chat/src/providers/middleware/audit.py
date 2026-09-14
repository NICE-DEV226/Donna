"""Middleware audit : trace des prompts/réponses pour la conformité.

Mode hash-only (défaut) : mémorise un digest sha256 du prompt ET de la
réponse — suffisant pour vérifier qu'un événement a eu lieu sans stocker le
contenu (conformité RGPD / minimisation). Mode verbose : écrit le texte en
clair dans le fichier d'audit configuré.

Garde-fou d'injection prompt léger : signale (jamais bloquant par défaut)
les schémas classiques d'exfiltration ("ignore previous instructions",
"forget everything", demande de sortie du system prompt...).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path

from xcore.sdk import get_logger

from .base import LLMContext, LLMMiddleware

logger = get_logger("chat.middleware.audit")

_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous",
    "ignore the system prompt",
    "forget everything",
    "disregard previous",
    "oublie les instructions précédentes",
    "oublie tout",
    "ignore le system prompt",
    "ne tiens pas compte des instructions",
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _flat_context_text(ctx: LLMContext) -> str:
    parts: list[str] = []
    for msg in ctx.messages:
        content = msg.get("content") or msg.get("text") or ""
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        parts.append(f"[{msg.get('role', '?')}] {content}")
    return "\n".join(parts)


def detect_injection(ctx: LLMContext) -> list[str]:
    """Retourne la liste des patterns d'injection détectés dans les messages
    utilisateur (exclut role=system)."""
    hits: list[str] = []
    haystack = "\n".join(
        str(m.get("content", "")) for m in ctx.messages if m.get("role") == "user"
    ).lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in haystack:
            hits.append(pattern)
    return hits


class AuditMiddleware(LLMMiddleware):
    def __init__(
        self,
        enabled: bool = True,
        verbose: bool = False,
        audit_file: str | None = None,
        block_on_injection: bool = False,
    ) -> None:
        super().__init__()
        self._enabled = enabled
        self._verbose = verbose
        self._file = Path(audit_file) if audit_file else None
        self._block = block_on_injection
        self._injection_hits: list[str] = []
        self.name = "audit"

    # ── Écriture ────────────────────────────────────────────────────────────

    def _append(self, ctx: LLMContext, response_text: str | None) -> None:
        if not self._enabled or self._file is None:
            return
        line = {
            "ts": time.time(),
            "request_id": ctx.request_id,
            "provider": ctx.provider,
            "method": ctx.method,
            "streaming": ctx.streaming,
            "prompt_hash": _digest(_flat_context_text(ctx)),
            "response_hash": _digest(response_text or ""),
            "injection": self._injection_hits or None,
        }
        if self._verbose:
            line["prompt"] = _flat_context_text(ctx)
            line["response"] = response_text

        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            try:
                os.chmod(self._file, stat.S_IRUSR | stat.S_IWUSR)  # 600 — secret par défaut
            except OSError:
                pass
        except OSError as exc:
            logger.warning("audit LLM impossible d'écrire %s : %s", self._file, exc)

    # ── Flow ────────────────────────────────────────────────────────────────

    async def before(self, ctx: LLMContext) -> None:
        self._injection_hits = detect_injection(ctx)
        if self._injection_hits:
            ctx.tags["injection"] = ",".join(self._injection_hits)
            if self._block:
                from .base import LLMMiddlewareError

                raise LLMMiddlewareError(
                    "injection prompt détectée : " + ", ".join(self._injection_hits)
                )

    async def after(self, ctx: LLMContext, result: dict) -> dict:
        self._append(ctx, result.get("content"))
        return result

    async def after_stream(self, ctx: LLMContext) -> None:
        # En streaming on n'a pas gardé le texte cumulé (performance) — on
        # audite le hash prompt + un marqueur.
        self._append(ctx, None)

    async def on_error(self, ctx: LLMContext, exc: Exception) -> dict | None:
        raise exc