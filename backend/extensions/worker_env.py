"""
worker_env — configuration partagée des processus Celery et du pont de statuts.

Pourquoi ce module : les workers Celery (chat.fire_reminder, rag.ingest_document)
ne bootent PAS xcore — ils n'ont ni integration.yaml ni accès aux services.
Leur seule source de config fiable est l'environnement du processus.

Historique (audit Vague 1) : chaque module de tâches hardcodait ses URLs en
`localhost`, et la config d'embeddings du worker (Ollama/768) divergeait de
l'API (Jina/1024 en prod). Résultat en Docker/Dokploy (Redis managé + auth,
hosts non-localhost) : rappels et statuts RAG morts en silence, recherche
vectorielle cassée (dimension figée dans la table vec0). Ce module est
désormais l'unique source de vérité côté worker.

Conventions :
- Défauts = comportement dev local historique (zéro changement sans env).
- Docker Compose : variables explicites posées dans docker-compose.yml.
- Dokploy : dériver des vars existantes, ex :
    DONNA_REMINDER_REDIS_URL   = ${PUBSUB_REDIS_URL}0
    DONNA_RAG_STATUS_REDIS_URL = ${PUBSUB_REDIS_URL}2
    DONNA_DB_URL               = sqlite:///data/db.sqlite3   (volume partagé)
    RAG_EMBED_PROVIDER/MODEL/DIM/API_KEY = mêmes valeurs que ext.rag côté API.
- Dev shell (worker lancé à la main) : exporter les vars ou laisser les
  défauts localhost — jamais de .env lu ici (les workers ne chargent pas dotenv).
"""

from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value else default


# ── Base de données (SQL synchrone côté worker — Celery est sync) ──────────
DONNA_DB_URL: str = _env("DONNA_DB_URL", "sqlite:///data/db.sqlite3")
# Variante async pour RagService recréé dans le worker d'ingestion.
DONNA_DB_URL_ASYNC: str = _env("DONNA_DB_URL_ASYNC", "sqlite+aiosqlite:///data/db.sqlite3")

# ── Redis ───────────────────────────────────────────────────────────────────
# Rappels : canal pub/sub + inbox, LUS par ext.pubsub côté API (base 0).
DONNA_REMINDER_REDIS_URL: str = _env("DONNA_REMINDER_REDIS_URL", "redis://localhost:6379/0")
# Statuts d'ingestion RAG : publiés par le worker, relayés par le pont API.
DONNA_RAG_STATUS_REDIS_URL: str = _env("DONNA_RAG_STATUS_REDIS_URL", "redis://localhost:6379/2")

REMINDER_PUBSUB_CHANNEL = "reminders"
RAG_STATUS_CHANNEL = "rag:status"
INBOX_KEY_PREFIX = "pubsub:inbox:"
INBOX_MAX_SIZE = 200

# ── Queues Celery ───────────────────────────────────────────────────────────
# `reminders` séparée de `rag` : une ingestion lourde ne doit jamais retarder
# un rappel temps-sensible (voir docker-compose.yml : worker dédié).
RAG_QUEUE = "rag"
REMINDERS_QUEUE = "reminders"

# ── Embeddings RAG (doivent matcher EXACTEMENT ext.rag côté API) ─────────────
OLLAMA_BASE_URL_DEFAULT = "http://localhost:11434"
EMBED_MODEL_DEFAULT = "nomic-embed-text"
EMBED_DIM_DEFAULT = 768


def rag_embed_config() -> dict:
    """Config RagService pour le worker d'ingestion — mêmes clés/valeurs que
    extensions.rag.service:RagService côté API. Une divergence provider/dim
    casse la recherche (dimension figée dans vec0 à la création)."""
    try:
        dim = int(_env("RAG_EMBED_DIM", "") or EMBED_DIM_DEFAULT)
    except ValueError:
        dim = EMBED_DIM_DEFAULT
    return {
        "db_url": DONNA_DB_URL_ASYNC,
        "ollama_base_url": _env("OLLAMA_BASE_URL", OLLAMA_BASE_URL_DEFAULT),
        "embed_provider": _env("RAG_EMBED_PROVIDER", "ollama"),
        "embed_model": _env("RAG_EMBED_MODEL", EMBED_MODEL_DEFAULT),
        "embed_dim": dim,
        # Vide = pas de clé = repli Ollama local (même philosophie que l'API).
        "embed_api_key": _env("RAG_EMBED_API_KEY", ""),
        "embed_base_url": _env("RAG_EMBED_BASE_URL", ""),
    }
