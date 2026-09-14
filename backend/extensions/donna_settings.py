"""
donna_settings — TOUS les réglages ops de Donna au même endroit.

Problème résolu (audit) : les constantes de comportement étaient éparpillées
dans une douzaine de fichiers (tools.py, memory.py, chat_routes.py,
rate_limit.py, rag/tasks.py, doc_extract, plugin.yaml...), impossibles à
trouver et à tuner sans fouiller le code. Désormais : UNE valeur par réglage,
lisible ici, surchargeable par l'environnement, documentée dans
backend/.env.example (le point d'entrée humain unique).

Règle de split (à respecter pour tout nouveau réglage) :
- Choix PRODUIT (persona, modèles par défaut, permissions, schéma d'outils)
  → reste dans plugin.yaml / le code.
- Bouton OPS (seuils, plafonds, budgets, timeouts, rate-limits, batch sizes)
  → ICI, via une variable d'environnement préfixée, avec défaut = comportement
  historique (zéro changement sans env).

Lecture : à l'import (comme worker_env). Les valeurs sont typées et
robustes aux chaînes vides (interpolation xcore ${VAR} absente → "").
"""

from __future__ import annotations

import os


def _str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name)
        return int(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name)
        return float(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ── Boucle d'appels d'outils ───────────────────────────────────────────────
# Garde-fou anti-boucle infinie modèle→outil→modèle (générer un document
# Word/Excel/PDF est intrinsèquement multi-étapes : create → add_* → save).
MAX_TOOL_ROUNDS: int = _int("DONNA_MAX_TOOL_ROUNDS", 12)

# Budget d'entrée CUMULÉ par message (tous rounds confondus, estimation
# chars/4 — voir app/chat/src/usage.py). Dépassé → on force la réponse
# finale SANS outils plutôt que de continuer à gonfler le contexte.
# Ordre de grandeur : ~11k tokens/round en contexte chargé → 80k ≈ 7 rounds
# pleins, les flux documentaires passent, les boucles aberrantes sont coupées.
MAX_INPUT_TOKENS_PER_REQUEST: int = _int("DONNA_MAX_INPUT_TOKENS_PER_REQUEST", 80_000)

# Plafond par RÉSULTAT d'outil réinjecté au modèle (fuites MCP : un
# get_document_text pouvait injecter 50k+ tokens à lui seul, à chaque round).
TOOL_RESULT_MAX_CHARS: int = _int("DONNA_TOOL_RESULT_MAX_CHARS", 6_000)

# ── Boucle sous-agent (delegation) ──────────────────────────────────────────
# Lorsque Donna délègue un travail documentaire à un sous-agent (redacteur,
# analyste), celui-ci tourne sur une boucle LLM séparée, avec ses propres
# outils MCP (filtrés via catalog, pas les miens).  Garde-fou dédié :
# un sous-agent n'a pas besoin de 12 rounds (creation Word = 2-3 appels
# max en général) — un budget plus court protège contre les boucles
# aberrantes en cas de consigne ambiguë.
SUB_AGENT_MAX_TOOL_ROUNDS: int = _int("DONNA_SUB_AGENT_MAX_TOOL_ROUNDS", 8)

# ── RAG ─────────────────────────────────────────────────────────────────────
RAG_TOP_K: int = _int("DONNA_RAG_TOP_K", 5)
# Gating : pas de recherche (ni embedding, ni rerank, ni contexte) pour les
# messages triviaux — "ok", "merci", "oui" ne nécessitent pas la base
# documentaire. Heuristique conservative (voir chat_routes._should_use_rag) :
# seuls les messages courts SANS marqueur de question sont sautés.
RAG_GATE_ENABLED: bool = _bool("DONNA_RAG_GATE_ENABLED", True)
RAG_GATE_MIN_CHARS: int = _int("DONNA_RAG_GATE_MIN_CHARS", 24)
# Score de rerank sous lequel un candidat est jugé non pertinent.
RERANK_MIN_SCORE: float = _float("DONNA_RERANK_MIN_SCORE", 0.0)

# ── Historique / mémoire ────────────────────────────────────────────────────
# Plafond DUR sur l'historique envoyé au LLM (après résumé glissant) : borne
# la croissance du contexte quelle que soit la longueur de la conversation.
MAX_HISTORY_CHARS: int = _int("DONNA_MAX_HISTORY_CHARS", 12_000)
SUMMARY_TRIGGER: int = _int("DONNA_SUMMARY_TRIGGER", 20)
SUMMARY_KEEP_RECENT: int = _int("DONNA_SUMMARY_KEEP_RECENT", 10)
SUMMARY_MAX_CHARS: int = _int("DONNA_SUMMARY_MAX_CHARS", 3_000)
# Appels LLM de fond (titre auto + résumé glissant, modèle local) :
# désactivables en environnement contraint (CPU).
ENABLE_TITLE_GEN: bool = _bool("DONNA_ENABLE_TITLE_GEN", True)
ENABLE_SUMMARY: bool = _bool("DONNA_ENABLE_SUMMARY", True)

# ── Upload / transcription ──────────────────────────────────────────────────
MAX_FILES_PER_REQUEST: int = _int("DONNA_MAX_FILES_PER_REQUEST", 10)
MAX_AUDIO_BYTES: int = _int("DONNA_MAX_AUDIO_BYTES", 10 * 1024 * 1024)
TRANSCRIBE_TIMEOUT_S: float = _float("DONNA_TRANSCRIBE_TIMEOUT_S", 600.0)
# Texte extrait d'une pièce jointe accepté dans le message (garde-fou tokens).
MAX_EXTRACTED_CHARS: int = _int("DONNA_MAX_EXTRACTED_CHARS", 20_000)

# ── Rate limits HTTP (par utilisateur, fenêtre glissante en mémoire) ─────────
CHAT_CALLS_PER_MINUTE: int = _int("DONNA_CHAT_PER_MINUTE", 60)
STREAM_CALLS_PER_MINUTE: int = _int("DONNA_STREAM_PER_MINUTE", 60)
UPLOAD_CALLS_PER_10MIN: int = _int("DONNA_UPLOAD_PER_10MIN", 10)

# ── Chunking ingestion RAG (worker) ─────────────────────────────────────────
CHUNK_SIZE: int = _int("DONNA_CHUNK_SIZE", 800)
CHUNK_OVERLAP: int = _int("DONNA_CHUNK_OVERLAP", 100)
# Taille des lots d'embeddings (embed_many) : 100 chunks = ~7 round-trips
# HTTP au lieu de 100. Trop grand = payloads lourdes + timeouts ; 16 est un
# compromis sûr pour Ollama local comme pour Jina/Gemini.
EMBED_BATCH_SIZE: int = _int("DONNA_EMBED_BATCH_SIZE", 16)
