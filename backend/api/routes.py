from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Query, Body
from fastapi.responses import JSONResponse

from backend.config.settings import get_settings, write_env_file
from backend.models.schemas import (
    GapCandidate,
    PlaceOrdersRequest,
    ScannerRequest,
    SettingsPayload,
    DirectTokenRequest,
    PreopenDepthRequest,
    OrderStatus,
)
from backend.models.state import state_manager
from backend.utils.kite_client import kite_client
from backend.scanner.gap_scanner import gap_scanner
from backend.execution.buy_executor import queue_or_execute
from backend.execution.backup_poller import backup_poller
from backend.websocket.order_stream import order_stream

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
router = APIRouter()


def _now_ist() -> str:
    return datetime.now(IST).isoformat()


def _seconds_until(hms: str) -> int:
    now = datetime.now(IST)
    h, m, s = (int(x) for x in hms.split(":"))
    target = now.replace(hour=h, minute=m, second=s, microsecond=0)
    diff = (target - now).total_seconds()
    return max(0, int(diff))


# ===========================================================================
# AUTH
# ===========================================================================

@router.get("/auth/login-url")
async def auth_login_url():
    url = kite_client.build_login_url()
    return {"login_url": url}


@router.post("/auth/callback")
async def auth_callback(request_token: str = Query(..., alias="code")):
    rs = get_settings()
    kite_client.access_token = None
    try:
        session = await kite_client.generate_session(request_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}")

    token = session.get("access_token", "")
    user_id = session.get("user_id", "user")
    if not token:
        raise HTTPException(status_code=400, detail="No access_token in response")

    kite_client.access_token = token
    await state_manager.set_access_token(token, user_id)

    if rs.write_env_from_ui:
        write_env_file({"KITE_ACCESS_TOKEN": token})

    return {"status": "authenticated", "user_id": user_id}


@router.post("/auth/direct-token")
async def auth_direct_token(payload: DirectTokenRequest):
    rs = get_settings()
    kite_client.access_token = payload.access_token
    await state_manager.set_access_token(payload.access_token, payload.user_id or "user")
    if rs.write_env_from_ui:
        write_env_file({"KITE_ACCESS_TOKEN": payload.access_token})
    return {"status": "authenticated", "user_id": payload.user_id}


@router.get("/auth/status")
async def auth_status():
    token = state_manager.get_access_token()
    return {
        "authenticated": bool(token),
        "user_id": state_manager.user_id,
        "ws_active": state_manager.ws_active,
    }


@router.post("/auth/start-order-stream")
async def start_order_stream():
    await order_stream.start()
    await backup_poller.start()
    return {"status": "started"}


@router.post("/auth/stop-order-stream")
async def stop_order_stream():
    await order_stream.stop()
    await backup_poller.stop()
    return {"status": "stopped"}


# ===========================================================================
# SCANNER
# ===========================================================================

@router.post("/scanner/run")
async def scanner_run(payload: ScannerRequest = Body(default=ScannerRequest())):
    rs = get_settings()
    # Apply per-request overrides
    if payload.min_gap_down_pct is not None:
        rs.min_gap_down_pct = payload.min_gap_down_pct
    if payload.max_gap_down_pct is not None:
        rs.max_gap_down_pct = payload.max_gap_down_pct
    if payload.min_price is not None:
        rs.min_price = payload.min_price
    if payload.min_volume is not None:
        rs.min_volume = payload.min_volume
    if payload.min_avg_volume_30d is not None:
        rs.min_avg_volume_30d = payload.min_avg_volume_30d
    if payload.min_market_cap is not None:
        rs.min_market_cap = payload.min_market_cap
    if payload.excluded_sectors is not None:
        rs.excluded_sectors = payload.excluded_sectors

    token = state_manager.get_access_token()
    if token:
        kite_client.access_token = token

    results = await gap_scanner.run(rs)
    ts = _now_ist()
    await state_manager.set_scan_results(results, ts)
    return {"candidates": [c.model_dump() for c in results], "count": len(results), "timestamp": ts}


@router.post("/scanner/refresh-universe")
async def scanner_refresh_universe():
    try:
        n = await kite_client.refresh_instruments()
        return {"status": "ok", "instruments_cached": n}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/scanner/filter-intraday")
async def scanner_filter_intraday():
    results = state_manager.get_scan_results()
    filtered = await gap_scanner.filter_intraday(results)
    return {"candidates": [c.model_dump() for c in filtered], "count": len(filtered)}


@router.post("/scanner/fetch-prev-close")
async def scanner_fetch_prev_close():
    token = state_manager.get_access_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    kite_client.access_token = token
    try:
        n = await kite_client.fetch_and_store_prev_close()
        return {"status": "ok", "updated": n}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/scanner/fetch-vol-history")
async def scanner_fetch_vol_history():
    token = state_manager.get_access_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    kite_client.access_token = token
    try:
        n = await kite_client.fetch_and_store_vol_history()
        return {"status": "ok", "updated": n}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/scanner/last-results")
async def scanner_last_results():
    results = state_manager.get_scan_results()
    return {
        "candidates": [c.model_dump() for c in results],
        "count": len(results),
        "timestamp": state_manager.last_scan_timestamp,
    }


@router.post("/scanner/preopen-depth")
async def scanner_preopen_depth(payload: PreopenDepthRequest):
    token = state_manager.get_access_token()
    if token:
        kite_client.access_token = token
    updated = await gap_scanner.fetch_preopen_depth(payload.candidates)
    return {"candidates": [c.model_dump() for c in updated]}


# ===========================================================================
# ORDERS & POSITIONS
# ===========================================================================

@router.post("/orders/place-buy")
async def place_buy(payload: PlaceOrdersRequest):
    token = state_manager.get_access_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        result = await queue_or_execute(payload)
        # Auto-arm engine if orders placed immediately
        if not result.get("queued"):
            await state_manager.arm_sl_engine(True)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/orders/pending-queue")
async def pending_queue():
    pending = state_manager.pending_orders
    count = sum(len(r.items) for r in pending)
    return {"pending_batches": len(pending), "pending_orders_count": count}


@router.get("/positions")
async def get_positions():
    positions = state_manager.get_positions()
    return {"positions": {k: v.model_dump() for k, v in positions.items()}}


@router.get("/positions/{symbol}")
async def get_position(symbol: str):
    pos = state_manager.get_position(symbol.upper())
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return pos.model_dump()


# ===========================================================================
# ENGINE & CONTROL
# ===========================================================================

@router.get("/engine/status")
async def engine_status():
    rs = get_settings()
    positions = state_manager.get_positions()
    open_count = sum(
        1 for p in positions.values()
        if p.buy_status == OrderStatus.COMPLETE and p.exit_leg_filled is None
    )
    return {
        "sl_engine_armed": state_manager.sl_engine_armed,
        "sl_engine_enabled": rs.sl_engine_enabled,
        "ws_active": state_manager.ws_active,
        "open_positions": open_count,
        "total_positions": len(positions),
        "orders_placed_count": state_manager.orders_placed_count,
    }


@router.post("/engine/arm")
async def engine_arm():
    await state_manager.arm_sl_engine(True)
    return {"sl_engine_armed": True}


@router.post("/engine/disarm")
async def engine_disarm():
    await state_manager.arm_sl_engine(False)
    return {"sl_engine_armed": False}


@router.post("/engine/sl-engine/toggle")
async def engine_sl_toggle():
    rs = get_settings()
    rs.sl_engine_enabled = not rs.sl_engine_enabled
    return {"sl_engine_enabled": rs.sl_engine_enabled}


@router.post("/engine/ws/start")
async def engine_ws_start():
    await order_stream.start()
    await backup_poller.start()
    return {"ws_active": True}


@router.post("/engine/ws/stop")
async def engine_ws_stop():
    await order_stream.stop()
    await backup_poller.stop()
    return {"ws_active": False}


@router.get("/engine/config")
async def engine_config():
    rs = get_settings()
    return {
        "sl_engine_enabled": rs.sl_engine_enabled,
        "sl_enabled": rs.sl_enabled,
        "market_sell_sl_enabled": rs.market_sell_sl_enabled,
        "sl_delay_seconds": rs.sl_delay_seconds,
        "default_sl_pct": rs.default_sl_pct,
        "default_target_pct": rs.default_target_pct,
        "scheduled_fire_enabled": rs.scheduled_fire_enabled,
        "scheduled_fire_time": rs.scheduled_fire_time,
        "adopt_mobile_buy_orders": rs.adopt_mobile_buy_orders,
        "disable_backup_poller": rs.disable_backup_poller,
    }


@router.put("/engine/config")
async def engine_config_update(payload: SettingsPayload):
    rs = get_settings()
    updates = payload.model_dump(exclude_none=True)
    state_manager.update_runtime_settings(**updates)
    return {"status": "updated", "config": updates}


# ===========================================================================
# SETTINGS & HEALTH
# ===========================================================================

@router.get("/settings")
async def settings_get():
    rs = get_settings()
    return {
        "min_gap_down_pct": rs.min_gap_down_pct,
        "max_gap_down_pct": rs.max_gap_down_pct,
        "min_price": rs.min_price,
        "min_volume": rs.min_volume,
        "min_avg_volume_30d": rs.min_avg_volume_30d,
        "min_market_cap": rs.min_market_cap,
        "excluded_sectors": rs.excluded_sectors,
        "default_sl_pct": rs.default_sl_pct,
        "default_target_pct": rs.default_target_pct,
        "buy_buffer_pct": rs.buy_buffer_pct,
        "sl_delay_seconds": rs.sl_delay_seconds,
        "poll_interval_ms": rs.poll_interval_ms,
        "max_order_placement_retries": rs.max_order_placement_retries,
        "retry_backoff_ms": rs.retry_backoff_ms,
        "scheduled_fire_time": rs.scheduled_fire_time,
        "scheduled_fire_enabled": rs.scheduled_fire_enabled,
        "adopt_mobile_buy_orders": rs.adopt_mobile_buy_orders,
        "sl_engine_enabled": rs.sl_engine_enabled,
        "sl_enabled": rs.sl_enabled,
        "market_sell_sl_enabled": rs.market_sell_sl_enabled,
        "auto_slice_orders": rs.auto_slice_orders,
        "disable_backup_poller": rs.disable_backup_poller,
        "write_env_from_ui": rs.write_env_from_ui,
    }


@router.put("/settings")
async def settings_update(payload: SettingsPayload):
    rs = get_settings()
    updates = payload.model_dump(exclude_none=True)
    # Handle excluded_sectors list
    if "excluded_sectors" in updates and isinstance(updates["excluded_sectors"], list):
        updates["excluded_sectors"] = updates["excluded_sectors"]
    state_manager.update_runtime_settings(**updates)
    if rs.write_env_from_ui:
        env_updates = {}
        for k, v in updates.items():
            if isinstance(v, list):
                env_updates[k.upper()] = ",".join(str(x) for x in v)
            else:
                env_updates[k.upper()] = str(v)
        write_env_file(env_updates)
    return {"status": "updated"}


@router.get("/health")
async def health():
    return {"status": "ok", "time": _now_ist()}


@router.get("/health/preflight")
async def health_preflight():
    rs = get_settings()
    token = state_manager.get_access_token()
    pending = state_manager.pending_orders
    pending_count = sum(len(r.items) for r in pending)

    return {
        "authenticated": bool(token),
        "ws_active": state_manager.ws_active,
        "sl_engine_armed": state_manager.sl_engine_armed,
        "orders_placed_count": state_manager.orders_placed_count,
        "time_to_scan_seconds": _seconds_until(rs.scan_time),
        "time_to_market_open_seconds": _seconds_until(rs.market_open_time),
        "pending_orders_count": pending_count,
        "last_scan_timestamp": state_manager.last_scan_timestamp,
        "server_time_ist": _now_ist(),
    }


# ===========================================================================
# ORDER POSTBACK (Kite pushes order updates here)
# ===========================================================================

@router.post("/kite/postback")
async def kite_postback(request: Request):
    """Kite order postback endpoint — configure this URL in your Kite app."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    await order_stream.process_postback(data)
    return {"status": "ok"}
