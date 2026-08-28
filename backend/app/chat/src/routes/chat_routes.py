from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xcore.kernel.api import AuthPayload, get_current_user
from xcore.sdk import get_logger

from extensions.doc_extract.extract import ExtractionError, classify, extract_text
from ..memory import (
    build_history,
    format_facts_context,
    format_pending_actions_context,
    format_reminders_context,
    load_facts,
    load_pending_actions,
    load_suspended_reminders,
    maybe_summarize,
)
from ..models import Attachment, Conversation, Message, PendingAction, Reminder, UserFact
from ..providers.base import ProviderUnavailableError
from ..providers.router import ProviderRouter
from ..schemas import (
    AttachmentOut,
    ChatRequest,
    ChatResponse,
    ConversationOut,
    FactOut,
    MessageOut,
    PendingActionOut,
    ProviderOut,
    ReminderOut,
    RenameConversationRequest,
    SetProviderRequest,
    SourceOut,
)
from ..tools import (
    ToolContext,
    cancel_pending_action,
    confirm_pending_action,
    run_chat_stream_with_tools,
    run_chat_with_tools,
)
from ..transcribe import Transcriber, TranscriptionError

logger = get_logger("chat.routes")

_VALID_PROVIDERS = {"ollama", "anthropic", "openai", "grok", "groq", "gemini"}


def _tenant_of(current_user: AuthPayload) -> str:
    return (current_user.get("user") or {}).get("tenant_id") or "default"


async def _resolve_conversation(
    session: AsyncSession,
    conversation_id: str | None,
    tenant_id: str,
    user_id: str,
    title_hint: str,
) -> Conversation:
    if conversation_id:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.tenant_id != tenant_id:
            raise HTTPException(404, "Conversation introuvable")
        return conversation

    conversation = Conversation(
        tenant_id=tenant_id,
        user_id=user_id,
        title=(title_hint or "Nouvelle conversation")[:60],
    )
    session.add(conversation)
    await session.flush()
    return conversation


# Score de rerank en dessous duquel un candidat n'est pas jugé pertinent par
# le cross-encoder — évite d'injecter 5 sources dont 4 hors-sujet à chaque
# question (le RRF seul ne sépare pas bien pertinent/non-pertinent).
_RERANK_MIN_SCORE = 0.0

# Marge de sécurité, pas une limite technique d'un provider précis : le texte
# extrait d'une pièce jointe (ex. une archive zip) s'ajoute à l'historique et
# au contexte RAG dans le même message — un fichier trop volumineux peut
# dépasser le budget de tokens du provider configuré et échouer en 503
# (ProviderUnavailableError), un message technique peu actionnable pour
# l'utilisateur. Mieux vaut refuser tôt, clairement, avant l'appel LLM.
_MAX_EXTRACTED_CHARS = 20_000


async def _rag_search(rag, tenant_id: str, query: str) -> list[dict]:
    """
    Dégradation silencieuse pour l'utilisateur (une base vide ou ext.rag
    indisponible ne doit jamais empêcher le chat de répondre) — mais loggée,
    pour ne pas perdre les échecs réels en silence.
    """
    try:
        results = await rag.search(tenant_id, query, top_k=5)
    except Exception as exc:
        logger.warning("recherche RAG échouée (dégradée, chat continue) : %s", exc)
        return []

    if results and "rerank_score" in results[0]:
        results = [r for r in results if r["rerank_score"] >= _RERANK_MIN_SCORE]
    return results


def _format_rag_context(results: list[dict]) -> dict[str, str] | None:
    """Message 'system' à insérer juste avant le tour utilisateur — jamais
    persisté en base (contexte propre à cet appel, pas à l'historique)."""
    if not results:
        return None
    blocks = [f"[Source: {r['source'] or r['doc_id']}]\n{r['text']}" for r in results]
    return {
        "role": "system",
        "content": (
            "Extraits de la base de connaissances de l'utilisateur, potentiellement "
            "utiles pour répondre. Utilise-les seulement s'ils sont pertinents à la "
            "question posée, ignore-les sinon.\n\n" + "\n\n---\n\n".join(blocks)
        ),
    }


def _build_sources(results: list[dict]) -> list[SourceOut]:
    """La section jugée pertinente (l'extrait retrouvé) + un lien vers le
    fichier source complet dans ext.storage, via le plugin rag."""
    return [
        SourceOut(
            doc_id=r["doc_id"],
            original_name=r["source"] or r["doc_id"],
            excerpt=r["text"],
            file_url=f"/app/rag/documents/{r['doc_id']}/file",
        )
        for r in results
    ]


async def _persist_generated_attachments(
    session, message_id: str, generated_files: list[dict]
) -> list[Attachment]:
    """Transforme les fichiers finalisés par save_generated_document (voir
    tools.py) en pièces jointes rattachées au message assistant — même
    mécanique que les pièces jointes uploadées par l'utilisateur dans
    /upload, juste déclenchée par un outil plutôt qu'un UploadFile."""
    created = []
    for gf in generated_files:
        attachment = Attachment(
            message_id=message_id,
            kind=gf["kind"],
            original_name=gf["original_name"],
            mime_type=gf["mime_type"],
            namespace=gf["namespace"],
            stored_name=gf["stored_name"],
            file_id=gf["file_id"],
        )
        session.add(attachment)
        created.append(attachment)
    if created:
        await session.flush()
    return created


def _build_attachments_out(attachments: list[Attachment]) -> list[AttachmentOut]:
    return [
        AttachmentOut(
            id=a.id,
            kind=a.kind,
            original_name=a.original_name,
            mime_type=a.mime_type,
            file_url=f"/app/chat/attachments/{a.id}/file",
            created_at=a.created_at,
        )
        for a in attachments
    ]


async def _generate_title(db, ollama: ProviderRouter, conversation_id: str, user_text: str) -> None:
    """
    Tâche de fond (non attendue par l'endpoint — ne doit jamais ralentir la
    réponse) : titre court généré par Ollama (tâche légère, toujours locale
    quel que soit le provider de génération configuré). Best-effort : un
    échec ici ne doit jamais faire planter quoi que ce soit.
    """
    try:
        title = await ollama.ollama.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Réponds uniquement par un titre court (5 mots maximum, sans "
                        "guillemets ni ponctuation finale) résumant le sujet du message "
                        "suivant, dans sa langue."
                    ),
                },
                {"role": "user", "content": user_text[:500]},
            ]
        )
        title = title.strip().strip('"').strip()[:60]
        if not title:
            return
        async with db.session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.title = title
    except Exception as exc:
        logger.warning("génération de titre échouée (ignorée) : %s", exc)


def chats_router(
    db,
    ollama: ProviderRouter,
    storage,
    transcriber: Transcriber,
    rag,
    websocket=None,
    google=None,
    call_plugin=None,
    mcp=None,
    build_provider=None,
) -> APIRouter:
    router = APIRouter(tags=["chat", "agent"])

    @router.post("/", summary="Send message for Donna", response_model=ChatResponse)
    async def chat(
        body: ChatRequest,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> ChatResponse:
        user_id = current_user["sub"]
        tenant_id = _tenant_of(current_user)

        rag_results = await _rag_search(rag, tenant_id, body.message)
        rag_context = _format_rag_context(rag_results)

        # Session courte : on écrit le message utilisateur et on referme AVANT
        # d'appeler Ollama (qui peut prendre 30-60s) pour ne pas garder le
        # verrou d'écriture SQLite ouvert pendant tout l'appel — sinon toute
        # autre requête d'écriture concurrente échoue en "database is locked".
        async with db.session() as session:
            conversation = await _resolve_conversation(
                session, body.conversation_id, tenant_id, user_id, body.message
            )
            facts_context = format_facts_context(await load_facts(session, tenant_id, user_id))
            reminders_context = format_reminders_context(
                await load_suspended_reminders(session, tenant_id, user_id)
            )
            pending_actions_context = format_pending_actions_context(
                await load_pending_actions(session, tenant_id, user_id)
            )
            ollama_messages = await build_history(session, conversation.id)
            if facts_context:
                ollama_messages.insert(0, facts_context)
            if reminders_context:
                ollama_messages.insert(0, reminders_context)
            if pending_actions_context:
                ollama_messages.insert(0, pending_actions_context)
            if rag_context:
                ollama_messages.append(rag_context)
            ollama_messages.append({"role": "user", "content": body.message})

            session.add(
                Message(conversation_id=conversation.id, role="user", content=body.message)
            )
            conversation_id = conversation.id

        tool_ctx = ToolContext(
            db=db,
            websocket=websocket,
            google=google,
            call_plugin=call_plugin,
            mcp=mcp,
            storage=storage,
            rag=rag,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        try:
            reply_text = await run_chat_with_tools(ollama, tool_ctx, ollama_messages)
        except ProviderUnavailableError as exc:
            # Message utilisateur déjà commité — l'échec du provider LLM ne le fait pas perdre.
            logger.warning("provider LLM indisponible (%s) : %s", ollama.default_name, exc)
            raise HTTPException(503, str(exc)) from exc

        async with db.session() as session:
            assistant_msg = Message(
                conversation_id=conversation_id, role="assistant", content=reply_text
            )
            session.add(assistant_msg)
            await session.flush()
            attachments = await _persist_generated_attachments(
                session, assistant_msg.id, tool_ctx.generated_files
            )

        if body.conversation_id is None:
            asyncio.create_task(_generate_title(db, ollama, conversation_id, body.message))
        asyncio.create_task(maybe_summarize(db, ollama, conversation_id))

        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply_text,
            sources=_build_sources(rag_results),
            memory_notes=tool_ctx.saved_facts,
            attachments=_build_attachments_out(attachments),
        )

    @router.post("/stream", summary="Envoyer un message, réponse en streaming (SSE)")
    async def chat_stream_endpoint(
        body: ChatRequest,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> StreamingResponse:
        user_id = current_user["sub"]
        tenant_id = _tenant_of(current_user)
        is_new_conversation = body.conversation_id is None

        rag_results = await _rag_search(rag, tenant_id, body.message)
        rag_context = _format_rag_context(rag_results)

        async with db.session() as session:
            conversation = await _resolve_conversation(
                session, body.conversation_id, tenant_id, user_id, body.message
            )
            facts_context = format_facts_context(await load_facts(session, tenant_id, user_id))
            reminders_context = format_reminders_context(
                await load_suspended_reminders(session, tenant_id, user_id)
            )
            pending_actions_context = format_pending_actions_context(
                await load_pending_actions(session, tenant_id, user_id)
            )
            ollama_messages = await build_history(session, conversation.id)
            if facts_context:
                ollama_messages.insert(0, facts_context)
            if reminders_context:
                ollama_messages.insert(0, reminders_context)
            if pending_actions_context:
                ollama_messages.insert(0, pending_actions_context)
            if rag_context:
                ollama_messages.append(rag_context)
            ollama_messages.append({"role": "user", "content": body.message})

            session.add(
                Message(conversation_id=conversation.id, role="user", content=body.message)
            )
            conversation_id = conversation.id

        tool_ctx = ToolContext(
            db=db,
            websocket=websocket,
            google=google,
            call_plugin=call_plugin,
            mcp=mcp,
            storage=storage,
            rag=rag,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        async def event_stream():
            yield f"event: start\ndata: {json.dumps({'conversation_id': conversation_id})}\n\n"

            chunks: list[str] = []
            try:
                async for event in run_chat_stream_with_tools(ollama, tool_ctx, ollama_messages):
                    if event["type"] == "delta":
                        chunks.append(event["content"])
                        yield f"data: {json.dumps({'delta': event['content']})}\n\n"
                    elif event["type"] == "tool_call":
                        yield f"event: tool_call\ndata: {json.dumps(event)}\n\n"
                    elif event["type"] == "provider_fallback":
                        yield f"event: provider_fallback\ndata: {json.dumps(event)}\n\n"
            except ProviderUnavailableError as exc:
                # Comme pour /  : sans ce log, un échec provider (rate limit,
                # clé invalide, timeout réseau) est invisible côté serveur —
                # le client ne voit qu'un toast générique "Chat failed".
                logger.warning("provider LLM indisponible (%s) : %s", ollama.default_name, exc)
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
                return
            except Exception:
                # Filet de dernier recours : une StreamingResponse a déjà
                # envoyé ses en-têtes (200) dès le premier octet — passé ce
                # point, une exception non catégorisée ne peut plus devenir
                # un code HTTP propre, elle coupe juste la connexion en
                # silence (constaté : validation d'arguments d'outil rejetée
                # par le SDK, le client ne voyait rien du tout, pas même
                # l'event "start"... si, mais rien après). Mieux vaut un
                # event "error" générique qu'un flux mort sans explication.
                logger.exception("erreur inattendue dans event_stream")
                yield f"event: error\ndata: {json.dumps({'error': 'Une erreur inattendue est survenue.'})}\n\n"
                return

            reply_text = "".join(chunks)
            async with db.session() as session:
                assistant_msg = Message(
                    conversation_id=conversation_id, role="assistant", content=reply_text
                )
                session.add(assistant_msg)
                await session.flush()
                attachments = await _persist_generated_attachments(
                    session, assistant_msg.id, tool_ctx.generated_files
                )

            if is_new_conversation:
                asyncio.create_task(_generate_title(db, ollama, conversation_id, body.message))
            asyncio.create_task(maybe_summarize(db, ollama, conversation_id))

            sources = [s.model_dump() for s in _build_sources(rag_results)]
            attachments_out = [a.model_dump(mode="json") for a in _build_attachments_out(attachments)]
            yield (
                "event: done\n"
                f"data: {json.dumps({'sources': sources, 'memory_notes': tool_ctx.saved_facts, 'attachments': attachments_out})}\n\n"
            )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.post(
        "/upload",
        summary="Envoyer un message avec fichiers (image/document, plusieurs possibles) et/ou audio",
        response_model=ChatResponse,
    )
    async def upload(
        conversation_id: str | None = Form(None),
        message: str | None = Form(None),
        files: list[UploadFile] = File(default_factory=list),
        audio: UploadFile | None = File(None),
        save_to_knowledge_base: bool = Form(False),
        current_user: AuthPayload = Depends(get_current_user),
    ) -> ChatResponse:
        user_id = current_user["sub"]
        tenant_id = _tenant_of(current_user)
        namespace = f"chat/{tenant_id}"

        text_parts: list[str] = [message] if message else []
        images_b64: list[str] = []
        pending_attachments: list[Attachment] = []

        if audio is not None:
            audio_bytes = await audio.read()
            suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
            try:
                transcript = await transcriber.transcribe(audio_bytes, suffix=suffix)
            except TranscriptionError as exc:
                raise HTTPException(400, str(exc)) from exc
            if transcript:
                text_parts.append(transcript)

            try:
                uploaded = await storage.save(audio_bytes, audio.filename or "audio", namespace)
            except Exception as exc:
                raise HTTPException(400, f"Échec du stockage audio : {exc}") from exc

            pending_attachments.append(
                Attachment(
                    kind="audio",
                    original_name=audio.filename or "audio",
                    mime_type=audio.content_type or "application/octet-stream",
                    namespace=uploaded.namespace,
                    stored_name=uploaded.stored_name,
                    file_id=uploaded.file_id,
                    extracted_text=transcript or None,
                )
            )

        for file in files:
            content = await file.read()
            filename = file.filename or "fichier"
            kind = classify(filename)

            try:
                uploaded = await storage.save(content, filename, namespace)
            except Exception as exc:
                raise HTTPException(400, f"Échec du stockage de '{filename}' : {exc}") from exc

            extracted: str | None = None
            if kind == "image":
                images_b64.append(base64.b64encode(content).decode())
                text_parts.append(f"[Image jointe : {filename}]")
            elif kind == "document":
                try:
                    extracted = extract_text(filename, content)
                except ExtractionError as exc:
                    raise HTTPException(400, str(exc)) from exc
                if extracted:
                    text_parts.append(f"[Contenu du document {filename}]\n{extracted}")
            else:
                raise HTTPException(400, f"Type de fichier non supporté : {filename}")

            pending_attachments.append(
                Attachment(
                    kind=kind,
                    original_name=filename,
                    mime_type=file.content_type or "application/octet-stream",
                    namespace=uploaded.namespace,
                    stored_name=uploaded.stored_name,
                    file_id=uploaded.file_id,
                    extracted_text=extracted,
                )
            )

            # Opt-in : le document rejoint la base de connaissances RAG en plus
            # d'être attaché à cette conversation. Réutilise le texte déjà
            # extrait et le fichier déjà stocké — pas de double upload/parsing.
            if save_to_knowledge_base and kind == "document" and extracted:
                rag_doc = await rag.create_document(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    namespace=uploaded.namespace,
                    stored_name=uploaded.stored_name,
                    file_id=uploaded.file_id,
                    original_name=filename,
                    mime_type=file.content_type or "application/octet-stream",
                )
                rag.enqueue_ingestion(rag_doc["id"], tenant_id, user_id, extracted)

        user_text = "\n\n".join(p for p in text_parts if p).strip()
        if not user_text and not images_b64:
            raise HTTPException(400, "Message, fichier ou audio requis")
        if len(user_text) > _MAX_EXTRACTED_CHARS:
            raise HTTPException(
                400,
                "Le contenu extrait de la pièce jointe est trop volumineux "
                f"({len(user_text)} caractères, maximum {_MAX_EXTRACTED_CHARS}) — "
                "essaie un fichier plus court ou plus ciblé.",
            )

        rag_results = await _rag_search(rag, tenant_id, user_text)
        rag_context = _format_rag_context(rag_results)

        # Session courte : voir commentaire dans chat() — on referme avant
        # l'appel Ollama pour ne pas garder le verrou d'écriture pendant
        # l'inférence.
        async with db.session() as session:
            conversation = await _resolve_conversation(
                session, conversation_id, tenant_id, user_id, user_text
            )
            facts_context = format_facts_context(await load_facts(session, tenant_id, user_id))
            reminders_context = format_reminders_context(
                await load_suspended_reminders(session, tenant_id, user_id)
            )
            pending_actions_context = format_pending_actions_context(
                await load_pending_actions(session, tenant_id, user_id)
            )
            ollama_messages = await build_history(session, conversation.id)
            if facts_context:
                ollama_messages.insert(0, facts_context)
            if reminders_context:
                ollama_messages.insert(0, reminders_context)
            if pending_actions_context:
                ollama_messages.insert(0, pending_actions_context)
            if rag_context:
                ollama_messages.append(rag_context)
            ollama_messages.append({"role": "user", "content": user_text})

            user_msg = Message(conversation_id=conversation.id, role="user", content=user_text)
            session.add(user_msg)
            await session.flush()

            for attachment in pending_attachments:
                attachment.message_id = user_msg.id
                session.add(attachment)

            conversation_id_out = conversation.id

        tool_ctx = ToolContext(
            db=db,
            websocket=websocket,
            google=google,
            call_plugin=call_plugin,
            mcp=mcp,
            storage=storage,
            rag=rag,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id_out,
        )
        try:
            reply_text = await run_chat_with_tools(
                ollama, tool_ctx, ollama_messages, images_b64=images_b64 or None
            )
        except ProviderUnavailableError as exc:
            raise HTTPException(503, str(exc)) from exc

        async with db.session() as session:
            assistant_msg = Message(
                conversation_id=conversation_id_out, role="assistant", content=reply_text
            )
            session.add(assistant_msg)
            await session.flush()
            attachments = await _persist_generated_attachments(
                session, assistant_msg.id, tool_ctx.generated_files
            )

        if conversation_id is None:
            asyncio.create_task(_generate_title(db, ollama, conversation_id_out, user_text))
        asyncio.create_task(maybe_summarize(db, ollama, conversation_id_out))

        return ChatResponse(
            conversation_id=conversation_id_out,
            reply=reply_text,
            sources=_build_sources(rag_results),
            memory_notes=tool_ctx.saved_facts,
            attachments=_build_attachments_out(attachments),
        )

    @router.get("/", summary="Lister mes conversations", response_model=list[ConversationOut])
    async def list_conversations(
        current_user: AuthPayload = Depends(get_current_user),
    ) -> list[ConversationOut]:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]

        async with db.session() as session:
            rows = (
                await session.execute(
                    select(Conversation)
                    .where(
                        Conversation.tenant_id == tenant_id,
                        Conversation.user_id == user_id,
                    )
                    .order_by(Conversation.created_at.desc())
                )
            ).scalars().all()

        return [ConversationOut(id=c.id, title=c.title) for c in rows]

    @router.patch(
        "/{conversation_id}",
        summary="Renommer une conversation",
        response_model=ConversationOut,
    )
    async def rename_conversation(
        conversation_id: str,
        body: RenameConversationRequest,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> ConversationOut:
        tenant_id = _tenant_of(current_user)
        title = body.title.strip()[:255]
        if not title:
            raise HTTPException(400, "Titre vide")

        async with db.session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None or conversation.tenant_id != tenant_id:
                raise HTTPException(404, "Conversation introuvable")
            conversation.title = title
            result = ConversationOut(id=conversation.id, title=conversation.title)

        return result

    @router.delete("/{conversation_id}", summary="Supprimer une conversation")
    async def delete_conversation(
        conversation_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> dict:
        tenant_id = _tenant_of(current_user)

        async with db.session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None or conversation.tenant_id != tenant_id:
                raise HTTPException(404, "Conversation introuvable")

            message_ids = (
                await session.execute(
                    select(Message.id).where(Message.conversation_id == conversation_id)
                )
            ).scalars().all()

            attachments = []
            if message_ids:
                attachments = (
                    await session.execute(
                        select(Attachment).where(Attachment.message_id.in_(message_ids))
                    )
                ).scalars().all()

            for attachment in attachments:
                await storage.delete(
                    attachment.file_id, attachment.namespace, attachment.stored_name
                )
                await session.delete(attachment)

            for message_id in message_ids:
                message = await session.get(Message, message_id)
                if message is not None:
                    await session.delete(message)

            await session.delete(conversation)

        return {"deleted": True}

    @router.get(
        "/{conversation_id}/attachments",
        summary="Lister les pièces jointes d'une conversation",
        response_model=list[AttachmentOut],
    )
    async def list_attachments(
        conversation_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> list[AttachmentOut]:
        tenant_id = _tenant_of(current_user)

        async with db.session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None or conversation.tenant_id != tenant_id:
                raise HTTPException(404, "Conversation introuvable")

            rows = (
                await session.execute(
                    select(Attachment)
                    .join(Message, Attachment.message_id == Message.id)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Attachment.created_at)
                )
            ).scalars().all()

        return [
            AttachmentOut(
                id=a.id,
                kind=a.kind,
                original_name=a.original_name,
                mime_type=a.mime_type,
                file_url=f"/app/chat/attachments/{a.id}/file",
                created_at=a.created_at,
            )
            for a in rows
        ]

    @router.get("/attachments/{attachment_id}/file", summary="Télécharger une pièce jointe")
    async def download_attachment(
        attachment_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> Response:
        tenant_id = _tenant_of(current_user)

        async with db.session() as session:
            row = (
                await session.execute(
                    select(Attachment)
                    .join(Message, Attachment.message_id == Message.id)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .where(Attachment.id == attachment_id, Conversation.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(404, "Pièce jointe introuvable")
            file_id, namespace, stored_name = row.file_id, row.namespace, row.stored_name
            mime_type, original_name = row.mime_type, row.original_name

        content_bytes = await storage.read(file_id, namespace, stored_name)
        if content_bytes is None:
            raise HTTPException(404, "Fichier introuvable dans le stockage")

        return Response(
            content=content_bytes,
            media_type=mime_type or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{original_name}"'},
        )

    @router.get(
        "/{conversation_id}/messages",
        summary="Historique d'une conversation",
        response_model=list[MessageOut],
    )
    async def get_messages(
        conversation_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> list[MessageOut]:
        tenant_id = _tenant_of(current_user)

        async with db.session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None or conversation.tenant_id != tenant_id:
                raise HTTPException(404, "Conversation introuvable")

            rows = (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at)
                )
            ).scalars().all()

            attachments_by_message: dict[str, list[Attachment]] = {}
            if rows:
                attachment_rows = (
                    await session.execute(
                        select(Attachment).where(
                            Attachment.message_id.in_([m.id for m in rows])
                        )
                    )
                ).scalars().all()
                for a in attachment_rows:
                    attachments_by_message.setdefault(a.message_id, []).append(a)

        return [
            MessageOut(
                role=m.role,
                content=m.content,
                attachments=_build_attachments_out(attachments_by_message.get(m.id, [])),
            )
            for m in rows
        ]

    @router.get(
        "/memory/facts",
        summary="Lister ce que Donna retient sur moi",
        response_model=list[FactOut],
    )
    async def list_facts(
        current_user: AuthPayload = Depends(get_current_user),
    ) -> list[FactOut]:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]

        async with db.session() as session:
            rows = (
                await session.execute(
                    select(UserFact)
                    .where(UserFact.tenant_id == tenant_id, UserFact.user_id == user_id)
                    .order_by(UserFact.created_at.desc())
                )
            ).scalars().all()

        return [FactOut(id=f.id, fact=f.fact, created_at=f.created_at) for f in rows]

    @router.delete("/memory/facts/{fact_id}", summary="Oublier un fait retenu")
    async def delete_fact(
        fact_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> dict:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]

        async with db.session() as session:
            fact = await session.get(UserFact, fact_id)
            if fact is None or fact.tenant_id != tenant_id or fact.user_id != user_id:
                raise HTTPException(404, "Fait introuvable")
            await session.delete(fact)

        return {"deleted": True}

    @router.get(
        "/memory/reminders",
        summary="Lister mes rappels (en attente ou programmés)",
        response_model=list[ReminderOut],
    )
    async def list_reminders(
        current_user: AuthPayload = Depends(get_current_user),
    ) -> list[ReminderOut]:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]

        async with db.session() as session:
            rows = (
                await session.execute(
                    select(Reminder)
                    .where(
                        Reminder.tenant_id == tenant_id,
                        Reminder.user_id == user_id,
                        Reminder.status.in_(["pending", "suspended"]),
                    )
                    .order_by(Reminder.created_at.desc())
                )
            ).scalars().all()

        return [
            ReminderOut(
                id=r.id, content=r.content, status=r.status, due_at=r.due_at, created_at=r.created_at
            )
            for r in rows
        ]

    @router.delete("/memory/reminders/{reminder_id}", summary="Annuler un rappel")
    async def cancel_reminder(
        reminder_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> dict:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]

        async with db.session() as session:
            reminder = await session.get(Reminder, reminder_id)
            if reminder is None or reminder.tenant_id != tenant_id or reminder.user_id != user_id:
                raise HTTPException(404, "Rappel introuvable")
            # Annulation « douce » : si une tâche xworker est déjà programmée
            # (due_at posé), fire_reminder vérifie ce statut avant de notifier
            # plutôt que de dépendre d'une révocation Celery.
            reminder.status = "cancelled"

        return {"cancelled": True}

    @router.get(
        "/memory/actions",
        summary="Lister les actions Google en attente de confirmation (email, agenda)",
        response_model=list[PendingActionOut],
    )
    async def list_pending_actions(
        current_user: AuthPayload = Depends(get_current_user),
    ) -> list[PendingActionOut]:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]

        async with db.session() as session:
            rows = (
                await session.execute(
                    select(PendingAction)
                    .where(
                        PendingAction.tenant_id == tenant_id,
                        PendingAction.user_id == user_id,
                        PendingAction.status == "pending",
                    )
                    .order_by(PendingAction.created_at.desc())
                )
            ).scalars().all()

        return [
            PendingActionOut(
                id=a.id, kind=a.kind, summary=a.summary, status=a.status, created_at=a.created_at
            )
            for a in rows
        ]

    async def _load_pending_action_or_404(action_id: str, tenant_id: str, user_id: str) -> PendingAction:
        async with db.session() as session:
            action = await session.get(PendingAction, action_id)
            if action is None or action.tenant_id != tenant_id or action.user_id != user_id:
                raise HTTPException(404, "Action introuvable")
            return action

    @router.post(
        "/memory/actions/{action_id}/confirm",
        summary="Confirmer et exécuter une action en attente (envoi email, modif agenda)",
    )
    async def confirm_action_endpoint(
        action_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> dict:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]
        action = await _load_pending_action_or_404(action_id, tenant_id, user_id)

        tool_ctx = ToolContext(
            db=db,
            websocket=websocket,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=action.conversation_id,
            google=google,
            call_plugin=call_plugin,
            mcp=mcp,
            storage=storage,
            rag=rag,
        )
        result = await confirm_pending_action(tool_ctx, action_id)
        return {"result": result}

    @router.post(
        "/memory/actions/{action_id}/cancel",
        summary="Annuler une action en attente sans l'exécuter",
    )
    async def cancel_action_endpoint(
        action_id: str,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> dict:
        tenant_id = _tenant_of(current_user)
        user_id = current_user["sub"]
        action = await _load_pending_action_or_404(action_id, tenant_id, user_id)

        tool_ctx = ToolContext(
            db=db,
            websocket=websocket,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=action.conversation_id,
            google=google,
            call_plugin=call_plugin,
            mcp=mcp,
            storage=storage,
            rag=rag,
        )
        result = await cancel_pending_action(tool_ctx, action_id)
        return {"result": result}

    @router.get(
        "/provider",
        summary="Provider LLM actif pour la génération de texte",
        response_model=ProviderOut,
    )
    async def get_active_provider(current_user: AuthPayload = Depends(get_current_user)) -> ProviderOut:
        return ProviderOut(provider=ollama.default_name)

    @router.post(
        "/provider",
        summary="Changer le provider LLM actif (en mémoire — pas de redémarrage requis, mais ne survit pas à un redémarrage)",
        response_model=ProviderOut,
    )
    async def set_active_provider(
        body: SetProviderRequest,
        current_user: AuthPayload = Depends(get_current_user),
    ) -> ProviderOut:
        name = body.provider.strip().lower()
        if name not in _VALID_PROVIDERS:
            raise HTTPException(
                400, f"Provider inconnu : '{name}'. Valides : {', '.join(sorted(_VALID_PROVIDERS))}."
            )

        if name == "ollama":
            ollama.set_default(None, "ollama")
            return ProviderOut(provider="ollama")

        if build_provider is None:
            raise HTTPException(503, "Changement de provider indisponible côté serveur.")

        new_provider = build_provider(name)
        if new_provider is None:
            raise HTTPException(
                400,
                f"Provider '{name}' invalide ou clé API absente (voir app/chat/.env) — "
                f"reste sur '{ollama.default_name}'.",
            )

        ollama.set_default(new_provider, name)
        return ProviderOut(provider=name)

    return router
