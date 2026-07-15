from __future__ import annotations
from enum import Enum
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

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
    API = "API"
    MOBILE = "MOBILE"
    WEB = "WEB"


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    SL = "SL"
    SLM = "SL-M"


class ProductType(str, Enum):
    MIS = "MIS"   # Intraday
    CNC = "CNC"   # Delivery
    NRML = "NRML"


# ---------------------------------------------------------------------------
# Gap Candidate
# ---------------------------------------------------------------------------

class GapCandidate(BaseModel):
    tradingsymbol: str
    exchange: str = "NSE"
    instrument_token: int = 0

    # Price
    prev_close: float = 0.0
    open_price: float = 0.0
    ltp: float = 0.0
    high: float = 0.0
    low: float = 0.0
    gap_pct: float = 0.0

    # Volume
    volume: int = 0
    avg_volume_20d: Optional[int] = None
    volume_spike: Optional[float] = None

    # Metadata
    market_cap: Optional[str] = None
    sector: Optional[str] = None
    scanned_at: Optional[str] = None

    # Pre-open depth
    preopen_buy_qty: Optional[int] = None
    preopen_sell_qty: Optional[int] = None
    preopen_buy_pct: Optional[float] = None
    preopen_sell_pct: Optional[float] = None

    # UI / per-row editable
    selected: bool = False
    investment_amount: float = 10000.0
    buy_limit_price: Optional[float] = None
    sl_pct_override: Optional[float] = None
    target_pct_override: Optional[float] = None
    use_market_price: bool = False
    quantity: Optional[int] = None


# ---------------------------------------------------------------------------
# Tracked Position
# ---------------------------------------------------------------------------

class TrackedPosition(BaseModel):
    tradingsymbol: str
    exchange: str = "NSE"
    instrument_token: int = 0

    # Buy
    buy_order_id: str = ""
    buy_status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    average_fill_price: float = 0.0
    entry_time: Optional[str] = None

    # Stop-loss
    sl_trigger_price: Optional[float] = None
    sl_order_id: Optional[str] = None
    sl_status: Optional[OrderStatus] = None
    sl_placed_at: Optional[str] = None

    # Target
    target_price: Optional[float] = None
    target_order_id: Optional[str] = None
    target_status: Optional[OrderStatus] = None

    # Exit
    exit_leg_filled: Optional[LegType] = None
    market_sell_sl_triggered: bool = False

    # Metadata
    source: OrderSource = OrderSource.API
    requested_product: str = "MIS"
    active_product: str = "MIS"
    sl_pct: float = 1.0
    target_pct: float = 1.5
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Order Event (normalized, from WebSocket or REST)
# ---------------------------------------------------------------------------

class OrderEvent(BaseModel):
    order_id: str
    status: OrderStatus = OrderStatus.UNKNOWN
    transaction_type: Optional[TransactionType] = None
    tradingsymbol: Optional[str] = None
    instrument_token: Optional[int] = None
    average_price: float = 0.0
    filled_quantity: int = 0
    product: Optional[str] = None
    source: Optional[str] = None
    parent_order_id: Optional[str] = None
    order_type: Optional[str] = None
    status_message: Optional[str] = None
    order_timestamp: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Kite Order Request
# ---------------------------------------------------------------------------

class KiteOrderRequest(BaseModel):
    tradingsymbol: str
    exchange: str = "NSE"
    transaction_type: str = "BUY"
    order_type: str = "LIMIT"
    quantity: int
    product: str = "MIS"
    price: float = 0.0
    trigger_price: Optional[float] = None
    validity: str = "DAY"
    tag: Optional[str] = None
    disclosed_quantity: int = 0
    squareoff: Optional[float] = None
    stoploss: Optional[float] = None
    trailing_stoploss: Optional[float] = None


# ---------------------------------------------------------------------------
# API Request/Response models
# ---------------------------------------------------------------------------

class PlaceOrderItem(BaseModel):
    tradingsymbol: str
    exchange: str = "NSE"
    instrument_token: int = 0
    investment_amount: float = 10000.0
    buy_limit_price: float = 0.0
    use_market_price: bool = False
    sl_pct: float = 1.0
    target_pct: float = 1.5
    quantity: Optional[int] = None


class PlaceOrdersRequest(BaseModel):
    items: List[PlaceOrderItem]


class ScannerRequest(BaseModel):
    min_gap_down_pct: Optional[float] = None
    max_gap_down_pct: Optional[float] = None
    min_price: Optional[float] = None
    min_volume: Optional[int] = None
    min_avg_volume_30d: Optional[int] = None
    min_market_cap: Optional[str] = None
    excluded_sectors: Optional[List[str]] = None


class SettingsPayload(BaseModel):
    min_gap_down_pct: Optional[float] = None
    max_gap_down_pct: Optional[float] = None
    min_price: Optional[float] = None
    min_volume: Optional[int] = None
    min_avg_volume_30d: Optional[int] = None
    min_market_cap: Optional[str] = None
    excluded_sectors: Optional[List[str]] = None
    default_sl_pct: Optional[float] = None
    default_target_pct: Optional[float] = None
    buy_buffer_pct: Optional[float] = None
    sl_delay_seconds: Optional[int] = None
    poll_interval_ms: Optional[int] = None
    max_order_placement_retries: Optional[int] = None
    retry_backoff_ms: Optional[int] = None
    scheduled_fire_time: Optional[str] = None
    scheduled_fire_enabled: Optional[bool] = None
    adopt_mobile_buy_orders: Optional[bool] = None
    sl_engine_enabled: Optional[bool] = None
    sl_enabled: Optional[bool] = None
    market_sell_sl_enabled: Optional[bool] = None
    auto_slice_orders: Optional[bool] = None
    disable_backup_poller: Optional[bool] = None
    write_env_from_ui: Optional[bool] = None


class DirectTokenRequest(BaseModel):
    access_token: str
    user_id: Optional[str] = "user"


class PreopenDepthRequest(BaseModel):
    candidates: List[GapCandidate]
