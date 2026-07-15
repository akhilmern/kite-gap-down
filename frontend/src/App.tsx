import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import CandidatesTable from './components/CandidatesTable'
import PositionsTable from './components/PositionsTable'
import SettingsPanel from './components/SettingsPanel'
import type { GapCandidate, AppSettings, PlaceOrderItem, PreflightData } from './types'
import * as api from './services/api'

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmtCountdown(s: number): string {
  if (s <= 0) return '00:00'
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function totalCapital(candidates: GapCandidate[]): string {
  const total = candidates.filter(c => c.selected).reduce((sum, c) => sum + c.investment_amount, 0)
  if (total >= 100000) return `₹${(total / 100000).toFixed(2)}L`
  return `₹${total.toLocaleString('en-IN')}`
}

// ── Alert Component ──────────────────────────────────────────────────────────

function Alert({ msg, type, onClose }: { msg: string; type: 'error' | 'success' | 'info'; onClose: () => void }) {
  return (
    <div className={`alert alert-${type}`} style={{ position: 'relative' }}>
      <span>{msg}</span>
      <button
        onClick={onClose}
        style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: 16 }}
      >×</button>
    </div>
  )
}

// ── Metric Tile ──────────────────────────────────────────────────────────────

function Metric({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="metric-tile">
      <div className="label">{label}</div>
      <div className={`value${color ? ` ${color}` : ''}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const qc = useQueryClient()
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [candidates, setCandidates] = useState<GapCandidate[]>([])
  const [localSettings, setLocalSettings] = useState<AppSettings | null>(null)
  const [alert, setAlert] = useState<{ msg: string; type: 'error' | 'success' | 'info' } | null>(null)

  // Apply theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  function showAlert(msg: string, type: 'error' | 'success' | 'info' = 'info') {
    setAlert({ msg, type })
    setTimeout(() => setAlert(null), 6000)
  }

  // ── Queries ────────────────────────────────────────────────────────────────

  const authQuery = useQuery({
    queryKey: ['auth'],
    queryFn: () => api.getAuthStatus().then(r => r.data),
    refetchInterval: 5000,
  })

  const engineQuery = useQuery({
    queryKey: ['engine'],
    queryFn: () => api.getEngineStatus().then(r => r.data),
    refetchInterval: 2500,
  })

  const preflightQuery = useQuery({
    queryKey: ['preflight'],
    queryFn: () => api.getPreflight().then(r => r.data),
    refetchInterval: 10000,
  })

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.getSettings().then(r => r.data),
    staleTime: Infinity,
  })

  useEffect(() => {
    if (settingsQuery.data && !localSettings) {
      setLocalSettings(settingsQuery.data)
    }
  }, [settingsQuery.data])

  const lastResultsQuery = useQuery({
    queryKey: ['lastResults'],
    queryFn: () => api.getLastResults().then(r => r.data),
    staleTime: Infinity,
  })

  useEffect(() => {
    if (lastResultsQuery.data?.candidates && candidates.length === 0) {
      setCandidates(lastResultsQuery.data.candidates)
    }
  }, [lastResultsQuery.data])

  const hasOpenPositions = (engineQuery.data?.open_positions ?? 0) > 0

  const positionsQuery = useQuery({
    queryKey: ['positions'],
    queryFn: () => api.getPositions().then(r => r.data),
    refetchInterval: hasOpenPositions ? 3000 : 10000,
    enabled: authQuery.data?.authenticated ?? false,
  })

  // ── Mutations ──────────────────────────────────────────────────────────────

  const loginMutation = useMutation({
    mutationFn: () => api.getLoginUrl().then(r => { window.location.href = r.data.login_url }),
  })

  const wsMutation = useMutation({
    mutationFn: (start: boolean) => start ? api.startWs() : api.stopWs(),
    onSuccess: (_data, start) => {
      showAlert(start ? 'Stream started' : 'Stream stopped', 'success')
      qc.invalidateQueries({ queryKey: ['auth'] })
      qc.invalidateQueries({ queryKey: ['engine'] })
    },
    onError: (e: Error) => showAlert(`Stream error: ${e.message}`, 'error'),
  })

  const slEngineMutation = useMutation({
    mutationFn: (arm: boolean) => arm ? api.armEngine() : api.disarmEngine(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['engine'] }),
    onError: (e: Error) => showAlert(`Engine error: ${e.message}`, 'error'),
  })

  const runScannerMutation = useMutation({
    mutationFn: () => api.runScanner(),
    onSuccess: data => {
      setCandidates(data.data.candidates)
      showAlert(`Scan complete — ${data.data.count} candidates found`, 'success')
    },
    onError: (e: Error) => showAlert(`Scan failed: ${e.message}`, 'error'),
  })

  const saveSettingsMutation = useMutation({
    mutationFn: (s: AppSettings) => api.updateSettings(s),
    onSuccess: () => showAlert('Settings saved', 'success'),
    onError: (e: Error) => showAlert(`Save failed: ${e.message}`, 'error'),
  })

  const refreshUniverseMutation = useMutation({
    mutationFn: () => api.refreshUniverse(),
    onSuccess: data => showAlert(`Universe refreshed — ${data.data.instruments_cached} instruments`, 'success'),
    onError: (e: Error) => showAlert(`Refresh failed: ${e.message}`, 'error'),
  })

  const fetchPrevCloseMutation = useMutation({
    mutationFn: () => api.fetchPrevClose(),
    onSuccess: data => showAlert(`Prev close fetched for ${data.data.updated} instruments`, 'success'),
    onError: (e: Error) => showAlert(`Fetch prev close failed: ${e.message}`, 'error'),
  })

  const fetchVolHistoryMutation = useMutation({
    mutationFn: () => api.fetchVolHistory(),
    onSuccess: data => showAlert(`Vol history fetched for ${data.data.updated} instruments`, 'success'),
    onError: (e: Error) => showAlert(`Fetch vol history failed: ${e.message}`, 'error'),
  })

  const fetchPreopenDepthMutation = useMutation({
    mutationFn: () => api.fetchPreopenDepth(candidates),
    onSuccess: data => {
      setCandidates(data.data.candidates)
      showAlert('Pre-open depth loaded', 'success')
    },
    onError: (e: Error) => showAlert(`Depth fetch failed: ${e.message}`, 'error'),
  })

  const placeOrdersMutation = useMutation({
    mutationFn: (items: PlaceOrderItem[]) => api.placeBuyOrders(items),
    onSuccess: data => {
      if (data.data.queued) {
        showAlert(`${data.data.count} orders queued — will fire at scheduled time`, 'success')
      } else {
        showAlert('Orders placed successfully', 'success')
      }
      qc.invalidateQueries({ queryKey: ['positions'] })
      qc.invalidateQueries({ queryKey: ['engine'] })
      qc.invalidateQueries({ queryKey: ['preflight'] })
    },
    onError: (e: Error) => showAlert(`Order failed: ${e.message}`, 'error'),
  })

  // ── Auth callback handling ────────────────────────────────────────────────

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('request_token') ?? params.get('code')
    if (code) {
      api.postAuthCallback(code)
        .then(() => {
          showAlert('Authentication successful!', 'success')
          window.history.replaceState({}, '', '/')
          qc.invalidateQueries({ queryKey: ['auth'] })
        })
        .catch(e => showAlert(`Auth failed: ${e.message}`, 'error'))
    }
  }, [])

  // ── Derived state ─────────────────────────────────────────────────────────

  const selectedCandidates = candidates.filter(c => c.selected)
  const preflight: PreflightData | undefined = preflightQuery.data
  const authenticated = authQuery.data?.authenticated ?? false
  const wsActive = authQuery.data?.ws_active ?? false
  const slEngineArmed = engineQuery.data?.sl_engine_armed ?? false

  function handlePlaceOrders() {
    const items: PlaceOrderItem[] = selectedCandidates.map(c => ({
      tradingsymbol: c.tradingsymbol,
      exchange: c.exchange,
      instrument_token: c.instrument_token,
      investment_amount: c.investment_amount,
      buy_limit_price: c.buy_limit_price ?? c.open_price,
      use_market_price: c.use_market_price,
      sl_pct: c.sl_pct_override ?? localSettings?.default_sl_pct ?? 1.0,
      target_pct: c.target_pct_override ?? localSettings?.default_target_pct ?? 1.5,
    }))
    if (items.length === 0) { showAlert('Select at least one candidate', 'error'); return }
    placeOrdersMutation.mutate(items)
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const positions = positionsQuery.data?.positions ?? {}
  const posCount = Object.keys(positions).length

  return (
    <div className="app-shell">
      {/* ── Sidebar ─────────────────────────────────────────── */}
      <div className={`sidebar${sidebarOpen ? '' : ' collapsed'}`}>
        {sidebarOpen && localSettings && (
          <SettingsPanel
            settings={localSettings}
            onChange={setLocalSettings}
            onSave={() => localSettings && saveSettingsMutation.mutate(localSettings)}
            saving={saveSettingsMutation.isPending}
          />
        )}
      </div>

      {/* ── Main ────────────────────────────────────────────── */}
      <div className="main-area">
        {/* Top bar */}
        <div className="topbar">
          <button className="btn-ghost" style={{ padding: '4px 6px', border: 'none', cursor: 'pointer', background: 'none' }}
            onClick={() => setSidebarOpen(v => !v)} title="Toggle sidebar">
            ☰
          </button>
          <div className="brand">
            <div className="brand-dot" />
            Gap-Down System
          </div>

          {/* Auth badge */}
          <span className={`badge ${authenticated ? 'badge-success' : 'badge-danger'}`}>
            {authenticated ? '● Authenticated' : '○ Not Authenticated'}
          </span>

          {/* Stream badge */}
          <span className={`badge ${wsActive ? 'badge-success' : 'badge-muted'}`}>
            {wsActive ? '● Stream Active' : '○ Stream Off'}
          </span>

          {/* Mobile protect badge */}
          {localSettings?.adopt_mobile_buy_orders && (
            <span className="badge badge-purple">📱 Mobile Protect</span>
          )}

          {/* SL Engine badge */}
          <span className={`badge ${slEngineArmed ? 'badge-success' : 'badge-muted'}`}>
            {slEngineArmed ? '⚡ Engine Armed' : '⚡ Engine Disarmed'}
          </span>

          <div style={{ flex: 1 }} />

          {/* Controls */}
          <button
            className={`btn btn-sm ${wsActive ? 'btn-outline' : 'btn-primary'}`}
            onClick={() => wsMutation.mutate(!wsActive)}
            disabled={wsMutation.isPending || !authenticated}
          >
            {wsActive ? '⏹ Stop Stream' : '▶ Start Stream'}
          </button>

          <button
            className={`btn btn-sm ${slEngineArmed ? 'btn-danger' : 'btn-success'}`}
            onClick={() => slEngineMutation.mutate(!slEngineArmed)}
            disabled={slEngineMutation.isPending}
          >
            {slEngineArmed ? '⚡ Disarm Engine' : '⚡ Arm Engine'}
          </button>

          {!authenticated && (
            <button
              className="btn btn-primary btn-sm"
              onClick={() => loginMutation.mutate()}
              disabled={loginMutation.isPending}
            >
              🔑 Login with Kite
            </button>
          )}

          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setTheme(t => t === 'light' ? 'dark' : 'light')}
            title="Toggle dark/light theme"
          >
            {theme === 'dark' ? '☀' : '🌙'}
          </button>
        </div>

        {/* Content */}
        <div className="content-area">
          {/* Alert */}
          {alert && <Alert msg={alert.msg} type={alert.type} onClose={() => setAlert(null)} />}

          {/* Preflight metrics */}
          <div className="metrics-row">
            <Metric
              label="Authentication"
              value={authenticated ? 'OK' : 'Offline'}
              color={authenticated ? 'success' : 'danger'}
            />
            <Metric
              label="Stream"
              value={wsActive ? 'Live' : 'Off'}
              color={wsActive ? 'success' : undefined}
            />
            <Metric
              label="Orders Placed"
              value={preflight?.orders_placed_count ?? 0}
              sub="this session"
            />
            <Metric
              label="Time to Scan"
              value={preflight ? fmtCountdown(preflight.time_to_scan_seconds) : '—'}
              sub="until 09:08 scan"
              color={preflight && preflight.time_to_scan_seconds < 60 ? 'warning' : undefined}
            />
            <Metric
              label="Time to Open"
              value={preflight ? fmtCountdown(preflight.time_to_market_open_seconds) : '—'}
              sub="until 09:15"
              color={preflight && preflight.time_to_market_open_seconds < 120 ? 'warning' : undefined}
            />
            <Metric
              label="Queued Orders"
              value={preflight?.pending_orders_count ?? 0}
              sub="will fire at scheduled time"
              color={(preflight?.pending_orders_count ?? 0) > 0 ? 'accent' : undefined}
            />
            <Metric
              label="Open Positions"
              value={engineQuery.data?.open_positions ?? 0}
              color={(engineQuery.data?.open_positions ?? 0) > 0 ? 'accent' : undefined}
            />
          </div>

          {/* Scanner controls */}
          <div className="controls-bar">
            <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>SCANNER</span>
            <button className="btn btn-outline btn-sm" onClick={() => refreshUniverseMutation.mutate()}
              disabled={refreshUniverseMutation.isPending}>
              {refreshUniverseMutation.isPending ? <><span className="spinner" /> Refreshing…</> : '🔄 Refresh Universe'}
            </button>
            <button className="btn btn-outline btn-sm" onClick={() => fetchPrevCloseMutation.mutate()}
              disabled={fetchPrevCloseMutation.isPending || !authenticated}>
              {fetchPrevCloseMutation.isPending ? <><span className="spinner" /> Fetching…</> : '📅 Fetch Prev Close'}
            </button>
            <button className="btn btn-outline btn-sm" onClick={() => fetchVolHistoryMutation.mutate()}
              disabled={fetchVolHistoryMutation.isPending || !authenticated}>
              {fetchVolHistoryMutation.isPending ? <><span className="spinner" /> Fetching…</> : '📈 Fetch Vol History'}
            </button>
            <button className="btn btn-outline btn-sm" onClick={() => fetchPreopenDepthMutation.mutate()}
              disabled={fetchPreopenDepthMutation.isPending || candidates.length === 0}>
              {fetchPreopenDepthMutation.isPending ? <><span className="spinner" /> Loading…</> : '📊 Fetch Depth'}
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => runScannerMutation.mutate()}
              disabled={runScannerMutation.isPending}>
              {runScannerMutation.isPending ? <><span className="spinner" /> Scanning…</> : '🔍 Run Scan'}
            </button>
          </div>

          {/* Selection bar */}
          <div className="selection-bar">
            <span className="stat">
              <strong>{selectedCandidates.length}</strong> selected
            </span>
            <span className="stat">
              Capital: <strong>{totalCapital(candidates)}</strong>
            </span>
            <span className="stat">
              Positions: <strong>{posCount}</strong>
            </span>
            <div style={{ flex: 1 }} />
            <button
              className="btn btn-success"
              onClick={handlePlaceOrders}
              disabled={placeOrdersMutation.isPending || selectedCandidates.length === 0 || !authenticated}
            >
              {placeOrdersMutation.isPending
                ? <><span className="spinner" /> Placing…</>
                : `🛒 Place ${selectedCandidates.length} Buy Order${selectedCandidates.length !== 1 ? 's' : ''}`}
            </button>
          </div>

          {/* Candidates table */}
          <CandidatesTable
            candidates={candidates}
            settings={localSettings}
            onChange={setCandidates}
          />

          {/* Positions table */}
          {(posCount > 0 || hasOpenPositions) && (
            <PositionsTable positions={positions} />
          )}
        </div>
      </div>
    </div>
  )
}
