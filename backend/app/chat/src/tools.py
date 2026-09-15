from __future__ import annotations

import json
import mimetypes
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from xcore.sdk import get_logger

from extensions.doc_extract.extract import ExtractionError, extract_text
from extensions.donna_settings import (
    MAX_INPUT_TOKENS_PER_REQUEST,
    MAX_TOOL_ROUNDS,
    SUB_AGENT_MAX_TOOL_ROUNDS,
    TOOL_RESULT_MAX_CHARS,
)
from extensions.worker_env import REMINDERS_QUEUE
from .memory import load_facts
from .models import PendingAction, Reminder, UserFact
from .usage import RequestUsage, cap_text

logger = get_logger("chat.tools")

# Garde-fou anti header-injection SMTP (voir _propose_email + xmailler) :
# destinataire et objet finissent en en-têtes MIME — un "\nBcc: ..." glissé
# par le modèle (ou un prompt injecté) y ajouterait des en-têtes arbitraires.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_MAX_EMAIL_LEN = 254
_MAX_SUBJECT_LEN = 200


def _valid_email(to: str) -> bool:
    return bool(to) and len(to) <= _MAX_EMAIL_LEN and _EMAIL_RE.match(to) is not None


def _valid_header(value: str, max_len: int) -> bool:
    return bool(value) and len(value) <= max_len and "\n" not in value and "\r" not in value
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
                "Enregistre UN fait durable sur l'utilisateur (préférence, "
                "contexte stable) — jamais de contexte ponctuel. Un seul fait "
                "par appel ; ne répète ni ne fusionne les faits déjà connus "
                "(visibles en contexte)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "Le fait nouveau, court et autonome.",
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
                "Corrige un fait existant devenu inexact, via son identifiant "
                "exact entre crochets en contexte."
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
                "Efface un fait devenu inutile, ou sur demande explicite "
                "d'oubli. Identifiant exact entre crochets."
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
                "Programme un rappel. Avec due_at ISO 8601 (déduit de la date "
                "actuelle en contexte, ex: '2026-08-27T09:00:00') il se "
                "déclenche seul à l'heure, même hors conversation ; sans "
                "due_at il reste en attente et tu le ressortiras toi-même."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Contenu du rappel.",
                    },
                    "due_at": {
                        "type": ["string", "null"],
                        "description": "Date/heure ISO 8601 si connue, sinon omis.",
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
                "Annule un rappel en attente listé en contexte (identifiant exact)."
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
                "Signale au frontend que ta réponse pose une question de "
                "clarification importante (EN PLUS de l'écrire normalement — "
                "ne la remplace pas)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "La question, telle quelle.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2 à 5 choix courts affichés en boutons, ou vide.",
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
                "Lecture seule Gmail. Syntaxe Gmail acceptée pour query "
                "(ex: 'from:x@y.com is:unread'), vide = plus récents."
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
            "description": "Lecture seule des prochains événements Google Agenda.",
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
                "Prépare un email SANS l'envoyer — crée une action en attente, "
                "exécutée seulement après confirmation explicite via confirm_action."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "format": "email",
                        "description": "Adresse email du destinataire — une seule adresse simple et valide, sans retour à la ligne.",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Objet de l'email — une seule ligne, 200 caractères maximum.",
                    },
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
                "Prépare une création/modification/suppression d'événement "
                "SANS l'appliquer — confirmation explicite requise via confirm_action."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "'create', 'update' ou 'delete'."},
                    "event_id": {"type": ["string", "null"], "description": "Requis pour update/delete."},
                    "title": {"type": ["string", "null"], "description": "Titre (create/update)."},
                    "start_datetime": {"type": ["string", "null"], "description": "Début ISO 8601."},
                    "end_datetime": {"type": ["string", "null"], "description": "Fin ISO 8601."},
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
                "Exécute une action en attente listée en contexte — UNIQUEMENT "
                "si l'utilisateur vient explicitement de la confirmer. Jamais "
                "dans le même échange que sa proposition."
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
                "Joint à la conversation un document créé via mcp_word_* / "
                "mcp_excel_* / mcp_pdf_* — OBLIGATOIRE avant ta réponse finale, "
                "avec le nom exact utilisé à la création. save_to_knowledge_base "
                "=true seulement sur demande explicite."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Nom exact utilisé à la création (avec extension).",
                    },
                    "save_to_knowledge_base": {
                        "type": ["boolean", "null"],
                        "description": "Vrai = rejoint aussi le RAG, seulement sur demande explicite.",
                    },
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Recherche sur le web via DuckDuckGo. Renvoie des résultats "
                "(titre, lien, extrait) pour trouver des informations en "
                "ligne, vérifier un fait ou compléter une réponse avec des "
                "sources extérieures."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La requête de recherche, précise et en français.",
                    },
                    "max_results": {
                        "type": ["integer", "null"],
                        "description": "Nombre max de résultats (défaut : 10).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_subagent",
            "description": (
                "Délègue un travail documentaire à un sous-agent spécialisé "
                "qui a les bons outils MCP (Word, Excel, PDF). Donne-lui une "
                "consigne précise ; il exécute et renvoie un résumé du résultat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "enum": ["redacteur", "analyste"],
                        "description": (
                            "Sous-agent : 'redacteur' (création/édition "
                            "documents Word, lecture PDF) ou 'analyste' "
                            "(classeurs Excel, extraction PDF)."
                        ),
                    },
                    "task": {
                        "type": "string",
                        "description": (
                            "Consigne précise du travail à accomplir : "
                            "contexte, format souhaité, chemin/nom du "
                            "fichier résultat, etc."
                        ),
                    },
                },
                "required": ["agent", "task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_status",
            "description": (
                "État de l'identité officielle Donna WhatsApp : appairage, "
                "connexion, transport, QR requis ou non."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "description": "Nom de l'appareil (défaut : official).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_chats",
            "description": (
                "Liste les conversations WhatsApp : contact, non-lus, dernier "
                "message, horodatage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Filtre optionnel sur le nom du contact.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre max de conversations (défaut 20).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_context",
            "description": (
                "Fenêtre de messages d'une conversation WhatsApp (chat = "
                "téléphone ou jid WhatsApp)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat": {
                        "type": "string",
                        "description": "Identifiant du chat (numéro ou @s.whatsapp.net).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre de messages (défaut 20).",
                    },
                },
                "required": ["chat"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_search",
            "description": (
                "Recherche textuelle dans les messages ou les contacts WhatsApp."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texte recherché.",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["contacts", "messages"],
                        "description": "messages (défaut) | contacts.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_send",
            "description": (
                "Envoie un message texte. mode=draft (défaut) crée un ticket à "
                "approuver ; mode/auto part directement si autorisé (anti-spam)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Téléphone ou jid du destinataire.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Corps du message (max 1000 caractères).",
                    },
                    "reply_to": {
                        "type": "string",
                        "description": "ID du message auquel répondre (optionnel).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["draft", "auto"],
                        "description": "draft (défaut) | auto",
                    },
                    "question": {
                        "type": "boolean",
                        "description": "True si le message attend une réponse.",
                    },
                },
                "required": ["recipient", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_media",
            "description": (
                "Envoie une pièce jointe (image, document...) depuis les "
                "racines autorisées."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Téléphone ou jid du destinataire.",
                    },
                    "file_ref": {
                        "type": "string",
                        "description": "Chemin du fichier dans les racines autorisées.",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Légende (optionnelle).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["draft", "auto"],
                        "description": "draft (défaut) | auto",
                    },
                },
                "required": ["recipient", "file_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_voice",
            "description": (
                "Envoie une note vocale (.opus/.ogg, Opus mono ~48 kHz) depuis "
                "les racines autorisées."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Téléphone ou jid du destinataire.",
                    },
                    "file_ref": {
                        "type": "string",
                        "description": "Chemin du fichier .opus/.ogg.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["draft", "auto"],
                        "description": "draft (défaut) | auto",
                    },
                },
                "required": ["recipient", "file_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_react",
            "description": (
                "Réagit à un message (émoticône de la liste autorisée : "
                "👌 ✅ 👍 ❤️ 😂 🤔 😮 🙏 🎉 📎)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat": {
                        "type": "string",
                        "description": "Identifiant du chat.",
                    },
                    "message": {
                        "type": "string",
                        "description": "ID du message auquel réagir.",
                    },
                    "emoji": {
                        "type": "string",
                        "enum": ["👌", "✅", "👍", "❤️", "😂", "🤔", "😮", "🙏", "🎉", "📎"],
                        "description": "L'émoticône de réaction.",
                    },
                },
                "required": ["chat", "message", "emoji"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_read",
            "description": (
                "Marque une conversation WhatsApp comme lue (ack)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat": {
                        "type": "string",
                        "description": "Identifiant du chat.",
                    },
                },
                "required": ["chat"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wa_admin_approve",
            "description": (
                "Approuve ou rejette un ticket d'envoi créé par wa_send / "
                "wa_media / wa_voice (mode draft)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "ID du ticket (tk_...).",
                    },
                    "approve": {
                        "type": "boolean",
                        "description": "True = approuver, false = rejeter.",
                    },
                },
                "required": ["ticket", "approve"],
            },
        },
    },
]


def _build_tools_hint() -> dict:
    """Consigne d'outils STATIQUE — volontairement sans date/heure : ce
    message ouvre chaque tour d'appels d'outils et doit rester IDENTIQUE
    d'un appel à l'autre pour préserver le prompt caching côté provider
    (préfixe stable). La date/heure vit dans _build_now_hint, placée en FIN
    de contexte (voir run_*), où elle n'invalide que la queue du cache."""
    return {
        "role": "system",
        "content": (
            "Tu as accès à ces outils :\n"
            "- remember_fact / update_fact / forget_fact : mémoire durable "
            "(faits stables uniquement). update/forget exigent l'identifiant "
            "exact entre crochets — jamais de doublon via remember_fact.\n"
            "- set_reminder / cancel_reminder : due_at ISO calculé depuis la "
            "date/heure donnée en fin de contexte ; sans date connue, omets "
            "due_at (reste en attente).\n"
            "- ask_user : signale une question de clarification (en plus de "
            "l'écrire normalement).\n"
            "- search_emails / list_upcoming_events : lecture seule.\n"
            "- propose_email / propose_calendar_event : préparent SANS "
            "exécuter. confirm_action / cancel_action : seulement sur une "
            "action listée en contexte, et confirm_action UNIQUEMENT après "
            "une confirmation explicite dans un message séparé — jamais "
            "proposer et confirmer dans le même tour.\n"
            "- delegate_to_subagent : confie UN travail documentaire à un "
            "sous-agent spécialisé et attend son résumé. Le sous-agent "
            "revient une seule fois (résultat final) ; s'il a produit un "
            "document, tu appelles ensuite save_generated_document avec le "
            "nom exact utilisé.\n"
            "- save_generated_document : joint à la conversation un document "
            "créé par un sous-agent (nom exact de la création) — OBLIGATOIRE "
            "avant la réponse finale si un document a été produit.\n"
            "Doute sur un fait/une date : question (ask_user) plutôt que deviner."
        ),
    }


def _build_now_hint(reference_now: datetime) -> dict:
    """Date/heure de référence DYNAMIQUE — placée juste avant le message
    utilisateur (fin de contexte) pour ne pas casser le cache du préfixe
    statique. Sert au calcul des due_at (set_reminder) et corrige la dérive
    d'inférence via ctx.reference_now (voir _set_reminder)."""
    return {
        "role": "system",
        "content": (
            f"Date et heure actuelles : {reference_now.isoformat(timespec='seconds')}."
        ),
    }


def _build_turns(messages: list[dict[str, str]], reference_now: datetime) -> list[dict]:
    """Assemble le contexte dans l'ordre optimal coût/qualité :
    [consigne statique (cachable)] + historique/contexte + [date dynamique] +
    [message utilisateur]. Le dernier élément est toujours le message
    utilisateur (les providers vision y attachent les images)."""
    static_hint = _build_tools_hint()
    now_hint = _build_now_hint(reference_now)
    if not messages:
        return [static_hint, now_hint]
    return [static_hint, *messages[:-1], now_hint, messages[-1]]


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
    # Ledger tokens de la requête (une instance = un message utilisateur) —
    # rempli à chaque appel LLM, loggé + renvoyé au client en fin de requête.
    usage: RequestUsage = field(default_factory=RequestUsage)
    # ProviderRouter (ou OllamaClient) pour exécuter les boucles LLM —
    # utilisé par le handler delegation (sous-agents) qui a besoin d'appeler
    # le LLM lui-même, depuis _delegate_to_subagent.
    ollama: Any = None
    # True une fois qu'un repli Ollama a eu lieu pendant CE tour —
    # partagé entre la boucle principale et les sous-agents pour ne pas
    # retenter le cloud après un premier échec.
    force_ollama: bool = False
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
        # Queue dédiée `reminders` (pas `rag`) : un rappel temps-sensible ne
        # doit jamais attendre derrière une ingestion lourde — voir
        # extensions/worker_env.py et docker-compose.yml (worker dédié).
        async_result = celery_app.send_task(
            "chat.fire_reminder", args=[reminder_id], eta=due_at, queue=REMINDERS_QUEUE
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
    # Validation stricte AVANT stockage : le destinataire/l'objet finissent
    # en en-têtes MIME à l'envoi (xmailler) — refuser tôt plutôt que
    # d'exécuter un envoi piégé à la confirmation.
    if not _valid_email(to):
        return f"Adresse destinataire invalide : {to[:80]!r} — fournis une adresse email simple et valide."
    if not _valid_header(subject, _MAX_SUBJECT_LEN):
        return "Objet invalide — une seule ligne de 200 caractères maximum, sans retour à la ligne."

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


async def _web_search(ctx: ToolContext, arguments: dict) -> str:
    """Recherche web DuckDuckGo via le pont MCP (`duckduckgo` -> tool
    natif `search`). Le pont est la seule source : pas de clé API à gérer
    ici, et le serveur (uvx duckduckgo-mcp-server) est déclaré en config
    comme les autres (pdf/excel/word)."""
    if ctx.mcp is None:
        return "Recherche web indisponible (ext.mcp_bridge non connecté)."
    try:
        content = await ctx.mcp.call_tool("duckduckgo", "search", arguments)
        return "\n".join(
            part.text
            for part in content
            if getattr(part, "text", None)
        ) or "Aucun résultat."
    except Exception as exc:
        logger.warning("web_search échoué : %s", exc)
        return "La recherche web a échoué, réessaie plus tard."


def _make_wa_handler(native_name: str):
    """Fabrique le handler `wa_*` → pont stdio `donna_whatsapp`.

    Le pont est la seule source : le serveur WhatsApp réel (binaire Go
    `donata`, transport memory en dev / whatsmeow en prod) est déclaré en
    **integration.yaml** dans `extensions.mcp_bridge.config.servers`
    (`donna_whatsapp:`), comme duckduckgo/pdf/excel/word. Aucune clé API à
    gérer ici — `ctx.mcp.call_tool` route vers le serveur stdio par son ID
    (`donna_whatsapp`) et le nom natif (`wa_chats`, `wa_send`, ...).

    Défauts : mode=draft (une approbation humaine est requise avant envoi,
    anti-spam anti-abus) ; wa_send/wa_media/wa_voice/wa_react partent en
    **?? d'abord** si le contexte est en draft ; passez mode=auto en config
    uniquement pour des campagnes explicites à fort pré-approbation.
    """

    async def _handler(ctx: ToolContext, arguments: dict) -> str:
        if ctx.mcp is None:
            return (
                f"{native_name} indisponible (ext.mcp_bridge non connecté)."
            )
        try:
            content = await ctx.mcp.call_tool(
                "donna_whatsapp", native_name, arguments
            )
            return "\n".join(
                part.text
                for part in content
                if getattr(part, "text", None)
            ) or "Aucun résultat."
        except Exception as exc:
            logger.warning("%s échoué : %s", native_name, exc)
            return (
                f"{native_name} a échoué, réessaie plus tard."
            )

    return _handler


_wa_status = _make_wa_handler("wa_status")
_wa_chats = _make_wa_handler("wa_chats")
_wa_context = _make_wa_handler("wa_context")
_wa_search = _make_wa_handler("wa_search")
_wa_send = _make_wa_handler("wa_send")
_wa_media = _make_wa_handler("wa_media")
_wa_voice = _make_wa_handler("wa_voice")
_wa_react = _make_wa_handler("wa_react")
_wa_read = _make_wa_handler("wa_read")
_wa_admin_approve = _make_wa_handler("wa_admin_approve")


async def _delegate_to_subagent(ctx: ToolContext, arguments: dict) -> str:
    """Délègue une tâche documentaire à un sous-agent : sa propre boucle
    LLM, SCOPÉE à ses propres outils MCP (catalog.mcp_tools_for_agent),
    jamais ceux de Donna — le point clé du design « donna orchestre ».

    Le sous-agent tourne sur un contexte FRAIS (sa spécialité + la
    consigne), exécute ses appels d'outils, et renvoie ici seulement son
    résumé final — pas les étapes intermédiaires, qui ne doivent pas
    polluer le contexte de Donna."""

    agent = str(arguments.get("agent", "")).strip()
    task = str(arguments.get("task", "")).strip()
    if not agent or not task:
        return "Champs 'agent' et 'task' requis."
    if ctx.mcp is None:
        return "Sous-agents (documents) indisponibles côté serveur."
    if ctx.ollama is None:
        return "Moteur de sous-agents indisponible côté serveur."

    tools = ctx.mcp.list_tools_schema_for_agent(agent)

    # Serveur filesystem scopé, ouvert sur la racine du dossier courant
    # du tenant : le sous-agent peut lire/écrire les fichiers de mission
    # (pièces jointes, documents produits) en plus de ses serveurs métier
    # (pdf/word/excel). open_scoped_server est idempotent par
    # (category, key) : rejoué à chaque délégation il est réutilisé tant
    # qu'il tourne, et fermé par close_all_scoped_servers à l'arrêt du
    # service (voir la limite documentée dans extensions/mcp_bridge).
    scoped_key = ctx.tenant_id
    scoped_root = _MCP_DOCUMENTS_ROOT / ctx.tenant_id
    try:
        scoped_root.mkdir(parents=True, exist_ok=True)
        await ctx.mcp.open_scoped_server("filesystem", scoped_key, str(scoped_root))
        tools += ctx.mcp.list_tools_schema_for_scoped(agent, "filesystem", scoped_key)
    except Exception as exc:
        logger.warning("filesystem scopé indisponible pour '%s' : %s", agent, exc)

    if not tools:
        subs = [s["name"] for s in ctx.mcp.list_sub_agents("donna")]
        return (
            f"Sous-agent '{agent}' inconnu ou sans outils "
            f"(disponibles : {', '.join(subs) or 'aucun'})."
        )

    description = ""
    for sub in ctx.mcp.list_sub_agents("donna"):
        if sub["name"] == agent:
            description = sub["description"]
            break

    sub_turns = [
        {
            "role": "system",
            "content": (
                f"Tu es le sous-agent '{agent}' de Donna, l'assistant principal. "
                f"Ta spécialité : {description or 'travail documentaire'}. "
                "Accomplis la tâche confiée ci-dessous avec tes outils. "
                "Dès que c'est fait, réponds par un résumé BREF et factuel "
                "de ton travail : fichier créé/édité (nom exact), données "
                "extraits, résultat clé. Pas d'étapes intermédiaires."
            ),
        },
        {"role": "user", "content": task},
    ]
    force_ollama = ctx.force_ollama

    for _ in range(SUB_AGENT_MAX_TOOL_ROUNDS):
        if ctx.usage.input_tokens >= MAX_INPUT_TOKENS_PER_REQUEST:
            return "Budget tokens du sous-agent dépassé avant la fin du travail."
        ctx.usage.add_request(sub_turns, tools)
        result = await ctx.ollama.chat_with_tools(
            sub_turns, tools=tools, force_ollama=force_ollama
        )
        ctx.usage.add_response(result.get("content"))
        if result.pop("fell_back_to_ollama", False):
            force_ollama = True
            ctx.force_ollama = True
        tool_calls = result["tool_calls"]
        if not tool_calls:
            return result["content"] or "Le sous-agent n'a rien renvoyé."

        ctx.usage.tool_rounds += 1
        sub_turns.append(
            {"role": "assistant", "content": result["content"] or "", "tool_calls": tool_calls}
        )
        for call in tool_calls:
            tool_result = await _execute_tool_call(ctx, call["name"], call["arguments"])
            sub_turns.append({"role": "tool", "name": call["name"], "content": tool_result})

    return "Le sous-agent a atteint sa limite de rounds sans réponse finale."


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
    "web_search": _web_search,
    "delegate_to_subagent": _delegate_to_subagent,
    "wa_status": _wa_status,
    "wa_chats": _wa_chats,
    "wa_context": _wa_context,
    "wa_search": _wa_search,
    "wa_send": _wa_send,
    "wa_media": _wa_media,
    "wa_voice": _wa_voice,
    "wa_react": _wa_react,
    "wa_read": _wa_read,
    "wa_admin_approve": _wa_admin_approve,
}


async def _execute_tool_call(ctx: ToolContext, name: str, arguments: dict) -> str:
    """Point de passage UNIQUE de tous les résultats d'outils réinjectés au
    modèle — plafonne à DONNA_TOOL_RESULT_MAX_CHARS : sans ça, un outil
    verbeux (ex: lecture de document MCP, plusieurs dizaines de milliers de
    caractères) est renvoyé EN ENTIER à chaque round, le poste de fuite n°1
    du budget tokens (constaté : le contexte gonfle à chaque tour)."""
    result = await _execute_tool_call_raw(ctx, name, arguments)
    if len(result) > TOOL_RESULT_MAX_CHARS:
        logger.info(
            "résultat d'outil tronqué", tool=name, chars=len(result), max_chars=TOOL_RESULT_MAX_CHARS
        )
    return cap_text(result, TOOL_RESULT_MAX_CHARS)


async def _execute_tool_call_raw(ctx: ToolContext, name: str, arguments: dict) -> str:
    if name.startswith("mcp_"):
        if ctx.mcp is None:
            return "Outils de documents (word/excel/pdf) indisponibles côté serveur."
        try:
            return await ctx.mcp.call_tool_named(name, arguments, tenant_id=ctx.tenant_id)
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
    """Les tools exposés de tous les concepts LLM/chat. Il n'y a plus de
    tools MCP dans le contexte de Donna : donna ne voit QUE ses tools
    natifs (+ web_search et delegate_to_subagent). Les tools documentaires
    (mcp_*) vivent dans les sous-agents et ne remontent que via une
    délégation. `ctx.mcp` n'est vérifié que pour déclarer web_search et
    delegate_to_subagent disponibles — sans lui, ces tools existent en
    code mais rendent une erreur explicite."""
    if ctx.mcp is None:
        return [
            t
            for t in TOOLS_SCHEMA
            if t["function"]["name"] not in ("delegate_to_subagent", "web_search")
        ]
    return TOOLS_SCHEMA


_EMPTY_REPLY_NUDGE = {
    "role": "user",
    "content": (
        "(Ta dernière réponse était vide. Réponds maintenant en texte, sans "
        "appeler d'outil — confirme ce qui vient d'être fait ou pose ta "
        "question.)"
    ),
}


async def _recover_empty_reply(
    ollama,
    turns: list[dict],
    images_b64: list[str] | None,
    force_ollama: bool = False,
    usage: RequestUsage | None = None,
) -> str:
    """Filet de sécurité : un modèle peut clôturer une série d'appels
    d'outils par une réponse texte vide au lieu de confirmer (constaté en
    pratique avec Groq après une création de document réussie) — un tour de
    plus, sans outils, pour forcer une vraie confirmation. Si même ça ne
    donne rien, un texte générique vaut mieux qu'une réponse vide."""
    turns.append(_EMPTY_REPLY_NUDGE)
    if usage is not None:
        usage.add_request(turns, None)
    retry = await ollama.chat_with_tools(
        turns, tools=None, images_b64=images_b64, force_ollama=force_ollama
    )
    if usage is not None:
        usage.add_response(retry.get("content"))
    return retry["content"] or "C'est fait."


async def run_chat_with_tools(
    ollama, ctx: ToolContext, messages: list[dict[str, str]], images_b64: list[str] | None = None
) -> str:
    """Boucle d'appel d'outils (non streaming) : le modèle peut appeler
    remember_fact autant de fois que nécessaire avant de produire sa réponse
    finale, qui est ce que cette fonction retourne."""
    ctx.reference_now = datetime.now().astimezone()
    # Ordre cache-friendly : consigne statique d'abord, date dynamique en
    # fin (voir _build_turns) — même contenu utile, bien meilleur taux de
    # cache préfixe côté provider.
    turns = _build_turns(messages, ctx.reference_now)
    # Le router (voir providers/router.py) sait déjà router une image vers
    # un provider vision qui supporte les tools s'il est configuré, et
    # désactive lui-même tools sur un repli Ollama (seul cas où tools+vision
    # est structurellement impossible) — pas besoin de le désactiver ici.
    tools = _effective_tools(ctx)
    # Une fois basculé sur Ollama (cloud indisponible), on y reste pour le
    # reste de CE tour de conversation — pas de shared state sur le router
    # (concurrence entre requêtes), juste une variable locale à cet appel.
    # Synchronisé sur ctx pour que les délégations sous-agent voient le même
    # état de fallback sans repartir sur le cloud (voir _delegate_to_subagent).
    ctx.force_ollama = False

    for _ in range(MAX_TOOL_ROUNDS):
        # Budget tokens cumulé : au-delà, on force la réponse finale SANS
        # outils plutôt que de continuer à gonfler le contexte (chaque round
        # renvoie TOUT : historique + résultats d'outils accumulés). Le 1er
        # round passe toujours (compteur à 0 au départ).
        if ctx.usage.input_tokens >= MAX_INPUT_TOKENS_PER_REQUEST:
            ctx.usage.budget_hit = True
            logger.warning(
                "budget tokens dépassé, réponse finale forcée",
                **ctx.usage.summary(),
            )
            break
        ctx.usage.add_request(turns, tools)
        result = await ollama.chat_with_tools(
            turns, tools=tools, images_b64=images_b64, force_ollama=ctx.force_ollama
        )
        ctx.usage.add_response(result.get("content"))
        if result.pop("fell_back_to_ollama", False):
            ctx.force_ollama = True
            ctx.usage.provider_fallbacks += 1
        tool_calls = result["tool_calls"]
        if not tool_calls:
            content = result["content"] or ""
            if content:
                return content
            return await _recover_empty_reply(ollama, turns, images_b64, ctx.force_ollama, ctx.usage)

        ctx.usage.tool_rounds += 1
        turns.append({"role": "assistant", "content": result["content"] or "", "tool_calls": tool_calls})
        for call in tool_calls:
            tool_result = await _execute_tool_call(ctx, call["name"], call["arguments"])
            turns.append({"role": "tool", "name": call["name"], "content": tool_result})

    ctx.usage.add_request(turns, None)
    result = await ollama.chat_with_tools(
        turns, tools=None, images_b64=images_b64, force_ollama=ctx.force_ollama
    )
    ctx.usage.add_response(result.get("content"))
    if result.pop("fell_back_to_ollama", False):
        ctx.force_ollama = True
        ctx.usage.provider_fallbacks += 1
    content = result["content"] or ""
    return content or await _recover_empty_reply(ollama, turns, images_b64, ctx.force_ollama, ctx.usage)


async def run_chat_stream_with_tools(
    ollama, ctx: ToolContext, messages: list[dict[str, str]], images_b64: list[str] | None = None
) -> AsyncIterator[dict]:
    """Version streaming : les jetons de la réponse finale sont émis au fur
    et à mesure ({'type': 'delta', ...}) ; un appel d'outil n'est pas
    fractionné et remonte comme événement ({'type': 'tool_call', ...}) une
    fois exécuté."""
    ctx.reference_now = datetime.now().astimezone()
    # Ordre cache-friendly : consigne statique d'abord, date dynamique en
    # fin (voir _build_turns) — même contenu utile, bien meilleur taux de
    # cache préfixe côté provider.
    turns = _build_turns(messages, ctx.reference_now)
    # Le router (voir providers/router.py) sait déjà router une image vers
    # un provider vision qui supporte les tools s'il est configuré, et
    # désactive lui-même tools sur un repli Ollama (seul cas où tools+vision
    # est structurellement impossible) — pas besoin de le désactiver ici.
    tools = _effective_tools(ctx)
    # Cf. run_chat_with_tools : une fois basculé sur Ollama dans ce tour, on y
    # reste plutôt que retenter le cloud (et son rate limit) à chaque round.
    ctx.force_ollama = False

    for _ in range(MAX_TOOL_ROUNDS):
        # Même budget que la version non-streaming (voir run_chat_with_tools).
        if ctx.usage.input_tokens >= MAX_INPUT_TOKENS_PER_REQUEST:
            ctx.usage.budget_hit = True
            logger.warning(
                "budget tokens dépassé, réponse finale forcée",
                **ctx.usage.summary(),
            )
            break
        content_parts: list[str] = []
        tool_calls: list[dict] = []

        ctx.usage.add_request(turns, tools)
        async for event in ollama.chat_stream_with_tools(
            turns, tools=tools, images_b64=images_b64, force_ollama=ctx.force_ollama
        ):
            if event["type"] == "delta":
                content_parts.append(event["content"])
                yield event
            elif event["type"] == "tool_calls":
                tool_calls = event["calls"]
            elif event["type"] == "provider_fallback":
                ctx.force_ollama = True
                ctx.usage.provider_fallbacks += 1
                yield event
        ctx.usage.add_response("".join(content_parts))

        if not tool_calls:
            if not content_parts:
                recovered = await _recover_empty_reply(ollama, turns, images_b64, ctx.force_ollama, ctx.usage)
                yield {"type": "delta", "content": recovered}
            return

        ctx.usage.tool_rounds += 1
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
    ctx.usage.add_request(turns, None)
    async for event in ollama.chat_stream_with_tools(
        turns, tools=None, images_b64=images_b64, force_ollama=ctx.force_ollama
    ):
        if event["type"] == "delta":
            final_parts.append(event["content"])
            yield event
        elif event["type"] == "provider_fallback":
            ctx.force_ollama = True
            ctx.usage.provider_fallbacks += 1
            yield event
    ctx.usage.add_response("".join(final_parts))

    if not final_parts:
        recovered = await _recover_empty_reply(ollama, turns, images_b64, ctx.force_ollama, ctx.usage)
        yield {"type": "delta", "content": recovered}
