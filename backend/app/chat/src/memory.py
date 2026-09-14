from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from xcore.sdk import get_logger

from extensions.donna_settings import (
    MAX_HISTORY_CHARS,
    SUMMARY_KEEP_RECENT,
    SUMMARY_MAX_CHARS,
    SUMMARY_TRIGGER,
)

from .models import ConversationSummary, Message, PendingAction, Reminder, UserFact
from .providers.router import ProviderRouter

logger = get_logger("chat.memory")

# Seuils de résumé glissant — réglages ops centralisés, voir
# extensions/donna_settings.py (DONNA_SUMMARY_*).
_SUMMARY_TRIGGER = SUMMARY_TRIGGER
_SUMMARY_KEEP_RECENT = SUMMARY_KEEP_RECENT
_SUMMARY_MAX_CHARS = SUMMARY_MAX_CHARS

_SUMMARY_PROMPT = (
    "Tu résumes une conversation entre un utilisateur et Donna, son assistante. "
    "Condense les échanges ci-dessous en un résumé factuel et concis qui garde "
    "le contexte utile pour la suite. Si un résumé précédent est fourni, "
    "intègre-le sans le répéter tel quel."
)


async def load_facts(session: AsyncSession, tenant_id: str, user_id: str) -> list[dict[str, str]]:
    rows = (
        await session.execute(
            select(UserFact).where(
                UserFact.tenant_id == tenant_id, UserFact.user_id == user_id
            )
        )
    ).scalars().all()
    return [{"id": r.id, "fact": r.fact} for r in rows]


def format_facts_context(facts: list[dict[str, str]]) -> dict[str, str] | None:
    if not facts:
        return None
    bullets = "\n".join(f"- [{f['id']}] {f['fact']}" for f in facts)
    return {
        "role": "system",
        "content": (
            "Ce que tu sais déjà sur cet utilisateur (mémoire persistante). Pour "
            "corriger ou effacer un fait devenu inexact, utilise update_fact ou "
            "forget_fact avec l'identifiant exact entre crochets :\n" + bullets
        ),
    }


async def load_suspended_reminders(
    session: AsyncSession, tenant_id: str, user_id: str
) -> list[dict[str, str]]:
    """Rappels créés sans date précise (outil set_reminder) — pas de tâche
    xworker programmée pour eux, ils ressurgissent ici jusqu'à ce que Donna
    obtienne une date ou que l'utilisateur les annule."""
    rows = (
        await session.execute(
            select(Reminder).where(
                Reminder.tenant_id == tenant_id,
                Reminder.user_id == user_id,
                Reminder.status == "suspended",
            )
        )
    ).scalars().all()
    return [{"id": r.id, "content": r.content} for r in rows]


def format_reminders_context(reminders: list[dict[str, str]]) -> dict[str, str] | None:
    if not reminders:
        return None
    bullets = "\n".join(f"- [{r['id']}] {r['content']}" for r in reminders)
    return {
        "role": "system",
        "content": (
            "Rappels en attente, sans date précise — ressors-les naturellement si "
            "l'occasion s'y prête, demande une date/heure pour les programmer "
            "précisément (set_reminder), ou annule-les avec cancel_reminder si "
            "l'utilisateur dit qu'ils ne sont plus utiles, avec l'identifiant exact "
            "entre crochets :\n" + bullets
        ),
    }


async def load_pending_actions(
    session: AsyncSession, tenant_id: str, user_id: str
) -> list[dict[str, str]]:
    rows = (
        await session.execute(
            select(PendingAction).where(
                PendingAction.tenant_id == tenant_id,
                PendingAction.user_id == user_id,
                PendingAction.status == "pending",
            )
        )
    ).scalars().all()
    return [{"id": r.id, "summary": r.summary} for r in rows]


def format_pending_actions_context(actions: list[dict[str, str]]) -> dict[str, str] | None:
    if not actions:
        return None
    bullets = "\n".join(f"- [{a['id']}] {a['summary']}" for a in actions)
    return {
        "role": "system",
        "content": (
            "Actions en attente de confirmation de l'utilisateur (touchent de vraies "
            "données externes — email, agenda). Appelle confirm_action ou cancel_action "
            "avec l'identifiant exact entre crochets, uniquement si l'utilisateur vient "
            "clairement de confirmer ou d'annuler l'une d'elles :\n" + bullets
        ),
    }


async def build_history(session: AsyncSession, conversation_id: str) -> list[dict[str, str]]:
    """Historique à envoyer au LLM : résumé du passé condensé (s'il existe)
    suivi des messages non encore couverts, en clair."""
    summary_row = await session.get(ConversationSummary, conversation_id)
    covered = summary_row.covered_messages if summary_row else 0

    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
            .offset(covered)
        )
    ).scalars().all()

    history = [{"role": m.role, "content": m.content} for m in rows]
    if summary_row and summary_row.summary:
        history.insert(
            0,
            {
                "role": "system",
                "content": f"Résumé du début de cette conversation :\n{summary_row.summary}",
            },
        )

    # Plafond DUR (DONNA_MAX_HISTORY_CHARS) : borne la croissance du contexte
    # quelle que soit la longueur de la conversation — on sacrifie les plus
    # anciens messages en clair en premier, le résumé (tête) ne saute jamais.
    if history:
        head, tail = (history[:1], history[1:]) if summary_row and summary_row.summary else ([], history)
        total = sum(len(m["content"]) for m in tail)
        while tail and len(tail) > 1 and total > MAX_HISTORY_CHARS:
            dropped = tail.pop(0)
            total -= len(dropped["content"])
        history = head + tail
    return history


async def maybe_summarize(db, ollama: ProviderRouter, conversation_id: str) -> None:
    """Tâche de fond, best-effort : condense les messages les plus anciens
    d'une conversation dès qu'ils dépassent la fenêtre récente gardée en
    clair — évite d'envoyer un historique illimité au LLM."""
    try:
        async with db.session() as session:
            summary_row = await session.get(ConversationSummary, conversation_id)
            covered = summary_row.covered_messages if summary_row else 0
            existing_summary = summary_row.summary if summary_row else None

            total = (
                await session.execute(
                    select(func.count(Message.id)).where(
                        Message.conversation_id == conversation_id
                    )
                )
            ).scalar_one()

            if total - covered < _SUMMARY_TRIGGER:
                return

            to_summarize_count = total - covered - _SUMMARY_KEEP_RECENT
            if to_summarize_count <= 0:
                return

            rows = (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at)
                    .offset(covered)
                    .limit(to_summarize_count)
                )
            ).scalars().all()

        if not rows:
            return

        transcript = "\n".join(f"{m.role}: {m.content}" for m in rows)
        parts = []
        if existing_summary:
            parts.append(f"Résumé précédent :\n{existing_summary}")
        parts.append(f"Nouveaux échanges à intégrer :\n{transcript}")

        new_summary = await ollama.ollama.chat(
            [
                {"role": "system", "content": _SUMMARY_PROMPT},
                {"role": "user", "content": "\n\n".join(parts)},
            ]
        )
        new_summary = new_summary.strip()[:_SUMMARY_MAX_CHARS]
        if not new_summary:
            return

        new_covered = covered + len(rows)
        async with db.session() as session:
            summary_row = await session.get(ConversationSummary, conversation_id)
            if summary_row is None:
                session.add(
                    ConversationSummary(
                        conversation_id=conversation_id,
                        summary=new_summary,
                        covered_messages=new_covered,
                    )
                )
            else:
                summary_row.summary = new_summary
                summary_row.covered_messages = new_covered
    except Exception as exc:
        logger.warning("résumé de conversation échoué (ignoré) : %s", exc)


async def get_context_status(db, conversation_id: str) -> dict:
    """État de la compaction du contexte pour le frontend — nombre total
    de messages, ceux déjà compacts dans un résumé, ceux encore en clair,
    taille du résumé, et pourcentage du budget utilisé (MAX_HISTORY_CHARS).

    Appelé depuis les routes chat après chaque réponse, ET depuis un
    endpoint dédié pour afficher un « badge santé » persistant."""
    recent_c = (
        select(
            Message.content,
            func.row_number()
            .over(partition_by=Message.conversation_id, order_by=Message.created_at)
            .label("rn"),
        )
        .where(Message.conversation_id == conversation_id)
        .subquery()
    )
    async with db.session() as session:
        rows = await session.execute(
            select(
                func.count(Message.id).label("total"),
                func.coalesce(ConversationSummary.covered_messages, 0).label("covered"),
                func.coalesce(func.length(ConversationSummary.summary), 0).label("summary_len"),
            )
            .outerjoin(
                ConversationSummary,
                ConversationSummary.conversation_id == Message.conversation_id,
            )
            .where(Message.conversation_id == conversation_id)
        ).first()
        covered = rows.covered
        recent_chars = (
            await session.scalar(
                select(
                    func.coalesce(func.sum(func.length(recent_c.c.content)), 0)
                ).where(recent_c.c.rn > covered)
            )
        ) or 0
    return _status_from_stats(rows.total, covered, rows.summary_len, recent_chars)


async def get_context_statuses(db, conversation_ids: list[str]) -> dict[str, dict]:
    """Version groupée de get_context_status — UNE requête pour N
    conversations (liste de l'historique) : chaque conversation reçoit son
    état sans N+1 queries."""
    if not conversation_ids:
        return {}

    # Rangs des messages par conversation (les plus anciens = rn 1) pour
    # isoler ceux qui restent "en clair" (rn > covered) après compaction.
    ranked = (
        select(
            Message.conversation_id,
            Message.content,
            func.row_number()
            .over(
                partition_by=Message.conversation_id, order_by=Message.created_at
            )
            .label("rn"),
        )
        .where(Message.conversation_id.in_(conversation_ids))
        .subquery()
    )

    async with db.session() as session:
        counts = (
            await session.execute(
                select(
                    Message.conversation_id,
                    func.count(Message.id).label("total"),
                )
                .where(Message.conversation_id.in_(conversation_ids))
                .group_by(Message.conversation_id)
            )
        ).all()
        summary_rows = (
            await session.execute(
                select(
                    ConversationSummary.conversation_id,
                    ConversationSummary.covered_messages,
                    func.length(ConversationSummary.summary),
                ).where(ConversationSummary.conversation_id.in_(conversation_ids))
            )
        ).all()
        recent_chars_rows = (
            await session.execute(
                select(
                    ranked.c.conversation_id,
                    func.sum(func.length(ranked.c.content)).label("recent_chars"),
                )
                .select_from(ranked)
                .outerjoin(
                    ConversationSummary,
                    ConversationSummary.conversation_id == ranked.c.conversation_id,
                )
                .where(
                    ranked.c.rn > func.coalesce(ConversationSummary.covered_messages, 0)
                )
                .group_by(ranked.c.conversation_id)
            )
        ).all()

    totals = {r[0]: r[1] for r in counts}
    summaries = {r[0]: (r[1], r[2]) for r in summary_rows}
    recent_chars = {r[0]: r[1] for r in recent_chars_rows}
    return {
        cid: _status_from_stats(
            totals.get(cid, 0),
            summaries.get(cid, (0, 0))[0],
            summaries.get(cid, (0, 0))[1],
            recent_chars.get(cid, 0),
        )
        for cid in conversation_ids
    }


def _status_from_stats(
    total: int, covered: int, summary_chars: int, recent_chars: int = 0
) -> dict:
    """Construit le dict de statut commun aux deux fonctions de stats.

    Budget utilisé = taille du résumé (contexte compacté) + taille réelle
    des messages gardés en clair. Le % est plafonné à 100 pour la barre de
    progression du frontend."""
    budget_used = summary_chars + recent_chars
    pct = min(100, int(budget_used * 100 / MAX_HISTORY_CHARS)) if MAX_HISTORY_CHARS else 0
    return {
        "total_messages": total,
        "covered_messages": covered,
        "recent_messages": max(0, total - covered),
        "summary_chars": summary_chars,
        "context_budget_used_pct": pct,
        "compacted": covered > 0,
    }
