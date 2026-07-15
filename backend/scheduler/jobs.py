from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import IST
from models.state import state_manager
from scanner.gap_scanner import gap_scanner
from utils.kite_client import kite_client

logger = logging.getLogger(__name__)


def _parse_time(t: str) -> time:
    """Parse HH:MM:SS string into a time object."""
    try:
        parts = t.strip().split(":")
        return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    except Exception:
        return time(9, 15, 1)


class SchedulerService:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=IST)
        self._started = False
        self._countdown_task: asyncio.Task | None = None
        self._fire_watcher_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._started:
            return
        self.scheduler.add_job(
            state_manager.reset_for_day,
            CronTrigger(hour=8, minute=0, second=0, timezone=IST),
            id="daily_state_reset",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._fetch_prev_close,
            CronTrigger(hour=8, minute=30, second=0, timezone=IST),
            id="auto_fetch_prev_close",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_scan,
            CronTrigger(hour=9, minute=8, second=0, timezone=IST),
            id="auto_gap_scan",
            replace_existing=True,
        )
        self.scheduler.start()
        self._started = True
        # Dynamic fire watcher — reads runtime settings every second so UI time changes
        # take effect immediately.
        self._fire_watcher_task = asyncio.create_task(self._fire_watcher_loop())

    async def stop(self) -> None:
        if not self._started:
            return
        for task in (self._countdown_task, self._fire_watcher_task):
            if task and not task.done():
                task.cancel()
        self.scheduler.shutdown(wait=False)
        self._started = False

    async def _fetch_prev_close(self) -> None:
        if not state_manager.access_token:
            logger.warning("auto_fetch_prev_close skipped: not authenticated")
            return
        updated = await kite_client.fetch_and_store_prev_close()
        logger.info("auto_fetch_prev_close: updated %d instruments", updated)

    async def _run_scan(self) -> None:
        await gap_scanner.run()

    async def _fire_watcher_loop(self) -> None:
        """
        Polls every second. When scheduled_fire_enabled is True and the clock
        reaches scheduled_fire_time, drain the queue and fire all pending orders.
        Tracks the date it last fired so it fires exactly once per calendar day.
        UI changes to scheduled_fire_time take effect on the very next second tick.
        """
        from execution.buy_executor import buy_executor  # noqa: PLC0415

        fired_on: str | None = None  # "YYYY-MM-DD" — prevent double-firing same day
        try:
            while True:
                await asyncio.sleep(1)
                now = datetime.now(IST)
                today = now.strftime("%Y-%m-%d")
                runtime = await state_manager.get_runtime_settings()

                if not runtime.scheduled_fire_enabled:
                    fired_on = None  # reset so it fires again if re-enabled later
                    continue

                fire_t = _parse_time(runtime.scheduled_fire_time)

                if fired_on != today and now.time() >= fire_t:
                    fired_on = today
                    queued = await state_manager.get_pending_orders_count()
                    logger.info(
                        "🚀  %s IST — firing %d queued order(s)…",
                        runtime.scheduled_fire_time,
                        queued,
                    )
                    fired = await buy_executor.fire_pending_orders()
                    logger.info("fire_watcher: %d item(s) submitted to Kite", fired)

        except asyncio.CancelledError:
            pass

    async def _start_countdown(self) -> None:
        """Spawns a background task that logs a countdown to the fire time every 30 s."""
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()
        self._countdown_task = asyncio.create_task(self._countdown_loop())

    async def _countdown_loop(self) -> None:
        """Logs remaining seconds to the scheduled fire time every 30 s."""
        try:
            while True:
                runtime = await state_manager.get_runtime_settings()
                fire_t = _parse_time(runtime.scheduled_fire_time)
                now = datetime.now(IST)
                if now.time() >= fire_t:
                    break
                fire_dt = now.replace(
                    hour=fire_t.hour, minute=fire_t.minute, second=fire_t.second, microsecond=0
                )
                remaining = int((fire_dt - now).total_seconds())
                queued = await state_manager.get_pending_orders_count()
                logger.info(
                    "⏳  order fire in %ds  |  queued orders: %d  |  fires at %s IST",
                    remaining,
                    queued,
                    runtime.scheduled_fire_time,
                )
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass


scheduler_service = SchedulerService()
