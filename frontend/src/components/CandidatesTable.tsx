import { useState, useMemo } from 'react'
import type { GapCandidate, AppSettings } from '../types'

interface Props {
  candidates: GapCandidate[]
  settings: AppSettings | null
  onChange: (updated: GapCandidate[]) => void
}

type SortKey = keyof GapCandidate
type SortDir = 'asc' | 'desc'

function fmt(n: number | null | undefined, dec = 2): string {
  if (n == null) return '—'
  return n.toFixed(dec)
}
function fmtVol(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(0) + 'K'
  return String(n)
}
function computeQty(c: GapCandidate): number {
  const price = c.buy_limit_price ?? c.open_price
  if (!price || !c.investment_amount) return 0
  return Math.floor(c.investment_amount / price)
}

const COLUMNS: { key: SortKey; label: string; title: string }[] = [
  { key: 'tradingsymbol', label: 'Symbol', title: 'NSE trading symbol' },
  { key: 'scanned_at', label: 'Scan Time', title: 'Time candidate was found' },
  { key: 'gap_pct', label: 'Gap %', title: 'Gap % = (Open − Prev Close) / Prev Close × 100' },
  { key: 'open_price', label: 'Open', title: 'Opening price' },
  { key: 'ltp', label: 'LTP', title: 'Last traded price' },
  { key: 'volume', label: 'Volume', title: "Today's traded volume" },
  { key: 'avg_volume_20d', label: 'Avg Vol 20D', title: '20-day average volume' },
  { key: 'volume_spike', label: 'Vol Spike', title: 'Volume spike ratio (today rate ÷ avg rate). ≥2x = high activity' },
  { key: 'preopen_buy_pct', label: 'Buy %', title: 'Pre-open buy qty as % of total depth — higher is more bullish' },
  { key: 'preopen_sell_pct', label: 'Sell %', title: 'Pre-open sell qty as % of total depth' },
  { key: 'investment_amount', label: 'Amount ₹', title: '₹ amount to invest in this stock' },
  { key: 'buy_limit_price', label: 'Limit Price', title: 'Buy limit price (auto-buffered from open price)' },
  { key: 'use_market_price', label: 'Mkt', title: 'Use market order instead of limit' },
  { key: 'sl_pct_override', label: 'SL %', title: 'Stop-loss % from fill price' },
  { key: 'target_pct_override', label: 'Tgt %', title: 'Target % from fill price' },
  { key: 'quantity', label: 'Qty', title: 'Estimated quantity = floor(Amount ÷ Price)' },
]

export default function CandidatesTable({ candidates, settings, onChange }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('gap_pct')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [search, setSearch] = useState('')

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  function update(idx: number, field: keyof GapCandidate, value: unknown) {
    const copy = candidates.map((c, i) => i === idx ? { ...c, [field]: value } : c)
    onChange(copy)
  }

  function toggleSelect(idx: number) {
    update(idx, 'selected', !candidates[idx].selected)
  }

  function selectAll(v: boolean) {
    onChange(candidates.map(c => ({ ...c, selected: v })))
  }

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return candidates.filter(c =>
      !q ||
      c.tradingsymbol.toLowerCase().includes(q) ||
      (c.sector ?? '').toLowerCase().includes(q) ||
      String(c.gap_pct).includes(q)
    )
  }, [candidates, search])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortKey] as number | string | null
      const bv = b[sortKey] as number | string | null
      if (av == null) return 1
      if (bv == null) return -1
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [filtered, sortKey, sortDir])

  const allSelected = filtered.length > 0 && filtered.every(c => c.selected)
  const defaultSl = settings?.default_sl_pct ?? 1.0
  const defaultTgt = settings?.default_target_pct ?? 1.5

  function spikeClass(spike: number | null): string {
    if (spike == null) return ''
    if (spike >= 2) return 'spike-high'
    if (spike >= 1.5) return 'spike-med'
    return ''
  }

  function depthRowClass(c: GapCandidate): string {
    if (c.preopen_buy_pct == null) return ''
    if (c.preopen_buy_pct >= 60) return 'depth-bull'
    if (c.preopen_buy_pct <= 40) return 'depth-bear'
    return ''
  }

  return (
    <div>
      <div className="section-header" style={{ marginBottom: 8 }}>
        <span className="section-title">Gap Candidates</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="section-count">{sorted.length} stocks</span>
          <div className="search-bar">
            <input
              type="text"
              placeholder="Search symbol / sector…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width: 220 }}
            />
          </div>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 32 }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={e => selectAll(e.target.checked)}
                />
              </th>
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  title={col.title}
                  onClick={() => handleSort(col.key)}
                >
                  {col.label}
                  {sortKey === col.key && (
                    <span style={{ marginLeft: 3 }}>{sortDir === 'asc' ? '↑' : '↓'}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="empty-state">
                  No candidates found. Run a scan first.
                </td>
              </tr>
            )}
            {sorted.map((c) => {
              // Map back to original index for editing
              const origIdx = candidates.indexOf(c)
              const sl = c.sl_pct_override ?? defaultSl
              const tgt = c.target_pct_override ?? defaultTgt
              const qty = computeQty(c)
              const scanTime = c.scanned_at
                ? new Date(c.scanned_at).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })
                : '—'

              return (
                <tr key={c.tradingsymbol} className={depthRowClass(c)}>
                  <td>
                    <input
                      type="checkbox"
                      checked={c.selected}
                      onChange={() => toggleSelect(origIdx)}
                    />
                  </td>
                  <td>
                    <strong>{c.tradingsymbol}</strong>
                    {c.sector && (
                      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{c.sector}</div>
                    )}
                  </td>
                  <td style={{ fontSize: 11 }}>{scanTime}</td>
                  <td className={c.gap_pct < 0 ? 'gap-neg' : 'gap-pos'}>
                    {c.gap_pct >= 0 ? '+' : ''}{fmt(c.gap_pct)}%
                  </td>
                  <td>₹{fmt(c.open_price)}</td>
                  <td>₹{fmt(c.ltp)}</td>
                  <td>{fmtVol(c.volume)}</td>
                  <td>{fmtVol(c.avg_volume_20d)}</td>
                  <td className={spikeClass(c.volume_spike)}>
                    {c.volume_spike != null ? `${fmt(c.volume_spike, 1)}x` : '—'}
                  </td>
                  <td style={{ fontWeight: c.preopen_buy_pct != null && c.preopen_buy_pct >= 60 ? 700 : 400 }}>
                    {c.preopen_buy_pct != null ? `${c.preopen_buy_pct}%` : '—'}
                  </td>
                  <td style={{ fontWeight: c.preopen_sell_pct != null && c.preopen_sell_pct >= 60 ? 700 : 400 }}>
                    {c.preopen_sell_pct != null ? `${c.preopen_sell_pct}%` : '—'}
                  </td>
                  <td>
                    <input
                      type="number"
                      className="cell-input"
                      value={c.investment_amount}
                      min={100}
                      step={1000}
                      onChange={e => update(origIdx, 'investment_amount', Number(e.target.value))}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      className="cell-input"
                      value={c.buy_limit_price ?? c.open_price}
                      min={0}
                      step={0.05}
                      onChange={e => update(origIdx, 'buy_limit_price', Number(e.target.value))}
                    />
                  </td>
                  <td title="Use market order">
                    <input
                      type="checkbox"
                      checked={c.use_market_price}
                      onChange={e => update(origIdx, 'use_market_price', e.target.checked)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      className="cell-input"
                      value={sl}
                      min={0.1}
                      step={0.1}
                      style={{ width: 60 }}
                      onChange={e => update(origIdx, 'sl_pct_override', Number(e.target.value))}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      className="cell-input"
                      value={tgt}
                      min={0.1}
                      step={0.1}
                      style={{ width: 60 }}
                      onChange={e => update(origIdx, 'target_pct_override', Number(e.target.value))}
                    />
                  </td>
                  <td style={{ fontWeight: 600 }}>
                    {qty > 0 ? qty : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
