from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time

import httpx

from config.settings import IST
from models.schemas import KiteOrderRequest, OrderSource, OrderStatus, PlaceOrdersRequest, TrackedPosition
from models.state import state_manager
from utils.kite_client import kite_client
from websocket.market_feed import _split_instrument_token

logger = logging.getLogger(__name__)


def _parse_time(t: str) -> time:
    """Parse HH:MM:SS string to a time object, fallback to 09:15:01."""
    try:
        parts = t.strip().split(":")
        return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    except Exception:
        return time(9, 15, 1)


class BuyExecutor:
    async def place_buy_orders(self, request: PlaceOrdersRequest) -> list[TrackedPosition]:
        """
        When scheduled_fire_enabled is True and the current time is before the
        scheduled fire time, queue the request for deferred execution.
        Otherwise fire immediately.
        """
        runtime = await state_manager.get_runtime_settings()
        now_ist = datetime.now(IST).time()
        fire_time = _parse_time(runtime.scheduled_fire_time)
        if runtime.scheduled_fire_enabled and now_ist < fire_time:
            total_queued = await state_manager.enqueue_orders(request)
            logger.info(
                "buy_orders_queued symbols=%s total_queued=%d — will fire at %s IST",
                [i.tradingsymbol for i in request.items],
                total_queued,
                runtime.scheduled_fire_time,
            )
            # Return placeholder positions so the frontend gets immediate feedback
            return [
                TrackedPosition(
                    tradingsymbol=item.tradingsymbol,
                    exchange=item.exchange,
                    instrument_token=item.instrument_token,
                    quantity_requested=item.quantity,
                    requested_product="MIS",
                    active_product="MIS",
                    buy_limit_price=item.buy_limit_price,
                    use_market_price=item.use_market_price,
                    sl_pct=item.sl_pct_override if item.sl_pct_override is not None else runtime.default_sl_pct,
                    target_pct=item.target_pct_override if item.target_pct_override is not None else runtime.default_target_pct,
                    source=OrderSource.API.value,
                    order_source=OrderSource.API.value,
                    buy_status=OrderStatus.PENDING,
                )
                for item in request.items
            ]

        return await self._execute_now(request)

    async def _execute_now(self, request: PlaceOrdersRequest) -> list[TrackedPosition]:
        """Fire all items in the request immediately against the Kite API."""
        runtime = await state_manager.get_runtime_settings()

        async def place_item(item):
            price = round(item.buy_limit_price, 2)
            if not item.use_market_price:
                price = round(price * (1 + runtime.buy_buffer_pct / 100), 2)
            order_type = "MARKET" if item.use_market_price else "LIMIT"

            # instrument_token stored as "NSE:SYMBOL"
            exchange, tradingsymbol = _split_instrument_token(
                item.instrument_token, item.tradingsymbol
            )

            position = TrackedPosition(
                tradingsymbol=item.tradingsymbol,
                exchange=item.exchange,
                instrument_token=item.instrument_token,
                quantity_requested=item.quantity,
                requested_product="MIS",
                active_product="MIS",
                buy_limit_price=price,
                use_market_price=item.use_market_price,
                sl_pct=item.sl_pct_override if item.sl_pct_override is not None else runtime.default_sl_pct,
                target_pct=item.target_pct_override if item.target_pct_override is not None else runtime.default_target_pct,
                source=OrderSource.API.value,
                order_source=OrderSource.API.value,
            )

            order = KiteOrderRequest(
                quantity=item.quantity,
                product="MIS",   # Kite intraday product code
                validity="DAY",
                price=0.0 if item.use_market_price else price,
                tag=f"buy-{item.tradingsymbol[:13]}",  # Kite tag ≤ 20 chars
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                instrument_token=item.instrument_token,
                order_type=order_type,
                transaction_type="BUY",
            )
            try:
                result = await kite_client.place_order(order)
                position.buy_order_id = result.order_ids[0]
                position.buy_status = OrderStatus.OPEN
                await state_manager.register_order_id(position.buy_order_id, position.tradingsymbol)
                await state_manager.increment_orders_placed_count()
                await state_manager.upsert_position(position)
            except httpx.HTTPError as exc:
                logger.exception("buy_order_failed symbol=%s", item.tradingsymbol)
                position.buy_status = OrderStatus.REJECTED
                position.error = str(exc)
                await state_manager.upsert_position(position)
            return position

        return await asyncio.gather(*(place_item(item) for item in request.items))

    async def fire_pending_orders(self) -> int:
        """
        Called by the 9:15 cron job. Drains the queue and executes every
        pending request. Returns the total number of order items fired.
        """
        pending = await state_manager.pop_pending_orders()
        if not pending:
            logger.info("fire_pending_orders: queue was empty — nothing to fire")
            return 0

        total_items = sum(len(r.items) for r in pending)
        logger.info(
            "fire_pending_orders: firing %d queued item(s) across %d request(s)",
            total_items,
            len(pending),
        )
        for req in pending:
            await self._execute_now(req)
        return total_items


buy_executor = BuyExecutor()
