from __future__ import annotations

from datetime import datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Query

from config.settings import IST
from execution.backup_poller import backup_poller
from execution.buy_executor import buy_executor
from models.schemas import (
    AuthStatusResponse,
    EngineConfig,
    EngineStatusResponse,
    HealthResponse,
    OAuthCallbackResponse,
    PlaceOrdersRequest,
    PreflightResponse,
    ScannerRequest,
    SettingsPayload,
)
from models.state import state_manager
from scanner.gap_scanner import gap_scanner
from utils.kite_client import kite_client
from websocket.order_stream import order_stream

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


def _parse_fire_time(t: str) -> time:
    """Parse HH:MM:SS string to a time object, fallback to 09:15:01."""
    try:
        parts = t.strip().split(":")
        return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    except Exception:
        return time(9, 15, 1)


@router.get("/health/preflight", response_model=PreflightResponse)
async def preflight() -> PreflightResponse:
    next_scan = _next_scan_time()
    now = datetime.now(IST)
    runtime = await state_manager.get_runtime_settings()
    fire_t = _parse_fire_time(runtime.scheduled_fire_time)
    fire_dt = now.replace(hour=fire_t.hour, minute=fire_t.minute, second=fire_t.second, microsecond=0)
    time_to_fire = max(int((fire_dt - now).total_seconds()), 0) if now.time() < fire_t else 0
    pending_count = await state_manager.get_pending_orders_count()
    return PreflightResponse(
        authenticated=bool(state_manager.access_token),
        stream_active=state_manager.ws_active,
        orders_placed_count=state_manager.orders_placed_count,
        time_to_next_scan_seconds=max(int((next_scan - now).total_seconds()), 0),
        time_to_market_open_seconds=time_to_fire,
        pending_orders_count=pending_count,
    )


@router.get("/auth/login-url")
async def get_login_url() -> dict[str, str]:
    """Return the Kite Connect login URL to redirect the user to."""
    return {"url": kite_client.build_login_url()}


@router.post("/auth/callback", response_model=OAuthCallbackResponse)
async def auth_callback(code: str = Query(...)) -> OAuthCallbackResponse:
    """
    Exchange the Kite request_token (passed as `code` query param for API
    compatibility) for an access_token.
    """
    session_data = await kite_client.exchange_code_for_token(code)
    access_token = session_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Access token was not returned by Kite")
    await state_manager.set_access_token(access_token, None)
    profile = await kite_client.get_profile()
    user_id = profile.get("user_id") or profile.get("user_name") or profile.get("email")
    await state_manager.set_access_token(access_token, user_id)
    await kite_client.write_env_settings({"KITE_ACCESS_TOKEN": access_token})
    return OAuthCallbackResponse(authenticated=True, user_id=user_id, access_token_present=True)


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status() -> AuthStatusResponse:
    return AuthStatusResponse(
        authenticated=bool(state_manager.access_token),
        user_id=state_manager.user_id,
        stream_active=state_manager.ws_active,
    )


@router.post("/auth/start-order-stream")
async def start_order_stream() -> dict[str, bool]:
    if not state_manager.access_token:
        raise HTTPException(status_code=400, detail="Authenticate first")
    await order_stream.start()
    return {"started": True}


@router.post("/auth/stop-order-stream")
async def stop_order_stream() -> dict[str, bool]:
    await order_stream.stop()
    return {"stopped": True}


@router.post("/scanner/run")
async def run_scanner(request: ScannerRequest) -> list[dict]:
    results = await gap_scanner.run(request)
    return [item.model_dump() for item in results]


@router.post("/scanner/refresh-universe")
async def refresh_universe() -> dict[str, int]:
    count = await gap_scanner.refresh_universe()
    return {"count": count}


@router.post("/scanner/filter-intraday")
async def filter_intraday() -> dict[str, int]:
    """Fetch live Kite instrument master and keep only intraday-eligible (EQ, NSE) stocks."""
    instruments = await kite_client.fetch_and_filter_intraday_eligible()
    return {"count": len(instruments)}


@router.post("/scanner/fetch-prev-close")
async def fetch_prev_close() -> dict[str, int]:
    if not state_manager.access_token:
        raise HTTPException(status_code=400, detail="Authenticate first")
    updated = await kite_client.fetch_and_store_prev_close()
    return {"updated": updated}


@router.post("/scanner/fetch-vol-history")
async def fetch_vol_history() -> dict[str, int]:
    if not state_manager.access_token:
        raise HTTPException(status_code=400, detail="Authenticate first")
    updated = await kite_client.fetch_and_store_vol_history()
    return {"updated": updated}


@router.get("/scanner/last-results")
async def last_results() -> dict[str, object]:
    results, timestamp = await state_manager.get_scan_results()
    return {"items": [item.model_dump() for item in results], "timestamp": timestamp}


@router.post("/scanner/preopen-depth")
async def fetch_preopen_depth() -> dict[str, object]:
    """
    Fetch full market quotes (depth) for the current scan candidates and return
    buy/sell quantity percentages per instrument.  Call this during 9:08–9:15
    to see pre-open order book imbalance before placing buy orders.

    Also patches the persisted scan results in state so the frontend's
    last-results endpoint returns the enriched data immediately.
    """
    if not state_manager.access_token:
        raise HTTPException(status_code=400, detail="Authenticate first")

    candidates, timestamp = await state_manager.get_scan_results()
    if not candidates:
        return {"items": [], "timestamp": timestamp}

    # Kite full-quote accepts up to 500 instrument keys per call
    all_keys = [c.instrument_token for c in candidates]
    batch_size = 500
    batches = [all_keys[i: i + batch_size] for i in range(0, len(all_keys), batch_size)]

    raw: dict[str, object] = {}
    for batch in batches:
        chunk = await kite_client.get_full_quotes(batch)
        raw.update(chunk)

    # Kite returns keys as "NSE:SYMBOL" matching our instrument_token format
    enriched: list[object] = []
    for candidate in candidates:
        quote = raw.get(candidate.instrument_token)
        if not isinstance(quote, dict):
            enriched.append(candidate)
            continue

        depth = quote.get("depth") or {}
        buy_levels  = depth.get("buy")  or []
        sell_levels = depth.get("sell") or []
        buy_qty  = sum(int(lvl.get("quantity", 0)) for lvl in buy_levels)
        sell_qty = sum(int(lvl.get("quantity", 0)) for lvl in sell_levels)
        total = buy_qty + sell_qty
        buy_pct  = round(buy_qty  / total * 100, 1) if total else None
        sell_pct = round(sell_qty / total * 100, 1) if total else None

        enriched.append(
            candidate.model_copy(update={
                "preopen_buy_qty":  buy_qty  or None,
                "preopen_sell_qty": sell_qty or None,
                "preopen_buy_pct":  buy_pct,
                "preopen_sell_pct": sell_pct,
            })
        )

    # Persist the enriched list back into state so last-results reflects it
    await state_manager.set_scan_results(enriched)  # type: ignore[arg-type]
    return {"items": [c.model_dump() if hasattr(c, "model_dump") else c for c in enriched], "timestamp": timestamp}


@router.post("/orders/place-buy")
async def place_buy_orders(request: PlaceOrdersRequest) -> list[dict]:
    if not state_manager.access_token:
        raise HTTPException(status_code=400, detail="Authenticate first")
    positions = await buy_executor.place_buy_orders(request)
    return [position.model_dump() for position in positions]


@router.get("/orders/pending-queue")
async def get_pending_queue() -> dict:
    """Returns the list of order items sitting in the pre-market queue (read-only)."""
    async with state_manager._lock:
        items = [item.model_dump() for req in state_manager.pending_orders for item in req.items]
    return {"count": len(items), "items": items}


@router.get("/positions")
async def get_positions() -> list[dict]:
    return [item.model_dump() for item in await state_manager.get_positions()]


@router.get("/positions/{symbol}")
async def get_position(symbol: str) -> dict:
    position = await state_manager.get_position(symbol)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    return position.model_dump()


@router.get("/engine/status", response_model=EngineStatusResponse)
async def engine_status() -> EngineStatusResponse:
    return EngineStatusResponse(
        sl_engine_armed=state_manager.sl_engine_armed,
        ws_active=state_manager.ws_active,
        tracked_positions=len(await state_manager.get_positions()),
        now_ist=datetime.now(IST).isoformat(),
    )


@router.post("/engine/arm")
async def arm_engine() -> dict[str, bool]:
    await state_manager.arm_sl_engine(True)
    await backup_poller.start()
    return {"armed": True}


@router.post("/engine/disarm")
async def disarm_engine() -> dict[str, bool]:
    await state_manager.arm_sl_engine(False)
    return {"armed": False}


@router.post("/engine/sl-engine/toggle")
async def toggle_sl_engine(payload: dict[str, bool]) -> dict[str, bool]:
    enabled = payload.get("enabled", True)
    await state_manager.update_runtime_settings(sl_engine_enabled=enabled)
    return {"sl_engine_enabled": enabled}


@router.post("/engine/ws/start")
async def ws_start() -> dict[str, bool]:
    if not state_manager.access_token:
        raise HTTPException(status_code=400, detail="Authenticate first")
    await order_stream.start()
    return {"started": True}


@router.post("/engine/ws/stop")
async def ws_stop() -> dict[str, bool]:
    await order_stream.stop()
    return {"stopped": True}


@router.get("/engine/config", response_model=EngineConfig)
async def get_engine_config() -> EngineConfig:
    return (await state_manager.get_runtime_settings()).to_engine_config()


@router.put("/engine/config", response_model=EngineConfig)
async def update_engine_config(payload: dict[str, object]) -> EngineConfig:
    runtime = await state_manager.update_runtime_settings(**payload)
    updated = await state_manager.get_runtime_settings()
    await kite_client.write_env_settings(
        {
            "ADOPT_MOBILE_BUY_ORDERS": updated.adopt_mobile_buy_orders,
            "DISABLE_BACKUP_POLLER": updated.disable_backup_poller,
            "SL_ENGINE_ENABLED": updated.sl_engine_enabled,
            "BUY_BUFFER_PCT": updated.buy_buffer_pct,
            "POLL_INTERVAL_MS": updated.poll_interval_ms,
        }
    )
    return runtime


@router.get("/settings")
async def get_settings() -> dict:
    runtime = await state_manager.get_runtime_settings()
    return SettingsPayload(
        min_gap_down_pct=runtime.min_gap_down_pct,
        max_gap_down_pct=runtime.max_gap_down_pct,
        min_price=runtime.min_price,
        min_volume=runtime.min_volume,
        min_avg_volume_30d=runtime.min_avg_volume_30d,
        min_market_cap=runtime.min_market_cap,
        excluded_sectors=runtime.excluded_sectors,
        default_sl_pct=runtime.default_sl_pct,
        default_target_pct=runtime.default_target_pct,
        buy_buffer_pct=runtime.buy_buffer_pct,
        poll_interval_ms=runtime.poll_interval_ms,
        adopt_mobile_buy_orders=runtime.adopt_mobile_buy_orders,
        disable_backup_poller=runtime.disable_backup_poller,
        sl_engine_enabled=runtime.sl_engine_enabled,
        sl_enabled=runtime.sl_enabled,
        auto_slice_orders=runtime.auto_slice_orders,
        sl_delay_seconds=runtime.sl_delay_seconds,
        market_sell_sl_enabled=runtime.market_sell_sl_enabled,
        scheduled_fire_enabled=runtime.scheduled_fire_enabled,
        scheduled_fire_time=runtime.scheduled_fire_time,
    ).model_dump()


@router.put("/settings")
async def update_settings(payload: SettingsPayload) -> dict:
    await state_manager.update_runtime_settings(**payload.model_dump())
    await kite_client.write_env_settings(
        {
            "MIN_GAP_DOWN_PCT": payload.min_gap_down_pct,
            "MAX_GAP_DOWN_PCT": payload.max_gap_down_pct,
            "MIN_PRICE": payload.min_price,
            "MIN_VOLUME": payload.min_volume,
            "MIN_AVG_VOLUME_30D": payload.min_avg_volume_30d,
            "MIN_MARKET_CAP": payload.min_market_cap,
            "EXCLUDED_SECTORS": payload.excluded_sectors,
            "DEFAULT_SL_PCT": payload.default_sl_pct,
            "DEFAULT_TARGET_PCT": payload.default_target_pct,
            "BUY_BUFFER_PCT": payload.buy_buffer_pct,
            "POLL_INTERVAL_MS": payload.poll_interval_ms,
            "ADOPT_MOBILE_BUY_ORDERS": payload.adopt_mobile_buy_orders,
            "DISABLE_BACKUP_POLLER": payload.disable_backup_poller,
            "SL_ENGINE_ENABLED": payload.sl_engine_enabled,
            "SL_ENABLED": payload.sl_enabled,
            "AUTO_SLICE_ORDERS": payload.auto_slice_orders,
            "SL_DELAY_SECONDS": payload.sl_delay_seconds,
            "MARKET_SELL_SL_ENABLED": payload.market_sell_sl_enabled,
            "SCHEDULED_FIRE_ENABLED": payload.scheduled_fire_enabled,
            "SCHEDULED_FIRE_TIME": payload.scheduled_fire_time,
        }
    )
    return {"saved": True}


def _next_scan_time() -> datetime:
    now = datetime.now(IST)
    scan = datetime.combine(now.date(), time(9, 8, 0), tzinfo=IST)
    if now >= scan:
        scan += timedelta(days=1)
    return scan
