from __future__ import annotations
import asyncio
from typing import Dict, List, Optional, Any
from backend.models.schemas import (
    GapCandidate,
    TrackedPosition,
    PlaceOrdersRequest,
    OrderStatus,
)
from backend.config.settings import get_settings, RuntimeSettings


class StateManager:
    """Singleton runtime state — all data is in-memory."""

    _instance: Optional["StateManager"] = None

    def __new__(cls) -> "StateManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = asyncio.Lock()

        # Auth
        self.access_token: Optional[str] = None
        self.user_id: Optional[str] = None

        # Scan
        self.last_scan_results: List[GapCandidate] = []
        self.last_scan_timestamp: Optional[str] = None

        # Positions
        self.positions: Dict[str, TrackedPosition] = {}          # symbol → position
        self.order_id_to_symbol: Dict[str, str] = {}             # order_id → symbol
        self.instrument_token_to_symbol: Dict[int, str] = {}     # token → symbol

        # Engine
        self.sl_engine_armed: bool = False
        self.ws_active: bool = False
        self.orders_placed_count: int = 0

        # Queue
        self.pending_orders: List[PlaceOrdersRequest] = []

        # Daily dedup flags
        self.fire_watcher_fired_today: bool = False
        self.prev_close_fetched_today: bool = False

        # Runtime settings
        self.runtime_settings: RuntimeSettings = get_settings()

        # Pre-load access token from env if present
        import os
        token = os.getenv("KITE_ACCESS_TOKEN", "")
        if token:
            self.access_token = token

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def set_access_token(self, token: str, user_id: str = "user") -> None:
        async with self._lock:
            self.access_token = token
            self.user_id = user_id

    async def clear_access_token(self) -> None:
        async with self._lock:
            self.access_token = None
            self.user_id = None

    def get_access_token(self) -> Optional[str]:
        return self.access_token

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def set_ws_active(self, active: bool) -> None:
        async with self._lock:
            self.ws_active = active

    # ------------------------------------------------------------------
    # Scan results
    # ------------------------------------------------------------------

    async def set_scan_results(self, results: List[GapCandidate], ts: str) -> None:
        async with self._lock:
            self.last_scan_results = results
            self.last_scan_timestamp = ts

    def get_scan_results(self) -> List[GapCandidate]:
        return self.last_scan_results

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def upsert_position(self, pos: TrackedPosition) -> None:
        async with self._lock:
            self.positions[pos.tradingsymbol] = pos
            if pos.buy_order_id:
                self.order_id_to_symbol[pos.buy_order_id] = pos.tradingsymbol
            if pos.instrument_token:
                self.instrument_token_to_symbol[pos.instrument_token] = pos.tradingsymbol
            # Also track SL and target order IDs
            if pos.sl_order_id:
                self.order_id_to_symbol[pos.sl_order_id] = pos.tradingsymbol
            if pos.target_order_id:
                self.order_id_to_symbol[pos.target_order_id] = pos.tradingsymbol

    def get_position(self, symbol: str) -> Optional[TrackedPosition]:
        return self.positions.get(symbol)

    def get_positions(self) -> Dict[str, TrackedPosition]:
        return dict(self.positions)

    def get_position_by_order_id(self, order_id: str) -> Optional[TrackedPosition]:
        symbol = self.order_id_to_symbol.get(order_id)
        if symbol:
            return self.positions.get(symbol)
        return None

    def get_symbol_by_token(self, token: int) -> Optional[str]:
        return self.instrument_token_to_symbol.get(token)

    # ------------------------------------------------------------------
    # Pending order queue
    # ------------------------------------------------------------------

    async def enqueue_orders(self, req: PlaceOrdersRequest) -> None:
        async with self._lock:
            self.pending_orders.append(req)

    async def pop_pending_orders(self) -> List[PlaceOrdersRequest]:
        async with self._lock:
            orders = list(self.pending_orders)
            self.pending_orders.clear()
            return orders

    # ------------------------------------------------------------------
    # SL engine
    # ------------------------------------------------------------------

    async def arm_sl_engine(self, armed: bool) -> None:
        async with self._lock:
            self.sl_engine_armed = armed

    # ------------------------------------------------------------------
    # Runtime settings
    # ------------------------------------------------------------------

    def get_runtime_settings(self) -> RuntimeSettings:
        return self.runtime_settings

    def update_runtime_settings(self, **kwargs: Any) -> None:
        rs = self.runtime_settings
        for k, v in kwargs.items():
            if hasattr(rs, k) and v is not None:
                setattr(rs, k, v)

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    async def reset_for_day(self) -> None:
        async with self._lock:
            self.positions.clear()
            self.order_id_to_symbol.clear()
            self.instrument_token_to_symbol.clear()
            self.last_scan_results = []
            self.last_scan_timestamp = None
            self.sl_engine_armed = False
            self.orders_placed_count = 0
            self.pending_orders.clear()
            self.fire_watcher_fired_today = False
            self.prev_close_fetched_today = False


state_manager = StateManager()
