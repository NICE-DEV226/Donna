"""
Tâche Celery de déclenchement des rappels — tourne dans le processus worker,
séparé de l'app FastAPI. Comme pour app/rag/src/tasks.py, pas d'accès direct
aux services xcore ici (ext.pubsub vit dans le processus API) : on publie
directement dans le format que services.extpubsub.provider.redis.RedisAdapter
utilise (canal pub/sub + clé d'inbox), pour bénéficier gratuitement de la
livraison temps réel ET de la remise différée si l'utilisateur est
déconnecté au moment où le rappel se déclenche.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from xcore.services.xworker import task

SYNC_DB_URL = "sqlite:///data/db.sqlite3"

# Doit correspondre à PUBSUB_REDIS_URL (.env) — canal d'événements ext.pubsub.
PUBSUB_REDIS_URL = "redis://localhost:6379/0"
PUBSUB_CHANNEL = "reminders"
_INBOX_KEY_PREFIX = "pubsub:inbox:"
_INBOX_MAX_SIZE = 200


def _load_reminder(reminder_id: str) -> dict | None:
    engine = create_engine(SYNC_DB_URL)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, tenant_id, user_id, conversation_id, content, status "
                    "FROM chat_reminders WHERE id = :id"
                ),
                {"id": reminder_id},
            ).fetchone()
    finally:
        engine.dispose()
    if row is None:
        return None
    return {
        "id": row[0],
        "tenant_id": row[1],
        "user_id": row[2],
        "conversation_id": row[3],
        "content": row[4],
        "status": row[5],
    }


def _mark_done(reminder_id: str) -> None:
    engine = create_engine(SYNC_DB_URL)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE chat_reminders SET status = 'done' WHERE id = :id"),
                {"id": reminder_id},
            )
    finally:
        engine.dispose()


def _insert_reminder_message(reminder: dict) -> str | None:
    """Un rappel qui se déclenche doit apparaître comme Donna qui parle
    d'elle-même dans l'historique — pas juste un événement websocket brut
    que l'utilisateur ne voit que s'il est connecté au bon moment. Pas
    d'appel LLM ici (tâche Celery : doit rester rapide et fiable, jamais
    dépendante d'un provider externe) — message gabarité, dans le ton
    direct de Donna."""
    if not reminder["conversation_id"]:
        return None

    message_id = str(uuid.uuid4())
    engine = create_engine(SYNC_DB_URL)
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM chat_conversations WHERE id = :id"),
                {"id": reminder["conversation_id"]},
            ).fetchone()
            if exists is None:
                return None
            conn.execute(
                text(
                    "INSERT INTO chat_messages (id, conversation_id, role, content, created_at) "
                    "VALUES (:id, :conversation_id, 'assistant', :content, :created_at)"
                ),
                {
                    "id": message_id,
                    "conversation_id": reminder["conversation_id"],
                    "content": f"Petit rappel : {reminder['content']}.",
                    "created_at": datetime.now(timezone.utc),
                },
            )
    finally:
        engine.dispose()
    return message_id


def _publish_reminder_due(reminder: dict, message_id: str | None) -> None:
    import redis

    event = {
        "user_id": reminder["user_id"],
        "tenant_id": reminder["tenant_id"],
        "type": "reminder_due",
        "reminder_id": reminder["id"],
        "conversation_id": reminder["conversation_id"],
        "message_id": message_id,
        "content": reminder["content"],
    }
    payload = json.dumps(event, ensure_ascii=False)

    r = redis.Redis.from_url(PUBSUB_REDIS_URL)
    try:
        r.publish(PUBSUB_CHANNEL, payload)
        key = f"{_INBOX_KEY_PREFIX}{reminder['user_id']}"
        r.rpush(key, payload)
        r.ltrim(key, -_INBOX_MAX_SIZE, -1)
    finally:
        r.close()


@task(name="chat.fire_reminder", queue="rag", bind=True, max_retries=2)
def fire_reminder(self, reminder_id: str) -> dict:
    """Déclenchée à l'heure prévue (ETA posée par set_reminder). Annulation
    « douce » : si le rappel a été annulé entre-temps (status='cancelled'),
    on ne notifie simplement pas — plus robuste qu'une révocation Celery, qui
    ne garantit rien si la tâche a déjà été mise en file."""
    reminder = _load_reminder(reminder_id)
    if reminder is None or reminder["status"] == "cancelled":
        return {"reminder_id": reminder_id, "status": "skipped"}

    message_id = _insert_reminder_message(reminder)
    _publish_reminder_due(reminder, message_id)
    _mark_done(reminder_id)
    return {"reminder_id": reminder_id, "status": "done", "message_id": message_id}
