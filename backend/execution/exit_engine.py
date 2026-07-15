from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time

from config.settings import IST
from models.schemas import KiteOrderRequest, LegType, OrderEvent, OrderSource, OrderStatus, TrackedPosition
from models.state import state_manager
from utils.kite_client import kite_client
from websocket.market_feed import market_feed, _split_instrument_token

logger = logging.getLogger(__name__)


class ExitEngine:
    async def on_order_update_event(self, event: OrderEvent) -> None:
        if not event.order_id:
            return

        position = await state_manager.get_position_by_order_id(event.order_id)
        if position is None:
            # transaction_type can be missing on scheduled orders from the
            # Kite app — treat absent as a potential BUY rather than dropping it
            tx = (event.transaction_type or "").upper()
            if tx in ("BUY", ""):
                position = await self._adopt_external_buy_if_needed(event)
                if position is not None:
                    runtime = await state_manager.get_runtime_settings()
                    if runtime.sl_engine_enabled:
                        if await self._position_is_live(position.tradingsymbol, position.instrument_token):
                            await self._fire_exit_orders(position)
                        else:
                            logger.warning(
                                "adopt_skip_no_live_position symbol=%s "
                                "— not found in Kite positions, skipping SL/target",
                                position.tradingsymbol,
                            )
                    return
        if position is None:
            return

        normalized_status = self._normalize_status(event.status)
        if event.order_id == position.buy_order_id:
            await self._handle_buy_update(position, event, normalized_status)
            return
        if event.order_id == position.sl_order_id:
            await self._handle_sl_update(position, normalized_status)
            return
        if event.order_id == position.target_order_id:
            await self._handle_target_update(position, normalized_status)

    async def _handle_buy_update(self, position: TrackedPosition, event: OrderEvent, status: OrderStatus) -> None:
        if position.buy_status == OrderStatus.COMPLETE:
            return
        position.buy_status = status
        if event.filled_quantity is not None:
            position.filled_quantity = event.filled_quantity
        if event.average_price is not None:
            position.average_fill_price = event.average_price
        if event.product:
            position.active_product = event.product
        if status != OrderStatus.COMPLETE:
            await state_manager.upsert_position(position)
            return
        position.entry_time = event.order_timestamp or datetime.now(IST).isoformat()
        position.precompute_exit_prices()
        await state_manager.upsert_position(position)
        runtime = await state_manager.get_runtime_settings()
        if not runtime.sl_engine_enabled:
            logger.warning("sl_engine_disabled symbol=%s buy_order_id=%s", position.tradingsymbol, position.buy_order_id)
            return
        await self._fire_exit_orders(position)

    async def _fire_exit_orders(self, position: TrackedPosition) -> None:
        if position.exit_leg_filled is not None or position.sl_order_id or position.target_order_id:
            return
        if position.target_price is None:
            return

        runtime = await state_manager.get_runtime_settings()
        quantity = position.filled_quantity or position.quantity_requested

        # instrument_token is "NSE:SYMBOL"; extract for Kite API
        exchange, tradingsymbol = _split_instrument_token(position.instrument_token, position.tradingsymbol)

        target_order = KiteOrderRequest(
            quantity=quantity,
            product=position.active_product,
            validity="DAY",
            price=position.target_price,
            tag=f"tgt-{position.tradingsymbol[:15]}",  # Kite tag ≤ 20 chars
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            instrument_token=position.instrument_token,
            order_type="LIMIT",
            transaction_type="SELL",
        )

        # Determine SL mode: market-sell monitoring vs. regular SL-M order
        use_market_sell_sl = (
            runtime.market_sell_sl_enabled
            and position.sl_trigger_price is not None
        )
        sl_order: KiteOrderRequest | None = None
        if not use_market_sell_sl and runtime.sl_enabled and position.sl_trigger_price is not None:
            sl_order = KiteOrderRequest(
                quantity=quantity,
                product=position.active_product,
                validity="DAY",
                price=0,
                tag=f"sl-{position.tradingsymbol[:16]}",  # Kite tag ≤ 20 chars
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                instrument_token=position.instrument_token,
                order_type="SL-M",
                transaction_type="SELL",
                trigger_price=position.sl_trigger_price,
            )

        is_intraday = position.active_product.upper() in ("MIS", "I")
        sl_delay = runtime.sl_delay_seconds if is_intraday and (sl_order is not None or use_market_sell_sl) else 0

        logger.info(
            "fire_exit_orders symbol=%s qty=%d product=%s sl_enabled=%s market_sell_sl=%s sl_trigger=%s target=%.2f sl_delay=%ds",
            position.tradingsymbol, quantity, position.active_product,
            runtime.sl_enabled,
            use_market_sell_sl,
            f"{position.sl_trigger_price:.2f}" if position.sl_trigger_price else "n/a",
            position.target_price,
            sl_delay,
        )

        # Place target immediately
        errors: list[str] = []
        try:
            target_result = await self._retry_place_order(target_order, runtime.max_order_placement_retries, runtime.retry_backoff_ms)
            position.target_order_id = target_result.order_ids[0]
            position.target_status = OrderStatus.OPEN
            await state_manager.register_order_id(position.target_order_id, position.tradingsymbol)
        except Exception as exc:  # noqa: BLE001
            logger.exception("target_order_failed symbol=%s: %s", position.tradingsymbol, exc)
            errors.append(f"Target order failed: {exc}")
            position.target_status = OrderStatus.REJECTED

        await state_manager.upsert_position(position)

        if use_market_sell_sl:
            if sl_delay > 0:
                logger.info(
                    "market_sell_sl_delay symbol=%s waiting=%ds",
                    position.tradingsymbol, sl_delay,
                )
                await asyncio.sleep(sl_delay)
            await market_feed.start_monitoring(position)
        elif sl_order is not None:
            if sl_delay > 0:
                logger.info(
                    "sl_delay_start symbol=%s waiting=%ds",
                    position.tradingsymbol, sl_delay,
                )
                await asyncio.sleep(sl_delay)
            try:
                sl_result = await self._retry_place_order(sl_order, runtime.max_order_placement_retries, runtime.retry_backoff_ms)
                position.sl_order_id = sl_result.order_ids[0]
                position.sl_status = OrderStatus.OPEN
                position.sl_placed_at = datetime.now(IST).isoformat()
                await state_manager.register_order_id(position.sl_order_id, position.tradingsymbol)
            except Exception as exc:  # noqa: BLE001
                logger.exception("sl_order_failed symbol=%s: %s", position.tradingsymbol, exc)
                errors.append(f"SL order failed: {exc}")
                position.sl_status = OrderStatus.REJECTED

        if errors:
            position.error = " | ".join(errors)

        await state_manager.upsert_position(position)

    async def _retry_place_order(self, order: KiteOrderRequest, retries: int, backoff_ms: int):
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                return await kite_client.place_order(order)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == retries - 1:
                    break
                await asyncio.sleep(backoff_ms / 1000)
        raise RuntimeError(f"Exit order placement failed: {last_error}")

    async def _handle_sl_update(self, position: TrackedPosition, status: OrderStatus) -> None:
        position.sl_status = status
        if status != OrderStatus.COMPLETE or position.exit_leg_filled is not None:
            await state_manager.upsert_position(position)
            return
        position.exit_leg_filled = LegType.STOP_LOSS
        if position.target_order_id and position.target_status not in {OrderStatus.CANCELLED, OrderStatus.COMPLETE}:
            await kite_client.cancel_order(position.target_order_id)
            position.target_status = OrderStatus.CANCELLED
        await state_manager.upsert_position(position)

    async def _handle_target_update(self, position: TrackedPosition, status: OrderStatus) -> None:
        position.target_status = status
        if status != OrderStatus.COMPLETE or position.exit_leg_filled is not None:
            await state_manager.upsert_position(position)
            return
        position.exit_leg_filled = LegType.TARGET
        if position.sl_order_id and position.sl_status not in {OrderStatus.CANCELLED, OrderStatus.COMPLETE}:
            await kite_client.cancel_order(position.sl_order_id)
            position.sl_status = OrderStatus.CANCELLED
        await state_manager.upsert_position(position)

    async def _position_is_live(self, tradingsymbol: str, instrument_token: str) -> bool:
        """
        Returns True if Kite reports a non-zero net quantity for this symbol
        in the positions endpoint. False means flat/closed — no SL/target order.
        """
        try:
            positions = await kite_client.get_positions()
            for pos in positions:
                symbol_match = pos.get("tradingsymbol") == tradingsymbol
                if symbol_match:
                    qty = int(pos.get("quantity") or pos.get("net_quantity") or 0)
                    return qty != 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("position_is_live_check_failed symbol=%s: %s — allowing SL", tradingsymbol, exc)
            return True
        return False

    # ── Today's session window: only adopt buy orders that arrived during
    # the current trading day (after 9:00 AM IST).
    _SESSION_START = time(9, 0, 0)
    _SESSION_END = time(15, 35, 0)

    async def _adopt_external_buy_if_needed(self, event: OrderEvent) -> TrackedPosition | None:
        runtime = await state_manager.get_runtime_settings()
        if not runtime.adopt_mobile_buy_orders:
            return None
        if self._normalize_status(event.status) != OrderStatus.COMPLETE:
            return None
        if not event.tradingsymbol or not event.instrument_token:
            return None

        now_ist = datetime.now(IST)
        now_time = now_ist.time()
        if not (self._SESSION_START <= now_time <= self._SESSION_END):
            logger.debug(
                "adopt_skipped_outside_session symbol=%s order_id=%s time=%s",
                event.tradingsymbol, event.order_id, now_time.strftime("%H:%M:%S"),
            )
            return None

        existing = await state_manager.get_position(event.tradingsymbol)
        if existing is not None:
            logger.debug(
                "adopt_skipped_already_tracked symbol=%s existing_buy_id=%s",
                event.tradingsymbol, existing.buy_order_id,
            )
            return None

        source = self._normalize_source(event.source)
        position = TrackedPosition(
            tradingsymbol=event.tradingsymbol,
            exchange="NSE",
            instrument_token=event.instrument_token,
            quantity_requested=event.filled_quantity or 0,
            requested_product=event.product or "MIS",
            active_product=event.product or "MIS",
            buy_limit_price=event.average_price or 0,
            use_market_price=True,
            sl_pct=runtime.default_sl_pct,
            target_pct=runtime.default_target_pct,
            source=source.value,
            order_source=source.value,
            buy_order_id=event.order_id,
            buy_status=OrderStatus.COMPLETE,
            filled_quantity=event.filled_quantity or 0,
            average_fill_price=event.average_price,
        )
        position.precompute_exit_prices()
        await state_manager.upsert_position(position)
        logger.info(
            "adopted_external_buy symbol=%s token=%s fill=%.2f qty=%d source=%s",
            event.tradingsymbol, event.instrument_token,
            event.average_price or 0, event.filled_quantity or 0, source.value,
        )
        return position

    def _normalize_status(self, status: str) -> OrderStatus:
        normalized = status.upper().replace(" ", "_")
        mapping = {
            "PENDING": OrderStatus.PENDING,
            "OPEN": OrderStatus.OPEN,
            "TRIGGER_PENDING": OrderStatus.OPEN,
            "COMPLETE": OrderStatus.COMPLETE,
            "COMPLETED": OrderStatus.COMPLETE,
            "REJECTED": OrderStatus.REJECTED,
            "CANCELLED": OrderStatus.CANCELLED,
            "CANCELED": OrderStatus.CANCELLED,
        }
        return mapping.get(normalized, OrderStatus.UNKNOWN)

    def _normalize_source(self, source: str | None) -> OrderSource:
        lowered = (source or "").lower()
        if "mobile" in lowered or "kite" in lowered:
            return OrderSource.MOBILE
        if "web" in lowered:
            return OrderSource.WEB
        return OrderSource.API


exit_engine = ExitEngine()
