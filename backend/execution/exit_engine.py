from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from backend.config.settings import get_settings
from backend.models.schemas import OrderEvent, OrderStatus, LegType, TrackedPosition, OrderSource
from backend.models.state import state_manager
from backend.utils.kite_client import kite_client

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Lock to prevent duplicate exit placements per position
_exit_locks: dict[str, asyncio.Lock] = {}


def _get_lock(symbol: str) -> asyncio.Lock:
    if symbol not in _exit_locks:
        _exit_locks[symbol] = asyncio.Lock()
    return _exit_locks[symbol]


def _now_ist() -> str:
    return datetime.now(IST).isoformat()


class ExitEngine:
    """Synthetic OCO exit engine — places SL and Target orders on buy fill."""

    async def handle_order_event(self, event: OrderEvent) -> None:
        """Route an order event to the appropriate handler."""
        rs = get_settings()
        if not rs.sl_engine_enabled:
            return
        if not state_manager.sl_engine_armed:
            return

        status = event.status
        tx = event.transaction_type

        if tx and tx.value == "BUY" and status == OrderStatus.COMPLETE:
            await self._handle_buy_complete(event)
        elif tx and tx.value == "SELL" and status == OrderStatus.COMPLETE:
            await self._handle_sell_complete(event)

    async def _handle_buy_complete(self, event: OrderEvent) -> None:
        """Buy order filled — place SL and target exits."""
        rs = get_settings()
        token = state_manager.get_access_token()
        if not token:
            return

        symbol = event.tradingsymbol
        pos = state_manager.get_position_by_order_id(event.order_id)

        # --- Mobile order adoption ---
        if pos is None and symbol:
            pos = state_manager.get_position(symbol)

        if pos is None:
            # Attempt mobile adoption
            if rs.adopt_mobile_buy_orders and symbol:
                now_ist = datetime.now(IST)
                if 9 <= now_ist.hour < 16:  # 09:00–16:00 IST
                    pos = TrackedPosition(
                        tradingsymbol=symbol,
                        exchange=event.tradingsymbol and "NSE" or "NSE",
                        instrument_token=event.instrument_token or 0,
                        buy_order_id=event.order_id,
                        source=OrderSource.MOBILE,
                        active_product=event.product or "MIS",
                        requested_product=event.product or "MIS",
                        sl_pct=rs.default_sl_pct,
                        target_pct=rs.default_target_pct,
                    )
                    logger.info("Adopting mobile order %s for %s", event.order_id, symbol)
                else:
                    return
            else:
                return

        async with _get_lock(pos.tradingsymbol):
            # Dedup: already handled this buy
            if pos.sl_order_id or pos.target_order_id:
                return

            # Update fill data
            fill_price = event.average_price or pos.average_fill_price
            fill_qty = event.filled_quantity or pos.filled_quantity
            pos.average_fill_price = fill_price
            pos.filled_quantity = fill_qty
            pos.buy_status = OrderStatus.COMPLETE
            # Use broker timestamp if available, else server time
            pos.entry_time = event.order_timestamp or _now_ist()
            await state_manager.upsert_position(pos)

            if fill_price <= 0:
                logger.warning("Buy fill price is 0 for %s — skipping exits", symbol)
                return

            # Compute exit prices
            sl_trigger = round(fill_price * (1 - pos.sl_pct / 100), 2)
            target_price = round(fill_price * (1 + pos.target_pct / 100), 2)
            pos.sl_trigger_price = sl_trigger
            pos.target_price = target_price

            product = pos.active_product
            kite_client.access_token = token

            # --- Place TARGET limit sell first ---
            target_data = {
                "tradingsymbol": pos.tradingsymbol,
                "exchange": pos.exchange,
                "transaction_type": "SELL",
                "order_type": "LIMIT",
                "quantity": fill_qty,
                "product": product,
                "price": target_price,
                "validity": "DAY",
                "tag": "GAPDOWN_TGT",
            }
            try:
                tid = await kite_client.place_order("regular", target_data)
                pos.target_order_id = tid
                pos.target_status = OrderStatus.OPEN
                logger.info("Target order placed %s @ %.2f id=%s", symbol, target_price, tid)
            except Exception as exc:
                logger.error("Target order failed %s: %s", symbol, exc)
                pos.error = f"Target failed: {exc}"

            await state_manager.upsert_position(pos)

            # --- SL placement ---
            if rs.market_sell_sl_enabled:
                # LTP monitoring mode — register for market feed watcher
                from backend.websocket.market_feed import market_feed
                market_feed.register(pos)
                logger.info("Registered %s for LTP SL monitoring @ %.2f", symbol, sl_trigger)
            else:
                # Classic SL-M mode — wait SL_DELAY_SECONDS then place
                asyncio.create_task(
                    self._delayed_sl_placement(pos, sl_trigger, fill_qty, product, token)
                )

    async def _delayed_sl_placement(
        self,
        pos: TrackedPosition,
        sl_trigger: float,
        qty: int,
        product: str,
        token: str,
    ) -> None:
        rs = get_settings()
        await asyncio.sleep(rs.sl_delay_seconds)

        # Refresh position — may have already exited
        current = state_manager.get_position(pos.tradingsymbol)
        if current and current.exit_leg_filled:
            logger.info("SL delay skipped — already exited %s", pos.tradingsymbol)
            return

        kite_client.access_token = token
        sl_data = {
            "tradingsymbol": pos.tradingsymbol,
            "exchange": pos.exchange,
            "transaction_type": "SELL",
            "order_type": "SL-M",
            "quantity": qty,
            "product": product,
            "price": 0,
            "trigger_price": sl_trigger,
            "validity": "DAY",
            "tag": "GAPDOWN_SL",
        }
        try:
            slid = await kite_client.place_order("regular", sl_data)
            pos.sl_order_id = slid
            pos.sl_status = OrderStatus.OPEN
            pos.sl_placed_at = _now_ist()
            logger.info("SL-M order placed %s @ trigger %.2f id=%s", pos.tradingsymbol, sl_trigger, slid)
        except Exception as exc:
            logger.error("SL order failed %s: %s", pos.tradingsymbol, exc)
            pos.error = f"SL failed: {exc}"
        await state_manager.upsert_position(pos)

    async def _handle_sell_complete(self, event: OrderEvent) -> None:
        """One exit leg filled — cancel the other."""
        token = state_manager.get_access_token()
        if not token:
            return

        symbol = event.tradingsymbol
        pos = state_manager.get_position_by_order_id(event.order_id)
        if pos is None and symbol:
            pos = state_manager.get_position(symbol)
        if pos is None:
            return

        async with _get_lock(pos.tradingsymbol):
            if pos.exit_leg_filled:
                return  # Already handled

            order_id = event.order_id
            kite_client.access_token = token

            # Determine which leg filled
            if order_id == pos.sl_order_id:
                pos.exit_leg_filled = LegType.STOP_LOSS
                pos.sl_status = OrderStatus.COMPLETE
                # Cancel target
                if pos.target_order_id:
                    try:
                        await kite_client.cancel_order("regular", pos.target_order_id)
                        pos.target_status = OrderStatus.CANCELLED
                        logger.info("SL hit — cancelled target %s for %s", pos.target_order_id, symbol)
                    except Exception as exc:
                        logger.warning("Cancel target error %s: %s", symbol, exc)

            elif order_id == pos.target_order_id:
                pos.exit_leg_filled = LegType.TARGET
                pos.target_status = OrderStatus.COMPLETE
                # Cancel SL
                if pos.sl_order_id:
                    try:
                        await kite_client.cancel_order("regular", pos.sl_order_id)
                        pos.sl_status = OrderStatus.CANCELLED
                        logger.info("Target hit — cancelled SL %s for %s", pos.sl_order_id, symbol)
                    except Exception as exc:
                        logger.warning("Cancel SL error %s: %s", symbol, exc)
            else:
                return  # Not our order

            await state_manager.upsert_position(pos)
            logger.info("Exit complete for %s via %s", symbol, pos.exit_leg_filled)


exit_engine = ExitEngine()
