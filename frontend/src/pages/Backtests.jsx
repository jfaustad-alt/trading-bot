import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import BacktestResults from '../components/BacktestResults'
import BacktestCompare from '../components/BacktestCompare'
import { formatMoney } from '../utils/format'
import './Backtests.css'

/*
  Backtests page — run, view, and compare backtests.

  Three sections:
    1. Run form — date picker (manual + presets) and Run button
    2. Queue — running backtests with progress
    3. Results — list of completed backtests, click to view details
*/

// Preset scenarios — important market events for stress-testing.
// Each one fills in the date picker so you don't have to remember dates.
const PRESETS = [
  { label: 'COVID Crash',      start: '2020-02-19', end: '2020-04-30', desc: 'Market crash & recovery' },
  { label: '2020 Recovery',    start: '2020-05-01', end: '2020-12-31', desc: 'Post-COVID bull run' },
  { label: '2021 Bull Run',    start: '2021-01-01', end: '2021-12-31', desc: 'Meme stocks, crypto hype' },
  { label: '2022 Bear Market', start: '2022-01-01', end: '2022-10-15', desc: 'Fed rate hikes, inflation' },
  { label: '2022 Recovery',    start: '2022-10-15', end: '2023-06-30', desc: 'Market bottomed, slow climb' },
  { label: '2023 AI Rally',    start: '2023-01-01', end: '2023-12-31', desc: 'AI/tech-led bull market' },
  { label: 'Russia-Ukraine',   start: '2022-02-01', end: '2022-05-31', desc: 'War, energy crisis, volatility' },
  { label: '2024 Election',    start: '2024-09-01', end: '2024-12-31', desc: 'US election period' },
]

export default function Backtests() {
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [name, setName] = useState('')
  const [capital, setCapital] = useState(100000)
  const [submitting, setSubmitting] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [compareMode, setCompareMode] = useState(false)
  const [compareIds, setCompareIds] = useState([])

  // Poll for backtest list (includes running status).
  const { data, refetch } = useApi('/api/backtests', { refreshInterval: 3000 })

  const backtests = data?.backtests || []
  const running = data?.running || []

  // Apply a preset scenario.
  const applyPreset = (preset) => {
    setStartDate(preset.start)
    setEndDate(preset.end)
    setName(preset.label)
  }

  // Submit a new backtest.
  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!startDate || !endDate) return

    setSubmitting(true)
    try {
      const resp = await fetch('/api/backtests/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          name: name || `${startDate} to ${endDate}`,
          capital,
        }),
      })
      if (resp.ok) {
        // Clear form and refresh list.
        setName('')
        refetch()
      }
    } catch {
      // Handle error silently.
    }
    setSubmitting(false)
  }

  // Toggle a backtest for comparison.
  const toggleCompare = (id) => {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= 4) return prev // Max 4
      return [...prev, id]
    })
  }

  // If viewing a specific backtest result.
  if (selectedRunId && !compareMode) {
    return (
      <div className="page fade-in">
        <button
          className="back-btn"
          onClick={() => setSelectedRunId(null)}
        >
          &larr; Back to list
        </button>
        <BacktestResults runId={selectedRunId} />
      </div>
    )
  }

  // If in compare mode.
  if (compareMode && compareIds.length >= 2) {
    return (
      <div className="page fade-in">
        <button
          className="back-btn"
          onClick={() => { setCompareMode(false); setCompareIds([]) }}
        >
          &larr; Exit comparison
        </button>
        <BacktestCompare runIds={compareIds} />
      </div>
    )
  }

  return (
    <div className="page fade-in">
      <h1 className="page-title">Backtests</h1>

      {/* --- Run Form --- */}
      <form className="backtest-form card" onSubmit={handleSubmit}>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Start Date</label>
            <input
              type="date"
              className="form-input"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label className="form-label">End Date</label>
            <input
              type="date"
              className="form-input"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              required
            />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group" style={{ flex: 2 }}>
            <label className="form-label">Name (optional)</label>
            <input
              type="text"
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. COVID Crash Test"
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Capital</label>
            <input
              type="number"
              className="form-input"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              min={1000}
              step={1000}
            />
          </div>
        </div>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting || !startDate || !endDate}
          style={{ width: '100%', marginTop: 8 }}
        >
          {submitting ? 'Starting...' : 'Run Backtest'}
        </button>
      </form>

      {/* --- Presets --- */}
      <div className="section-header">
        <span className="section-title">Scenario Presets</span>
      </div>
      <div className="presets-grid">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            className="preset-btn card"
            onClick={() => applyPreset(p)}
          >
            <div className="preset-label">{p.label}</div>
            <div className="preset-desc">{p.desc}</div>
            <div className="preset-dates text-muted">
              {p.start} to {p.end}
            </div>
          </button>
        ))}
      </div>

      {/* --- Running --- */}
      {running.length > 0 && (
        <>
          <div className="section-header">
            <span className="section-title">Running</span>
          </div>
          {running.map((r) => (
            <div key={r.run_id} className="card running-card">
              <div className="running-name">{r.name || 'Backtest'}</div>
              <div className="running-info text-muted">
                {r.start_date} to {r.end_date}
              </div>
              <div className="running-progress">
                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{
                      width: r.estimated_seconds > 0
                        ? `${Math.min(100, (r.elapsed_seconds / r.estimated_seconds) * 100)}%`
                        : '50%',
                      background: 'var(--blue)',
                      animation: 'pulse 1.5s infinite',
                    }}
                  />
                </div>
                <span className="text-muted" style={{ fontSize: 11, marginTop: 4 }}>
                  ~{Math.ceil(r.estimated_seconds - r.elapsed_seconds)}s remaining
                  ({r.estimated_days} trading days)
                </span>
              </div>
            </div>
          ))}
        </>
      )}

      {/* --- Completed --- */}
      <div className="section-header">
        <span className="section-title">Completed</span>
        {compareIds.length >= 2 && (
          <button
            className="btn btn-primary"
            style={{ padding: '6px 14px', fontSize: 12 }}
            onClick={() => setCompareMode(true)}
          >
            Compare ({compareIds.length})
          </button>
        )}
      </div>
      {backtests.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: 24 }}>
          <span className="text-muted">No backtests yet. Run one above!</span>
        </div>
      ) : (
        <div className="backtest-list">
          {backtests.map((bt) => {
            const isSelected = compareIds.includes(bt.id)
            const returnColor = (bt.total_return_pct || 0) >= 0 ? 'text-green' : 'text-red'
            return (
              <div
                key={bt.id}
                className={`card backtest-card ${isSelected ? 'backtest-card-selected' : ''}`}
              >
                <div className="backtest-card-header" onClick={() => setSelectedRunId(bt.id)}>
                  <div>
                    <div className="backtest-card-name">
                      {bt.name || `${bt.start_date} to ${bt.end_date}`}
                    </div>
                    <div className="text-muted" style={{ fontSize: 11 }}>
                      {bt.start_date} to {bt.end_date}
                      {bt.duration_seconds && ` · ${bt.duration_seconds.toFixed(0)}s`}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className={`backtest-card-return ${returnColor}`}>
                      {bt.total_return_pct != null ? `${bt.total_return_pct >= 0 ? '+' : ''}${bt.total_return_pct.toFixed(2)}%` : '—'}
                    </div>
                    <div className="text-muted" style={{ fontSize: 11 }}>
                      {bt.win_rate != null ? `${bt.win_rate.toFixed(0)}% win` : ''}
                      {bt.total_trades != null ? ` · ${bt.total_trades} trades` : ''}
                    </div>
                  </div>
                </div>
                <div className="backtest-card-footer">
                  <label className="compare-check">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleCompare(bt.id)}
                    />
                    <span>Compare</span>
                  </label>
                  <span className={`badge ${bt.status === 'completed' ? 'badge-green' : 'badge-red'}`}>
                    {bt.status}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
