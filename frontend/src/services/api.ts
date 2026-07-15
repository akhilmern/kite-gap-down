import axios from 'axios'

import type {
  AuthStatus,
  EngineStatus,
  GapCandidate,
  LastResultsResponse,
  PlaceOrderItem,
  PreflightStatus,
  SettingsPayload,
  TrackedPosition,
} from '../types'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? 'http://15.206.229.206:6666/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

export const getAuthStatus = async () => {
  const { data } = await api.get<AuthStatus>('/auth/status')
  return data
}

export const getLoginUrl = async () => {
  const { data } = await api.get<{ url: string }>('/auth/login-url')
  return data.url
}

export const authCallback = async (code: string) => {
  const { data } = await api.post('/auth/callback', undefined, {
    params: { code },
  })
  return data
}

export const startOrderStream = async () => {
  const { data } = await api.post('/auth/start-order-stream')
  return data
}

export const stopOrderStream = async () => {
  const { data } = await api.post('/auth/stop-order-stream')
  return data
}

export const wsStart = async () => {
  const { data } = await api.post('/engine/ws/start')
  return data
}

export const wsStop = async () => {
  const { data } = await api.post('/engine/ws/stop')
  return data
}

export const toggleSlEngine = async (enabled: boolean) => {
  const { data } = await api.post('/engine/sl-engine/toggle', { enabled })
  return data as { sl_engine_enabled: boolean }
}

export const getEngineConfig = async () => {
  const { data } = await api.get('/engine/config')
  return data as { sl_engine_enabled: boolean; disable_backup_poller: boolean }
}

export const getSettings = async () => {
  const { data } = await api.get<SettingsPayload>('/settings')
  return data
}

export const updateSettings = async (payload: SettingsPayload) => {
  const { data } = await api.put('/settings', payload)
  return data
}

export const runScanner = async (payload: Partial<SettingsPayload>) => {
  const { data } = await api.post<GapCandidate[]>('/scanner/run', payload)
  return data
}

export const getLastResults = async () => {
  const { data } = await api.get<LastResultsResponse>('/scanner/last-results')
  return data
}

export const refreshUniverse = async () => {
  const { data } = await api.post<{ count: number }>('/scanner/refresh-universe')
  return data
}

export const fetchPrevClose = async () => {
  const { data } = await api.post<{ updated: number }>('/scanner/fetch-prev-close')
  return data
}

export const fetchVolHistory = async () => {
  const { data } = await api.post<{ updated: number }>('/scanner/fetch-vol-history')
  return data
}

export const fetchPreopenDepth = async () => {
  const { data } = await api.post<{ items: GapCandidate[]; timestamp?: string | null }>('/scanner/preopen-depth')
  return data
}

export const placeBuyOrders = async (items: PlaceOrderItem[]) => {
  const { data } = await api.post<TrackedPosition[]>('/orders/place-buy', { items })
  return data
}

export const getPositions = async () => {
  const { data } = await api.get<TrackedPosition[]>('/positions')
  return data
}

export const getEngineStatus = async () => {
  const { data } = await api.get<EngineStatus>('/engine/status')
  return data
}

export const getPreflight = async () => {
  const { data } = await api.get<PreflightStatus>('/health/preflight')
  return data
}

export const updateEngineConfig = async (payload: Partial<SettingsPayload>) => {
  const { data } = await api.put('/engine/config', payload)
  return data
}

export const armEngine = async () => {
  const { data } = await api.post('/engine/arm')
  return data
}

export const disarmEngine = async () => {
  const { data } = await api.post('/engine/disarm')
  return data
}

export default api
