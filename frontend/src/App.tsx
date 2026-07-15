import type { ReactNode } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  Moon,
  Play,
  RefreshCcw,
  Save,
  Shield,
  Sun,
  Wifi,
} from 'lucide-react'

import {
  armEngine,
  authCallback,
  fetchPrevClose,
  fetchPreopenDepth,
  fetchVolHistory,
  getAuthStatus,
  getEngineConfig,
  getEngineStatus,
  getLastResults,
  getLoginUrl,
  getPositions,
  getPreflight,
  getSettings,
  placeBuyOrders,
  refreshUniverse,
  runScanner,
  startOrderStream,
  toggleSlEngine,
  updateSettings,
  wsStart,
  wsStop,
} from './services/api'
import type { AlertState, GapCandidate, PlaceOrderItem, SettingsPayload, TrackedPosition } from './types'
import { CandidatesTable } from './components/CandidatesTable'
import { PositionsTable } from './components/PositionsTable'
import { SettingsPanel } from './components/SettingsPanel'
import './styles.css'

const queryClient = new QueryClient()

// ─── Theme persistence ─────────────────────────────────────────
type Theme = 'dark' | 'light'

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem('theme') as Theme | null
    return stored === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme)
  try {
    localStorage.setItem('theme', theme)
  } catch {
    // ignore
  }
}


// ─── Dashboard ─────────────────────────────────────────────────
function Dashboard() {
  const client = useQueryClient()
  const [alert, setAlert] = useState<AlertState | null>(null)
  const [candidates, setCandidates] = useState<GapCandidate[]>([])
  const [settingsDraft, setSettingsDraft] = useState<SettingsPayload | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [theme, setTheme] = useState<Theme>(getStoredTheme)
  const [slEngineEnabled, setSlEngineEnabled] = useState(true)

  // apply theme on change
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))
  const toggleSidebar = () => setSidebarOpen((v) => !v)

  // ─── queries ──────────────────────────────────────────────────
  const authQuery = useQuery({
    queryKey: ['auth-status'],
    queryFn: getAuthStatus,
    refetchInterval: 5000,
  })

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  })

  const positionsQuery = useQuery({
    queryKey: ['positions'],
    queryFn: getPositions,
    enabled: authQuery.data?.authenticated ?? false,
    refetchInterval: authQuery.data?.authenticated ? 3000 : false,
  })

  const engineQuery = useQuery({
    queryKey: ['engine-status'],
    queryFn: getEngineStatus,
    refetchInterval: authQuery.data?.authenticated ? 2500 : false,
  })

  const engineConfigQuery = useQuery({
    queryKey: ['engine-config'],
    queryFn: getEngineConfig,
    enabled: authQuery.data?.authenticated ?? false,
  })

  const hasOpenPositions = useMemo(
    () =>
      (positionsQuery.data ?? []).some(
        (item: TrackedPosition) =>
          item.buy_status === 'OPEN' ||
          item.buy_status === 'PENDING' ||
          item.sl_status === 'OPEN' ||
          item.target_status === 'OPEN',
      ),
    [positionsQuery.data],
  )

  const preflightQuery = useQuery({
    queryKey: ['preflight'],
    queryFn: getPreflight,
    refetchInterval: 10000,
  })

  const lastResultsQuery = useQuery({
    queryKey: ['last-results'],
    queryFn: getLastResults,
  })

  // ─── effects ──────────────────────────────────────────────────
  useEffect(() => {
    if (settingsQuery.data) {
      setSettingsDraft(settingsQuery.data)
    }
  }, [settingsQuery.data])

  useEffect(() => {
    if (engineConfigQuery.data) {
      setSlEngineEnabled(engineConfigQuery.data.sl_engine_enabled)
    }
  }, [engineConfigQuery.data])


  
  useEffect(() => {
    if (lastResultsQuery.data?.items && lastResultsQuery.data.items.length > 0) {
      setCandidates(
        lastResultsQuery.data.items.map((item) => ({
          ...item,
          selected: item.selected ?? false,
          investment_amount: item.investment_amount ?? 10000,
          buy_limit_price: item.buy_limit_price ?? item.ltp,
          use_market_price: item.use_market_price ?? false,
        })),
      )
    }
  }, [lastResultsQuery.data])

  // OAuth redirect code handling
  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get('code')
    if (!code) {
      return
    }
    ;(async () => {
      try {
        await authCallback(code)
        await startOrderStream()
        setAlert({ type: 'success', message: 'Kite authentication completed and stream started.' })
        window.history.replaceState({}, '', window.location.pathname)
        await client.invalidateQueries()
      } catch (error) {
        setAlert({ type: 'error', message: `Auth callback failed: ${formatError(error)}` })
      }
    })()
  }, [client])

  // live-refresh open positions
  useEffect(() => {
    if (!authQuery.data?.authenticated || !hasOpenPositions) {
      return
    }
    const interval = window.setInterval(() => {
      client.invalidateQueries({ queryKey: ['positions'] })
      client.invalidateQueries({ queryKey: ['engine-status'] })
    }, 2500)
    return () => window.clearInterval(interval)
  }, [authQuery.data?.authenticated, client, hasOpenPositions])

  // ─── mutations ────────────────────────────────────────────────
  const loginMutation = useMutation({
    mutationFn: getLoginUrl,
    onSuccess: (url) => {
      window.location.href = url
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Unable to load Kite login URL: ${formatError(error)}` })
    },
  })

  const wsMutation = useMutation({
    mutationFn: async (start: boolean) => (start ? wsStart() : wsStop()),
    onSuccess: (_data, start) => {
      setAlert({ type: 'success', message: start ? 'WebSocket stream started.' : 'WebSocket stream stopped.' })
      client.invalidateQueries({ queryKey: ['auth-status'] })
      client.invalidateQueries({ queryKey: ['engine-status'] })
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Stream toggle failed: ${formatError(error)}` })
    },
  })

  const slEngineMutation = useMutation({
    mutationFn: async (enabled: boolean) => toggleSlEngine(enabled),
    onSuccess: (data) => {
      setSlEngineEnabled(data.sl_engine_enabled)
      setAlert({ type: 'success', message: `SL engine ${data.sl_engine_enabled ? 'enabled' : 'disabled'}.` })
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `SL engine toggle failed: ${formatError(error)}` })
    },
  })

  const runScannerMutation = useMutation({
    mutationFn: async () => {
      if (!settingsDraft) {
        throw new Error('Settings not loaded')
      }
      return runScanner({
        min_gap_down_pct: settingsDraft.min_gap_down_pct,
        max_gap_down_pct: settingsDraft.max_gap_down_pct,
        min_price: settingsDraft.min_price,
        min_volume: settingsDraft.min_volume,
        min_avg_volume_30d: settingsDraft.min_avg_volume_30d,
        min_market_cap: settingsDraft.min_market_cap,
        excluded_sectors: settingsDraft.excluded_sectors,
      })
    },
    onSuccess: (rows) => {
      setCandidates(
        rows.map((item) => ({
          ...item,
          selected: false,
          investment_amount: item.investment_amount ?? 10000,
          buy_limit_price: item.buy_limit_price ?? item.ltp,
          use_market_price: item.use_market_price ?? false,
        })),
      )
      setAlert({ type: 'success', message: `Scanner returned ${rows.length} candidates.` })
      client.invalidateQueries({ queryKey: ['last-results'] })
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Scanner failed: ${formatError(error)}` })
    },
  })

  const saveSettingsMutation = useMutation({
    mutationFn: async () => {
      if (!settingsDraft) {
        throw new Error('Settings not loaded')
      }
      return updateSettings(settingsDraft)
    },
    onSuccess: () => {
      setAlert({ type: 'success', message: 'Settings saved and written to .env.' })
      client.invalidateQueries({ queryKey: ['settings'] })
      client.invalidateQueries({ queryKey: ['preflight'] })
      client.refetchQueries({ queryKey: ['settings'] })
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Saving settings failed: ${formatError(error)}` })
    },
  })

  const placeOrdersMutation = useMutation({
    mutationFn: async () => {
      const selected = candidates.filter((item) => item.selected)
      if (!selected.length) {
        throw new Error('Select at least one stock')
      }
      const items: PlaceOrderItem[] = selected.map((item) => ({
        tradingsymbol: item.tradingsymbol,
        instrument_token: item.instrument_token,
        exchange: item.exchange,
        investment_amount: item.investment_amount ?? 0,
        buy_limit_price: item.buy_limit_price ?? item.ltp,
        sl_pct_override: item.sl_pct_override ?? null,
        target_pct_override: item.target_pct_override ?? null,
        use_market_price: item.use_market_price,
      }))
      return placeBuyOrders(items)
    },
    onSuccess: async (rows) => {
      setAlert({
        type: 'success',
        message: `Submitted ${rows.length} buy order${rows.length !== 1 ? 's' : ''}.`,
      })
      await armEngine()
      client.invalidateQueries({ queryKey: ['positions'] })
      client.invalidateQueries({ queryKey: ['engine-status'] })
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Buy order placement failed: ${formatError(error)}` })
    },
  })

  const refreshUniverseMutation = useMutation({
    mutationFn: refreshUniverse,
    onSuccess: (data) => {
      setAlert({ type: 'success', message: `Instrument universe refreshed (${data.count} instruments).` })
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Universe refresh failed: ${formatError(error)}` })
    },
  })

  const fetchPrevCloseMutation = useMutation({
    mutationFn: fetchPrevClose,
    onSuccess: (data) => {
      setAlert({ type: 'success', message: `Prev close fetched for ${data.updated} stocks. You can now run the scan.` })
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Fetch prev close failed: ${formatError(error)}` })
    },
  })

  const fetchVolHistoryMutation = useMutation({
    mutationFn: fetchVolHistory,
    onSuccess: (data) => {
      setAlert({ type: 'success', message: `20-day volume history cached for ${data.updated} stocks.` })
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Fetch vol history failed: ${formatError(error)}` })
    },
  })

  const fetchPreopenDepthMutation = useMutation({
    mutationFn: fetchPreopenDepth,
    onSuccess: (data) => {
      if (data.items.length > 0) {
        // Merge depth fields into existing candidates, preserving user-edited fields
        setCandidates((current) => {
          const depthByToken = new Map(data.items.map((d) => [d.instrument_token, d]))
          return current.map((item) => {
            const depth = depthByToken.get(item.instrument_token)
            if (!depth) return item
            return {
              ...item,
              preopen_buy_qty: depth.preopen_buy_qty ?? item.preopen_buy_qty,
              preopen_sell_qty: depth.preopen_sell_qty ?? item.preopen_sell_qty,
              preopen_buy_pct: depth.preopen_buy_pct ?? item.preopen_buy_pct,
              preopen_sell_pct: depth.preopen_sell_pct ?? item.preopen_sell_pct,
            }
          })
        })
        setAlert({ type: 'success', message: `Pre-open depth fetched for ${data.items.length} candidates.` })
      } else {
        setAlert({ type: 'info', message: 'No scan results found. Run a scan first.' })
      }
    },
    onError: (error) => {
      setAlert({ type: 'error', message: `Pre-open depth fetch failed: ${formatError(error)}` })
    },
  })

  // ─── derived UI values ─────────────────────────────────────────
  const streamReady = authQuery.data?.stream_active || engineQuery.data?.ws_active
  const selectedCount = useMemo(() => candidates.filter((item) => item.selected).length, [candidates])
  const selectedInvestment = useMemo(
    () => candidates.filter((item) => item.selected).reduce((sum, item) => sum + (item.investment_amount ?? 0), 0),
    [candidates],
  )

  // ─── render ───────────────────────────────────────────────────
  return (
    <>
      {/* Floating re-open button shown only when collapsed */}
      {!sidebarOpen && (
        <button
          className="sidebar-toggle-fab"
          onClick={toggleSidebar}
          aria-label="Open sidebar"
          title="Open settings panel"
        >
          <ChevronRight size={18} />
        </button>
      )}

      <div className={`app-shell${sidebarOpen ? '' : ' sidebar-collapsed'}`}>
        {/* ── Sidebar ─────────────────────────────────────────── */}
        <aside className="sidebar" aria-hidden={!sidebarOpen}>
          <div className="panel brand-panel">
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
              <div>
                  <p className="eyebrow">Zerodha Kite / NSE</p>
                  <h1>Gap-Down Fill</h1>
                </div>
              <button
                className="sidebar-toggle-btn"
                onClick={toggleSidebar}
                aria-label="Close sidebar"
                title="Collapse panel"
              >
                <ChevronLeft size={18} />
              </button>
            </div>
            <p className="muted" style={{ marginBottom: 0 }}>
              FastAPI execution engine · async order routing · synthetic OCO exits
            </p>
          </div>

          <SettingsPanel settings={settingsDraft} onChange={setSettingsDraft} onSave={() => saveSettingsMutation.mutate()} />
        </aside>

        {/* ── Main content ─────────────────────────────────────── */}
        <main className="main-content">
          {/* Topbar */}
          <header className="topbar panel">
            <div className="topbar-left">
              <button
                className="sidebar-toggle-btn"
                onClick={toggleSidebar}
                aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
                title={sidebarOpen ? 'Collapse settings' : 'Expand settings'}
              >
                {sidebarOpen ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
              </button>

              <StatusBadge
                icon={<Wifi size={15} />}
                label={streamReady ? 'Stream active' : 'Stream offline'}
                tone={streamReady ? 'success' : 'muted'}
              />
              <StatusBadge
                icon={<Shield size={15} />}
                label={settingsDraft?.adopt_mobile_buy_orders ? 'Mobile protect on' : 'Mobile protect off'}
                tone={settingsDraft?.adopt_mobile_buy_orders ? 'success' : 'warning'}
              />
              <StatusBadge
                icon={<CheckCircle2 size={15} />}
                label={
                  authQuery.data?.authenticated
                    ? `Auth${authQuery.data.user_id ? ` · ${authQuery.data.user_id}` : ''}`
                    : 'Not authenticated'
                }
                tone={authQuery.data?.authenticated ? 'success' : 'muted'}
              />
            </div>

            <div className="topbar-actions">
              {/* WS engine toggle */}
              <button
                className={`button ${streamReady ? 'active-toggle' : 'secondary'}`}
                onClick={() => wsMutation.mutate(!streamReady)}
                disabled={wsMutation.isPending || !authQuery.data?.authenticated}
                title={streamReady ? 'Stop WebSocket stream' : 'Start WebSocket stream'}
              >
                {wsMutation.isPending ? <LoaderCircle className="spin" size={14} /> : <Wifi size={14} />}
                {streamReady ? 'WS On' : 'WS Off'}
              </button>

              {/* SL engine toggle */}
              <button
                className={`button ${slEngineEnabled ? 'active-toggle' : 'secondary'}`}
                onClick={() => slEngineMutation.mutate(!slEngineEnabled)}
                disabled={slEngineMutation.isPending}
                title={slEngineEnabled ? 'Disable SL/target engine' : 'Enable SL/target engine'}
              >
                {slEngineMutation.isPending ? <LoaderCircle className="spin" size={14} /> : <Shield size={14} />}
                {slEngineEnabled ? 'SL On' : 'SL Off'}
              </button>

              {/* Theme toggle */}
              <button
                className="theme-toggle"
                onClick={toggleTheme}
                aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
              >
                {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
              </button>

              <button
                className="button secondary"
                onClick={() => loginMutation.mutate()}
                disabled={loginMutation.isPending}
              >
                {loginMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <Shield size={16} />}
                Login with Kite
              </button>
            </div>
          </header>

          {/* Alert banner */}
          {alert && (
            <div className={`alert ${alert.type}`}>
              <div className="alert-content">
                {alert.type === 'error' ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
                <span>{alert.message}</span>
              </div>
              <button className="ghost" onClick={() => setAlert(null)}>
                Dismiss
              </button>
            </div>
          )}

          {/* Preflight row */}
          <section className="panel">
            <div className="section-header">
              <div>
                <h2>Preflight</h2>
                <p className="muted">Auth status, stream health, time to next auto-scan, and order fire countdown.</p>
              </div>
            </div>
            <div className="preflight-row">
              <Metric label="Authenticated" value={preflightQuery.data?.authenticated ? 'Yes ✓' : 'No'} />
              <Metric label="Stream active" value={preflightQuery.data?.stream_active ? 'Yes ✓' : 'No'} />
              <Metric label="Orders placed" value={String(preflightQuery.data?.orders_placed_count ?? 0)} />
              <Metric label="Next auto-scan in" value={`${preflightQuery.data?.time_to_next_scan_seconds ?? 0}s`} />
              {(preflightQuery.data?.time_to_market_open_seconds ?? 0) > 0 && (
                <Metric label="Orders fire in" value={`${preflightQuery.data!.time_to_market_open_seconds}s`} />
              )}
              {(preflightQuery.data?.pending_orders_count ?? 0) > 0 && (
                <Metric label="Queued orders" value={String(preflightQuery.data!.pending_orders_count)} />
              )}
            </div>
          </section>

          {/* Scanner controls */}
          <section className="panel">
            <div className="section-header">
              <div>
                <h2>Scanner controls</h2>
                <p className="muted">Run full NSE gap scan then submit concurrent buy orders.</p>
              </div>
              <div className="controls-actions">
                <button
                  className="button secondary"
                  onClick={() => refreshUniverseMutation.mutate()}
                  disabled={refreshUniverseMutation.isPending}
                >
                  {refreshUniverseMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <RefreshCcw size={16} />}
                  Refresh universe
                </button>
                <button
                  className="button secondary"
                  onClick={() => fetchPrevCloseMutation.mutate()}
                  disabled={fetchPrevCloseMutation.isPending || !authQuery.data?.authenticated}
                  title="Fetch yesterday's closing prices for all NSE stocks. Run this once before the scan."
                >
                  {fetchPrevCloseMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <RefreshCcw size={16} />}
                  Fetch prev close
                </button>
                <button
                  className="button secondary"
                  onClick={() => fetchVolHistoryMutation.mutate()}
                  disabled={fetchVolHistoryMutation.isPending || !authQuery.data?.authenticated}
                  title="Pre-fetch 20-day volume history for all NSE stocks. Run this once before market open to enable Vol Spike column."
                >
                  {fetchVolHistoryMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <RefreshCcw size={16} />}
                  Fetch vol history
                </button>
                <button
                  className="button secondary"
                  onClick={() => fetchPreopenDepthMutation.mutate()}
                  disabled={fetchPreopenDepthMutation.isPending || !authQuery.data?.authenticated || candidates.length === 0}
                  title="Fetch pre-open order book depth (buy/sell %) for current scan candidates. Use during 9:08–9:15."
                >
                  {fetchPreopenDepthMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <RefreshCcw size={16} />}
                  Fetch depth
                </button>
                <button
                  className="button primary"
                  onClick={() => runScannerMutation.mutate()}
                  disabled={runScannerMutation.isPending || !settingsDraft}
                >
                  {runScannerMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
                  Run scan
                </button>
              </div>
            </div>

            <div className="selection-bar">
              <Metric label="Selected rows" value={String(selectedCount)} />
              <Metric label="Selected capital" value={`₹${selectedInvestment.toLocaleString('en-IN')}`} />
              <Metric label="Tracked positions" value={String(positionsQuery.data?.length ?? 0)} />
              <button
                className="button primary"
                onClick={() => placeOrdersMutation.mutate()}
                disabled={placeOrdersMutation.isPending || !selectedCount}
              >
                {placeOrdersMutation.isPending ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                Place buy orders
              </button>
            </div>
          </section>

          {/* Candidates */}
          <section className="panel">
            <div className="section-header">
              <h2>Gap candidates</h2>
              <p className="muted">
                Limit price includes the buy buffer %. Quantity = floor(amount / buffered price).
              </p>
            </div>
            <CandidatesTable candidates={candidates} settings={settingsDraft} onChange={setCandidates} />
          </section>

          {/* Positions */}
          <section className="panel">
            <div className="section-header">
              <h2>Tracked positions</h2>
              <p className="muted">
                Live entry, SL-M, target, exit leg, and error columns. Auto-refreshes while any position is open.
              </p>
            </div>
            <PositionsTable positions={positionsQuery.data ?? []} />
          </section>
        </main>
      </div>
    </>
  )
}

function StatusBadge({ icon, label, tone }: { icon: ReactNode; label: string; tone: 'success' | 'warning' | 'muted' }) {
  return (
    <span className={`status-badge ${tone}`}>
      {icon}
      {label}
    </span>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function formatError(error: unknown) {
  if (error instanceof Error) {
    return error.message
  }
  return String(error)
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  )
}
