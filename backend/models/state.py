from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from config.settings import IST, settings
from models.schemas import EngineConfig, GapCandidate, PlaceOrdersRequest, TrackedPosition


@dataclass
class RuntimeSettings:
    min_gap_down_pct: float = settings.min_gap_down_pct
    max_gap_down_pct: float = settings.max_gap_down_pct
    min_price: float = settings.min_price
    min_volume: int = settings.min_volume
    min_avg_volume_30d: int = settings.min_avg_volume_30d
    min_market_cap: float = settings.min_market_cap
    excluded_sectors: list[str] = field(default_factory=lambda: list(settings.excluded_sectors))
    default_sl_pct: float = settings.default_sl_pct
    default_target_pct: float = settings.default_target_pct
    buy_buffer_pct: float = settings.buy_buffer_pct
    poll_interval_ms: int = settings.poll_interval_ms
    adopt_mobile_buy_orders: bool = settings.adopt_mobile_buy_orders
    disable_backup_poller: bool = settings.disable_backup_poller
    sl_engine_enabled: bool = settings.sl_engine_enabled
    sl_enabled: bool = settings.sl_enabled
    auto_slice_orders: bool = settings.auto_slice_orders
    sl_delay_seconds: int = settings.sl_delay_seconds
    market_sell_sl_enabled: bool = settings.market_sell_sl_enabled
    max_order_placement_retries: int = settings.max_order_placement_retries
    retry_backoff_ms: int = settings.retry_backoff_ms
    scheduled_fire_enabled: bool = settings.scheduled_fire_enabled
    scheduled_fire_time: str = settings.scheduled_fire_time

    def to_engine_config(self) -> EngineConfig:
        return EngineConfig(
            adopt_mobile_buy_orders=self.adopt_mobile_buy_orders,
            poll_interval_ms=self.poll_interval_ms,
            buy_buffer_pct=self.buy_buffer_pct,
            disable_backup_poller=self.disable_backup_poller,
            sl_engine_enabled=self.sl_engine_enabled,
            default_sl_pct=self.default_sl_pct,
            default_target_pct=self.default_target_pct,
        )


class StateManager:
    def __init__(self) -> None:
        self.last_scan_results: list[GapCandidate] = []
        self.last_scan_timestamp: str | None = None
        self.positions: dict[str, TrackedPosition] = {}
        self.order_id_to_symbol: dict[str, str] = {}
        self.instrument_token_to_symbol: dict[str, str] = {}
        self.sl_engine_armed: bool = False
        self.access_token: str | None = None
        self.user_id: str | None = None
        self.ws_active: bool = False
        self.orders_placed_count: int = 0
        self.runtime_settings = RuntimeSettings()
        self._lock = asyncio.Lock()
        # Orders queued between 9:08–9:14:50, fired at 9:15 by cron
        self.pending_orders: list[PlaceOrdersRequest] = []

    async def reset_for_day(self) -> None:
        async with self._lock:
            self.last_scan_results = []
            self.last_scan_timestamp = None
            self.positions = {}
            self.order_id_to_symbol = {}
            self.instrument_token_to_symbol = {}
            self.sl_engine_armed = False
            self.orders_placed_count = 0
            self.pending_orders = []

    async def enqueue_orders(self, request: PlaceOrdersRequest) -> int:
        """Queue an order request to be fired at market open (9:15)."""
        async with self._lock:
            self.pending_orders.append(request)
            return sum(len(r.items) for r in self.pending_orders)

    async def pop_pending_orders(self) -> list[PlaceOrdersRequest]:
        """Drain and return all queued order requests atomically."""
        async with self._lock:
            pending = list(self.pending_orders)
            self.pending_orders = []
            return pending

    async def get_pending_orders_count(self) -> int:
        async with self._lock:
            return sum(len(r.items) for r in self.pending_orders)

    async def set_access_token(self, access_token: str, user_id: str | None) -> None:
        async with self._lock:
            self.access_token = access_token
            self.user_id = user_id

    async def clear_access_token(self) -> None:
        async with self._lock:
            self.access_token = None
            self.user_id = None
            self.ws_active = False

    async def set_ws_active(self, active: bool) -> None:
        async with self._lock:
            self.ws_active = active

    async def set_scan_results(self, candidates: list[GapCandidate]) -> None:
        async with self._lock:
            self.last_scan_results = candidates
            self.last_scan_timestamp = datetime.now(IST).isoformat()

    async def get_scan_results(self) -> tuple[list[GapCandidate], str | None]:
        async with self._lock:
            return list(self.last_scan_results), self.last_scan_timestamp

    async def upsert_position(self, position: TrackedPosition) -> TrackedPosition:
        async with self._lock:
            self.positions[position.tradingsymbol] = position
            self.instrument_token_to_symbol[position.instrument_token] = position.tradingsymbol
            for order_id in [position.buy_order_id, position.sl_order_id, position.target_order_id]:
                if order_id:
                    self.order_id_to_symbol[order_id] = position.tradingsymbol
            return position

    async def register_order_id(self, order_id: str, symbol: str) -> None:
        async with self._lock:
            self.order_id_to_symbol[order_id] = symbol

    async def increment_orders_placed_count(self) -> None:
        async with self._lock:
            self.orders_placed_count += 1

    async def get_position(self, symbol: str) -> TrackedPosition | None:
        async with self._lock:
            return self.positions.get(symbol)

    async def get_position_by_order_id(self, order_id: str) -> TrackedPosition | None:
        async with self._lock:
            symbol = self.order_id_to_symbol.get(order_id)
            if not symbol:
                return None
            return self.positions.get(symbol)

    async def get_positions(self) -> list[TrackedPosition]:
        async with self._lock:
            return list(self.positions.values())

    async def arm_sl_engine(self, armed: bool) -> None:
        async with self._lock:
            self.sl_engine_armed = armed

    async def update_runtime_settings(self, **kwargs: object) -> EngineConfig:
        async with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.runtime_settings, key):
                    setattr(self.runtime_settings, key, value)
            return self.runtime_settings.to_engine_config()

    async def get_runtime_settings(self) -> RuntimeSettings:
        async with self._lock:
            return RuntimeSettings(
                min_gap_down_pct=self.runtime_settings.min_gap_down_pct,
                max_gap_down_pct=self.runtime_settings.max_gap_down_pct,
                min_price=self.runtime_settings.min_price,
                min_volume=self.runtime_settings.min_volume,
                min_avg_volume_30d=self.runtime_settings.min_avg_volume_30d,
                min_market_cap=self.runtime_settings.min_market_cap,
                excluded_sectors=list(self.runtime_settings.excluded_sectors),
                default_sl_pct=self.runtime_settings.default_sl_pct,
                default_target_pct=self.runtime_settings.default_target_pct,
                buy_buffer_pct=self.runtime_settings.buy_buffer_pct,
                poll_interval_ms=self.runtime_settings.poll_interval_ms,
                adopt_mobile_buy_orders=self.runtime_settings.adopt_mobile_buy_orders,
                disable_backup_poller=self.runtime_settings.disable_backup_poller,
                sl_engine_enabled=self.runtime_settings.sl_engine_enabled,
                sl_enabled=self.runtime_settings.sl_enabled,
                auto_slice_orders=self.runtime_settings.auto_slice_orders,
                sl_delay_seconds=self.runtime_settings.sl_delay_seconds,
                market_sell_sl_enabled=self.runtime_settings.market_sell_sl_enabled,
                max_order_placement_retries=self.runtime_settings.max_order_placement_retries,
                retry_backoff_ms=self.runtime_settings.retry_backoff_ms,
                scheduled_fire_enabled=self.runtime_settings.scheduled_fire_enabled,
                scheduled_fire_time=self.runtime_settings.scheduled_fire_time,
            )


state_manager = StateManager()
