from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution.exit_engine import exit_engine
from models.schemas import KiteOrderResult, LegType, OrderEvent, OrderStatus, TrackedPosition
from models.state import state_manager
from utils.kite_client import kite_client


@pytest.fixture(autouse=True)
async def reset_state():
    await state_manager.reset_for_day()
    await state_manager.update_runtime_settings(
        adopt_mobile_buy_orders=True,
        default_sl_pct=1.0,
        default_target_pct=1.5,
        auto_slice_orders=True,
        max_order_placement_retries=2,
        retry_backoff_ms=1,
        sl_delay_seconds=0,  # disable SL delay in tests so they don't hang
    )
    yield
    await state_manager.reset_for_day()


@pytest.mark.asyncio
async def test_buy_fill_places_sl_and_target(monkeypatch):
    position = TrackedPosition(
        tradingsymbol="SBIN",
        instrument_token="NSE:SBIN",
        quantity_requested=10,
        buy_limit_price=800,
        sl_pct=1.0,
        target_pct=1.5,
        buy_order_id="buy-1",
    )
    await state_manager.upsert_position(position)

    calls = []

    async def fake_place(order):
        calls.append(order)
        return KiteOrderResult(order_ids=[f"oid-{len(calls)}"])

    monkeypatch.setattr(kite_client, "place_order", fake_place)

    await exit_engine.on_order_update_event(
        OrderEvent(
            order_id="buy-1",
            status="COMPLETE",
            transaction_type="BUY",
            average_price=801.25,
            filled_quantity=10,
            product="MIS",
        )
    )

    saved = await state_manager.get_position("SBIN")
    assert saved is not None
    assert saved.buy_status == OrderStatus.COMPLETE
    assert saved.sl_trigger_price == 793.24
    assert saved.target_price == 813.27
    # Target is placed first, then SL
    assert saved.target_order_id == "oid-1"
    assert saved.sl_order_id == "oid-2"
    assert calls[0].order_type == "LIMIT"   # target
    assert calls[1].order_type == "SL-M"    # sl


@pytest.mark.asyncio
async def test_sl_fill_cancels_target_leg(monkeypatch):
    position = TrackedPosition(
        tradingsymbol="SBIN",
        instrument_token="NSE:SBIN",
        quantity_requested=10,
        buy_limit_price=800,
        sl_pct=1.0,
        target_pct=1.5,
        buy_order_id="buy-1",
        buy_status=OrderStatus.COMPLETE,
        filled_quantity=10,
        average_fill_price=800,
        sl_order_id="sl-1",
        sl_status=OrderStatus.OPEN,
        target_order_id="target-1",
        target_status=OrderStatus.OPEN,
    )
    position.precompute_exit_prices()
    await state_manager.upsert_position(position)

    cancelled = []

    async def fake_cancel(order_id):
        cancelled.append(order_id)
        return {"status": "success"}

    monkeypatch.setattr(kite_client, "cancel_order", fake_cancel)

    await exit_engine.on_order_update_event(OrderEvent(order_id="sl-1", status="COMPLETE"))
    saved = await state_manager.get_position("SBIN")
    assert saved is not None
    assert saved.exit_leg_filled == LegType.STOP_LOSS
    assert saved.target_status == OrderStatus.CANCELLED
    assert cancelled == ["target-1"]


@pytest.mark.asyncio
async def test_target_fill_cancels_sl_leg(monkeypatch):
    position = TrackedPosition(
        tradingsymbol="SBIN",
        instrument_token="NSE:SBIN",
        quantity_requested=10,
        buy_limit_price=800,
        sl_pct=1.0,
        target_pct=1.5,
        buy_order_id="buy-1",
        buy_status=OrderStatus.COMPLETE,
        filled_quantity=10,
        average_fill_price=800,
        sl_order_id="sl-1",
        sl_status=OrderStatus.OPEN,
        target_order_id="target-1",
        target_status=OrderStatus.OPEN,
    )
    position.precompute_exit_prices()
    await state_manager.upsert_position(position)

    cancelled = []

    async def fake_cancel(order_id):
        cancelled.append(order_id)
        return {"status": "success"}

    monkeypatch.setattr(kite_client, "cancel_order", fake_cancel)

    await exit_engine.on_order_update_event(OrderEvent(order_id="target-1", status="COMPLETE"))
    saved = await state_manager.get_position("SBIN")
    assert saved is not None
    assert saved.exit_leg_filled == LegType.TARGET
    assert saved.sl_status == OrderStatus.CANCELLED
    assert cancelled == ["sl-1"]


@pytest.mark.asyncio
async def test_duplicate_buy_complete_is_idempotent(monkeypatch):
    position = TrackedPosition(
        tradingsymbol="SBIN",
        instrument_token="NSE:SBIN",
        quantity_requested=10,
        buy_limit_price=800,
        sl_pct=1.0,
        target_pct=1.5,
        buy_order_id="buy-1",
    )
    await state_manager.upsert_position(position)

    count = 0

    async def fake_place(order):
        nonlocal count
        count += 1
        return KiteOrderResult(order_ids=[f"oid-{count}"])

    monkeypatch.setattr(kite_client, "place_order", fake_place)

    event = OrderEvent(order_id="buy-1", status="COMPLETE", transaction_type="BUY", average_price=800, filled_quantity=10, product="MIS")
    await exit_engine.on_order_update_event(event)
    await exit_engine.on_order_update_event(event)

    assert count == 2


@pytest.mark.asyncio
async def test_mobile_buy_adopted_when_enabled(monkeypatch):
    from datetime import datetime
    from config.settings import IST
    import execution.exit_engine as ee_module

    # Simulate a timestamp during market hours so the session-time guard passes
    market_open_dt = datetime(2024, 1, 15, 9, 20, 0, tzinfo=IST)
    monkeypatch.setattr(ee_module, "datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: market_open_dt),
        "combine": datetime.combine,
    }))

    # Confirm the live-position check returns True (position is open in Kite)
    async def fake_position_is_live(tradingsymbol, instrument_token):
        return True

    monkeypatch.setattr(exit_engine, "_position_is_live", fake_position_is_live)

    async def fake_place(order):
        return KiteOrderResult(order_ids=[f"{order.tag}-1"])

    monkeypatch.setattr(kite_client, "place_order", fake_place)

    await exit_engine.on_order_update_event(
        OrderEvent(
            order_id="mobile-buy-1",
            status="COMPLETE",
            transaction_type="BUY",
            tradingsymbol="INFY",
            instrument_token="NSE:INFY",
            average_price=1500,
            filled_quantity=5,
            product="D",
            source="mobile-app",
        )
    )
    saved = await state_manager.get_position("INFY")
    assert saved is not None
    assert saved.order_source == "mobile"
    assert saved.active_product == "D"
    assert saved.sl_order_id is not None
    assert saved.target_order_id is not None


@pytest.mark.asyncio
async def test_mobile_buy_not_adopted_outside_session(monkeypatch):
    """Orders arriving outside 9:00–15:35 IST must not create positions."""
    from datetime import datetime
    from config.settings import IST
    import execution.exit_engine as ee_module

    # Simulate midnight — outside session window
    midnight_dt = datetime(2024, 1, 15, 0, 0, 0, tzinfo=IST)
    monkeypatch.setattr(ee_module, "datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: midnight_dt),
        "combine": datetime.combine,
    }))

    async def fake_place(order):
        return KiteOrderResult(order_ids=["unexpected"])

    monkeypatch.setattr(kite_client, "place_order", fake_place)

    await exit_engine.on_order_update_event(
        OrderEvent(
            order_id="old-buy-99",
            status="COMPLETE",
            transaction_type="BUY",
            tradingsymbol="WIPRO",
            instrument_token="NSE:WIPRO",
            average_price=400,
            filled_quantity=10,
            product="I",
            source="mobile-app",
        )
    )

    assert await state_manager.get_position("WIPRO") is None


@pytest.mark.asyncio
async def test_mobile_buy_ignored_when_disabled(monkeypatch):
    await state_manager.update_runtime_settings(adopt_mobile_buy_orders=False)

    async def fake_place(order):
        return KiteOrderResult(order_ids=["unexpected"])

    monkeypatch.setattr(kite_client, "place_order", fake_place)

    await exit_engine.on_order_update_event(
        OrderEvent(
            order_id="mobile-buy-2",
            status="COMPLETE",
            transaction_type="BUY",
            tradingsymbol="TCS",
            instrument_token="NSE:TCS",
            average_price=3900,
            filled_quantity=3,
            product="D",
            source="mobile-app",
        )
    )

    assert await state_manager.get_position("TCS") is None
