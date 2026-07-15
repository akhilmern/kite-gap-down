"""market_feed.py — LTP price monitor for market-sell SL exits.

When `market_sell_sl_enabled` is on, the exit engine calls
`market_feed.start_monitoring(position)` instead of placing a SL-M order.
A background task then polls the Kite full-quote REST endpoint every second
and fires a MARKET SELL as soon as the LTP touches or crosses the
pre-computed `sl_trigger_price`.

One polling loop services all monitored positions; each position is removed
from the watch-list as soon as it exits (either via a market-sell SL or via
the target order filling first).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from config.settings import IST
from models.schemas import KiteOrderRequest, LegType, OrderStatus, TrackedPosition
from models.state import state_manager
from utils.kite_client import kite_client

logger = logging.getLogger(__name__)

# How often (seconds) to poll LTP for all watched positions.
_POLL_INTERVAL = 1.0


class MarketFeed:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # instrument_token (NSE:SYMBOL) → TrackedPosition
        self._watched: dict[str, TrackedPosition] = {}
        self._lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    async def start_monitoring(self, position: TrackedPosition) -> None:
        """Register a position for LTP-based SL monitoring and ensure the loop is running."""
        async with self._lock:
            self._watched[position.instrument_token] = position
        logger.info(
            "market_feed_watch symbol=%s token=%s sl_trigger=%.2f",
            position.tradingsymbol,
            position.instrument_token,
            position.sl_trigger_price or 0,
        )
        await self._ensure_running()

    async def stop_monitoring(self, instrument_token: str) -> None:
        """Remove a single position from the watch-list."""
        async with self._lock:
            self._watched.pop(instrument_token, None)

    async def stop(self) -> None:
        """Stop the entire monitoring loop (called on order-stream shutdown)."""
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            self._watched.clear()

    async def restart(self) -> None:
        """Reset stop flag so monitoring can be restarted (after order-stream restart)."""
        self._stop = asyncio.Event()

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        logger.info("market_feed_loop_start")
        while not self._stop.is_set():
            async with self._lock:
                positions = list(self._watched.values())

            if not positions:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            # Fetch LTP for all watched tokens in one batch
            # instrument_token is stored as "NSE:SYMBOL" format
            tokens = [p.instrument_token for p in positions]
            try:
                quotes = await kite_client.get_full_quotes(tokens)
            except Exception as exc:  # noqa: BLE001
                logger.warning("market_feed_quote_error: %s", exc)
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            # Build token → LTP lookup; Kite returns keys as "NSE:SYMBOL"
            ltp_by_token: dict[str, float] = {}
            for _key, quote in quotes.items():
                if not isinstance(quote, dict):
                    continue
                ltp = kite_client._to_float(quote.get("last_price"))
                if _key and ltp is not None:
                    ltp_by_token[_key] = ltp

            for position in positions:
                await self._check_position(position, ltp_by_token)

            await asyncio.sleep(_POLL_INTERVAL)

        logger.info("market_feed_loop_stop")

    async def _check_position(
        self,
        position: TrackedPosition,
        ltp_by_token: dict[str, float],
    ) -> None:
        """Fire a market sell if the LTP has hit or crossed the SL trigger price."""
        fresh = await state_manager.get_position(position.tradingsymbol)
        if fresh is None:
            await self.stop_monitoring(position.instrument_token)
            return

        if fresh.exit_leg_filled is not None:
            await self.stop_monitoring(fresh.instrument_token)
            return

        if fresh.market_sell_sl_triggered:
            await self.stop_monitoring(fresh.instrument_token)
            return

        if fresh.sl_trigger_price is None:
            return

        ltp = ltp_by_token.get(fresh.instrument_token)
        if ltp is None:
            return

        if ltp > fresh.sl_trigger_price:
            return  # Price still above SL, keep watching

        # ── SL hit — fire market sell ────────────────────────────────────────
        logger.info(
            "market_sell_sl_trigger symbol=%s ltp=%.2f sl_trigger=%.2f",
            fresh.tradingsymbol,
            ltp,
            fresh.sl_trigger_price,
        )

        fresh.market_sell_sl_triggered = True
        await state_manager.upsert_position(fresh)
        await self.stop_monitoring(fresh.instrument_token)

        runtime = await state_manager.get_runtime_settings()
        quantity = fresh.filled_quantity or fresh.quantity_requested

        # Build a Kite market sell order
        # instrument_token is "NSE:SYMBOL"; extract parts for Kite API
        exchange, tradingsymbol = _split_instrument_token(fresh.instrument_token, fresh.tradingsymbol)

        market_sell = KiteOrderRequest(
            quantity=quantity,
            product=fresh.active_product,
            validity="DAY",
            price=0,
            tag=f"msl-{fresh.tradingsymbol[:14]}",  # Kite tag ≤ 20 chars
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            instrument_token=fresh.instrument_token,
            order_type="MARKET",
            transaction_type="SELL",
        )

        try:
            result = await kite_client.place_order(market_sell)
            sl_order_id = result.order_ids[0] if result.order_ids else None
            fresh.sl_order_id = sl_order_id
            fresh.sl_status = OrderStatus.OPEN
            fresh.sl_placed_at = datetime.now(IST).isoformat()
            if sl_order_id:
                await state_manager.register_order_id(sl_order_id, fresh.tradingsymbol)
            logger.info(
                "market_sell_sl_placed symbol=%s order_id=%s",
                fresh.tradingsymbol,
                sl_order_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "market_sell_sl_failed symbol=%s: %s", fresh.tradingsymbol, exc
            )
            fresh.sl_status = OrderStatus.REJECTED
            fresh.error = f"Market SL sell failed: {exc}"

        await state_manager.upsert_position(fresh)


def _split_instrument_token(instrument_token: str, fallback_symbol: str) -> tuple[str, str]:
    """Split 'NSE:SBIN' into ('NSE', 'SBIN'). Falls back to ('NSE', symbol)."""
    if ":" in instrument_token:
        exchange, symbol = instrument_token.split(":", 1)
        return exchange, symbol
    return "NSE", fallback_symbol


market_feed = MarketFeed()
