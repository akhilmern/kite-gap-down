from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.config.settings import get_settings
from backend.models.schemas import OrderEvent, OrderStatus, TransactionType
from backend.models.state import state_manager
from backend.utils.kite_client import kite_client

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def normalize_order_event(raw: Dict[str, Any]) -> Optional[OrderEvent]:
    """Normalize a Kite order dict to our OrderEvent schema."""
    try:
        status_map = {
            "COMPLETE": OrderStatus.COMPLETE,
            "REJECTED": OrderStatus.REJECTED,
            "CANCELLED": OrderStatus.CANCELLED,
            "OPEN": OrderStatus.OPEN,
            "PENDING": OrderStatus.PENDING,
            "TRIGGER PENDING": OrderStatus.OPEN,
            "AMO REQ RECEIVED": OrderStatus.PENDING,
        }
        tx_map = {"BUY": TransactionType.BUY, "SELL": TransactionType.SELL}

        status_str = str(raw.get("status", "")).upper()
        tx_str = str(raw.get("transaction_type", "")).upper()
        ts = raw.get("order_timestamp") or raw.get("exchange_update_timestamp")
        if isinstance(ts, datetime):
            ts = ts.isoformat()

        return OrderEvent(
            order_id=str(raw.get("order_id", "")),
            status=status_map.get(status_str, OrderStatus.UNKNOWN),
            transaction_type=tx_map.get(tx_str),
            tradingsymbol=raw.get("tradingsymbol"),
            instrument_token=raw.get("instrument_token"),
            average_price=float(raw.get("average_price") or 0),
            filled_quantity=int(raw.get("filled_quantity") or 0),
            product=raw.get("product"),
            source=raw.get("app_id") or raw.get("source"),
            parent_order_id=raw.get("parent_order_id"),
            order_type=raw.get("order_type"),
            status_message=raw.get("status_message"),
            order_timestamp=str(ts) if ts else None,
            raw=raw,
        )
    except Exception as exc:
        logger.warning("normalize_order_event error: %s raw=%s", exc, raw)
        return None


class BackupPoller:
    """Fallback REST poller when WebSocket is down or as belt-and-suspenders."""

    def __init__(self) -> None:
        self._running = False
        self._seen_complete: set[str] = set()

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._loop())
        logger.info("Backup poller started")

    async def stop(self) -> None:
        self._running = False
        logger.info("Backup poller stopped")

    async def _loop(self) -> None:
        from backend.execution.exit_engine import exit_engine
        rs = get_settings()

        while self._running:
            interval = rs.poll_interval_ms / 1000.0
            if rs.disable_backup_poller:
                await asyncio.sleep(interval)
                continue

            token = state_manager.get_access_token()
            if not token:
                await asyncio.sleep(interval)
                continue

            kite_client.access_token = token
            try:
                orders: List[Dict] = await kite_client.get_orders()
                for raw in orders:
                    event = normalize_order_event(raw)
                    if event is None:
                        continue
                    # Only process newly completed orders
                    if event.status == OrderStatus.COMPLETE:
                        dedup_key = f"{event.order_id}:{event.filled_quantity}"
                        if dedup_key not in self._seen_complete:
                            self._seen_complete.add(dedup_key)
                            await exit_engine.handle_order_event(event)
                    elif event.status in (OrderStatus.OPEN, OrderStatus.PENDING):
                        # Update buy status in position
                        pos = state_manager.get_position_by_order_id(event.order_id)
                        if pos and pos.buy_order_id == event.order_id:
                            pos.buy_status = event.status
                            await state_manager.upsert_position(pos)
            except Exception as exc:
                resp_status = getattr(getattr(exc, "response", None), "status_code", None)
                if resp_status == 401:
                    logger.warning("Backup poller: 401 — pausing 30s")
                    await asyncio.sleep(30)
                    continue
                logger.error("Backup poller error: %s", exc)

            await asyncio.sleep(interval)


backup_poller = BackupPoller()
