"""
ext.rag — moteur de recherche RAG pour Donna.

Extension pure : pas de HTTP, pas de notion de requête/JWT. Expose une
capacité "recherche dans la base de connaissances" consommée par n'importe
quel plugin (chat, rag, ...) via self.get_service("ext.rag").

Isolation multi-tenant : sqlite-vec (partition key) + FTS5 (jointure filtrée)
— chaque tenant ne voit jamais les chunks d'un autre.

Configuration dans integration.yaml :
    extensions:
      rag:
        module: services.rag.service:RagService
        config:
          db_url: sqlite+aiosqlite:///data/db.sqlite3
          ollama_base_url: http://localhost:11434
          embed_model: nomic-embed-text
          embed_dim: 768
"""

from __future__ import annotations

import json
import re
import struct
import uuid
from typing import Any

import httpx
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from xcore.kernel.observability import get_logger
from xcore.services.base import BaseService, ServiceStatus

from .fusion import reciprocal_rank_fusion
from .reranker import Reranker

logger = get_logger("ext.rag")

_FTS_TOKEN = re.compile(r"\w+", re.UNICODE)


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _sanitize_fts_query(query: str) -> str | None:
    """
    FTS5 a sa propre syntaxe de requête (?, *, ", -, (, ) sont des opérateurs)
    — une question en langage naturel ("... ?") la casse telle quelle. On
    extrait juste les mots et on les joint en OR pour un recall large (la
    fusion RRF avec le vecteur se charge de la précision).
    """
    tokens = _FTS_TOKEN.findall(query)
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


_DOCUMENT_COLUMNS = (
    "id",
    "tenant_id",
    "user_id",
    "namespace",
    "stored_name",
    "file_id",
    "original_name",
    "mime_type",
    "status",
    "error",
    "chunk_count",
    "created_at",
    "updated_at",
)


def _document_row_to_dict(row) -> dict[str, Any]:
    return dict(zip(_DOCUMENT_COLUMNS, row))


class RagService(BaseService):
    name = "rag"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._cfg = config or {}
        self._db_url = self._cfg.get("db_url", "sqlite+aiosqlite:///data/db.sqlite3")
        self._embed_model = self._cfg.get("embed_model", "nomic-embed-text")
        self._embed_dim = int(self._cfg.get("embed_dim", 768))
        self._ollama_base_url = self._cfg.get("ollama_base_url", "http://localhost:11434")
        self._rerank_enabled = bool(self._cfg.get("rerank_enabled", True))
        self._engine = None
        self._http: httpx.AsyncClient | None = None
        self._reranker = Reranker()

    async def init(self) -> None:
        self._status = ServiceStatus.INITIALIZING

        import sqlite_vec

        self._engine = create_async_engine(self._db_url)

        @event.listens_for(self._engine.sync_engine, "connect")
        def _load_vec(dbapi_conn, _record) -> None:
            async def _do_load(raw_conn) -> None:
                await raw_conn.enable_load_extension(True)
                await raw_conn.load_extension(sqlite_vec.loadable_path())
                await raw_conn.enable_load_extension(False)

            dbapi_conn.run_async(_do_load)

        self._http = httpx.AsyncClient(base_url=self._ollama_base_url, timeout=60.0)

        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS rag_chunks (
                        id INTEGER PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        doc_id TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        metadata TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_rag_chunks_doc ON rag_chunks(tenant_id, doc_id)")
            )
            await conn.execute(
                text(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_vec USING vec0(
                        embedding float[{self._embed_dim}],
                        tenant_id TEXT partition key
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(
                        text, content='rag_chunks', content_rowid='id'
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS rag_documents (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        namespace TEXT NOT NULL,
                        stored_name TEXT NOT NULL,
                        file_id TEXT NOT NULL,
                        original_name TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        error TEXT,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_rag_documents_owner "
                    "ON rag_documents(tenant_id, user_id)"
                )
            )

        self._status = ServiceStatus.READY

    async def shutdown(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        if self._engine is not None:
            await self._engine.dispose()
        self._status = ServiceStatus.STOPPED

    async def health_check(self) -> tuple[bool, str]:
        if self._engine is None:
            return False, "moteur non initialisé"
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT vec_version()"))
            return True, "ok"
        except Exception as exc:
            return False, str(exc)

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "status": self._status.value, "model": self._embed_model}

    # ── Embeddings ───────────────────────────────────────────

    async def embed(self, content: str) -> list[float]:
        resp = await self._http.post(
            "/api/embed", json={"model": self._embed_model, "input": content}
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"][0]

    # ── Ingestion ────────────────────────────────────────────

    async def index_chunk(
        self,
        tenant_id: str,
        doc_id: str,
        chunk_index: int,
        content: str,
        metadata: dict | None = None,
    ) -> int:
        embedding = await self.embed(content)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    INSERT INTO rag_chunks (tenant_id, doc_id, chunk_index, text, metadata)
                    VALUES (:tenant_id, :doc_id, :chunk_index, :content, :metadata)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "doc_id": doc_id,
                    "chunk_index": chunk_index,
                    "content": content,
                    "metadata": json.dumps(metadata or {}),
                },
            )
            chunk_id = result.lastrowid

            await conn.execute(
                text(
                    "INSERT INTO rag_vec(rowid, embedding, tenant_id) VALUES (:id, :embedding, :tenant_id)"
                ),
                {"id": chunk_id, "embedding": _pack(embedding), "tenant_id": tenant_id},
            )
            await conn.execute(
                text("INSERT INTO rag_fts(rowid, text) VALUES (:id, :content)"),
                {"id": chunk_id, "content": content},
            )

        return chunk_id

    async def delete_document(self, tenant_id: str, doc_id: str) -> int:
        async with self._engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id FROM rag_chunks WHERE tenant_id = :tenant_id AND doc_id = :doc_id"
                    ),
                    {"tenant_id": tenant_id, "doc_id": doc_id},
                )
            ).fetchall()
            ids = [r[0] for r in rows]
            if not ids:
                return 0

            for chunk_id in ids:
                await conn.execute(text("DELETE FROM rag_vec WHERE rowid = :id"), {"id": chunk_id})
                await conn.execute(text("DELETE FROM rag_fts WHERE rowid = :id"), {"id": chunk_id})
            await conn.execute(
                text(
                    "DELETE FROM rag_chunks WHERE tenant_id = :tenant_id AND doc_id = :doc_id"
                ),
                {"tenant_id": tenant_id, "doc_id": doc_id},
            )
        return len(ids)

    # ── Recherche hybride (vecteur + BM25, fusion RRF) ──────────

    async def search(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 5,
        candidates: int = 20,
    ) -> list[dict[str, Any]]:
        query_embedding = await self.embed(query)

        async with self._engine.connect() as conn:
            vec_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT rowid FROM rag_vec
                        WHERE embedding MATCH :embedding AND tenant_id = :tenant_id AND k = :k
                        ORDER BY distance
                        """
                    ),
                    {"embedding": _pack(query_embedding), "tenant_id": tenant_id, "k": candidates},
                )
            ).fetchall()
            vec_ranked = [r[0] for r in vec_rows]

            fts_query = _sanitize_fts_query(query)
            fts_ranked: list[int] = []
            if fts_query is not None:
                fts_rows = (
                    await conn.execute(
                        text(
                            """
                            SELECT rag_chunks.id
                            FROM rag_fts
                            JOIN rag_chunks ON rag_fts.rowid = rag_chunks.id
                            WHERE rag_fts MATCH :query AND rag_chunks.tenant_id = :tenant_id
                            ORDER BY bm25(rag_fts) ASC
                            LIMIT :candidates
                            """
                        ),
                        {"query": fts_query, "tenant_id": tenant_id, "candidates": candidates},
                    )
                ).fetchall()
                fts_ranked = [r[0] for r in fts_rows]

            fused = reciprocal_rank_fusion([vec_ranked, fts_ranked])
            # Pool complet (pas juste top_k) : le rerank a besoin de candidats
            # à départager, pas juste du résultat déjà tranché par RRF.
            candidate_ids = [i for i, _ in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)]
            if not candidate_ids:
                return []

            placeholders = ", ".join(f":id{i}" for i in range(len(candidate_ids)))
            params = {f"id{i}": chunk_id for i, chunk_id in enumerate(candidate_ids)}
            chunk_rows = (
                await conn.execute(
                    text(
                        f"""
                        SELECT rag_chunks.id, rag_chunks.doc_id, rag_chunks.chunk_index,
                               rag_chunks.text, rag_chunks.metadata, rag_documents.original_name
                        FROM rag_chunks
                        LEFT JOIN rag_documents ON rag_documents.id = rag_chunks.doc_id
                        WHERE rag_chunks.id IN ({placeholders})
                        """
                    ),
                    params,
                )
            ).fetchall()

        by_id = {r[0]: r for r in chunk_rows}
        candidates_out = []
        for chunk_id in candidate_ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            candidates_out.append(
                {
                    "id": row[0],
                    "doc_id": row[1],
                    "chunk_index": row[2],
                    "text": row[3],
                    "metadata": json.loads(row[4]) if row[4] else {},
                    "source": row[5],
                    "score": fused[chunk_id],
                }
            )

        if self._rerank_enabled and candidates_out:
            try:
                return await self._reranker.rerank(query, candidates_out, top_k=top_k)
            except Exception as exc:
                logger.warning("rerank échoué, fallback classement RRF : %s", exc)

        return candidates_out[:top_k]

    # ── Suivi des documents (upload → ingestion en tâche de fond) ──────

    async def create_document(
        self,
        tenant_id: str,
        user_id: str,
        namespace: str,
        stored_name: str,
        file_id: str,
        original_name: str,
        mime_type: str,
    ) -> dict[str, Any]:
        """Enregistre un document en statut 'pending' — à combiner avec enqueue_ingestion()."""
        doc_id = str(uuid.uuid4())
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO rag_documents
                        (id, tenant_id, user_id, namespace, stored_name, file_id, original_name,
                         mime_type, status, chunk_count, created_at, updated_at)
                    VALUES
                        (:id, :tenant_id, :user_id, :namespace, :stored_name, :file_id, :original_name,
                         :mime_type, 'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": doc_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "namespace": namespace,
                    "stored_name": stored_name,
                    "file_id": file_id,
                    "original_name": original_name,
                    "mime_type": mime_type,
                },
            )
        doc = await self.get_document(tenant_id, doc_id)
        assert doc is not None
        return doc

    def enqueue_ingestion(self, doc_id: str, tenant_id: str, user_id: str, content: str) -> None:
        """Envoie la tâche Celery d'ingestion — appelant n'a pas besoin de connaître le nom de la tâche."""
        from xcore.sdk import task_registry

        task_registry["rag.ingest_document"].apply_async(
            kwargs={"doc_id": doc_id, "tenant_id": tenant_id, "user_id": user_id, "content": content},
            queue="rag",
        )

    async def get_document(self, tenant_id: str, doc_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT * FROM rag_documents WHERE id = :id AND tenant_id = :tenant_id"),
                    {"id": doc_id, "tenant_id": tenant_id},
                )
            ).fetchone()
        return _document_row_to_dict(row) if row else None

    async def list_documents(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT * FROM rag_documents
                        WHERE tenant_id = :tenant_id AND user_id = :user_id
                        ORDER BY created_at DESC
                        """
                    ),
                    {"tenant_id": tenant_id, "user_id": user_id},
                )
            ).fetchall()
        return [_document_row_to_dict(r) for r in rows]

    async def delete_document_record(self, tenant_id: str, doc_id: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM rag_documents WHERE id = :id AND tenant_id = :tenant_id"),
                {"id": doc_id, "tenant_id": tenant_id},
            )
        return result.rowcount > 0
