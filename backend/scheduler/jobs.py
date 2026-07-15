from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config.settings import get_settings
from backend.models.state import state_manager
from backend.utils.kite_client import kite_client
from backend.scanner.gap_scanner import gap_scanner

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


# ------------------------------------------------------------------
# Cron job handlers
# ------------------------------------------------------------------

async def job_daily_reset() -> None:
    logger.info("[SCHEDULER] Daily reset at 08:00 IST")
    await state_manager.reset_for_day()


async def job_auto_prev_close() -> None:
    logger.info("[SCHEDULER] Auto prev-close fetch at 08:30 IST")
    token = state_manager.get_access_token()
    if not token:
        logger.warning("No access token — skipping auto prev-close")
        return
    kite_client.access_token = token
    try:
        n = await kite_client.fetch_and_store_prev_close()
        logger.info("Prev close fetched for %d instruments", n)
    except Exception as exc:
        logger.error("Auto prev-close error: %s", exc)


async def job_auto_scan() -> None:
    logger.info("[SCHEDULER] Auto gap scan at 09:08 IST")
    token = state_manager.get_access_token()
    if not token:
        logger.warning("No access token — skipping auto scan")
        return
    kite_client.access_token = token
    try:
        rs = get_settings()
        results = await gap_scanner.run(rs)
        ts = datetime.now(IST).isoformat()
        await state_manager.set_scan_results(results, ts)
        logger.info("Auto scan: %d candidates", len(results))
    except Exception as exc:
        logger.error("Auto scan error: %s", exc)


# ------------------------------------------------------------------
# Fire watcher — per-second loop
# ------------------------------------------------------------------

_fire_watcher_task: asyncio.Task | None = None


async def _fire_watcher_loop() -> None:
    """Check every second if queued orders should fire."""
    from backend.execution.buy_executor import execute_orders

    while True:
        await asyncio.sleep(1)
        rs = get_settings()
        if not rs.scheduled_fire_enabled:
            continue

        now_ist = datetime.now(IST)
        try:
            fire_h, fire_m, fire_s = (int(x) for x in rs.scheduled_fire_time.split(":"))
        except Exception:
            continue

        fire_dt = now_ist.replace(hour=fire_h, minute=fire_m, second=fire_s, microsecond=0)

        # Only fire during market hours on the current day
        if now_ist < fire_dt:
            continue
        if state_manager.fire_watcher_fired_today:
            continue
        # Only fire between 09:15 and 09:30 to avoid accidental fires after market
        if now_ist.hour >= 9 and now_ist.hour < 10:
            pending = await state_manager.pop_pending_orders()
            if pending:
                logger.info("[FIRE WATCHER] Firing %d queued order batches", len(pending))
                for req in pending:
                    try:
                        await execute_orders(req)
                    except Exception as exc:
                        logger.error("[FIRE WATCHER] Execute error: %s", exc)
            state_manager.fire_watcher_fired_today = True

            # Auto-arm SL engine after fire
            await state_manager.arm_sl_engine(True)
            logger.info("[FIRE WATCHER] SL engine auto-armed after order fire")


def start_scheduler() -> None:
    global _fire_watcher_task

    rs = get_settings()

    scheduler.add_job(
        job_daily_reset,
        CronTrigger(hour=8, minute=0, second=0, timezone="Asia/Kolkata"),
        id="daily_reset",
        replace_existing=True,
    )
    scheduler.add_job(
        job_auto_prev_close,
        CronTrigger(hour=8, minute=30, second=0, timezone="Asia/Kolkata"),
        id="auto_prev_close",
        replace_existing=True,
    )
    scheduler.add_job(
        job_auto_scan,
        CronTrigger(hour=9, minute=8, second=0, timezone="Asia/Kolkata"),
        id="auto_scan",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("APScheduler started with 3 cron jobs")

    # Fire watcher — asyncio task
    _fire_watcher_task = asyncio.create_task(_fire_watcher_loop())
    logger.info("Fire watcher task started")


def stop_scheduler() -> None:
    global _fire_watcher_task
    if scheduler.running:
        scheduler.shutdown(wait=False)
    if _fire_watcher_task:
        _fire_watcher_task.cancel()
