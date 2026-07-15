from __future__ import annotations
import os
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Kite Connect Auth ---
    KITE_API_KEY: str = "ho9u08e1kpez1dhw"
    KITE_API_SECRET: str = "08s8vmurbseywsg2nntug0j11usb743q"
    KITE_REDIRECT_URI: str = "http://localhost:6666/api/auth/callback"
    KITE_ACCESS_TOKEN: Optional[str] = None

    # --- API Base ---
    KITE_API_BASE: str = "https://api.kite.trade"

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 6666
    LOG_LEVEL: str = "INFO"
    FRONTEND_BASE_URL: str = "http://localhost:5555"

    # --- Scanner / Gap Filters ---
    MIN_GAP_DOWN_PCT: float = -2.0
    MAX_GAP_DOWN_PCT: float = -15.0
    MIN_PRICE: float = 100.0
    MIN_VOLUME: int = 20000
    MIN_AVG_VOLUME_30D: int = 20000
    MIN_MARKET_CAP: str = "2B"
    EXCLUDED_SECTORS: str = "Health"

    # --- Execution ---
    DEFAULT_SL_PCT: float = 1.0
    DEFAULT_TARGET_PCT: float = 1.5
    BUY_BUFFER_PCT: float = 0.25
    SL_DELAY_SECONDS: int = 45
    POLL_INTERVAL_MS: int = 10000
    MAX_ORDER_PLACEMENT_RETRIES: int = 4
    RETRY_BACKOFF_MS: int = 300

    # --- Timing (IST) ---
    SCAN_TIME: str = "09:08:00"
    BUY_WINDOW_END: str = "09:14:50"
    SL_ENGINE_ARM_TIME: str = "09:14:55"
    MARKET_OPEN_TIME: str = "09:15:00"
    SL_ENGINE_DISARM_TIME: str = "09:20:00"
    SCHEDULED_FIRE_TIME: str = "09:15:01"

    # --- Feature Flags ---
    SCHEDULED_FIRE_ENABLED: bool = True
    ADOPT_MOBILE_BUY_ORDERS: bool = True
    SL_ENGINE_ENABLED: bool = True
    SL_ENABLED: bool = True
    MARKET_SELL_SL_ENABLED: bool = False
    AUTO_SLICE_ORDERS: bool = True
    DISABLE_BACKUP_POLLER: bool = False
    WRITE_ENV_FROM_UI: bool = True


# --- Runtime settings (mutable, not pydantic-settings) ---
class RuntimeSettings:
    """Mutable copy of settings used at runtime; can be updated without restart."""

    def __init__(self, s: Settings):
        self.kite_api_key: str = s.KITE_API_KEY
        self.kite_api_secret: str = s.KITE_API_SECRET
        self.kite_redirect_uri: str = s.KITE_REDIRECT_URI
        self.kite_api_base: str = s.KITE_API_BASE

        self.min_gap_down_pct: float = s.MIN_GAP_DOWN_PCT
        self.max_gap_down_pct: float = s.MAX_GAP_DOWN_PCT
        self.min_price: float = s.MIN_PRICE
        self.min_volume: int = s.MIN_VOLUME
        self.min_avg_volume_30d: int = s.MIN_AVG_VOLUME_30D
        self.min_market_cap: str = s.MIN_MARKET_CAP
        self.excluded_sectors: List[str] = [
            x.strip() for x in s.EXCLUDED_SECTORS.split(",") if x.strip()
        ]

        self.default_sl_pct: float = s.DEFAULT_SL_PCT
        self.default_target_pct: float = s.DEFAULT_TARGET_PCT
        self.buy_buffer_pct: float = s.BUY_BUFFER_PCT
        self.sl_delay_seconds: int = s.SL_DELAY_SECONDS
        self.poll_interval_ms: int = s.POLL_INTERVAL_MS
        self.max_order_placement_retries: int = s.MAX_ORDER_PLACEMENT_RETRIES
        self.retry_backoff_ms: int = s.RETRY_BACKOFF_MS

        self.scan_time: str = s.SCAN_TIME
        self.buy_window_end: str = s.BUY_WINDOW_END
        self.sl_engine_arm_time: str = s.SL_ENGINE_ARM_TIME
        self.market_open_time: str = s.MARKET_OPEN_TIME
        self.sl_engine_disarm_time: str = s.SL_ENGINE_DISARM_TIME
        self.scheduled_fire_time: str = s.SCHEDULED_FIRE_TIME

        self.scheduled_fire_enabled: bool = s.SCHEDULED_FIRE_ENABLED
        self.adopt_mobile_buy_orders: bool = s.ADOPT_MOBILE_BUY_ORDERS
        self.sl_engine_enabled: bool = s.SL_ENGINE_ENABLED
        self.sl_enabled: bool = s.SL_ENABLED
        self.market_sell_sl_enabled: bool = s.MARKET_SELL_SL_ENABLED
        self.auto_slice_orders: bool = s.AUTO_SLICE_ORDERS
        self.disable_backup_poller: bool = s.DISABLE_BACKUP_POLLER
        self.write_env_from_ui: bool = s.WRITE_ENV_FROM_UI

        self.host: str = s.HOST
        self.port: int = s.PORT
        self.log_level: str = s.LOG_LEVEL
        self.frontend_base_url: str = s.FRONTEND_BASE_URL


_base_settings = Settings()
runtime_settings = RuntimeSettings(_base_settings)


def get_settings() -> RuntimeSettings:
    return runtime_settings


def write_env_file(updates: dict) -> None:
    """Persist updated settings back to .env file."""
    env_path = ".env"
    existing: dict[str, str] = {}
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    existing[k.strip().upper()] = v.strip()
    existing.update({k.upper(): str(v) for k, v in updates.items()})
    with open(env_path, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
