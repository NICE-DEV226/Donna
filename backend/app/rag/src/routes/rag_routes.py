from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from xcore.kernel.api import AuthPayload, get_current_user

from extensions.doc_extract.extract import ExtractionError, classify, extract_text

from ..schemas import DocumentOut


def _tenant_of(current_user: AuthPayload) -> str:
    return (current_user.get("user") or {}).get("tenant_id") or "default"


def rag_router(storage, rag) -> APIRouter:
    router = APIRouter(tags=["rag"])

    @router.post("/documents", summary="Ajouter un document à la base de connaissances")
    async def upload_document(
        file: UploadFile = File(...),
        current_user: AuthPayload = Depends(get_current_user),
    ) -> DocumentOut:
        user_id = current_user["sub"]
        tenant_id = _tenant_of(current_user)
        namespace = f"rag/{tenant_id}"
        filename = file.filename or "document"

        if classify(filename) != "document":
            raise HTTPException(400, f"Type de fichier non supporté pour le RAG : {filename}")

        content_bytes = await file.read()
        try:
            extracted = extract_text(filename, content_bytes)
        except ExtractionError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not extracted:
            raise HTTPException(400, "Aucun texte exploitable dans ce document")

        try:
            uploaded = await storage.save(content_bytes, filename, namespace)
        except Exception as exc:
            raise HTTPException(400, f"Échec du stockage : {exc}") from exc

        doc = await rag.create_document(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=uploaded.namespace,
            stored_name=uploaded.stored_name,
            file_id=uploaded.file_id,
            original_name=filename,
            mime_type=file.content_type or "application/octet-stream",
        )
        rag.enqueue_ingestion(doc["id"], tenant_id, user_id, extracted)
        return DocumentOut(**doc)

    @router.post(
        "/documents/{document_id}/reingest",
        summary="Relancer l'ingestion d'un document existant (pending/failed)",
    )
    async def reingest_document(
        document_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> DocumentOut:
        user_id = current_user["sub"]
        tenant_id = _tenant_of(current_user)

        doc = await rag.get_document(tenant_id, document_id)
        if doc is None:
            raise HTTPException(404, "Document introuvable")

        content_bytes = await storage.read(doc["file_id"], doc["namespace"], doc["stored_name"])
        if content_bytes is None:
            raise HTTPException(404, "Fichier introuvable dans le stockage")

        try:
            extracted = extract_text(doc["original_name"], content_bytes)
        except ExtractionError as exc:
            raise HTTPException(400, str(exc)) from exc

        rag.enqueue_ingestion(document_id, tenant_id, user_id, extracted)
        return DocumentOut(**doc)

    @router.post(
        "/documents/discover",
        summary="Découvrir et ingérer les fichiers déjà présents dans le stockage",
        response_model=list[DocumentOut],
    )
    async def discover_documents(
        current_user: AuthPayload = Depends(get_current_user),
    ) -> list[DocumentOut]:
        """
        Scanne le namespace rag/{tenant} du stockage et ingère tout fichier
        pas encore suivi dans rag_documents (ex : déposé manuellement, ou
        depuis une source externe). Le nom d'origine n'est pas récupérable
        pour ces fichiers (seul {file_id}{ext} est physiquement stocké) —
        le stored_name sert de nom faute de mieux.
        """
        user_id = current_user["sub"]
        tenant_id = _tenant_of(current_user)
        namespace = f"rag/{tenant_id}"

        known = await rag.list_documents(tenant_id, user_id)
        known_stored_names = {d["stored_name"] for d in known}

        found = await storage.list(namespace)
        new_docs = []
        for entry in found:
            if entry["stored_name"] in known_stored_names:
                continue

            content_bytes = await storage.read(
                entry["file_id"], entry["namespace"], entry["stored_name"]
            )
            if content_bytes is None:
                continue

            if classify(entry["stored_name"]) != "document":
                continue
            try:
                extracted = extract_text(entry["stored_name"], content_bytes)
            except ExtractionError:
                continue
            if not extracted:
                continue

            doc = await rag.create_document(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=entry["namespace"],
                stored_name=entry["stored_name"],
                file_id=entry["file_id"],
                original_name=entry["stored_name"],
                mime_type="application/octet-stream",
            )
            rag.enqueue_ingestion(doc["id"], tenant_id, user_id, extracted)
            new_docs.append(DocumentOut(**doc))

        return new_docs

    @router.get("/documents", summary="Lister mes documents", response_model=list[DocumentOut])
    async def list_documents(
        current_user: AuthPayload = Depends(get_current_user),
    ) -> list[DocumentOut]:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]
        docs = await rag.list_documents(tenant_id, user_id)
        return [DocumentOut(**d) for d in docs]

    @router.get(
        "/documents/{document_id}/file",
        summary="Télécharger le fichier source d'un document",
    )
    async def download_document(
        document_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> Response:
        tenant_id = _tenant_of(current_user)

        doc = await rag.get_document(tenant_id, document_id)
        if doc is None:
            raise HTTPException(404, "Document introuvable")

        content_bytes = await storage.read(doc["file_id"], doc["namespace"], doc["stored_name"])
        if content_bytes is None:
            raise HTTPException(404, "Fichier introuvable dans le stockage")

        return Response(
            content=content_bytes,
            media_type=doc["mime_type"] or "application/octet-stream",
            headers={
                "Content-Disposition": f'inline; filename="{doc["original_name"]}"'
            },
        )

    @router.delete("/documents/{document_id}", summary="Supprimer un document de la base")
    async def delete_document(
        document_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> dict:
        tenant_id = _tenant_of(current_user)

        doc = await rag.get_document(tenant_id, document_id)
        if doc is None:
            raise HTTPException(404, "Document introuvable")

        await storage.delete(doc["file_id"], doc["namespace"], doc["stored_name"])
        deleted_chunks = await rag.delete_document(tenant_id, document_id)
        await rag.delete_document_record(tenant_id, document_id)

        return {"deleted": True, "chunks_removed": deleted_chunks}

    return router
