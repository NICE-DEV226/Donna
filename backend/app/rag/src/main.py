from __future__ import annotations

import asyncio

from fastapi import APIRouter
from xcore.sdk import AutoDispatchMixin, TrustedBase, get_logger

from .routes.rag_routes import rag_router
from .status_bridge import run_status_bridge

logger = get_logger("rag.plugin")


class Plugin(AutoDispatchMixin, TrustedBase):
    async def on_load(self) -> None:
        self._storage = self.get_service("ext.storage")
        self._rag = self.get_service("ext.rag")
        self._websocket = self.get_service("ext.websocket")

        self._bridge_task = asyncio.create_task(run_status_bridge(self._websocket))

        self.app = APIRouter()
        self.app.include_router(rag_router(self._storage, self._rag))

        logger.info("rag plugin prêt")

    async def on_unload(self) -> None:
        self._bridge_task.cancel()

    def get_router(self) -> APIRouter | None:
        return self.app
