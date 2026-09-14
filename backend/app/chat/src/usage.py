"""
Comptabilité tokens par requête — le prérequis à toute optimisation de coût.

Estimation heuristique (chars/4, calibrée FR/EN latin — approximative pour
CJK/emoji, suffisante pour des budgets et des logs, PAS pour de la
facturation exacte). Uniforme tous providers : les vrais compteurs
(Ollama prompt_eval_count, OpenAI usage...) diffèrent par provider et ne
sont pas toujours exposés en streaming — uniformité > précision ici.
Suivi réel : Vague 3 MLOps (capturer les compteurs natifs quand présents).

Le ledger vit sur ToolContext (une instance = un message utilisateur) et est
rempli dans tools.run_chat_with_tools / run_chat_stream_with_tools, puis
loggé en une ligne structurée + renvoyé au client (ChatResponse.usage,
event SSE done) pour rendre le coût VISIBLE.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# ~4 caractères par token (BPE latin). Overheads fixes : rôle/nom/structure
# par message + enveloppe function-calling par outil déclaré.
_CHARS_PER_TOKEN = 4
_TOKENS_PER_MESSAGE = 4


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict], tools: list[dict] | None = None) -> int:
    total = 0
    for msg in messages:
        total += _TOKENS_PER_MESSAGE
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            total += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))
    if tools:
        total += estimate_tokens(json.dumps(tools, ensure_ascii=False))
    return total


def cap_text(text: str, max_chars: int, marker: str = "\n\n[…résultat tronqué…]") -> str:
    """Plafonne un texte réinjecté au modèle (résultats d'outils)."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + marker


@dataclass
class RequestUsage:
    """Ledger d'une requête chat complète (tous rounds d'outils confondus)."""

    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_rounds: int = 0
    rag_used: bool = False
    rag_skipped_by_gate: bool = False
    budget_hit: bool = False
    provider_fallbacks: int = 0

    def add_request(self, messages: list[dict], tools: list[dict] | None = None) -> None:
        self.llm_calls += 1
        self.input_tokens += estimate_messages_tokens(messages, tools)

    def add_response(self, content: str | None) -> None:
        self.output_tokens += estimate_tokens(content)

    def summary(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_rounds": self.tool_rounds,
            "rag_used": self.rag_used,
            "rag_skipped_by_gate": self.rag_skipped_by_gate,
            "budget_hit": self.budget_hit,
            "provider_fallbacks": self.provider_fallbacks,
        }
