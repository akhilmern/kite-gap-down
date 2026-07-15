import type { AppSettings } from '../types'

interface Props {
  settings: AppSettings
  onChange: (updated: AppSettings) => void
  onSave: () => void
  saving: boolean
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="toggle-wrap" style={{ marginBottom: 10 }}>
      <label className="toggle">
        <input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} />
        <div className="toggle-track" />
      </label>
      <span className="toggle-label">{label}</span>
    </div>
  )
}

function NumInput({ label, value, onChange, min, max, step, unit }: {
  label: string; value: number; onChange: (v: number) => void;
  min?: number; max?: number; step?: number; unit?: string
}) {
  return (
    <div className="input-row">
      <label>{label}{unit && <span style={{ color: 'var(--text-light)', marginLeft: 4 }}>({unit})</span>}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step ?? 0.1}
        onChange={e => onChange(Number(e.target.value))}
      />
    </div>
  )
}

export default function SettingsPanel({ settings, onChange, onSave, saving }: Props) {
  function set<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    onChange({ ...settings, [key]: value })
  }

  return (
    <div className="settings-panel">
      {/* ---- Scanner ---- */}
      <h3>Scanner Filters</h3>
      <NumInput label="Min Gap Down %" value={settings.min_gap_down_pct} step={0.5}
        onChange={v => set('min_gap_down_pct', v)} />
      <NumInput label="Max Gap Down %" value={settings.max_gap_down_pct} step={0.5}
        onChange={v => set('max_gap_down_pct', v)} />
      <NumInput label="Min Price" value={settings.min_price} step={10} unit="₹"
        onChange={v => set('min_price', v)} />
      <NumInput label="Min Volume" value={settings.min_volume} step={5000} unit="shares"
        onChange={v => set('min_volume', v)} />
      <NumInput label="Min Avg Volume 30D" value={settings.min_avg_volume_30d} step={5000} unit="shares"
        onChange={v => set('min_avg_volume_30d', v)} />
      <div className="input-row">
        <label>Min Market Cap</label>
        <input
          type="text"
          value={settings.min_market_cap}
          placeholder="e.g. 2B"
          onChange={e => set('min_market_cap', e.target.value)}
        />
      </div>
      <div className="input-row">
        <label>Excluded Sectors (comma-separated)</label>
        <input
          type="text"
          value={settings.excluded_sectors.join(', ')}
          placeholder="e.g. Health, Pharma"
          onChange={e => set('excluded_sectors', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
        />
      </div>

      {/* ---- Execution ---- */}
      <h3>Execution</h3>
      <NumInput label="Default SL %" value={settings.default_sl_pct} step={0.1} unit="%"
        onChange={v => set('default_sl_pct', v)} />
      <NumInput label="Default Target %" value={settings.default_target_pct} step={0.1} unit="%"
        onChange={v => set('default_target_pct', v)} />
      <NumInput label="Buy Buffer %" value={settings.buy_buffer_pct} step={0.05} unit="%"
        onChange={v => set('buy_buffer_pct', v)} />
      <NumInput label="SL Delay" value={settings.sl_delay_seconds} step={5} unit="seconds"
        onChange={v => set('sl_delay_seconds', v)} />
      <NumInput label="Poll Interval" value={settings.poll_interval_ms} step={1000} unit="ms"
        onChange={v => set('poll_interval_ms', v)} />
      <NumInput label="Order Retries" value={settings.max_order_placement_retries} step={1}
        onChange={v => set('max_order_placement_retries', v)} />

      {/* ---- Scheduled Fire ---- */}
      <h3>Scheduled Fire</h3>
      <Toggle
        label="Scheduled Fire Enabled"
        value={settings.scheduled_fire_enabled}
        onChange={v => set('scheduled_fire_enabled', v)}
      />
      <div className="input-row">
        <label>Fire Time (IST)</label>
        <input
          type="text"
          value={settings.scheduled_fire_time}
          placeholder="HH:MM:SS"
          onChange={e => set('scheduled_fire_time', e.target.value)}
        />
      </div>

      {/* ---- Feature Toggles ---- */}
      <h3>Feature Toggles</h3>
      <Toggle label="Adopt Mobile Buy Orders" value={settings.adopt_mobile_buy_orders}
        onChange={v => set('adopt_mobile_buy_orders', v)} />
      <Toggle label="Place SL-M Orders" value={settings.sl_enabled}
        onChange={v => set('sl_enabled', v)} />
      <Toggle label="Market-Sell SL (LTP polling)" value={settings.market_sell_sl_enabled}
        onChange={v => set('market_sell_sl_enabled', v)} />
      <Toggle label="Auto-Slice Orders" value={settings.auto_slice_orders}
        onChange={v => set('auto_slice_orders', v)} />
      <Toggle label="Disable Backup Poller" value={settings.disable_backup_poller}
        onChange={v => set('disable_backup_poller', v)} />
      <Toggle label="Write Settings to .env" value={settings.write_env_from_ui}
        onChange={v => set('write_env_from_ui', v)} />

      <hr className="divider" />
      <button
        className="btn btn-primary"
        style={{ width: '100%' }}
        onClick={onSave}
        disabled={saving}
      >
        {saving ? <><span className="spinner" /> Saving…</> : '💾  Save Settings'}
      </button>
    </div>
  )
}
