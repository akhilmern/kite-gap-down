from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
IST = ZoneInfo("Asia/Kolkata")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Gap-Down Fill Trading System"
    api_prefix: str = "/api"
    host: str = "0.0.0.0"
    port: int = 6666
    cors_origins: list[str] = [
        "http://localhost:5555",
        "http://127.0.0.1:5555",
    ]

    # Kite Connect credentials
    kite_api_key: str = Field(default="", alias="KITE_API_KEY")
    kite_api_secret: str = Field(default="", alias="KITE_API_SECRET")
    kite_access_token: str = Field(default="", alias="KITE_ACCESS_TOKEN")
    kite_redirect_uri: str = Field(default="", alias="KITE_REDIRECT_URI")
    frontend_base_url: str = Field(default="http://localhost:5555", alias="FRONTEND_BASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    scan_time: str = "09:08:00"
    buy_window_end: str = "09:14:50"
    sl_engine_arm_time: str = "09:14:55"
    market_open_time: str = "09:15:00"
    sl_engine_disarm_time: str = "09:20:00"
    scheduled_fire_enabled: bool = Field(default=True, alias="SCHEDULED_FIRE_ENABLED")
    scheduled_fire_time: str = Field(default="09:15:01", alias="SCHEDULED_FIRE_TIME")

    min_gap_down_pct: float = -2.0
    max_gap_down_pct: float = -15.0
    min_price: float = 100.0
    min_volume: int = 20000
    min_avg_volume_30d: int = 20000
    min_market_cap: float = 2_000_000_000
    excluded_sectors: list[str] = ["Health"]

    default_sl_pct: float = 1.0
    default_target_pct: float = 1.5
    buy_buffer_pct: float = 0.25
    poll_interval_ms: int = 10_000
    max_order_placement_retries: int = 4
    retry_backoff_ms: int = 300
    scanner_batch_size: int = 200
    scanner_concurrency: int = 3
    scanner_timeout_seconds: float = 15.0
    scanner_retries: int = 3
    order_status_poll_seconds: float = 2.5
    positions_poll_seconds: float = 2.5
    adopt_mobile_buy_orders: bool = True
    disable_backup_poller: bool = False
    sl_engine_enabled: bool = True
    sl_enabled: bool = True
    auto_slice_orders: bool = True
    sl_delay_seconds: int = 45
    market_sell_sl_enabled: bool = False
    write_env_from_ui: bool = True


settings = AppSettings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
