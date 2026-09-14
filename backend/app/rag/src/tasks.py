"""
Tâche Celery d'ingestion RAG — tourne dans le processus worker, séparé de
l'app FastAPI. Pas d'accès direct aux services xcore (ext.rag, ext.websocket
vivent dans le processus API) : on recrée une instance RagService le temps de
la tâche, et on publie les mises à jour de statut sur Redis pour que l'app
FastAPI les relaie aux clients websocket (voir status_bridge.py).

Config : extensions/worker_env.py — les URLs et surtout la config d'embeddings
(provider/modèle/dimension) DOIVENT matcher ext.rag côté API (historiquement
le worker hardcodait Ollama/768 contre Jina/1024 en prod → recherche cassée,
dimension figée dans vec0).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Le worker ne boote pas xcore : backend/ n'est pas forcément sur sys.path —
# bootstrap explicite avant tout import extensions.*.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import create_engine, text  # noqa: E402

from extensions import worker_env  # noqa: E402
from extensions.donna_settings import CHUNK_OVERLAP, CHUNK_SIZE  # noqa: E402
from xcore.services.xworker import task  # noqa: E402

try:
    # Disponible uniquement dans le processus worker (celery installé).
    from celery.signals import worker_process_shutdown
except ImportError:  # pragma: no cover - import API/test sans celery
    worker_process_shutdown = None

# Chunking ingestion — réglages ops centralisés, voir
# extensions/donna_settings.py (DONNA_CHUNK_*).

_engine = None


def _get_engine():
    """Moteur SQL partagé du processus (un par process prefork — créé
    paresseusement APRES le fork, jamais hérité)."""
    global _engine
    if _engine is None:
        _engine = create_engine(worker_env.DONNA_DB_URL, pool_pre_ping=True)
    return _engine


if worker_process_shutdown is not None:  # pragma: no cover - signal worker réel

    @worker_process_shutdown.connect
    def _dispose_engine(**kwargs) -> None:
        global _engine
        if _engine is not None:
            _engine.dispose()
            _engine = None


def _publish_status(tenant_id: str, user_id: str, doc_id: str) -> None:
    import redis

    with _get_engine().connect() as conn:
        current = conn.execute(
            text("SELECT id, original_name, status FROM rag_documents WHERE id = :id"),
            {"id": doc_id},
        ).fetchone()
        previous = conn.execute(
            text(
                """
                SELECT id, original_name, status FROM rag_documents
                WHERE tenant_id = :tenant_id AND status IN ('done', 'failed') AND id != :id
                ORDER BY updated_at DESC LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "id": doc_id},
        ).fetchone()
        nxt = conn.execute(
            text(
                """
                SELECT id, original_name, status FROM rag_documents
                WHERE tenant_id = :tenant_id AND status = 'pending' AND id != :id
                ORDER BY created_at ASC LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "id": doc_id},
        ).fetchone()

    def _slot(row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {"document_id": row[0], "original_name": row[1], "status": row[2]}

    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "previous": _slot(previous),
        "current": _slot(current),
        "next": _slot(nxt),
    }

    r = redis.Redis.from_url(worker_env.DONNA_RAG_STATUS_REDIS_URL)
    try:
        r.publish(worker_env.RAG_STATUS_CHANNEL, json.dumps(payload, ensure_ascii=False))
    finally:
        r.close()


def _set_status(doc_id: str, status: str, chunk_count: int | None = None, error: str | None = None) -> None:
    with _get_engine().begin() as conn:
        fields = {"status": status, "error": error}
        sql = "UPDATE rag_documents SET status = :status, error = :error, updated_at = CURRENT_TIMESTAMP"
        if chunk_count is not None:
            sql += ", chunk_count = :chunk_count"
            fields["chunk_count"] = chunk_count
        sql += " WHERE id = :id"
        fields["id"] = doc_id
        conn.execute(text(sql), fields)


async def _ingest_async(content: str, tenant_id: str, doc_id: str) -> int:
    # Import tardif : évite de charger RagService (donc sqlite_vec) au simple
    # import du module de tâches, seulement quand une tâche s'exécute vraiment.
    from extensions.donna_settings import EMBED_BATCH_SIZE
    from extensions.rag.service import RagService

    from .chunking import chunk_text

    # Config embeddings depuis l'environnement (worker_env) — IDENTIQUE à
    # ext.rag côté API, jamais de littéraux ici (voir module docstring).
    rag = RagService(worker_env.rag_embed_config())
    await rag.init()
    try:
        chunks = chunk_text(content, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        # Embeddings par lots (DONNA_EMBED_BATCH_SIZE, défaut 16) : 100 chunks
        # = ~7 round-trips HTTP au lieu de 100 séquentiels. Les écritures
        # restent unitaires (1 transaction/chunk, sémantique inchangée).
        batch_size = max(1, EMBED_BATCH_SIZE)
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            embeddings = await rag.embed_many(batch)
            for offset, (chunk, embedding) in enumerate(zip(batch, embeddings)):
                await rag.index_chunk_with_embedding(
                    tenant_id, doc_id, start + offset, chunk, embedding
                )
        return len(chunks)
    finally:
        await rag.shutdown()


@task(name="rag.ingest_document", queue=worker_env.RAG_QUEUE, bind=True, max_retries=2)
def ingest_document(self, doc_id: str, tenant_id: str, user_id: str, content: str) -> dict:
    """
    Ingère un document déjà extrait en texte (content) : chunking + embedding
    + indexation dans ext.rag. Met à jour rag_documents.status et publie sur
    Redis à chaque transition pour que le bridge websocket informe l'utilisateur.
    """
    _set_status(doc_id, "processing")
    _publish_status(tenant_id, user_id, doc_id)

    try:
        chunk_count = asyncio.run(_ingest_async(content, tenant_id, doc_id))
        _set_status(doc_id, "done", chunk_count=chunk_count)
        _publish_status(tenant_id, user_id, doc_id)
        return {"doc_id": doc_id, "status": "done", "chunk_count": chunk_count}
    except Exception as exc:
        _set_status(doc_id, "failed", error=str(exc))
        _publish_status(tenant_id, user_id, doc_id)
        raise
