import type { TrackedPosition, OrderStatus, LegType } from '../types'

interface Props {
  positions: Record<string, TrackedPosition>
}

function statusChip(status: OrderStatus | null | undefined): React.ReactNode {
  if (!status) return <span className="chip chip-pending">—</span>
  const map: Record<string, string> = {
    COMPLETE: 'chip-complete',
    OPEN: 'chip-open',
    PENDING: 'chip-pending',
    REJECTED: 'chip-rejected',
    CANCELLED: 'chip-cancelled',
    UNKNOWN: 'chip-pending',
  }
  return <span className={`chip ${map[status] ?? 'chip-pending'}`}>{status}</span>
}

function exitChip(leg: LegType | null): React.ReactNode {
  if (!leg) return <span className="chip chip-pending">—</span>
  if (leg === 'STOP_LOSS') return <span className="chip chip-sl">SL HIT</span>
  if (leg === 'TARGET') return <span className="chip chip-target">TARGET HIT</span>
  return <span className="chip chip-pending">{leg}</span>
}

function sourceChip(source: string): React.ReactNode {
  const map: Record<string, string> = {
    API: 'chip-open',
    MOBILE: 'chip-pending',
    WEB: 'chip-pending',
  }
  return <span className={`chip ${map[source] ?? 'chip-pending'}`}>{source}</span>
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

function fmtPrice(n: number | null | undefined): string {
  if (n == null || n === 0) return '—'
  return `₹${n.toFixed(2)}`
}

export default function PositionsTable({ positions }: Props) {
  const entries = Object.values(positions)

  return (
    <div>
      <div className="section-header" style={{ marginBottom: 8 }}>
        <span className="section-title">Tracked Positions</span>
        <span className="section-count">{entries.length} positions</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Source</th>
              <th>Buy Status</th>
              <th>Entry Time</th>
              <th>Qty</th>
              <th>Avg Fill</th>
              <th>SL Trigger</th>
              <th>SL Placed</th>
              <th>SL Status</th>
              <th>Target Price</th>
              <th>Tgt Status</th>
              <th>Exit Leg</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && (
              <tr>
                <td colSpan={13} className="empty-state">
                  No positions tracked yet.
                </td>
              </tr>
            )}
            {entries.map(pos => (
              <tr key={pos.tradingsymbol}>
                <td><strong>{pos.tradingsymbol}</strong></td>
                <td>{sourceChip(pos.source)}</td>
                <td>{statusChip(pos.buy_status)}</td>
                <td style={{ fontSize: 12 }}>{fmtTime(pos.entry_time)}</td>
                <td>{pos.filled_quantity || '—'}</td>
                <td>{fmtPrice(pos.average_fill_price)}</td>
                <td style={{ color: 'var(--danger)', fontWeight: 600 }}>
                  {fmtPrice(pos.sl_trigger_price)}
                </td>
                <td style={{ fontSize: 11 }}>{fmtTime(pos.sl_placed_at)}</td>
                <td>{statusChip(pos.sl_status)}</td>
                <td style={{ color: 'var(--success)', fontWeight: 600 }}>
                  {fmtPrice(pos.target_price)}
                </td>
                <td>{statusChip(pos.target_status)}</td>
                <td>{exitChip(pos.exit_leg_filled)}</td>
                <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {pos.error
                    ? <span style={{ color: 'var(--danger)', fontSize: 11 }} title={pos.error}>⚠ {pos.error.slice(0, 30)}</span>
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
