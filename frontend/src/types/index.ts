export type OrderStatus = 'PENDING' | 'OPEN' | 'COMPLETE' | 'REJECTED' | 'CANCELLED' | 'UNKNOWN'
export type LegType = 'STOP_LOSS' | 'TARGET' | null

export interface GapCandidate {
  tradingsymbol: string
  exchange: string
  instrument_token: string
  prev_close: number
  open_price: number
  ltp: number
  gap_pct: number
  volume: number
  avg_volume_20d?: number | null
  volume_spike?: number | null
  avg_volume_30d?: number | null
  market_cap?: number | null
  sector?: string | null
  selected: boolean
  investment_amount?: number | null
  buy_limit_price?: number | null
  sl_pct_override?: number | null
  target_pct_override?: number | null
  use_market_price: boolean
  quantity: number
  scanned_at?: string | null
  // Pre-open depth fields
  preopen_buy_qty?: number | null
  preopen_sell_qty?: number | null
  preopen_buy_pct?: number | null
  preopen_sell_pct?: number | null
}

export interface TrackedPosition {
  tradingsymbol: string
  exchange: string
  instrument_token: string
  quantity_requested: number
  requested_product: string
  active_product: string
  buy_limit_price: number
  use_market_price: boolean
  sl_pct: number
  target_pct: number
  source: string
  order_source: string
  buy_order_id?: string | null
  buy_status: OrderStatus
  filled_quantity: number
  average_fill_price?: number | null
  entry_time?: string | null
  sl_trigger_price?: number | null
  sl_order_id?: string | null
  sl_status: OrderStatus
  sl_placed_at?: string | null
  target_price?: number | null
  target_order_id?: string | null
  target_status: OrderStatus
  exit_leg_filled?: LegType
  market_sell_sl_triggered?: boolean
  error?: string | null
}

export interface ScannerRequest {
  min_gap_down_pct?: number
  max_gap_down_pct?: number
  min_price?: number
  min_volume?: number
  min_avg_volume_30d?: number
  min_market_cap?: number
  excluded_sectors?: string[]
}

export interface PlaceOrderItem {
  tradingsymbol: string
  instrument_token: string
  exchange: string
  investment_amount: number
  buy_limit_price: number
  sl_pct_override?: number | null
  target_pct_override?: number | null
  use_market_price: boolean
}

export interface EngineStatus {
  sl_engine_armed: boolean
  ws_active: boolean
  tracked_positions: number
  now_ist: string
}

export interface AuthStatus {
  authenticated: boolean
  user_id?: string | null
  stream_active: boolean
}

export interface SettingsPayload {
  min_gap_down_pct: number
  max_gap_down_pct: number
  min_price: number
  min_volume: number
  min_avg_volume_30d: number
  min_market_cap: number
  excluded_sectors: string[]
  default_sl_pct: number
  default_target_pct: number
  buy_buffer_pct: number
  poll_interval_ms: number
  sl_delay_seconds: number
  adopt_mobile_buy_orders: boolean
  disable_backup_poller: boolean
  sl_engine_enabled: boolean
  sl_enabled: boolean
  auto_slice_orders: boolean
  market_sell_sl_enabled: boolean
  scheduled_fire_enabled: boolean
  scheduled_fire_time: string
}

export interface PreflightStatus {
  authenticated: boolean
  stream_active: boolean
  orders_placed_count: number
  time_to_next_scan_seconds: number
  time_to_market_open_seconds: number
  pending_orders_count: number
}

export interface LastResultsResponse {
  items: GapCandidate[]
  timestamp?: string | null
}

export interface AlertState {
  type: 'success' | 'error' | 'info'
  message: string
}
