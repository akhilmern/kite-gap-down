"""order_stream.py — Kite order-update stream.

Uses the Kite Connect portfolio WebSocket (KiteTicker) to receive real-time
order/trade updates.  The kiteconnect library's `KiteTicker` is callback-based
and synchronous internally, so we bridge it into asyncio via
`loop.call_soon_threadsafe`.

Kite sends order updates via `on_order_update(ws, data)` where `data` is a
dict with the full order payload.  We normalise it and forward to exit_engine.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

from execution.exit_engine import exit_engine
from models.state import state_manager
from utils.kite_client import kite_client
from websocket.market_feed import market_feed

logger = logging.getLogger(__name__)


class OrderStream:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop = asyncio.Event()
        await market_feed.restart()
        self._loop = asyncio.get_event_loop()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await market_feed.stop()

    async def _run(self) -> None:
        """
        Kite Connect WebSocket for order/portfolio updates.

        The Kite Connect Python library (`kiteconnect.KiteTicker`) is
        thread-based and callback-driven.  We run it on a background thread
        and dispatch order-update messages back into the asyncio event loop
        via `call_soon_threadsafe`.

        Kite order-update events arrive on `on_order_update(ws, data)` as dicts.
        """
        from config.settings import settings

        backoff = 2
        while not self._stop.is_set():
            if not state_manager.access_token:
                await asyncio.sleep(5)
                continue

            # Import kiteconnect lazily so the app starts without it installed
            # during development (falls back to a plain REST-polling mode).
            try:
                from kiteconnect import KiteTicker  # type: ignore[import]
            except ImportError:
                logger.warning(
                    "kiteconnect package not installed — order stream unavailable. "
                    "Install with: pip install kiteconnect"
                )
                await state_manager.set_ws_active(False)
                await asyncio.sleep(30)
                continue

            loop = self._loop or asyncio.get_event_loop()
            connected_event = asyncio.Event()
            stop_event = asyncio.Event()

            kws = KiteTicker(settings.kite_api_key, state_manager.access_token)

            def on_connect(ws, response):
                logger.info("order_stream_connected")
                loop.call_soon_threadsafe(lambda: asyncio.ensure_future(state_manager.set_ws_active(True)))
                loop.call_soon_threadsafe(connected_event.set)

            def on_close(ws, code, reason):
                logger.warning("order_stream_closed code=%s reason=%s", code, reason)
                loop.call_soon_threadsafe(lambda: asyncio.ensure_future(state_manager.set_ws_active(False)))
                loop.call_soon_threadsafe(stop_event.set)

            def on_error(ws, code, reason):
                logger.error("order_stream_error code=%s reason=%s", code, reason)
                loop.call_soon_threadsafe(stop_event.set)

            def on_order_update(ws, data):
                """Called by KiteTicker on every order/trade update."""
                logger.debug("order_update_raw: %s", data)
                event = kite_client.normalize_order_event(data)
                if event is None:
                    return
                # Schedule coroutine on the asyncio event loop from this thread
                loop.call_soon_threadsafe(
                    lambda e=event: asyncio.ensure_future(exit_engine.on_order_update_event(e))
                )

            kws.on_connect = on_connect
            kws.on_close = on_close
            kws.on_error = on_error
            kws.on_order_update = on_order_update

            # KiteTicker.connect() blocks — run it in a thread
            ticker_thread = threading.Thread(
                target=lambda: kws.connect(threaded=False),
                daemon=True,
            )
            ticker_thread.start()

            # Wait until connected or stop requested
            try:
                await asyncio.wait_for(connected_event.wait(), timeout=30)
                backoff = 2
                # Now wait for stop signal or stream disconnect
                while not self._stop.is_set() and not stop_event.is_set():
                    await asyncio.sleep(1)
            except asyncio.TimeoutError:
                logger.warning("order_stream_connect_timeout")

            # Clean up KiteTicker
            try:
                kws.close()
            except Exception:  # noqa: BLE001
                pass
            await state_manager.set_ws_active(False)

            if self._stop.is_set():
                return

            logger.info("order_stream: reconnecting in %ds", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


order_stream = OrderStream()
