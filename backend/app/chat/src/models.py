from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Nouvelle conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Message(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversations.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Attachment(Base):
    __tablename__ = "chat_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_messages.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # "image" | "document" | "audio"
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(127))
    namespace: Mapped[str] = mapped_column(String(128))
    stored_name: Mapped[str] = mapped_column(String(255))
    file_id: Mapped[str] = mapped_column(String(64))
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class UserFact(Base):
    """Fait persistant retenu sur un utilisateur, indépendant de toute
    conversation — mémoire qui survit d'une conversation à l'autre."""

    __tablename__ = "chat_user_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    fact: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Reminder(Base):
    """Rappel programmé par Donna (outil set_reminder). Avec due_at connu,
    déclenché par une tâche xworker à l'heure dite ; sans due_at, reste
    'suspended' et ressurgit comme contexte dans les prochaines conversations
    (voir chat.memory.load_suspended_reminders) jusqu'à ce qu'une date soit
    précisée ou qu'il soit annulé."""

    __tablename__ = "chat_reminders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversations.id"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="suspended")
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PendingAction(Base):
    """Action proposée par Donna qui touche de vraies données externes
    (envoyer un email, modifier un événement d'agenda) — jamais exécutée
    directement : stockée ici, réinjectée en contexte (voir
    chat.memory.load_pending_actions) jusqu'à ce que l'utilisateur confirme
    ou annule explicitement (outils confirm_action / cancel_action)."""

    __tablename__ = "chat_pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversations.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # "send_email" | "calendar_event"
    payload: Mapped[str] = mapped_column(Text)  # JSON, structure dépend de `kind`
    summary: Mapped[str] = mapped_column(Text)  # description lisible, montrée en contexte
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ConversationSummary(Base):
    """Résumé glissant du début d'une conversation longue — les messages les
    plus récents restent envoyés en clair, ceux couverts ici ne le sont plus
    (voir chat.memory.build_history)."""

    __tablename__ = "chat_conversation_summaries"

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversations.id"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text)
    covered_messages: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
