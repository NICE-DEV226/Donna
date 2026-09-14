"""
Tâche Celery de déclenchement des rappels — tourne dans le processus worker,
séparé de l'app FastAPI. Comme pour app/rag/src/tasks.py, pas d'accès direct
aux services xcore ici (ext.pubsub vit dans le processus API) : on publie
directement dans le format que services.extpubsub.provider.redis.RedisAdapter
utilise (canal pub/sub + clé d'inbox), pour bénéficier gratuitement de la
livraison temps réel ET de la remise différée si l'utilisateur est
déconnecté au moment où le rappel se déclenche.

Config : extensions/worker_env.py (jamais de localhost hardcodé — voir
l'historique dans ce module : le worker était aveugle en Docker).

Sémantique de livraison : au-moins-une-fois. Le claim atomique
pending → notifying élimine les doubles déclenchements courants (double
livraison Celery) ; en cas de crash entre publish et mark_done, la reprise
reste sûre : message d'historique dédupliqué par id déterministe (INSERT OR
IGNORE) et notification dédupliquée côté frontend par reminder_id.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Le worker ne boote pas xcore : backend/ n'est pas forcément sur sys.path
# (celery -A ... importé depuis /app ou ailleurs) — bootstrap explicite,
# même pattern que app/rag/src/tasks.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import create_engine, text  # noqa: E402

from extensions import worker_env  # noqa: E402
from xcore.services.xworker import task  # noqa: E402

try:
    # Disponible uniquement dans le processus worker (celery installé).
    from celery.signals import worker_process_shutdown
except ImportError:  # pragma: no cover - import API/test sans celery
    worker_process_shutdown = None


_engine = None


def _get_engine():
    """Moteur SQL partagé du processus (un par process prefork — créé
    paresseusement APRES le fork, jamais hérité). Fini le create_engine +
    dispose() à chaque opération (3× par rappel historiquement)."""
    global _engine
    if _engine is None:
        _engine = create_engine(worker_env.DONNA_DB_URL, pool_pre_ping=True)
    return _engine


if worker_process_shutdown is not None:  # pragma: no cover - signal worker réel

    @worker_process_shutdown.connect
    def _dispose_engine(**kwargs) -> None:
        global _engine
        if _engine is not None:
            _engine.dispose()
            _engine = None


def _reminder_message_id(reminder_id: str) -> str:
    """Id déterministe (uuid5, 36 chars comme la colonne) pour rendre
    l'insertion du message de rappel idempotente (INSERT OR IGNORE)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"donna:reminder:{reminder_id}"))


def _claim_reminder(reminder_id: str, owner_task_id: str | None) -> dict | None:
    """Revendique le rappel pour ce worker. Transition atomique
    pending → notifying (un seul gagnant en cas de double livraison).
    Reprise : si le claim est 'notifying' ET appartient déjà à cette même
    tâche Celery (redelivery après crash, même request.id), on reprend —
    les étapes sont idempotentes (voir module docstring). Sinon None."""
    engine = _get_engine()
    with engine.begin() as conn:
        claimed = conn.execute(
            text(
                "UPDATE chat_reminders SET status = 'notifying', task_id = :task_id "
                "WHERE id = :id AND status = 'pending'"
            ),
            {"id": reminder_id, "task_id": owner_task_id},
        ).rowcount
        if claimed != 1 and owner_task_id:
            claimed = conn.execute(
                text(
                    "UPDATE chat_reminders SET task_id = :task_id "
                    "WHERE id = :id AND status = 'notifying' AND task_id = :task_id"
                ),
                {"id": reminder_id, "task_id": owner_task_id},
            ).rowcount
        if claimed != 1:
            return None
        row = conn.execute(
            text(
                "SELECT id, tenant_id, user_id, conversation_id, content, status "
                "FROM chat_reminders WHERE id = :id"
            ),
            {"id": reminder_id},
        ).fetchone()
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
    with _get_engine().begin() as conn:
        conn.execute(
            text("UPDATE chat_reminders SET status = 'done' WHERE id = :id AND status = 'notifying'"),
            {"id": reminder_id},
        )


def _insert_reminder_message(reminder: dict) -> str | None:
    """Un rappel qui se déclenche doit apparaître comme Donna qui parle
    d'elle-même dans l'historique — pas juste un événement websocket brut
    que l'utilisateur ne voit que s'il est connecté au bon moment. Pas
    d'appel LLM ici (tâche Celery : doit rester rapide et fiable, jamais
    dépendante d'un provider externe) — message gabarité, dans le ton
    direct de Donna."""
    if not reminder["conversation_id"]:
        return None

    message_id = _reminder_message_id(reminder["id"])
    with _get_engine().begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM chat_conversations WHERE id = :id"),
            {"id": reminder["conversation_id"]},
        ).fetchone()
        if exists is None:
            return None
        # OR IGNORE : rejouer ce rappel (reprise après crash) ne duplique
        # jamais le message, grâce à l'id déterministe.
        conn.execute(
            text(
                "INSERT OR IGNORE INTO chat_messages (id, conversation_id, role, content, created_at) "
                "VALUES (:id, :conversation_id, 'assistant', :content, :created_at)"
            ),
            {
                "id": message_id,
                "conversation_id": reminder["conversation_id"],
                "content": f"Petit rappel : {reminder['content']}.",
                "created_at": datetime.now(timezone.utc),
            },
        )
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

    r = redis.Redis.from_url(worker_env.DONNA_REMINDER_REDIS_URL)
    try:
        r.publish(worker_env.REMINDER_PUBSUB_CHANNEL, payload)
        key = f"{worker_env.INBOX_KEY_PREFIX}{reminder['user_id']}"
        r.rpush(key, payload)
        r.ltrim(key, -worker_env.INBOX_MAX_SIZE, -1)
    finally:
        r.close()


@task(name="chat.fire_reminder", queue=worker_env.REMINDERS_QUEUE, bind=True, max_retries=2)
def fire_reminder(self, reminder_id: str) -> dict:
    """Déclenchée à l'heure prévue (ETA posée par set_reminder). Annulation
    « douce » : si le rappel a été annulé entre-temps (ni pending ni claim
    repris par nous), on ne notifie simplement pas — plus robuste qu'une
    révocation Celery, qui ne garantit rien si la tâche a déjà été mise en file."""
    reminder = _claim_reminder(reminder_id, getattr(getattr(self, "request", None), "id", None))
    if reminder is None:
        return {"reminder_id": reminder_id, "status": "skipped"}

    message_id = _insert_reminder_message(reminder)
    _publish_reminder_due(reminder, message_id)
    _mark_done(reminder_id)
    return {"reminder_id": reminder_id, "status": "done", "message_id": message_id}
