from __future__ import annotations

import asyncio
import logging

from app.services.views import ViewService

logger = logging.getLogger(__name__)


class HousekeepingService:
    def __init__(self, view_service: ViewService, interval_seconds: int = 3600) -> None:
        self.view_service = view_service
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.view_service.cleanup_expired_sessions()
        self._task = asyncio.create_task(self._loop(), name="workspace-housekeeping")

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval_seconds)
                cleaned = await self.view_service.cleanup_expired_sessions()
                if cleaned:
                    logger.info("Cleaned %s expired moderator workspaces", cleaned)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Workspace housekeeping failed")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
