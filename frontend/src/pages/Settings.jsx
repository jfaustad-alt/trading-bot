import { useState, useEffect, useCallback } from 'react'
import { useApi } from '../hooks/useApi'
import { formatMoney } from '../utils/format'
import './Settings.css'

/*
  Settings page — edit bot parameters with safety checks.

  HOW THE BACKTEST-BEFORE-APPLY FLOW WORKS:
    1. User edits a setting (e.g., changes risk from 1% to 2%).
    2. The "pending changes" bar appears at the bottom.
    3. User clicks "Compare" → two backtests start (old vs. new settings).
    4. User clicks "Apply" → changes are saved to the bot.
    5. User clicks "Discard" → changes are thrown away.

  This prevents blind parameter changes — you always see the impact first.
*/

export default function Settings() {
  // Load current settings from the API.
  const { data: currentSettings, refetch } = useApi('/api/settings')

  // Local state for edited values (starts as a copy of current settings).
  const [edited, setEdited] = useState(null)
  const [saving, setSaving] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [compareResult, setCompareResult] = useState(null)
  const [message, setMessage] = useState(null)

  // Initialize edited state when settings load.
  useEffect(() => {
    if (currentSettings && !edited) {
      setEdited({ ...currentSettings })
    }
  }, [currentSettings, edited])

  // Check if any values have changed.
  const hasChanges = edited && currentSettings && (
    JSON.stringify(edited) !== JSON.stringify(currentSettings)
  )

  // Get what changed (for display).
  const getChanges = useCallback(() => {
    if (!edited || !currentSettings) return {}
    const changes = {}
    for (const key of Object.keys(edited)) {
      if (key === 'stop_loss_atr_multipliers') {
        const currentATR = currentSettings[key] || {}
        const editedATR = edited[key] || {}
        for (const strat of Object.keys(editedATR)) {
          if (editedATR[strat] !== currentATR[strat]) {
            changes[`atr_${strat}`] = {
              from: currentATR[strat],
              to: editedATR[strat],
            }
          }
        }
      } else if (key === 'trading_windows') {
        if (JSON.stringify(edited[key]) !== JSON.stringify(currentSettings[key])) {
          changes[key] = { from: currentSettings[key], to: edited[key] }
        }
      } else if (edited[key] !== currentSettings[key]) {
        changes[key] = { from: currentSettings[key], to: edited[key] }
      }
    }
    return changes
  }, [edited, currentSettings])

  // Update a simple setting.
  const updateSetting = (key, value) => {
    setEdited(prev => ({ ...prev, [key]: value }))
    setCompareResult(null)
  }

  // Update an ATR multiplier.
  const updateATR = (strategy, value) => {
    setEdited(prev => ({
      ...prev,
      stop_loss_atr_multipliers: {
        ...prev.stop_loss_atr_multipliers,
        [strategy]: value,
      },
    }))
    setCompareResult(null)
  }

  // Run comparison backtest.
  const runCompare = useCallback(async () => {
    if (!hasChanges) return
    setComparing(true)
    setCompareResult(null)
    try {
      const changes = {}
      for (const [key, val] of Object.entries(getChanges())) {
        if (key.startsWith('atr_')) {
          const strat = key.replace('atr_', '')
          if (!changes.stop_loss_atr_multipliers) changes.stop_loss_atr_multipliers = {}
          changes.stop_loss_atr_multipliers[strat] = val.to
        } else if (key === 'trading_windows') {
          changes[key] = val.to
        } else {
          changes[key] = val.to
        }
      }

      const res = await fetch('/api/settings/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ changes }),
      })
      const data = await res.json()
      setCompareResult(data)
      setMessage({ type: 'info', text: 'Comparison backtests started. Check the Backtests tab for results.' })
    } catch {
      setMessage({ type: 'error', text: 'Failed to start comparison.' })
    } finally {
      setComparing(false)
    }
  }, [hasChanges, getChanges])

  // Apply changes.
  const applyChanges = useCallback(async () => {
    if (!hasChanges) return
    setSaving(true)
    try {
      const changes = {}
      for (const [key, val] of Object.entries(getChanges())) {
        if (key.startsWith('atr_')) {
          const strat = key.replace('atr_', '')
          if (!changes.stop_loss_atr_multipliers) changes.stop_loss_atr_multipliers = {}
          changes.stop_loss_atr_multipliers[strat] = val.to
        } else if (key === 'trading_windows') {
          changes[key] = val.to
        } else {
          changes[key] = val.to
        }
      }

      await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
      })
      refetch()
      setEdited(null) // Will re-initialize from refetched data.
      setCompareResult(null)
      setMessage({ type: 'success', text: 'Settings applied successfully.' })
    } catch {
      setMessage({ type: 'error', text: 'Failed to save settings.' })
    } finally {
      setSaving(false)
    }
  }, [hasChanges, getChanges, refetch])

  // Discard changes.
  const discardChanges = () => {
    setEdited(currentSettings ? { ...currentSettings } : null)
    setCompareResult(null)
    setMessage(null)
  }

  // Reset to defaults.
  const resetDefaults = async () => {
    setSaving(true)
    try {
      await fetch('/api/settings/reset', { method: 'POST' })
      refetch()
      setEdited(null)
      setCompareResult(null)
      setMessage({ type: 'success', text: 'Settings reset to defaults.' })
    } catch {
      setMessage({ type: 'error', text: 'Failed to reset settings.' })
    } finally {
      setSaving(false)
    }
  }

  if (!edited) {
    return (
      <div className="page fade-in">
        <h1 className="page-title">Settings</h1>
        <div className="card text-muted" style={{ textAlign: 'center', padding: 24 }}>
          Loading settings...
        </div>
      </div>
    )
  }

  const changes = getChanges()
  const changeCount = Object.keys(changes).length

  return (
    <div className="page fade-in">
      <div className="settings-header">
        <h1 className="page-title">Settings</h1>
        <button className="reset-btn" onClick={resetDefaults} disabled={saving}>
          Reset Defaults
        </button>
      </div>

      {message && (
        <div className={`settings-message message-${message.type}`}>
          {message.text}
          <button className="message-dismiss" onClick={() => setMessage(null)}>&times;</button>
        </div>
      )}

      {/* --- Risk Management --- */}
      <div className="section-header">
        <span className="section-title">Risk Management</span>
      </div>

      <div className="settings-group">
        <SettingRow
          label="Risk Per Trade"
          help="Maximum percentage of your portfolio risked on each trade"
          value={edited.risk_per_trade_pct}
          suffix="%"
          displayMultiplier={100}
          min={0.1}
          max={10}
          step={0.1}
          onChange={(v) => updateSetting('risk_per_trade_pct', v / 100)}
          changed={changes.risk_per_trade_pct}
        />
        <SettingRow
          label="Max Open Positions"
          help="Maximum number of stocks held at the same time"
          value={edited.max_open_positions}
          min={1}
          max={50}
          step={1}
          onChange={(v) => updateSetting('max_open_positions', v)}
          changed={changes.max_open_positions}
          isInteger
        />
        <SettingRow
          label="Daily Profit Target"
          help="Stop trading after making this much profit in a day"
          value={edited.daily_profit_target}
          prefix="$"
          min={10}
          max={10000}
          step={10}
          onChange={(v) => updateSetting('daily_profit_target', v)}
          changed={changes.daily_profit_target}
        />
        <SettingRow
          label="Daily Loss Limit"
          help="Stop trading after losing this much in a day"
          value={edited.daily_loss_limit}
          prefix="$"
          min={10}
          max={10000}
          step={10}
          onChange={(v) => updateSetting('daily_loss_limit', v)}
          changed={changes.daily_loss_limit}
        />
        <SettingRow
          label="Target Increase Amount"
          help="How much the daily target increases after a winning streak"
          value={edited.target_increase_amount}
          prefix="$"
          min={0}
          max={500}
          step={5}
          onChange={(v) => updateSetting('target_increase_amount', v)}
          changed={changes.target_increase_amount}
        />
        <SettingRow
          label="Target Increase Streak"
          help="Number of consecutive profitable days needed to increase the target"
          value={edited.target_increase_streak}
          suffix=" days"
          min={1}
          max={30}
          step={1}
          onChange={(v) => updateSetting('target_increase_streak', v)}
          changed={changes.target_increase_streak}
          isInteger
        />
      </div>

      {/* --- Stop Loss ATR Multipliers --- */}
      <div className="section-header">
        <span className="section-title">Stop Loss (ATR Multipliers)</span>
      </div>
      <p className="settings-help-text">
        ATR = Average True Range. Higher multiplier = wider stop loss (more room to move).
        Lower = tighter stop (exits faster).
      </p>

      <div className="settings-group">
        {Object.entries(edited.stop_loss_atr_multipliers).map(([strategy, value]) => (
          <SettingRow
            key={strategy}
            label={strategy.replace('_', ' ')}
            value={value}
            suffix="x"
            min={0.5}
            max={5.0}
            step={0.1}
            onChange={(v) => updateATR(strategy, v)}
            changed={changes[`atr_${strategy}`]}
          />
        ))}
      </div>

      {/* --- Trading Windows --- */}
      <div className="section-header">
        <span className="section-title">Trading Windows (ET)</span>
      </div>
      <p className="settings-help-text">
        Time windows when the bot is allowed to trade (US Eastern Time).
      </p>

      <div className="settings-group">
        {edited.trading_windows.map((window, i) => (
          <div key={i} className="window-row">
            <span className="window-label">Window {i + 1}</span>
            <input
              type="time"
              className="time-input"
              value={window.start}
              onChange={(e) => {
                const newWindows = [...edited.trading_windows]
                newWindows[i] = { ...newWindows[i], start: e.target.value }
                updateSetting('trading_windows', newWindows)
              }}
            />
            <span className="window-separator">to</span>
            <input
              type="time"
              className="time-input"
              value={window.end}
              onChange={(e) => {
                const newWindows = [...edited.trading_windows]
                newWindows[i] = { ...newWindows[i], end: e.target.value }
                updateSetting('trading_windows', newWindows)
              }}
            />
          </div>
        ))}
      </div>

      {/* --- Pending Changes Bar --- */}
      {hasChanges && (
        <div className="changes-bar">
          <div className="changes-summary">
            <span className="changes-count">{changeCount} change{changeCount !== 1 ? 's' : ''}</span>
            <div className="changes-list">
              {Object.entries(changes).map(([key, val]) => (
                <span key={key} className="change-chip">
                  {key.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          </div>
          <div className="changes-actions">
            <button className="btn-compare" onClick={runCompare} disabled={comparing}>
              {comparing ? 'Starting...' : 'Compare'}
            </button>
            <button className="btn-apply" onClick={applyChanges} disabled={saving}>
              {saving ? 'Saving...' : 'Apply'}
            </button>
            <button className="btn-discard" onClick={discardChanges}>
              Discard
            </button>
          </div>
        </div>
      )}

      {/* --- Compare Results --- */}
      {compareResult && (
        <div className="card compare-info" style={{ marginTop: 12 }}>
          <p className="text-muted" style={{ fontSize: 12 }}>
            Comparison backtests started. Go to the{' '}
            <strong>Backtests</strong> tab to see results:
          </p>
          <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
            <span className="badge badge-gold">Current #{compareResult.current_run_id}</span>
            <span className="badge badge-green">Proposed #{compareResult.proposed_run_id}</span>
          </div>
        </div>
      )}

      {/* Spacer for the changes bar */}
      {hasChanges && <div style={{ height: 80 }} />}
    </div>
  )
}


/*
  SettingRow — a single editable setting with label, input, and change indicator.

  Props:
    label: Display name
    help: Tooltip/description text
    value: Current value (number)
    onChange: Callback with the new value
    changed: Object { from, to } if this setting was changed (or undefined)
    prefix: Text before the value (e.g., "$")
    suffix: Text after the value (e.g., "%")
    displayMultiplier: Multiply value for display (e.g., 100 for percentages)
    min, max, step: Input constraints
    isInteger: Round to integer
*/
function SettingRow({
  label, help, value, onChange, changed,
  prefix = '', suffix = '', displayMultiplier = 1,
  min, max, step, isInteger = false,
}) {
  const displayValue = Math.round(value * displayMultiplier * 100) / 100

  const handleChange = (e) => {
    let raw = parseFloat(e.target.value)
    if (isNaN(raw)) return
    if (isInteger) raw = Math.round(raw)
    // Convert display value back to actual value.
    const actual = raw / displayMultiplier
    onChange(actual)
  }

  return (
    <div className={`setting-row ${changed ? 'setting-changed' : ''}`}>
      <div className="setting-info">
        <span className="setting-label">{label}</span>
        {help && <span className="setting-help">{help}</span>}
      </div>
      <div className="setting-input-wrap">
        {prefix && <span className="setting-prefix">{prefix}</span>}
        <input
          type="number"
          className="setting-input"
          value={displayValue}
          min={min}
          max={max}
          step={step}
          onChange={handleChange}
        />
        {suffix && <span className="setting-suffix">{suffix}</span>}
      </div>
      {changed && (
        <div className="setting-diff">
          <span className="text-red">{prefix}{typeof changed.from === 'number' ? (changed.from * displayMultiplier).toFixed(step < 1 ? 1 : 0) : JSON.stringify(changed.from)}{suffix}</span>
          <span className="change-arrow">&rarr;</span>
          <span className="text-green">{prefix}{typeof changed.to === 'number' ? (changed.to * displayMultiplier).toFixed(step < 1 ? 1 : 0) : JSON.stringify(changed.to)}{suffix}</span>
        </div>
      )}
    </div>
  )
}
