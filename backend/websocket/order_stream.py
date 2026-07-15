from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
from datetime import datetime

from backend.config.settings import get_settings
from backend.models.state import state_manager
from backend.execution.backup_poller import normalize_order_event

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class OrderStream:
    """
    Kite Connect order stream using the REST poller as the primary mechanism.
    
    Kite Connect does NOT provide a persistent WebSocket for order updates
    in the standard API — it uses:
      1. Postback: HTTP POST pushed by Kite to your server when orders update
      2. Polling the /orders REST endpoint (backup poller)
    
    This module handles the postback endpoint processing. The backup_poller
    handles periodic REST polling. Together they cover all order update scenarios.
    
    For Kite ticker (market data), the kiteconnect library provides a WebSocket.
    We use httpx REST for OHLC/LTP which is simpler and avoids the binary protocol.
    """

    def __init__(self) -> None:
        self._running = False
        self._reconnect_delay = 2

    async def start(self) -> None:
        """Mark WS as conceptually active (postback + poller handle updates)."""
        self._running = True
        await state_manager.set_ws_active(True)
        logger.info("Order stream active (postback + polling mode)")

    async def stop(self) -> None:
        self._running = False
        await state_manager.set_ws_active(False)
        logger.info("Order stream stopped")

    async def process_postback(self, data: Dict[str, Any]) -> None:
        """Process a Kite order postback payload."""
        from backend.execution.exit_engine import exit_engine
        event = normalize_order_event(data)
        if event is None:
            return
        logger.info(
            "Postback: %s %s %s qty=%d price=%.2f",
            event.tradingsymbol,
            event.transaction_type,
            event.status,
            event.filled_quantity,
            event.average_price,
        )
        await exit_engine.handle_order_event(event)

    @property
    def is_active(self) -> bool:
        return state_manager.ws_active


order_stream = OrderStream()
