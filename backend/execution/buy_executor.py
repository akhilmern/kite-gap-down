from __future__ import annotations
import asyncio
import logging
import math
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from backend.config.settings import get_settings
from backend.models.schemas import (
    GapCandidate, TrackedPosition, PlaceOrdersRequest, PlaceOrderItem,
    OrderStatus, OrderSource, KiteOrderRequest
)
from backend.models.state import state_manager
from backend.utils.kite_client import kite_client

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _now_ist() -> str:
    return datetime.now(IST).isoformat()


async def _place_single_order(
    item: PlaceOrderItem,
    token: str,
) -> TrackedPosition:
    """Place one buy order and return an initial TrackedPosition."""
    rs = get_settings()
    kite_client.access_token = token

    # Compute price
    if item.use_market_price or item.buy_limit_price <= 0:
        order_type = "MARKET"
        price = 0.0
    else:
        order_type = "LIMIT"
        buffered = item.buy_limit_price * (1 + rs.buy_buffer_pct / 100)
        price = round(buffered, 2)

    # Compute quantity
    if item.quantity and item.quantity > 0:
        qty = item.quantity
    else:
        ref_price = price if price > 0 else item.buy_limit_price
        qty = math.floor(item.investment_amount / ref_price) if ref_price > 0 else 1

    if qty <= 0:
        qty = 1

    order_data = {
        "tradingsymbol": item.tradingsymbol,
        "exchange": item.exchange,
        "transaction_type": "BUY",
        "order_type": order_type,
        "quantity": qty,
        "product": "MIS",
        "price": price,
        "validity": "DAY",
        "tag": "GAPDOWN",
    }

    pos = TrackedPosition(
        tradingsymbol=item.tradingsymbol,
        exchange=item.exchange,
        instrument_token=item.instrument_token,
        buy_status=OrderStatus.PENDING,
        source=OrderSource.API,
        requested_product="MIS",
        active_product="MIS",
        sl_pct=item.sl_pct,
        target_pct=item.target_pct,
        filled_quantity=qty,
    )

    # Try MIS first; fallback to CNC on rejection
    for product in ("MIS", "CNC"):
        order_data["product"] = product
        try:
            order_id = await kite_client.place_order("regular", order_data)
            pos.buy_order_id = order_id
            pos.active_product = product
            pos.buy_status = OrderStatus.OPEN
            logger.info(
                "Buy order placed %s qty=%d price=%.2f product=%s id=%s",
                item.tradingsymbol, qty, price, product, order_id,
            )
            return pos
        except Exception as exc:
            if product == "CNC":
                pos.buy_status = OrderStatus.REJECTED
                pos.error = str(exc)
                logger.error("Buy order failed %s: %s", item.tradingsymbol, exc)
                return pos
            logger.warning(
                "%s MIS rejected (%s), retrying CNC…", item.tradingsymbol, exc
            )

    return pos


async def execute_orders(req: PlaceOrdersRequest) -> List[TrackedPosition]:
    """Execute all orders in request concurrently."""
    token = state_manager.get_access_token()
    if not token:
        raise ValueError("Not authenticated")

    tasks = [_place_single_order(item, token) for item in req.items]
    positions: List[TrackedPosition] = await asyncio.gather(*tasks)

    for pos in positions:
        await state_manager.upsert_position(pos)

    # Increment count
    state_manager.orders_placed_count += len(positions)

    return positions


async def queue_or_execute(req: PlaceOrdersRequest) -> dict:
    """Queue orders if scheduled fire enabled; otherwise execute immediately."""
    rs = get_settings()
    now_ist = datetime.now(IST)
    fire_h, fire_m, fire_s = (int(x) for x in rs.scheduled_fire_time.split(":"))
    fire_dt = now_ist.replace(hour=fire_h, minute=fire_m, second=fire_s, microsecond=0)

    if rs.scheduled_fire_enabled and now_ist < fire_dt:
        await state_manager.enqueue_orders(req)
        return {"queued": True, "count": len(req.items)}
    else:
        positions = await execute_orders(req)
        return {"queued": False, "positions": [p.model_dump() for p in positions]}
