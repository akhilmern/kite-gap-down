import { useState, useMemo } from 'react'
import type { Dispatch, SetStateAction } from 'react'

import type { GapCandidate, SettingsPayload } from '../types'

type SortKey =
  | 'tradingsymbol'
  | 'scanned_at'
  | 'gap_pct'
  | 'open_price'
  | 'ltp'
  | 'volume'
  | 'avg_volume_20d'
  | 'volume_spike'
  | 'preopen_buy_pct'
  | 'preopen_sell_pct'

type SortDir = 'asc' | 'desc'

interface Props {
  candidates: GapCandidate[]
  settings: SettingsPayload | null
  onChange: Dispatch<SetStateAction<GapCandidate[]>>
}

export function CandidatesTable({ candidates, settings, onChange }: Props) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('gap_pct')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const updateRow = (symbol: string, updater: (current: GapCandidate) => GapCandidate) => {
    onChange((current) => current.map((item) => (item.tradingsymbol === symbol ? updater(item) : item)))
  }

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return candidates
    return candidates.filter(
      (c) =>
        c.tradingsymbol.toLowerCase().includes(q) ||
        (c.sector ?? '').toLowerCase().includes(q) ||
        c.gap_pct.toFixed(2).includes(q),
    )
  }, [candidates, search])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let av: number | string
      let bv: number | string
      switch (sortKey) {
        case 'tradingsymbol':
          av = a.tradingsymbol
          bv = b.tradingsymbol
          break
        case 'scanned_at':
          av = a.scanned_at ?? ''
          bv = b.scanned_at ?? ''
          break
        case 'gap_pct':
          av = a.gap_pct
          bv = b.gap_pct
          break
        case 'open_price':
          av = a.open_price
          bv = b.open_price
          break
        case 'ltp':
          av = a.ltp
          bv = b.ltp
          break
        case 'volume':
          av = a.volume
          bv = b.volume
          break
        case 'avg_volume_20d':
          av = a.avg_volume_20d ?? -1
          bv = b.avg_volume_20d ?? -1
          break
        case 'volume_spike':
          av = a.volume_spike ?? -1
          bv = b.volume_spike ?? -1
          break
        case 'preopen_buy_pct':
          av = a.preopen_buy_pct ?? -1
          bv = b.preopen_buy_pct ?? -1
          break
        case 'preopen_sell_pct':
          av = a.preopen_sell_pct ?? -1
          bv = b.preopen_sell_pct ?? -1
          break
        default:
          return 0
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [filtered, sortKey, sortDir])

  return (
    <div>
      <div className="candidates-search-bar">
        <input
          type="search"
          className="candidates-search-input"
          placeholder="Search by symbol, sector, or gap %…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <span className="candidates-search-count">
            {sorted.length} / {candidates.length}
          </span>
        )}
      </div>

      <div className="table-wrap">
        <table className="data-table candidates-table">
          <thead>
            <tr>
              <th>Select</th>
              <SortTh label="Symbol" col="tradingsymbol" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTh label="Scan Time" col="scanned_at" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTh label="Gap %" col="gap_pct" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTh label="Open" col="open_price" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTh label="LTP" col="ltp" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTh label="Volume" col="volume" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortTh
                label="Avg Vol 20D"
                col="avg_volume_20d"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
                title="Average daily volume over last 20 sessions"
              />
              <SortTh
                label="Vol Spike"
                col="volume_spike"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
                title="Today's per-minute volume rate vs 20-day average per-minute rate"
              />
              <SortTh
                label="Buy %"
                col="preopen_buy_pct"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
                title="Pre-open buy quantity % of total order book depth (fetch via 'Fetch depth' button)"
              />
              <SortTh
                label="Sell %"
                col="preopen_sell_pct"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
                title="Pre-open sell quantity % of total order book depth (fetch via 'Fetch depth' button)"
              />
              <th>Investment Amount</th>
              <th>Buy Limit Price</th>
              <th>Market</th>
              <th>SL %</th>
              <th>Target %</th>
              <th>Qty</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={17} className="empty-cell">
                  {candidates.length === 0
                    ? 'No candidates available. Run a scan to populate the table.'
                    : 'No results match your search.'}
                </td>
              </tr>
            ) : (
              sorted.map((item) => {
                const displayedLimitPrice = item.use_market_price
                  ? item.buy_limit_price ?? item.ltp
                  : round2((item.buy_limit_price ?? item.ltp) * (1 + (settings?.buy_buffer_pct ?? 0) / 100))
                const quantity =
                  displayedLimitPrice > 0 && item.investment_amount
                    ? Math.max(1, Math.floor(item.investment_amount / displayedLimitPrice))
                    : 0

                return (
                  <tr key={item.tradingsymbol}>
                    <td>
                      <input
                        type="checkbox"
                        checked={item.selected}
                        onChange={(event) =>
                          updateRow(item.tradingsymbol, (current) => ({
                            ...current,
                            selected: event.target.checked,
                          }))
                        }
                      />
                    </td>
                    <td>{item.tradingsymbol}</td>
                    <td className="time-cell">{formatTime(item.scanned_at)}</td>
                    <td className={item.gap_pct < 0 ? 'negative' : ''}>{item.gap_pct.toFixed(2)}%</td>
                    <td>{formatCurrency(item.open_price)}</td>
                    <td>{formatCurrency(item.ltp)}</td>
                    <td>{item.volume.toLocaleString('en-IN')}</td>
                    <td>{item.avg_volume_20d != null ? item.avg_volume_20d.toLocaleString('en-IN') : '—'}</td>
                    <td className={item.volume_spike != null && item.volume_spike >= 2 ? 'spike-high' : ''}>
                      {item.volume_spike != null ? `${item.volume_spike.toFixed(2)}x` : '—'}
                    </td>
                    <td className={depthTone(item.preopen_buy_pct, 'buy')}>
                      {formatDepthPct(item.preopen_buy_pct, item.preopen_buy_qty)}
                    </td>
                    <td className={depthTone(item.preopen_sell_pct, 'sell')}>
                      {formatDepthPct(item.preopen_sell_pct, item.preopen_sell_qty)}
                    </td>
                    <td>
                      <input
                        type="number"
                        value={item.investment_amount ?? ''}
                        onChange={(event) =>
                          updateRow(item.tradingsymbol, (current) => ({
                            ...current,
                            investment_amount: event.target.value ? Number(event.target.value) : null,
                          }))
                        }
                      />
                    </td>
                    <td>
                      <div className="stacked-field">
                        <input
                          type="number"
                          value={item.buy_limit_price ?? item.ltp}
                          disabled={item.use_market_price}
                          onChange={(event) =>
                            updateRow(item.tradingsymbol, (current) => ({
                              ...current,
                              buy_limit_price: event.target.value ? Number(event.target.value) : current.ltp,
                            }))
                          }
                        />
                        <small>buffered: {formatCurrency(displayedLimitPrice)}</small>
                      </div>
                    </td>
                    <td>
                      <label className="toggle-cell">
                        <input
                          type="checkbox"
                          checked={item.use_market_price}
                          onChange={(event) =>
                            updateRow(item.tradingsymbol, (current) => ({
                              ...current,
                              use_market_price: event.target.checked,
                            }))
                          }
                        />
                        <span>{item.use_market_price ? 'On' : 'Off'}</span>
                      </label>
                    </td>
                    <td>
                      <input
                        type="number"
                        value={item.sl_pct_override ?? settings?.default_sl_pct ?? ''}
                        onChange={(event) =>
                          updateRow(item.tradingsymbol, (current) => ({
                            ...current,
                            sl_pct_override: event.target.value ? Number(event.target.value) : null,
                          }))
                        }
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        value={item.target_pct_override ?? settings?.default_target_pct ?? ''}
                        onChange={(event) =>
                          updateRow(item.tradingsymbol, (current) => ({
                            ...current,
                            target_pct_override: event.target.value ? Number(event.target.value) : null,
                          }))
                        }
                      />
                    </td>
                    <td>{quantity}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── SortTh ──────────────────────────────────────────────────────────────────

interface SortThProps {
  label: string
  col: SortKey
  sortKey: SortKey
  sortDir: SortDir
  onSort: (col: SortKey) => void
  title?: string
}

function SortTh({ label, col, sortKey, sortDir, onSort, title }: SortThProps) {
  const active = sortKey === col
  return (
    <th
      className={`sortable-th${active ? ' sort-active' : ''}`}
      title={title}
      onClick={() => onSort(col)}
    >
      <span className="th-inner">
        {label}
        <span className="sort-icon" aria-hidden>
          {active ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
        </span>
      </span>
    </th>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatCurrency(value: number) {
  return `₹${value.toFixed(2)}`
}

function round2(value: number) {
  return Math.round(value * 100) / 100
}

function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return '—'
  }
}

function formatDepthPct(pct?: number | null, qty?: number | null): string {
  if (pct == null) return '—'
  const qtyStr = qty != null ? ` (${qty.toLocaleString('en-IN')})` : ''
  return `${pct.toFixed(1)}%${qtyStr}`
}

function depthTone(pct?: number | null, side?: 'buy' | 'sell'): string {
  if (pct == null) return ''
  if (side === 'buy' && pct >= 60) return 'depth-buy-strong'
  if (side === 'buy' && pct >= 50) return 'depth-buy-mild'
  if (side === 'sell' && pct >= 60) return 'depth-sell-strong'
  if (side === 'sell' && pct >= 50) return 'depth-sell-mild'
  return ''
}
