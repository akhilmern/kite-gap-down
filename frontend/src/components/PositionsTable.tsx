import type { TrackedPosition } from '../types'

interface Props {
  positions: TrackedPosition[]
}

export function PositionsTable({ positions }: Props) {
  return (
    <div className="table-wrap">
      <table className="data-table positions-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Source</th>
            <th>Buy Status</th>
            <th>Entry Time</th>
            <th>Qty</th>
            <th>Avg Fill</th>
            <th>SL Trigger</th>
            <th>SL Placed At</th>
            <th>SL Status</th>
            <th>Target Price</th>
            <th>Target Status</th>
            <th>Exit Leg</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {positions.length === 0 ? (
            <tr>
              <td colSpan={13} className="empty-cell">
                No tracked positions yet.
              </td>
            </tr>
          ) : (
            positions.map((position) => (
              <tr key={position.buy_order_id ?? position.tradingsymbol}>
                <td>{position.tradingsymbol}</td>
                <td>{position.order_source}</td>
                <td><StatusChip status={position.buy_status} /></td>
                <td className="time-cell">{formatTime(position.entry_time)}</td>
                <td>{position.filled_quantity || position.quantity_requested}</td>
                <td>{formatPrice(position.average_fill_price)}</td>
                <td>{formatPrice(position.sl_trigger_price)}</td>
                <td className="time-cell">{formatTime(position.sl_placed_at)}</td>
                <td><StatusChip status={position.sl_status} /></td>
                <td>{formatPrice(position.target_price)}</td>
                <td><StatusChip status={position.target_status} /></td>
                <td>{position.exit_leg_filled ?? '—'}</td>
                <td className="error-text">{position.error ?? '—'}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

function StatusChip({ status }: { status: TrackedPosition['buy_status'] }) {
  const tone = {
    COMPLETE: 'success',
    OPEN: 'primary',
    REJECTED: 'danger',
    CANCELLED: 'danger',
    PENDING: 'muted',
    UNKNOWN: 'muted',
  }[status]

  return <span className={`status-chip ${tone}`}>{status}</span>
}

function formatPrice(value?: number | null) {
  return value == null ? '—' : `₹${value.toFixed(2)}`
}

function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  } catch {
    return '—'
  }
}
