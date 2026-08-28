from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from xcore.sdk import get_logger

from extensions.doc_extract.extract import ExtractionError, extract_text
from .memory import load_facts
from .models import PendingAction, Reminder, UserFact

logger = get_logger("chat.tools")

# Nombre max d'allers-retours modèle -> outil -> modèle avant de forcer une
# réponse texte — garde-fou contre une boucle d'appels d'outils qui ne
# converge jamais. Volontairement plus haut que ce qu'un simple appel
# d'outil demanderait : générer un document (word/excel/pdf via MCP) est
# intrinsèquement multi-étapes (create -> plusieurs add_* -> finalize).
MAX_TOOL_ROUNDS = 12

# Sous-dossiers de travail des serveurs MCP document (voir integration.yaml,
# extensions.mcp_bridge.servers.*.cwd) — c'est là que create_document/
# create_workbook/etc. écrivent leurs fichiers, puisque chaque serveur y est
# lancé avec ce cwd.
_MCP_DOCUMENTS_ROOT = Path("data/mcp_documents")

# Quota sur les documents générés (word/excel/pdf) — même plafond par
# fichier que ext.storage (max_size_mb: 25, voir integration.yaml) pour
# rester cohérent, plus un plafond cumulé par tenant puisque ces fichiers
# vivent sur disque local hors du contrôle de taille de ext.storage tant
# que save_generated_document n'a pas tourné.
_MAX_GENERATED_FILE_BYTES = 25 * 1_048_576
_MAX_TENANT_DOCS_BYTES = 200 * 1_048_576


def _tenant_docs_usage_bytes(tenant_id: str) -> int:
    total = 0
    for sub in ("word", "excel", "pdf"):
        tenant_dir = _MCP_DOCUMENTS_ROOT / sub / tenant_id
        if tenant_dir.is_dir():
            total += sum(f.stat().st_size for f in tenant_dir.iterdir() if f.is_file())
    return total

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": (
                "Enregistre UN SEUL fait nouveau, durable et utile à propos de "
                "l'utilisateur, pour s'en souvenir dans les prochaines conversations. "
                "À utiliser seulement pour une information stable (préférence, "
                "contexte personnel ou professionnel) — jamais pour du contexte "
                "ponctuel propre à cette seule question. N'inclus dans le texte que "
                "l'information nouvelle : ne répète pas et ne fusionne pas avec des "
                "faits déjà connus (visibles plus haut dans la conversation) — appelle "
                "l'outil une fois par fait distinct si plusieurs faits apparaissent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": (
                            "Le nouveau fait à retenir, et rien d'autre — formulé court "
                            "et de façon autonome, sans reprendre un fait déjà connu."
                        ),
                    }
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_fact",
            "description": (
                "Corrige un fait déjà retenu, devenu inexact ou incomplet (ex: "
                "l'utilisateur a changé de poste). Utilise l'identifiant exact montré "
                "en contexte entre crochets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_id": {"type": "string", "description": "Identifiant exact du fait, entre crochets en contexte."},
                    "fact": {"type": "string", "description": "Le fait corrigé, formulé court et autonome."},
                },
                "required": ["fact_id", "fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_fact",
            "description": (
                "Efface définitivement un fait retenu, s'il n'est plus pertinent ou "
                "que l'utilisateur demande à ce qu'il soit oublié. Utilise "
                "l'identifiant exact montré en contexte entre crochets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_id": {"type": "string", "description": "Identifiant exact du fait, entre crochets en contexte."},
                },
                "required": ["fact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Programme un rappel pour l'utilisateur. Si une date/heure précise "
                "est donnée ou déductible de la date actuelle (voir contexte), fournis "
                "due_at au format ISO 8601 complet (ex: '2026-08-27T09:00:00') — le "
                "rappel se déclenchera automatiquement à ce moment, même si "
                "l'utilisateur n'est pas en conversation. Si aucune date/heure n'est "
                "connue, omets due_at : le rappel reste en attente et tu pourras le "
                "ressortir toi-même dans une prochaine conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Ce dont il faut se souvenir / rappeler à l'utilisateur.",
                    },
                    "due_at": {
                        "type": ["string", "null"],
                        "description": (
                            "Date et heure ISO 8601 du rappel, si connue ou déductible. "
                            "Omis ou null si aucune date n'est donnée."
                        ),
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": (
                "Annule un rappel — à utiliser quand l'utilisateur indique que ce "
                "n'est plus utile. Fonctionne sur les rappels en attente sans date "
                "listés en contexte ; pour un rappel déjà programmé à une date "
                "précise, l'identifiant n'est visible que si l'utilisateur te l'a "
                "donné explicitement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "Identifiant exact du rappel, entre crochets en contexte."},
                },
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Signale au frontend que tu poses une question de clarification "
                "importante à l'utilisateur (ex: préciser une date pour un rappel). "
                "N'appelle ceci qu'en plus d'écrire la question normalement dans ta "
                "réponse — ça ne la remplace pas, ça la met en évidence côté "
                "interface."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "La question posée à l'utilisateur, telle quelle.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Si la question a des réponses prédéfinies (2 à 5 choix "
                            "courts), liste-les ici — l'interface les affiche en "
                            "boutons cliquables. Laisse vide pour une question ouverte."
                        ),
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": (
                "Cherche dans les emails Gmail de l'utilisateur (lecture seule). "
                "Utilise la syntaxe de recherche Gmail pour query si besoin (ex: "
                "'from:x@y.com is:unread'), ou un texte libre."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": ["string", "null"], "description": "Recherche Gmail, ou vide/null pour les plus récents."},
                    "max_results": {"type": ["integer", "null"], "description": "Nombre max de résultats (5 par défaut, 10 max)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_upcoming_events",
            "description": "Liste les prochains événements de l'agenda Google de l'utilisateur (lecture seule).",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": ["integer", "null"], "description": "Nombre max d'événements (10 par défaut)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_email",
            "description": (
                "Prépare un email à envoyer au nom de l'utilisateur — NE L'ENVOIE PAS. "
                "Stocke une action en attente que l'utilisateur doit confirmer "
                "explicitement (via confirm_action) avant tout envoi réel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Adresse email du destinataire."},
                    "subject": {"type": "string", "description": "Objet de l'email."},
                    "body": {"type": "string", "description": "Corps du message, texte brut."},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_calendar_event",
            "description": (
                "Prépare une création, modification ou suppression d'événement dans "
                "l'agenda Google de l'utilisateur — NE L'APPLIQUE PAS. Stocke une "
                "action en attente que l'utilisateur doit confirmer explicitement "
                "(via confirm_action) avant toute modification réelle de l'agenda."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "'create', 'update' ou 'delete'."},
                    "event_id": {"type": ["string", "null"], "description": "Requis pour update/delete — identifiant de l'événement Google."},
                    "title": {"type": ["string", "null"], "description": "Titre de l'événement (create/update)."},
                    "start_datetime": {"type": ["string", "null"], "description": "Début, ISO 8601 (create/update)."},
                    "end_datetime": {"type": ["string", "null"], "description": "Fin, ISO 8601 (create/update)."},
                    "description": {"type": ["string", "null"], "description": "Description optionnelle."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_action",
            "description": (
                "Confirme et exécute réellement une action en attente (voir contexte) — "
                "envoie l'email ou applique le changement d'agenda. N'appelle ceci que "
                "si l'utilisateur vient de confirmer explicitement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_id": {"type": "string", "description": "Identifiant exact montré en contexte entre crochets."},
                },
                "required": ["action_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_action",
            "description": "Annule une action en attente sans l'exécuter (voir contexte).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_id": {"type": "string", "description": "Identifiant exact montré en contexte entre crochets."},
                },
                "required": ["action_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_generated_document",
            "description": (
                "Termine et joint à la conversation un document créé via les outils "
                "word/excel/pdf (mcp_word_*, mcp_excel_*, mcp_pdf_*) — à appeler une "
                "fois le document fini, avec le même nom de fichier utilisé lors de sa "
                "création (create_document, create_workbook, markdown_to_pdf...)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Nom de fichier exact utilisé à la création (avec extension).",
                    },
                    "save_to_knowledge_base": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Si vrai, le document rejoint aussi la base de "
                            "connaissances (RAG) en plus d'être joint à la "
                            "conversation — seulement si l'utilisateur l'a demandé "
                            "explicitement. Faux par défaut."
                        ),
                    },
                },
                "required": ["filename"],
            },
        },
    },
]


def _build_tools_hint(reference_now: datetime) -> dict:
    now = reference_now.isoformat(timespec="seconds")
    return {
        "role": "system",
        "content": (
            f"Date et heure actuelles : {now}.\n"
            "Tu as accès à ces outils :\n"
            "- remember_fact : retiens un fait durable sur l'utilisateur. "
            "update_fact / forget_fact corrigent ou effacent un fait déjà connu "
            "(identifiant exact entre crochets en contexte) — jamais en ajoutant "
            "un doublon via remember_fact.\n"
            "- set_reminder : programme un rappel, avec due_at (calculé à partir de "
            "la date actuelle ci-dessus) si une date/heure est connue, sans due_at "
            "sinon. cancel_reminder annule un rappel en attente listé en contexte.\n"
            "- ask_user : signale qu'une question de clarification est posée.\n"
            "- search_emails / list_upcoming_events : lecture seule Gmail/Calendar.\n"
            "- propose_email / propose_calendar_event : préparent une action sans "
            "l'exécuter — ENVOYER un email ou MODIFIER l'agenda exige TOUJOURS une "
            "confirmation explicite de l'utilisateur avant confirm_action, jamais "
            "d'exécution directe.\n"
            "- confirm_action / cancel_action : à utiliser uniquement sur une action "
            "listée en contexte, avec son identifiant exact, et seulement si "
            "l'utilisateur vient clairement de confirmer ou d'annuler.\n"
            "- mcp_word_* / mcp_excel_* / mcp_pdf_* : création de documents Word, "
            "Excel et PDF (plusieurs appels successifs pour un même document sont "
            "normaux : create_document/create_workbook puis add_heading/add_table/"
            "write_workbook_data... ne t'arrête pas après le premier appel). "
            "Utilise toujours le MÊME nom de fichier à chaque étape. OBLIGATOIRE : "
            "dès la dernière étape de contenu terminée, appelle "
            "save_generated_document avec ce nom AVANT de répondre en texte — "
            "jamais de réponse finale sans cet appel, sans ça l'utilisateur n'a "
            "aucun accès au fichier même s'il existe. Ajoute "
            "save_to_knowledge_base=true seulement si l'utilisateur a "
            "explicitement demandé que ce document rejoigne sa base de "
            "connaissances.\n"
            "Si tu as un doute sur un fait ou une date, pose la question à "
            "l'utilisateur (via ask_user en plus de ta réponse) plutôt que de "
            "deviner."
        ),
    }


@dataclass
class ToolContext:
    db: Any
    websocket: Any
    tenant_id: str
    user_id: str
    conversation_id: str
    google: Any = None
    # Callable(plugin_name, action, payload) -> dict — voir xcore
    # TrustedBase.call_plugin, injecté par le plugin chat pour joindre le
    # pont IPC xauth.get_oauth_token (seul xauth possède les jetons Google).
    call_plugin: Any = None
    mcp: Any = None
    storage: Any = None
    rag: Any = None
    saved_facts: list[str] = field(default_factory=list)
    # Fichiers finalisés via save_generated_document PENDANT ce tour — le
    # routeur (chat_routes.py) les transforme en pièces jointes une fois le
    # message assistant persisté (voir la même logique que /upload).
    generated_files: list[dict] = field(default_factory=list)
    # Heure de référence montrée au modèle (voir _build_tools_hint), posée par
    # run_chat_with_tools/run_chat_stream_with_tools au tout début du tour —
    # sert à corriger le due_at d'un rappel de la dérive d'inférence (voir
    # _set_reminder : sur ce type de machine, un appel Ollama peut prendre
    # plusieurs minutes, largement de quoi rendre "dans 3 minutes" caduc si
    # calculé contre une référence déjà périmée au moment de l'exécution).
    reference_now: datetime | None = None
    # Actions proposées PENDANT ce tour d'appels d'outils (voir
    # _propose_email/_propose_calendar_event) — sert de garde-fou dans
    # _confirm_action : un modèle plus agentique (constaté avec un provider
    # cloud plus capable qu'Ollama) peut enchaîner propose_* puis
    # confirm_action dans le MÊME tour, sans qu'aucune confirmation humaine
    # réelle n'ait eu lieu entre les deux. La consigne dans
    # _build_tools_hint ne suffit pas à l'en empêcher (constaté en
    # pratique) — proposer et confirmer doivent être structurellement
    # séparés par un aller-retour HTTP complet, pas juste demandés poliment.
    proposed_this_turn: set = field(default_factory=set)


async def _notify(ctx: ToolContext, event: str, payload: dict) -> None:
    """Notification websocket best-effort vers le frontend — un échec ici ne
    doit jamais faire échouer l'outil qui l'a déclenché.

    send_to_user, pas broadcast : le canal "user" est partagé par TOUS les
    utilisateurs connectés (broadcast() y diffuse à tout le monde, sans
    filtrage — un vrai bug de cloisonnement constaté en revue, pas juste
    théorique dès que deux utilisateurs sont connectés en même temps)."""
    if ctx.websocket is None:
        return
    try:
        await ctx.websocket.send_to_user(
            ctx.user_id, "user", event, {"conversation_id": ctx.conversation_id, **payload}
        )
    except Exception as exc:
        logger.warning("notification websocket '%s' échouée : %s", event, exc)


async def _remember_fact(ctx: ToolContext, arguments: dict) -> str:
    fact = str(arguments.get("fact", "")).strip()[:500]
    if not fact:
        return "Aucun fait fourni."

    async with ctx.db.session() as session:
        existing = {f["fact"].lower() for f in await load_facts(session, ctx.tenant_id, ctx.user_id)}
        if fact.lower() in existing:
            return "Ce fait était déjà connu."
        session.add(UserFact(tenant_id=ctx.tenant_id, user_id=ctx.user_id, fact=fact))

    ctx.saved_facts.append(fact)
    await _notify(ctx, "memory_fact_saved", {"fact": fact})
    return "Fait enregistré."


async def _update_fact(ctx: ToolContext, arguments: dict) -> str:
    fact_id = str(arguments.get("fact_id", "")).strip()
    fact = str(arguments.get("fact", "")).strip()[:500]
    if not fact_id or not fact:
        return "Identifiant et fait requis."

    async with ctx.db.session() as session:
        row = await session.get(UserFact, fact_id)
        if row is None or row.tenant_id != ctx.tenant_id or row.user_id != ctx.user_id:
            return "Fait introuvable."
        row.fact = fact

    await _notify(ctx, "memory_fact_updated", {"fact_id": fact_id, "fact": fact})
    return "Fait corrigé."


async def _forget_fact(ctx: ToolContext, arguments: dict) -> str:
    fact_id = str(arguments.get("fact_id", "")).strip()
    if not fact_id:
        return "Identifiant requis."

    async with ctx.db.session() as session:
        row = await session.get(UserFact, fact_id)
        if row is None or row.tenant_id != ctx.tenant_id or row.user_id != ctx.user_id:
            return "Fait introuvable."
        await session.delete(row)

    await _notify(ctx, "memory_fact_forgotten", {"fact_id": fact_id})
    return "Fait oublié."


def _parse_due_at(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    # Naïve -> présumée heure locale du serveur (cohérent avec l'heure
    # montrée au modèle dans _build_tools_hint) ; avec ou sans offset, on
    # normalise en UTC pour le stockage et la programmation xworker.
    return dt.astimezone(timezone.utc)


async def _set_reminder(ctx: ToolContext, arguments: dict) -> str:
    content = str(arguments.get("content", "")).strip()[:500]
    if not content:
        return "Aucun contenu de rappel fourni."

    due_at_raw = arguments.get("due_at")
    due_at = _parse_due_at(due_at_raw) if due_at_raw else None

    if due_at is not None and ctx.reference_now is not None:
        # Corrige la dérive entre l'heure montrée au modèle et l'heure réelle
        # d'exécution (l'inférence peut prendre plusieurs minutes ici) — décale
        # due_at du même delta pour préserver le délai RELATIF voulu par
        # l'utilisateur ("dans 3 minutes" doit rester ~3 min après maintenant,
        # pas ~3 min après une référence déjà périmée).
        drift = datetime.now().astimezone(timezone.utc) - ctx.reference_now.astimezone(timezone.utc)
        if drift.total_seconds() > 0:
            due_at = due_at + drift

    status = "pending" if due_at else "suspended"

    reminder = Reminder(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=ctx.conversation_id,
        content=content,
        due_at=due_at,
        status=status,
    )
    async with ctx.db.session() as session:
        session.add(reminder)
        await session.flush()
        reminder_id = reminder.id

    if due_at is None:
        await _notify(ctx, "reminder_scheduled", {"reminder_id": reminder_id, "content": content, "due_at": None})
        return "Rappel enregistré sans date précise — je le ressortirai au bon moment."

    # Import tardif : évite de charger celery/kombu si aucun rappel daté
    # n'est jamais créé pendant la vie du processus.
    from xcore.services.xworker.registry import get_app

    try:
        celery_app = get_app()
        async_result = celery_app.send_task(
            "chat.fire_reminder", args=[reminder_id], eta=due_at, queue="rag"
        )
        async with ctx.db.session() as session:
            row = await session.get(Reminder, reminder_id)
            if row is not None:
                row.task_id = async_result.id
    except Exception as exc:
        logger.warning("programmation xworker du rappel échouée : %s", exc)
        return "Rappel enregistré, mais sa programmation a échoué — je le garde en attente."

    await _notify(
        ctx,
        "reminder_scheduled",
        {"reminder_id": reminder_id, "content": content, "due_at": due_at.isoformat()},
    )
    return f"Rappel programmé pour {due_at.isoformat()}."


async def _cancel_reminder(ctx: ToolContext, arguments: dict) -> str:
    reminder_id = str(arguments.get("reminder_id", "")).strip()
    if not reminder_id:
        return "Identifiant requis."

    async with ctx.db.session() as session:
        row = await session.get(Reminder, reminder_id)
        if row is None or row.tenant_id != ctx.tenant_id or row.user_id != ctx.user_id:
            return "Rappel introuvable."
        row.status = "cancelled"

    await _notify(ctx, "reminder_cancelled", {"reminder_id": reminder_id})
    return "Rappel annulé."


def _sanitize_options(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    # Limites larges (choix courts, peu nombreux) — un dropdown de 40 items
    # ou un roman en guise de bouton ne serait de toute façon pas cliquable.
    return [str(o).strip()[:100] for o in raw[:6] if str(o).strip()]


async def _ask_user(ctx: ToolContext, arguments: dict) -> str:
    question = str(arguments.get("question", "")).strip()[:500]
    if not question:
        return "Aucune question fournie."

    options = _sanitize_options(arguments.get("options"))
    await _notify(ctx, "donna_question", {"question": question, "options": options})
    return "Question signalée au frontend."


async def _get_google_token(ctx: ToolContext) -> str:
    """Résout un access_token Google valide via le pont IPC xauth (seul
    xauth possède les jetons chiffrés — voir app/xauth/src/ipc.py). Lève
    RuntimeError avec un message explicite (non lié, expiré...) plutôt que
    de propager une KeyError/AttributeError opaque."""
    if ctx.call_plugin is None:
        raise RuntimeError("Pont vers le service d'authentification indisponible.")
    result = await ctx.call_plugin(
        "auth", "xauth.get_oauth_token", {"user_id": ctx.user_id, "provider": "google"}
    )
    if result.get("status") != "ok":
        raise RuntimeError(result.get("msg") or "Jeton Google indisponible.")
    return result["access_token"]


async def _search_emails(ctx: ToolContext, arguments: dict) -> str:
    if ctx.google is None:
        return "Service Google indisponible côté serveur."
    try:
        access_token = await _get_google_token(ctx)
    except RuntimeError as exc:
        return f"Impossible d'accéder à Gmail : {exc}"

    query = str(arguments.get("query") or "").strip() or None
    max_results = min(int(arguments.get("max_results") or 5), 10)

    try:
        listing = await ctx.google.list_messages(access_token, query=query, max_results=max_results)
    except Exception as exc:
        logger.warning("search_emails échoué : %s", exc)
        return "Échec de la recherche Gmail."

    message_ids = [m["id"] for m in listing.get("messages", []) or []]
    if not message_ids:
        return "Aucun email trouvé."

    lines = []
    for mid in message_ids:
        try:
            msg = await ctx.google.get_message(access_token, mid, format="metadata")
        except Exception:
            continue
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        lines.append(
            f"- De {headers.get('From', '?')} — Objet : {headers.get('Subject', '(sans objet)')} "
            f"— {msg.get('snippet', '')[:120]}"
        )

    return "\n".join(lines) if lines else "Aucun email trouvé."


async def _list_upcoming_events(ctx: ToolContext, arguments: dict) -> str:
    if ctx.google is None:
        return "Service Google indisponible côté serveur."
    try:
        access_token = await _get_google_token(ctx)
    except RuntimeError as exc:
        return f"Impossible d'accéder à l'agenda : {exc}"

    max_results = min(int(arguments.get("max_results") or 10), 20)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        events = await ctx.google.list_events(access_token, time_min=now_iso, max_results=max_results)
    except Exception as exc:
        logger.warning("list_upcoming_events échoué : %s", exc)
        return "Échec de la lecture de l'agenda."

    if not events:
        return "Aucun événement à venir."

    lines = []
    for ev in events:
        start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date", "?")
        lines.append(f"- [{ev.get('id')}] {ev.get('summary', '(sans titre)')} — {start}")
    return "\n".join(lines)


async def _propose_email(ctx: ToolContext, arguments: dict) -> str:
    to = str(arguments.get("to", "")).strip()
    subject = str(arguments.get("subject", "")).strip()
    body = str(arguments.get("body", "")).strip()
    if not to or not subject:
        return "Destinataire et objet requis."

    payload = {"to": to, "subject": subject, "body": body}
    summary = f"Envoyer un email à {to} — objet : « {subject} »"
    action_id = str(uuid.uuid4())

    async with ctx.db.session() as session:
        session.add(
            PendingAction(
                id=action_id,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                conversation_id=ctx.conversation_id,
                kind="send_email",
                payload=json.dumps(payload, ensure_ascii=False),
                summary=summary,
            )
        )

    ctx.proposed_this_turn.add(action_id)
    await _notify(ctx, "action_proposed", {"action_id": action_id, "kind": "send_email", "summary": summary})
    return f"Email préparé (action {action_id}), en attente de confirmation de l'utilisateur avant envoi."


async def _propose_calendar_event(ctx: ToolContext, arguments: dict) -> str:
    action = str(arguments.get("action", "")).strip().lower()
    if action not in {"create", "update", "delete"}:
        return "action doit être 'create', 'update' ou 'delete'."
    if action in {"update", "delete"} and not arguments.get("event_id"):
        return "event_id requis pour update/delete."

    payload = {
        "action": action,
        "event_id": arguments.get("event_id"),
        "title": arguments.get("title"),
        "start_datetime": arguments.get("start_datetime"),
        "end_datetime": arguments.get("end_datetime"),
        "description": arguments.get("description"),
    }
    summary_map = {
        "create": f"Créer l'événement « {arguments.get('title', '?')} » ({arguments.get('start_datetime', '?')})",
        "update": f"Modifier l'événement {arguments.get('event_id')}",
        "delete": f"Supprimer l'événement {arguments.get('event_id')}",
    }
    action_id = str(uuid.uuid4())

    async with ctx.db.session() as session:
        session.add(
            PendingAction(
                id=action_id,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                conversation_id=ctx.conversation_id,
                kind="calendar_event",
                payload=json.dumps(payload, ensure_ascii=False),
                summary=summary_map[action],
            )
        )

    ctx.proposed_this_turn.add(action_id)
    await _notify(
        ctx, "action_proposed", {"action_id": action_id, "kind": "calendar_event", "summary": summary_map[action]}
    )
    return f"Action agenda préparée ({action_id}), en attente de confirmation de l'utilisateur."


async def _confirm_action(ctx: ToolContext, arguments: dict) -> str:
    action_id = str(arguments.get("action_id", "")).strip()
    if not action_id:
        return "Aucun identifiant d'action fourni."

    if action_id in ctx.proposed_this_turn:
        return (
            "Cette action vient d'être proposée à l'instant, dans ce même échange — "
            "elle ne peut pas être confirmée avant que l'utilisateur ne réponde "
            "explicitement dans un nouveau message. N'appelle pas confirm_action "
            "toi-même ici."
        )

    async with ctx.db.session() as session:
        action = await session.get(PendingAction, action_id)
        if action is None or action.tenant_id != ctx.tenant_id or action.user_id != ctx.user_id:
            return "Action introuvable."
        if action.status != "pending":
            return f"Cette action n'est plus en attente (statut : {action.status})."
        kind, payload_raw = action.kind, action.payload

    payload = json.loads(payload_raw)

    if ctx.google is None:
        return "Service Google indisponible côté serveur."
    try:
        access_token = await _get_google_token(ctx)
    except RuntimeError as exc:
        return f"Confirmation impossible : {exc}"

    try:
        if kind == "send_email":
            await ctx.google.send_email(
                access_token, to=payload["to"], subject=payload["subject"], body_text=payload.get("body")
            )
            result_text = f"Email envoyé à {payload['to']}."
        elif kind == "calendar_event":
            sub_action = payload["action"]
            if sub_action == "create":
                event = {
                    "summary": payload.get("title"),
                    "description": payload.get("description"),
                    "start": {"dateTime": payload.get("start_datetime")},
                    "end": {"dateTime": payload.get("end_datetime")},
                }
                await ctx.google.create_event(access_token, event)
                result_text = "Événement créé."
            elif sub_action == "update":
                event = {
                    k: v
                    for k, v in {
                        "summary": payload.get("title"),
                        "description": payload.get("description"),
                    }.items()
                    if v is not None
                }
                if payload.get("start_datetime"):
                    event["start"] = {"dateTime": payload["start_datetime"]}
                if payload.get("end_datetime"):
                    event["end"] = {"dateTime": payload["end_datetime"]}
                await ctx.google.update_event(access_token, payload["event_id"], event)
                result_text = "Événement modifié."
            else:
                await ctx.google.delete_event(access_token, payload["event_id"])
                result_text = "Événement supprimé."
        else:
            return f"Type d'action inconnu : {kind}"
    except Exception as exc:
        logger.warning("confirm_action (%s) échoué : %s", kind, exc)
        async with ctx.db.session() as session:
            row = await session.get(PendingAction, action_id)
            if row is not None:
                row.status = "failed"
        return f"Échec de l'exécution : {exc}"

    async with ctx.db.session() as session:
        row = await session.get(PendingAction, action_id)
        if row is not None:
            row.status = "executed"

    await _notify(ctx, "action_executed", {"action_id": action_id, "kind": kind, "result": result_text})
    return result_text


async def _cancel_action(ctx: ToolContext, arguments: dict) -> str:
    action_id = str(arguments.get("action_id", "")).strip()
    if not action_id:
        return "Aucun identifiant d'action fourni."

    async with ctx.db.session() as session:
        action = await session.get(PendingAction, action_id)
        if action is None or action.tenant_id != ctx.tenant_id or action.user_id != ctx.user_id:
            return "Action introuvable."
        action.status = "cancelled"

    await _notify(ctx, "action_cancelled", {"action_id": action_id})
    return "Action annulée."


async def confirm_pending_action(ctx: ToolContext, action_id: str) -> str:
    """Même exécution que le tool confirm_action, appelable directement
    depuis une route REST — un bouton « Confirmer » frontend ne doit pas
    dépendre de la capacité d'un petit modèle local à comprendre "oui envoie
    ça" comme un appel d'outil (constaté en pratique : il arrive qu'il se
    contente d'en parler dans sa réponse au lieu de l'invoquer)."""
    return await _confirm_action(ctx, {"action_id": action_id})


async def cancel_pending_action(ctx: ToolContext, action_id: str) -> str:
    return await _cancel_action(ctx, {"action_id": action_id})


async def _save_generated_document(ctx: ToolContext, arguments: dict) -> str:
    filename = str(arguments.get("filename", "")).strip()
    if not filename:
        return "Nom de fichier requis."
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return "Nom de fichier invalide."

    found: Path | None = None
    for sub in ("word", "excel", "pdf"):
        candidate = _MCP_DOCUMENTS_ROOT / sub / ctx.tenant_id / filename
        if candidate.is_file():
            found = candidate
            break

    if found is None:
        return (
            f"Fichier '{filename}' introuvable — vérifie qu'il a bien été créé avec "
            "exactement ce nom avant d'appeler save_generated_document."
        )

    file_size = found.stat().st_size
    if file_size > _MAX_GENERATED_FILE_BYTES:
        found.unlink(missing_ok=True)
        return (
            f"Document trop volumineux ({file_size / 1_048_576:.1f} Mo, max "
            f"{_MAX_GENERATED_FILE_BYTES // 1_048_576} Mo) — supprimé, réessaie avec un "
            "contenu plus court."
        )

    tenant_usage = _tenant_docs_usage_bytes(ctx.tenant_id)
    if tenant_usage > _MAX_TENANT_DOCS_BYTES:
        found.unlink(missing_ok=True)
        return (
            "Quota de documents générés dépassé pour ce compte "
            f"({_MAX_TENANT_DOCS_BYTES // 1_048_576} Mo au total) — supprime d'anciens "
            "documents avant d'en créer de nouveaux."
        )

    if ctx.storage is None:
        return "Document créé mais service de stockage indisponible — impossible de le joindre."

    content = found.read_bytes()
    mime_type = mimetypes.guess_type(found.name)[0] or "application/octet-stream"

    try:
        uploaded = await ctx.storage.save(content, found.name, f"chat/{ctx.tenant_id}")
    except Exception as exc:
        logger.warning("échec du stockage du document généré '%s' : %s", filename, exc)
        return f"Échec de l'enregistrement du document : {exc}"

    ctx.generated_files.append(
        {
            "kind": "document",
            "original_name": found.name,
            "mime_type": mime_type,
            "namespace": uploaded.namespace,
            "stored_name": uploaded.stored_name,
            "file_id": uploaded.file_id,
        }
    )

    result = f"Document '{found.name}' enregistré et joint à la conversation."

    if arguments.get("save_to_knowledge_base") and ctx.rag is not None:
        try:
            extracted = extract_text(found.name, content)
        except ExtractionError as exc:
            logger.warning("extraction du document généré '%s' échouée : %s", filename, exc)
            extracted = None
        if extracted:
            try:
                rag_doc = await ctx.rag.create_document(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    namespace=uploaded.namespace,
                    stored_name=uploaded.stored_name,
                    file_id=uploaded.file_id,
                    original_name=found.name,
                    mime_type=mime_type,
                )
                ctx.rag.enqueue_ingestion(rag_doc["id"], ctx.tenant_id, ctx.user_id, extracted)
                result += " Ajouté à la base de connaissances."
            except Exception as exc:
                logger.warning("ingestion RAG du document généré '%s' échouée : %s", filename, exc)

    await _notify(ctx, "document_generated", {"filename": found.name, "mime_type": mime_type})
    return result


_HANDLERS = {
    "remember_fact": _remember_fact,
    "update_fact": _update_fact,
    "forget_fact": _forget_fact,
    "set_reminder": _set_reminder,
    "cancel_reminder": _cancel_reminder,
    "ask_user": _ask_user,
    "search_emails": _search_emails,
    "list_upcoming_events": _list_upcoming_events,
    "propose_email": _propose_email,
    "propose_calendar_event": _propose_calendar_event,
    "confirm_action": _confirm_action,
    "cancel_action": _cancel_action,
    "save_generated_document": _save_generated_document,
}


async def _execute_tool_call(ctx: ToolContext, name: str, arguments: dict) -> str:
    if name.startswith("mcp_"):
        if ctx.mcp is None:
            return "Outils de documents (word/excel/pdf) indisponibles côté serveur."
        try:
            return await ctx.mcp.call_tool(name, arguments, tenant_id=ctx.tenant_id)
        except Exception as exc:
            logger.warning("appel MCP '%s' échoué : %s", name, exc)
            return "Échec de l'exécution de l'outil."

    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Outil inconnu : {name}"
    try:
        return await handler(ctx, arguments)
    except Exception as exc:
        logger.warning("exécution de l'outil '%s' échouée : %s", name, exc)
        return "Échec de l'exécution de l'outil."


def _effective_tools(ctx: ToolContext) -> list[dict]:
    if ctx.mcp is None:
        return TOOLS_SCHEMA
    return TOOLS_SCHEMA + ctx.mcp.list_tools_schema()


_EMPTY_REPLY_NUDGE = {
    "role": "user",
    "content": (
        "(Ta dernière réponse était vide. Réponds maintenant en texte, sans "
        "appeler d'outil — confirme ce qui vient d'être fait ou pose ta "
        "question.)"
    ),
}


async def _recover_empty_reply(
    ollama, turns: list[dict], images_b64: list[str] | None, force_ollama: bool = False
) -> str:
    """Filet de sécurité : un modèle peut clôturer une série d'appels
    d'outils par une réponse texte vide au lieu de confirmer (constaté en
    pratique avec Groq après une création de document réussie) — un tour de
    plus, sans outils, pour forcer une vraie confirmation. Si même ça ne
    donne rien, un texte générique vaut mieux qu'une réponse vide."""
    turns.append(_EMPTY_REPLY_NUDGE)
    retry = await ollama.chat_with_tools(
        turns, tools=None, images_b64=images_b64, force_ollama=force_ollama
    )
    return retry["content"] or "C'est fait."


async def run_chat_with_tools(
    ollama, ctx: ToolContext, messages: list[dict[str, str]], images_b64: list[str] | None = None
) -> str:
    """Boucle d'appel d'outils (non streaming) : le modèle peut appeler
    remember_fact autant de fois que nécessaire avant de produire sa réponse
    finale, qui est ce que cette fonction retourne."""
    ctx.reference_now = datetime.now().astimezone()
    turns = [_build_tools_hint(ctx.reference_now), *messages]
    # Le router (voir providers/router.py) sait déjà router une image vers
    # un provider vision qui supporte les tools s'il est configuré, et
    # désactive lui-même tools sur un repli Ollama (seul cas où tools+vision
    # est structurellement impossible) — pas besoin de le désactiver ici.
    tools = _effective_tools(ctx)
    # Une fois basculé sur Ollama (cloud indisponible), on y reste pour le
    # reste de CE tour de conversation — pas de shared state sur le router
    # (concurrence entre requêtes), juste une variable locale à cet appel.
    force_ollama = False

    for _ in range(MAX_TOOL_ROUNDS):
        result = await ollama.chat_with_tools(
            turns, tools=tools, images_b64=images_b64, force_ollama=force_ollama
        )
        if result.pop("fell_back_to_ollama", False):
            force_ollama = True
        tool_calls = result["tool_calls"]
        if not tool_calls:
            content = result["content"] or ""
            if content:
                return content
            return await _recover_empty_reply(ollama, turns, images_b64, force_ollama)

        turns.append({"role": "assistant", "content": result["content"] or "", "tool_calls": tool_calls})
        for call in tool_calls:
            tool_result = await _execute_tool_call(ctx, call["name"], call["arguments"])
            turns.append({"role": "tool", "name": call["name"], "content": tool_result})

    result = await ollama.chat_with_tools(
        turns, tools=None, images_b64=images_b64, force_ollama=force_ollama
    )
    if result.pop("fell_back_to_ollama", False):
        force_ollama = True
    content = result["content"] or ""
    return content or await _recover_empty_reply(ollama, turns, images_b64, force_ollama)


async def run_chat_stream_with_tools(
    ollama, ctx: ToolContext, messages: list[dict[str, str]], images_b64: list[str] | None = None
) -> AsyncIterator[dict]:
    """Version streaming : les jetons de la réponse finale sont émis au fur
    et à mesure ({'type': 'delta', ...}) ; un appel d'outil n'est pas
    fractionné et remonte comme événement ({'type': 'tool_call', ...}) une
    fois exécuté."""
    ctx.reference_now = datetime.now().astimezone()
    turns = [_build_tools_hint(ctx.reference_now), *messages]
    # Le router (voir providers/router.py) sait déjà router une image vers
    # un provider vision qui supporte les tools s'il est configuré, et
    # désactive lui-même tools sur un repli Ollama (seul cas où tools+vision
    # est structurellement impossible) — pas besoin de le désactiver ici.
    tools = _effective_tools(ctx)
    # Cf. run_chat_with_tools : une fois basculé sur Ollama dans ce tour, on y
    # reste plutôt que retenter le cloud (et son rate limit) à chaque round.
    force_ollama = False

    for _ in range(MAX_TOOL_ROUNDS):
        content_parts: list[str] = []
        tool_calls: list[dict] = []

        async for event in ollama.chat_stream_with_tools(
            turns, tools=tools, images_b64=images_b64, force_ollama=force_ollama
        ):
            if event["type"] == "delta":
                content_parts.append(event["content"])
                yield event
            elif event["type"] == "tool_calls":
                tool_calls = event["calls"]
            elif event["type"] == "provider_fallback":
                force_ollama = True
                yield event

        if not tool_calls:
            if not content_parts:
                recovered = await _recover_empty_reply(ollama, turns, images_b64, force_ollama)
                yield {"type": "delta", "content": recovered}
            return

        turns.append(
            {"role": "assistant", "content": "".join(content_parts), "tool_calls": tool_calls}
        )
        for call in tool_calls:
            tool_result = await _execute_tool_call(ctx, call["name"], call["arguments"])
            yield {
                "type": "tool_call",
                "name": call["name"],
                "result": tool_result,
                "arguments": call["arguments"],
            }
            turns.append({"role": "tool", "name": call["name"], "content": tool_result})

    final_parts: list[str] = []
    async for event in ollama.chat_stream_with_tools(
        turns, tools=None, images_b64=images_b64, force_ollama=force_ollama
    ):
        if event["type"] == "delta":
            final_parts.append(event["content"])
            yield event
        elif event["type"] == "provider_fallback":
            force_ollama = True
            yield event

    if not final_parts:
        recovered = await _recover_empty_reply(ollama, turns, images_b64, force_ollama)
        yield {"type": "delta", "content": recovered}
