from __future__ import annotations

import asyncio
import logging

import httpx

from execution.exit_engine import exit_engine
from models.state import state_manager
from utils.kite_client import kite_client

logger = logging.getLogger(__name__)

_AUTH_RETRY_SECONDS = 30  # how long to wait after a 401 before retrying


class BackupPoller:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_daily_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_daily_loop(self) -> None:
        while not self._stop_event.is_set():
            runtime = await state_manager.get_runtime_settings()
            if runtime.disable_backup_poller:
                await asyncio.sleep(5)
                continue
            # Skip polling entirely if there is no token yet
            if not state_manager.access_token:
                await asyncio.sleep(5)
                continue
            unauthorised = await self.poll_once()
            if unauthorised:
                # Token expired — pause polling until re-auth, check every 30s
                logger.warning(
                    "backup_poller_paused: token invalid, retrying in %ds", _AUTH_RETRY_SECONDS
                )
                await asyncio.sleep(_AUTH_RETRY_SECONDS)
                continue
            runtime = await state_manager.get_runtime_settings()
            await asyncio.sleep(runtime.poll_interval_ms / 1000)

    async def poll_once(self) -> bool:
        """Poll the order book once. Returns True if a 401 was received."""
        try:
            orders = await kite_client.get_order_book()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return True  # signal caller to pause
            logger.exception("backup_poller_fetch_failed")
            return False
        except Exception:  # noqa: BLE001
            logger.exception("backup_poller_fetch_failed")
            return False
        for order in orders:
            event = kite_client.normalize_order_book_event(order)
            await exit_engine.on_order_update_event(event)
        return False


backup_poller = BackupPoller()
