import axios from 'axios'
import type {
  GapCandidate, AppSettings, PlaceOrderItem, AuthStatus,
  EngineStatus, PreflightData, ScanResult, TrackedPosition
} from '../types'

const BASE = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_BASE ?? '/api'

export const api = axios.create({ baseURL: BASE, timeout: 30000 })

// Auth
export const getLoginUrl = () => api.get<{ login_url: string }>('/auth/login-url')
export const postAuthCallback = (code: string) => api.post(`/auth/callback?code=${code}`)
export const postDirectToken = (token: string, userId?: string) =>
  api.post('/auth/direct-token', { access_token: token, user_id: userId ?? 'user' })
export const getAuthStatus = () => api.get<AuthStatus>('/auth/status')
export const startOrderStream = () => api.post('/auth/start-order-stream')
export const stopOrderStream = () => api.post('/auth/stop-order-stream')

// Scanner
export const runScanner = (overrides?: Partial<AppSettings>) => api.post<ScanResult>('/scanner/run', overrides ?? {})
export const refreshUniverse = () => api.post('/scanner/refresh-universe')
export const filterIntraday = () => api.post('/scanner/filter-intraday')
export const fetchPrevClose = () => api.post('/scanner/fetch-prev-close')
export const fetchVolHistory = () => api.post('/scanner/fetch-vol-history')
export const getLastResults = () => api.get<ScanResult>('/scanner/last-results')
export const fetchPreopenDepth = (candidates: GapCandidate[]) =>
  api.post<{ candidates: GapCandidate[] }>('/scanner/preopen-depth', { candidates })

// Orders & Positions
export const placeBuyOrders = (items: PlaceOrderItem[]) =>
  api.post('/orders/place-buy', { items })
export const getPendingQueue = () => api.get('/orders/pending-queue')
export const getPositions = () =>
  api.get<{ positions: Record<string, TrackedPosition> }>('/positions')
export const getPosition = (symbol: string) => api.get<TrackedPosition>(`/positions/${symbol}`)

// Engine
export const getEngineStatus = () => api.get<EngineStatus>('/engine/status')
export const armEngine = () => api.post('/engine/arm')
export const disarmEngine = () => api.post('/engine/disarm')
export const toggleSlEngine = () => api.post('/engine/sl-engine/toggle')
export const startWs = () => api.post('/engine/ws/start')
export const stopWs = () => api.post('/engine/ws/stop')
export const getEngineConfig = () => api.get('/engine/config')
export const updateEngineConfig = (cfg: Partial<AppSettings>) => api.put('/engine/config', cfg)

// Settings
export const getSettings = () => api.get<AppSettings>('/settings')
export const updateSettings = (s: Partial<AppSettings>) => api.put('/settings', s)

// Health
export const getHealth = () => api.get('/health')
export const getPreflight = () => api.get<PreflightData>('/health/preflight')
