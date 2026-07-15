from __future__ import annotations

from enum import Enum
from math import floor
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class LegType(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"


class OrderSource(str, Enum):
    API = "api"
    MOBILE = "mobile"
    WEB = "web"


class GapCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tradingsymbol: str
    exchange: str = "NSE_EQ"
    instrument_token: str
    prev_close: float
    open_price: float
    ltp: float
    gap_pct: float
    volume: int = 0
    avg_volume_20d: int | None = None
    volume_spike: float | None = None
    avg_volume_30d: int | None = None
    market_cap: float | None = None
    sector: str | None = None
    selected: bool = False
    investment_amount: float | None = None
    buy_limit_price: float | None = None
    sl_pct_override: float | None = None
    target_pct_override: float | None = None
    use_market_price: bool = False
    scanned_at: str | None = None
    # Pre-open depth (populated by /scanner/preopen-depth)
    preopen_buy_qty: int | None = None
    preopen_sell_qty: int | None = None
    preopen_buy_pct: float | None = None
    preopen_sell_pct: float | None = None

    @computed_field
    @property
    def quantity(self) -> int:
        if not self.investment_amount or not self.buy_limit_price or self.buy_limit_price <= 0:
            return 0
        return max(1, floor(self.investment_amount / self.buy_limit_price))


class TrackedPosition(BaseModel):
    tradingsymbol: str
    exchange: str = "NSE_EQ"
    instrument_token: str
    quantity_requested: int
    requested_product: str = "I"
    active_product: str = "I"
    buy_limit_price: float
    use_market_price: bool = False
    sl_pct: float
    target_pct: float
    source: str = OrderSource.API.value
    order_source: str = OrderSource.API.value

    buy_order_id: str | None = None
    buy_status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    average_fill_price: float | None = None
    entry_time: str | None = None

    sl_trigger_price: float | None = None
    sl_order_id: str | None = None
    sl_status: OrderStatus = OrderStatus.PENDING
    sl_placed_at: str | None = None

    target_price: float | None = None
    target_order_id: str | None = None
    target_status: OrderStatus = OrderStatus.PENDING

    exit_leg_filled: LegType | None = None
    market_sell_sl_triggered: bool = False
    error: str | None = None

    def precompute_exit_prices(self) -> None:
        if self.average_fill_price is None:
            return
        self.sl_trigger_price = round(self.average_fill_price * (1 - self.sl_pct / 100), 2)
        self.target_price = round(self.average_fill_price * (1 + self.target_pct / 100), 2)


class ScannerRequest(BaseModel):
    min_gap_down_pct: float | None = None
    max_gap_down_pct: float | None = None
    min_price: float | None = None
    min_volume: int | None = None
    min_avg_volume_30d: int | None = None
    min_market_cap: float | None = None
    excluded_sectors: list[str] | None = None


class PlaceOrderItem(BaseModel):
    tradingsymbol: str
    instrument_token: str
    exchange: str = "NSE_EQ"
    investment_amount: float
    buy_limit_price: float
    sl_pct_override: float | None = None
    target_pct_override: float | None = None
    use_market_price: bool = False

    @computed_field
    @property
    def quantity(self) -> int:
        base_price = self.buy_limit_price
        if base_price <= 0:
            return 1
        return max(1, floor(self.investment_amount / base_price))


class PlaceOrdersRequest(BaseModel):
    items: list[PlaceOrderItem]


class AuthStatusResponse(BaseModel):
    authenticated: bool
    user_id: str | None = None
    stream_active: bool = False


class EngineConfig(BaseModel):
    adopt_mobile_buy_orders: bool
    poll_interval_ms: int
    buy_buffer_pct: float
    disable_backup_poller: bool
    sl_engine_enabled: bool
    default_sl_pct: float
    default_target_pct: float


class EngineStatusResponse(BaseModel):
    sl_engine_armed: bool
    ws_active: bool
    tracked_positions: int
    now_ist: str


class HealthResponse(BaseModel):
    status: str = "ok"


class PreflightResponse(BaseModel):
    authenticated: bool
    stream_active: bool
    orders_placed_count: int
    time_to_next_scan_seconds: int
    time_to_market_open_seconds: int
    pending_orders_count: int


class SettingsPayload(BaseModel):
    min_gap_down_pct: float
    max_gap_down_pct: float
    min_price: float
    min_volume: int
    min_avg_volume_30d: int
    min_market_cap: float
    excluded_sectors: list[str]
    default_sl_pct: float
    default_target_pct: float
    buy_buffer_pct: float
    poll_interval_ms: int
    adopt_mobile_buy_orders: bool
    disable_backup_poller: bool
    sl_engine_enabled: bool
    sl_enabled: bool
    auto_slice_orders: bool
    sl_delay_seconds: int
    market_sell_sl_enabled: bool
    scheduled_fire_enabled: bool
    scheduled_fire_time: str


class OAuthCallbackResponse(BaseModel):
    authenticated: bool
    user_id: str | None = None
    access_token_present: bool


class DirectTokenPayload(BaseModel):
    access_token: str
    user_id: str | None = None


class KiteOrderRequest(BaseModel):
    """Order request for the Kite Connect API."""
    quantity: int
    product: str                   # MIS, CNC, NRML
    validity: str = "DAY"
    price: float = 0
    tag: str | None = None
    tradingsymbol: str             # e.g. "SBIN"
    exchange: str = "NSE"
    instrument_token: str          # "NSE:SBIN" — used for state lookup only
    order_type: str                # MARKET, LIMIT, SL, SL-M
    transaction_type: str          # BUY, SELL
    disclosed_quantity: int = 0
    trigger_price: float = 0
    variety: str = "regular"       # regular, amo, co, iceberg


class KiteOrderResult(BaseModel):
    order_ids: list[str] = Field(default_factory=list)
    latency_ms: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OrderEvent(BaseModel):
    order_id: str
    status: str
    transaction_type: str | None = None
    tradingsymbol: str | None = None
    instrument_token: str | None = None
    average_price: float | None = None
    filled_quantity: int | None = None
    product: str | None = None
    source: str | None = None
    parent_order_id: str | None = None
    order_type: str | None = None
    status_message: str | None = None
    order_timestamp: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
