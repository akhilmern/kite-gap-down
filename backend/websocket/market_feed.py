from __future__ import annotations
import asyncio
import logging
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
from datetime import datetime

from backend.config.settings import get_settings
from backend.models.schemas import TrackedPosition
from backend.models.state import state_manager
from backend.utils.kite_client import kite_client

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class MarketFeed:
    """LTP monitoring for Market-Sell SL mode.
    
    Uses Kite REST polling (not the ticker WebSocket) to monitor LTP
    and fire market sell when price breaches SL trigger.
    """

    def __init__(self) -> None:
        self._running = False
        self._watch: Dict[str, TrackedPosition] = {}  # symbol → position
        self._lock = asyncio.Lock()

    def register(self, pos: TrackedPosition) -> None:
        self._watch[pos.tradingsymbol] = pos
        logger.info("MarketFeed: registered %s sl_trigger=%.2f", pos.tradingsymbol, pos.sl_trigger_price or 0)

    def unregister(self, symbol: str) -> None:
        self._watch.pop(symbol, None)

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._loop())
        logger.info("Market feed loop started")

    async def stop(self) -> None:
        self._running = False

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(1)
            if not self._watch:
                continue

            token = state_manager.get_access_token()
            if not token:
                continue

            symbols = list(self._watch.keys())
            instruments = [f"NSE:{s}" for s in symbols]
            kite_client.access_token = token

            try:
                ltp_data = await kite_client.get_ltp(instruments)
            except Exception as exc:
                logger.error("MarketFeed LTP error: %s", exc)
                continue

            for sym in symbols:
                pos = self._watch.get(sym)
                if pos is None or pos.market_sell_sl_triggered or pos.exit_leg_filled:
                    self.unregister(sym)
                    continue

                key = f"NSE:{sym}"
                info = ltp_data.get(key, {})
                ltp = float(info.get("last_price", 0) or 0)
                if ltp <= 0:
                    continue

                if pos.sl_trigger_price and ltp <= pos.sl_trigger_price:
                    logger.info(
                        "MarketFeed: LTP %.2f ≤ SL trigger %.2f — firing market sell for %s",
                        ltp, pos.sl_trigger_price, sym
                    )
                    await self._fire_market_sell(pos, token)
                    self.unregister(sym)

    async def _fire_market_sell(self, pos: TrackedPosition, token: str) -> None:
        kite_client.access_token = token
        order_data = {
            "tradingsymbol": pos.tradingsymbol,
            "exchange": pos.exchange,
            "transaction_type": "SELL",
            "order_type": "MARKET",
            "quantity": pos.filled_quantity,
            "product": pos.active_product,
            "price": 0,
            "validity": "DAY",
            "tag": "GAPDOWN_MKTSL",
        }
        try:
            oid = await kite_client.place_order("regular", order_data)
            pos.market_sell_sl_triggered = True
            pos.sl_order_id = oid
            await state_manager.upsert_position(pos)
            logger.info("Market sell fired for %s order_id=%s", pos.tradingsymbol, oid)
            # Cancel target if exists
            if pos.target_order_id:
                try:
                    await kite_client.cancel_order("regular", pos.target_order_id)
                except Exception as exc:
                    logger.warning("Cancel target after market sell: %s", exc)
        except Exception as exc:
            logger.error("Market sell failed %s: %s", pos.tradingsymbol, exc)


market_feed = MarketFeed()
