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

from extensions.worker_env import DONNA_RAG_STATUS_REDIS_URL, RAG_STATUS_CHANNEL

logger = get_logger("rag.status_bridge")

# Backoff de reconnexion : le pont doit survivre à un redémarrage Redis
# (historiquement, la 1re coupure tuait le pont définitivement — statuts
# RAG plus jamais relayés jusqu'au redémarrage de l'API).
_RECONNECT_INITIAL_S = 1.0
_RECONNECT_MAX_S = 60.0


async def run_status_bridge(websocket_service) -> None:
    """Boucle de supervision — à lancer comme asyncio task en arrière-plan
    (on_load). Ne se termine que sur annulation (on_unload) : toute autre
    sortie (coupure Redis, erreur réseau) déclenche une reconnexion avec
    backoff exponentiel plutôt qu'une mort silencieuse."""
    import redis.asyncio as aioredis

    backoff = _RECONNECT_INITIAL_S
    while True:
        client = None
        try:
            client = aioredis.from_url(DONNA_RAG_STATUS_REDIS_URL)
            pubsub = client.pubsub()
            await pubsub.subscribe(RAG_STATUS_CHANNEL)
            backoff = _RECONNECT_INITIAL_S
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
            logger.warning(
                "pont statuts RAG interrompu, reconnexion dans %.0fs : %s", backoff, exc
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_S)
        finally:
            if client is not None:
                with contextlib.suppress(Exception):
                    await pubsub.unsubscribe(RAG_STATUS_CHANNEL)
                    await client.aclose()
