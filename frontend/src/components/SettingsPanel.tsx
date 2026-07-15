import type { Dispatch, SetStateAction } from 'react'
import { Save } from 'lucide-react'

import type { SettingsPayload } from '../types'

interface Props {
  settings: SettingsPayload | null
  onChange: Dispatch<SetStateAction<SettingsPayload | null>>
  onSave: () => void
}

export function SettingsPanel({ settings, onChange, onSave }: Props) {
  if (!settings) {
    return <div className="panel">Loading settings…</div>
  }

  const updateField = <K extends keyof SettingsPayload>(key: K, value: SettingsPayload[K]) => {
    onChange((current) => (current ? { ...current, [key]: value } : current))
  }

  return (
    <div className="panel settings-panel">
      <div className="section-header">
        <div>
          <h2>Settings</h2>
          <p className="muted">Temporary runtime settings with optional .env write-through for the next restart.</p>
        </div>
      </div>

      <div className="settings-group">
        <h3>Scanner</h3>
        <label>
          <span>Min gap %</span>
          <input type="number" value={settings.min_gap_down_pct} onChange={(event) => updateField('min_gap_down_pct', Number(event.target.value))} />
        </label>
        <label>
          <span>Max gap %</span>
          <input type="number" value={settings.max_gap_down_pct} onChange={(event) => updateField('max_gap_down_pct', Number(event.target.value))} />
        </label>
        <label>
          <span>Min price</span>
          <input type="number" value={settings.min_price} onChange={(event) => updateField('min_price', Number(event.target.value))} />
        </label>
        <label>
          <span>Min volume</span>
          <input type="number" value={settings.min_volume} onChange={(event) => updateField('min_volume', Number(event.target.value))} />
        </label>
        <label>
          <span>Min avg volume 30d</span>
          <input type="number" value={settings.min_avg_volume_30d} onChange={(event) => updateField('min_avg_volume_30d', Number(event.target.value))} />
        </label>
        <label>
          <span>Min market cap</span>
          <input type="number" value={settings.min_market_cap} onChange={(event) => updateField('min_market_cap', Number(event.target.value))} />
        </label>
        <label>
          <span>Excluded sectors</span>
          <input
            type="text"
            value={settings.excluded_sectors.join(', ')}
            onChange={(event) =>
              updateField(
                'excluded_sectors',
                event.target.value
                  .split(',')
                  .map((item) => item.trim())
                  .filter(Boolean),
              )
            }
          />
        </label>
      </div>

      <div className="settings-group">
        <h3>Execution</h3>
        <label>
          <span>Default SL %</span>
          <input type="number" value={settings.default_sl_pct} onChange={(event) => updateField('default_sl_pct', Number(event.target.value))} />
        </label>
        <label>
          <span>Default target %</span>
          <input type="number" value={settings.default_target_pct} onChange={(event) => updateField('default_target_pct', Number(event.target.value))} />
        </label>
        <label>
          <span>Buy buffer %</span>
          <input type="number" value={settings.buy_buffer_pct} onChange={(event) => updateField('buy_buffer_pct', Number(event.target.value))} />
        </label>
        <label>
          <span>Poll interval ms</span>
          <input type="number" value={settings.poll_interval_ms} onChange={(event) => updateField('poll_interval_ms', Number(event.target.value))} />
        </label>
        <label>
          <span>SL delay seconds</span>
          <input type="number" min={0} value={settings.sl_delay_seconds} onChange={(event) => updateField('sl_delay_seconds', Number(event.target.value))} />
        </label>
      </div>

      <div className="settings-group">
        <h3>Scheduled Order Fire</h3>
        <Toggle
          label="Scheduled fire enabled (queue orders and fire at the time below)"
          checked={settings.scheduled_fire_enabled}
          onChange={(value) => updateField('scheduled_fire_enabled', value)}
        />
        <label>
          <span>Fire time (HH:MM:SS IST)</span>
          <input
            type="time"
            step="1"
            value={settings.scheduled_fire_time}
            onChange={(event) => updateField('scheduled_fire_time', event.target.value)}
            style={{ fontVariantNumeric: 'tabular-nums' }}
          />
        </label>
        <p className="muted" style={{ fontSize: '0.75rem', margin: 0 }}>
          When enabled, buy orders placed between 09:08 and this time are queued and fired together at exactly this time.
          Disable to place orders immediately when the button is clicked.
        </p>
      </div>

      <div className="settings-group">
      <h3>Toggles</h3>
      <Toggle
        label="Adopt mobile/web buys"
        checked={settings.adopt_mobile_buy_orders}
        onChange={(value) => updateField('adopt_mobile_buy_orders', value)}
      />
      <Toggle
        label="Place SL order"
        checked={settings.sl_enabled}
        onChange={(value) => updateField('sl_enabled', value)}
      />
      <Toggle
        label="Market sell at SL (disables SL-M order, polls LTP after SL delay)"
        checked={settings.market_sell_sl_enabled}
        onChange={(value) => updateField('market_sell_sl_enabled', value)}
      />
      <Toggle
        label="Auto slice orders"
        checked={settings.auto_slice_orders}
        onChange={(value) => updateField('auto_slice_orders', value)}
      />
    </div>

      <button className="button primary full-width" onClick={onSave}>
        <Save size={16} />
        Save settings
      </button>
    </div>
  )
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="toggle-row">
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  )
}
