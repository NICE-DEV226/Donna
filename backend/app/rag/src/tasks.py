"""
Tâche Celery d'ingestion RAG — tourne dans le processus worker, séparé de
l'app FastAPI. Pas d'accès direct aux services xcore (ext.rag, ext.websocket
vivent dans le processus API) : on recrée une instance RagService le temps de
la tâche, et on publie les mises à jour de statut sur Redis pour que l'app
FastAPI les relaie aux clients websocket (voir status_bridge.py).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from xcore.services.xworker import task

REDIS_STATUS_URL = "redis://localhost:6379/2"
STATUS_CHANNEL = "rag:status"
SYNC_DB_URL = "sqlite:///data/db.sqlite3"

RAG_CONFIG = {
    "db_url": "sqlite+aiosqlite:///data/db.sqlite3",
    "ollama_base_url": "http://localhost:11434",
    "embed_model": "nomic-embed-text",
    "embed_dim": 768,
}

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def _publish_status(tenant_id: str, user_id: str, doc_id: str) -> None:
    import redis

    engine = create_engine(SYNC_DB_URL)
    try:
        with engine.connect() as conn:
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
    finally:
        engine.dispose()

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

    r = redis.Redis.from_url(REDIS_STATUS_URL)
    try:
        r.publish(STATUS_CHANNEL, json.dumps(payload, ensure_ascii=False))
    finally:
        r.close()


def _set_status(doc_id: str, status: str, chunk_count: int | None = None, error: str | None = None) -> None:
    engine = create_engine(SYNC_DB_URL)
    try:
        with engine.begin() as conn:
            fields = {"status": status, "error": error}
            sql = "UPDATE rag_documents SET status = :status, error = :error, updated_at = CURRENT_TIMESTAMP"
            if chunk_count is not None:
                sql += ", chunk_count = :chunk_count"
                fields["chunk_count"] = chunk_count
            sql += " WHERE id = :id"
            fields["id"] = doc_id
            conn.execute(text(sql), fields)
    finally:
        engine.dispose()


async def _ingest_async(content: str, tenant_id: str, doc_id: str) -> int:
    # Import tardif : évite de charger RagService (donc sqlite_vec) au simple
    # import du module de tâches, seulement quand une tâche s'exécute vraiment.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from extensions.rag.service import RagService

    from .chunking import chunk_text

    rag = RagService(RAG_CONFIG)
    await rag.init()
    try:
        chunks = chunk_text(content, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        for i, chunk in enumerate(chunks):
            await rag.index_chunk(tenant_id, doc_id, i, chunk)
        return len(chunks)
    finally:
        await rag.shutdown()


@task(name="rag.ingest_document", queue="rag", bind=True, max_retries=2)
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
