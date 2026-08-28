from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from xcore.sdk import get_logger

from .models import ConversationSummary, Message, PendingAction, Reminder, UserFact
from .providers.router import ProviderRouter

logger = get_logger("chat.memory")

# Nombre de messages non encore résumés au-delà duquel on déclenche une
# nouvelle passe de résumé, et nombre de messages récents qu'on garde
# toujours en clair (jamais résumés) pour ne pas perdre le fil immédiat.
_SUMMARY_TRIGGER = 20
_SUMMARY_KEEP_RECENT = 10
_SUMMARY_MAX_CHARS = 3000

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
