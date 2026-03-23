import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import StatCard from '../components/StatCard'
import EloBadge from '../components/EloBadge'
import PositionsTable from '../components/PositionsTable'
import TradesTable from '../components/TradesTable'
import EquityChart from '../components/EquityChart'
import { formatMoney, formatPct } from '../utils/format'
import './Live.css'

/*
  Live — the home tab. Shows the bot's real-time state.

  This page auto-refreshes every 10 seconds by passing
  { refreshInterval: 10000 } to the useApi hook. The data comes
  from Flask's /api/status endpoint (same as the old dashboard).

  Layout (top to bottom):
    1. Header bar with market status
    2. Stat cards (equity, P&L, target, win rate)
    3. ELO badge + market info
    4. Charts (equity curve, ELO history)
    5. Open positions table
    6. Recent trades table
    7. Panic button
*/

export default function Live() {
  const { data, loading, error } = useApi('/api/status', { refreshInterval: 10000 })
  const { data: historyData } = useApi('/api/equity_history', { refreshInterval: 30000 })
  const [panicLoading, setPanicLoading] = useState(false)

  // Handle the panic button — close all positions
  const handlePanic = async () => {
    if (!window.confirm('Close ALL positions? This cannot be undone.')) return
    setPanicLoading(true)
    try {
      await fetch('/api/override', { method: 'POST' })
    } catch {
      // Non-critical
    }
    setPanicLoading(false)
  }

  if (loading && !data) {
    return (
      <div className="page" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span className="text-muted">Connecting to bot...</span>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="page" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span className="text-red">Connection error: {error}</span>
      </div>
    )
  }

  const s = data || {}
  const rankInfo = s.elo_rank_info || {}
  const pnlColor = s.daily_pnl >= 0 ? 'text-green' : 'text-red'

  return (
    <div className="page fade-in">
      {/* --- Header --- */}
      <div className="live-header">
        <div className="live-logo">TRADING BOT</div>
        <div className="live-status-row">
          <span className={`badge ${s.market_open ? 'badge-green' : 'badge-red'}`}>
            {s.market_open ? 'MARKET OPEN' : 'MARKET CLOSED'}
          </span>
          {s.last_updated && (
            <span className="live-updated text-muted">
              Updated {new Date(s.last_updated).toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* --- Stat Cards --- */}
      <div className="grid-4" style={{ marginBottom: 12 }}>
        <StatCard
          label="Equity"
          value={formatMoney(s.equity)}
          sub={`Cash: ${formatMoney(s.cash)}`}
        />
        <StatCard
          label="Daily P&L"
          value={formatMoney(s.daily_pnl, true)}
          sub={s.daily_pnl_pct != null ? formatPct(s.daily_pnl_pct) : undefined}
          color={pnlColor}
        />
        <StatCard
          label="Daily Target"
          value={formatMoney(s.daily_target)}
          sub={`${s.trade_count || 0} trades today`}
        />
        <StatCard
          label="Win Rate"
          value={s.win_rate != null ? `${s.win_rate.toFixed(1)}%` : '—'}
          sub={s.can_trade ? 'Active' : 'Paused'}
          color={s.can_trade ? 'text-green' : 'text-red'}
        />
      </div>

      {/* --- ELO + Market Info --- */}
      <div className="grid-2" style={{ marginBottom: 12 }}>
        <EloBadge rating={s.elo_rating || 1000} rankInfo={rankInfo} />
        <div className="card">
          <div className="card-label">Market</div>
          <div className="market-info-item">
            <span className="text-muted">Condition</span>
            <span className="badge badge-gold">{s.market_condition || '—'}</span>
          </div>
          <div className="market-info-item" style={{ marginTop: 10 }}>
            <span className="text-muted">Strategy</span>
            <span style={{ fontWeight: 600 }}>{s.active_strategy || '—'}</span>
          </div>
        </div>
      </div>

      {/* --- Charts --- */}
      <div className="grid-2" style={{ marginBottom: 12 }}>
        <div>
          <div className="section-title" style={{ marginBottom: 8 }}>Equity Curve</div>
          <EquityChart
            data={historyData?.equity_history}
            label="Equity"
            color="#00e676"
          />
        </div>
        <div>
          <div className="section-title" style={{ marginBottom: 8 }}>ELO Rating</div>
          <EquityChart
            data={historyData?.elo_history}
            label="ELO"
            color="#ffd740"
          />
        </div>
      </div>

      {/* --- Open Positions --- */}
      <div className="section-header">
        <span className="section-title">Open Positions</span>
        <span className="text-muted" style={{ fontSize: 12 }}>
          {s.positions?.length || 0} held
        </span>
      </div>
      <PositionsTable positions={s.positions} />

      {/* --- Recent Trades --- */}
      <div className="section-header">
        <span className="section-title">Recent Trades</span>
      </div>
      <TradesTable trades={s.recent_trades} />

      {/* --- Panic Button --- */}
      <div className="panic-section">
        <button
          className="btn btn-danger panic-btn"
          onClick={handlePanic}
          disabled={panicLoading}
        >
          {panicLoading ? 'CLOSING...' : 'CLOSE ALL POSITIONS'}
        </button>
      </div>
    </div>
  )
}
