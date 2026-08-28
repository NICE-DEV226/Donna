"""
Pont Redis → websocket : le worker Celery (processus séparé) publie les
mises à jour de statut d'ingestion sur Redis (voir tasks.py::_publish_status).
Ce module tourne côté processus FastAPI, écoute ce canal, et relaie sur le
canal "user" via ext.websocket.send_to_user() — filtré par le user_id porté
par le payload, PAS broadcast() : le canal "user" est partagé par tous les
utilisateurs connectés, broadcast() y aurait diffusé le statut d'indexation
de chacun à tout le monde (vrai bug de cloisonnement, pas théorique).
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from xcore.sdk import get_logger

logger = get_logger("rag.status_bridge")

REDIS_STATUS_URL = "redis://localhost:6379/2"
STATUS_CHANNEL = "rag:status"


async def run_status_bridge(websocket_service) -> None:
    """Boucle infinie — à lancer comme asyncio task en arrière-plan (on_load)."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(REDIS_STATUS_URL)
    pubsub = client.pubsub()
    await pubsub.subscribe(STATUS_CHANNEL)

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            with contextlib.suppress(Exception):
                payload = json.loads(message["data"])
                user_id = payload.get("user_id")
                if not user_id:
                    continue
                await websocket_service.send_to_user(user_id, "user", "rag_ingestion_status", payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("status bridge interrompu : %s", exc)
    finally:
        await pubsub.unsubscribe(STATUS_CHANNEL)
        await client.aclose()
