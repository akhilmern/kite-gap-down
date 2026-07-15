export type OrderStatus = 'PENDING' | 'OPEN' | 'COMPLETE' | 'REJECTED' | 'CANCELLED' | 'UNKNOWN'
export type LegType = 'STOP_LOSS' | 'TARGET'
export type OrderSource = 'API' | 'MOBILE' | 'WEB'

export interface GapCandidate {
  tradingsymbol: string
  exchange: string
  instrument_token: number
  prev_close: number
  open_price: number
  ltp: number
  high: number
  low: number
  gap_pct: number
  volume: number
  avg_volume_20d: number | null
  volume_spike: number | null
  market_cap: string | null
  sector: string | null
  scanned_at: string | null
  preopen_buy_qty: number | null
  preopen_sell_qty: number | null
  preopen_buy_pct: number | null
  preopen_sell_pct: number | null
  selected: boolean
  investment_amount: number
  buy_limit_price: number | null
  sl_pct_override: number | null
  target_pct_override: number | null
  use_market_price: boolean
  quantity: number | null
}

export interface TrackedPosition {
  tradingsymbol: string
  exchange: string
  instrument_token: number
  buy_order_id: string
  buy_status: OrderStatus
  filled_quantity: number
  average_fill_price: number
  entry_time: string | null
  sl_trigger_price: number | null
  sl_order_id: string | null
  sl_status: OrderStatus | null
  sl_placed_at: string | null
  target_price: number | null
  target_order_id: string | null
  target_status: OrderStatus | null
  exit_leg_filled: LegType | null
  market_sell_sl_triggered: boolean
  source: OrderSource
  requested_product: string
  active_product: string
  sl_pct: number
  target_pct: number
  error: string | null
}

export interface AuthStatus {
  authenticated: boolean
  user_id: string | null
  ws_active: boolean
}

export interface EngineStatus {
  sl_engine_armed: boolean
  sl_engine_enabled: boolean
  ws_active: boolean
  open_positions: number
  total_positions: number
  orders_placed_count: number
}

export interface PreflightData {
  authenticated: boolean
  ws_active: boolean
  sl_engine_armed: boolean
  orders_placed_count: number
  time_to_scan_seconds: number
  time_to_market_open_seconds: number
  pending_orders_count: number
  last_scan_timestamp: string | null
  server_time_ist: string
}

export interface AppSettings {
  min_gap_down_pct: number
  max_gap_down_pct: number
  min_price: number
  min_volume: number
  min_avg_volume_30d: number
  min_market_cap: string
  excluded_sectors: string[]
  default_sl_pct: number
  default_target_pct: number
  buy_buffer_pct: number
  sl_delay_seconds: number
  poll_interval_ms: number
  max_order_placement_retries: number
  retry_backoff_ms: number
  scheduled_fire_time: string
  scheduled_fire_enabled: boolean
  adopt_mobile_buy_orders: boolean
  sl_engine_enabled: boolean
  sl_enabled: boolean
  market_sell_sl_enabled: boolean
  auto_slice_orders: boolean
  disable_backup_poller: boolean
  write_env_from_ui: boolean
}

export interface PlaceOrderItem {
  tradingsymbol: string
  exchange: string
  instrument_token: number
  investment_amount: number
  buy_limit_price: number
  use_market_price: boolean
  sl_pct: number
  target_pct: number
  quantity?: number
}

export interface ScanResult {
  candidates: GapCandidate[]
  count: number
  timestamp: string
}
