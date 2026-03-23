import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import StatCard from './StatCard'
import EquityChart from './EquityChart'
import { formatMoney, formatPct } from '../utils/format'
import './BacktestResults.css'

/*
  BacktestResults — detailed view of a single backtest run.

  Shows:
    1. Summary stat cards (return, win rate, drawdown, ELO change)
    2. Equity curve chart
    3. Drawdown chart
    4. Daily timeline (strategy + SPY % + volatility + news headline)
    5. Filterable trade log

  Props:
    runId: The backtest_runs.id to display
*/

export default function BacktestResults({ runId }) {
  const { data, loading } = useApi(`/api/backtests/${runId}`)
  const [tradeFilter, setTradeFilter] = useState('all') // 'all', 'wins', 'losses'
  const [strategyFilter, setStrategyFilter] = useState('all')

  if (loading || !data) {
    return <div className="card text-muted" style={{ padding: 40, textAlign: 'center' }}>Loading results...</div>
  }

  const { run, daily_results, trades } = data
  if (!run) return <div className="text-red">Backtest not found</div>

  // --- Compute drawdown series from daily equity ---
  const drawdownData = computeDrawdown(daily_results)

  // --- Get unique strategies for the filter ---
  const strategies = [...new Set(trades.map((t) => t.strategy).filter(Boolean))]

  // --- Filter trades ---
  const sellTrades = trades.filter((t) => t.action === 'sell' && t.pnl != null)
  const filteredTrades = sellTrades.filter((t) => {
    if (tradeFilter === 'wins' && t.pnl <= 0) return false
    if (tradeFilter === 'losses' && t.pnl > 0) return false
    if (strategyFilter !== 'all' && t.strategy !== strategyFilter) return false
    return true
  })

  const returnColor = (run.total_return_pct || 0) >= 0 ? 'text-green' : 'text-red'

  return (
    <div className="fade-in">
      <h2 className="page-title">{run.name || `${run.start_date} to ${run.end_date}`}</h2>

      {/* --- Summary Stats --- */}
      <div className="grid-4" style={{ marginBottom: 12 }}>
        <StatCard
          label="Total Return"
          value={`${run.total_return_pct >= 0 ? '+' : ''}${run.total_return_pct?.toFixed(2)}%`}
          sub={formatMoney(run.total_return, true)}
          color={returnColor}
        />
        <StatCard
          label="Win Rate"
          value={`${run.win_rate?.toFixed(1)}%`}
          sub={`${run.total_trades} trades`}
        />
        <StatCard
          label="Max Drawdown"
          value={formatMoney(run.max_drawdown)}
          sub={`${run.max_drawdown_pct?.toFixed(2)}%`}
          color="text-red"
        />
        <StatCard
          label="ELO Change"
          value={run.elo_end != null ? `${run.elo_start?.toFixed(0)} → ${run.elo_end?.toFixed(0)}` : '—'}
          sub={run.elo_end != null
            ? `${run.elo_end - run.elo_start >= 0 ? '+' : ''}${(run.elo_end - run.elo_start).toFixed(0)} pts`
            : undefined}
          color={run.elo_end >= run.elo_start ? 'text-green' : 'text-red'}
        />
      </div>

      {/* --- Extra Stats Row --- */}
      <div className="grid-4" style={{ marginBottom: 12 }}>
        <StatCard label="Avg Win" value={formatMoney(run.avg_win)} color="text-green" />
        <StatCard label="Avg Loss" value={formatMoney(run.avg_loss)} color="text-red" />
        <StatCard label="Profitable Days" value={`${run.profitable_days}`} sub={`of ${(run.profitable_days || 0) + (run.losing_days || 0)}`} />
        <StatCard label="Avg Daily P&L" value={formatMoney(run.avg_daily_pnl, true)} color={(run.avg_daily_pnl || 0) >= 0 ? 'text-green' : 'text-red'} />
      </div>

      {/* --- Charts --- */}
      <div className="grid-2" style={{ marginBottom: 12 }}>
        <div>
          <div className="section-title" style={{ marginBottom: 8 }}>Equity Curve</div>
          <EquityChart
            data={daily_results.map((d) => ({ date: d.date, equity: d.equity }))}
            label="Equity"
            color="#00e676"
          />
        </div>
        <div>
          <div className="section-title" style={{ marginBottom: 8 }}>Drawdown</div>
          <EquityChart
            data={drawdownData}
            label="Drawdown %"
            color="#ff5252"
          />
        </div>
      </div>

      {/* --- Daily Timeline --- */}
      <div className="section-header">
        <span className="section-title">Daily Timeline</span>
      </div>
      <div className="table-container" style={{ marginBottom: 12 }}>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Strategy</th>
              <th>Market</th>
              <th>SPY</th>
              <th>P&L</th>
              <th>Trades</th>
              <th>News</th>
            </tr>
          </thead>
          <tbody>
            {daily_results.map((d) => {
              const pnlColor = d.daily_pnl >= 0 ? 'text-green' : 'text-red'
              const satOut = d.sat_out_flag === 1
              return (
                <tr key={d.date} className={satOut ? 'sat-out-row' : ''}>
                  <td className="text-mono">{d.date}</td>
                  <td>
                    <span className="badge badge-gold" style={{ fontSize: 10 }}>
                      {d.strategy}
                    </span>
                  </td>
                  <td className="text-muted">{d.market_condition}</td>
                  <td className={`text-mono ${(d.spy_change_pct || 0) >= 0 ? 'text-green' : 'text-red'}`}>
                    {d.spy_change_pct != null ? formatPct(d.spy_change_pct) : '—'}
                  </td>
                  <td className={`text-mono ${pnlColor}`}>
                    {formatMoney(d.daily_pnl, true)}
                  </td>
                  <td className="text-mono">{d.trade_count || 0}</td>
                  <td className="news-cell" title={d.news_headline || ''}>
                    {d.news_headline
                      ? d.news_headline.length > 40
                        ? d.news_headline.substring(0, 40) + '...'
                        : d.news_headline
                      : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* --- Trade Log --- */}
      <div className="section-header">
        <span className="section-title">Trade Log</span>
        <div className="trade-filters">
          <select
            className="form-input filter-select"
            value={tradeFilter}
            onChange={(e) => setTradeFilter(e.target.value)}
          >
            <option value="all">All trades</option>
            <option value="wins">Winners only</option>
            <option value="losses">Losers only</option>
          </select>
          <select
            className="form-input filter-select"
            value={strategyFilter}
            onChange={(e) => setStrategyFilter(e.target.value)}
          >
            <option value="all">All strategies</option>
            {strategies.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Price</th>
              <th>Strategy</th>
              <th>P&L</th>
            </tr>
          </thead>
          <tbody>
            {filteredTrades.length === 0 ? (
              <tr><td colSpan={7} className="text-muted" style={{ textAlign: 'center' }}>No trades match filters</td></tr>
            ) : (
              filteredTrades.map((t, i) => {
                const pnlColor = t.pnl >= 0 ? 'text-green' : 'text-red'
                return (
                  <tr key={`${t.timestamp}-${t.symbol}-${i}`}>
                    <td className="text-mono text-muted">{t.timestamp}</td>
                    <td style={{ fontWeight: 600 }}>{t.symbol}</td>
                    <td>
                      <span className={`badge ${t.action === 'buy' ? 'badge-green' : 'badge-red'}`}>
                        {t.action.toUpperCase()}
                      </span>
                    </td>
                    <td className="text-mono">{t.qty}</td>
                    <td className="text-mono">{formatMoney(t.price)}</td>
                    <td className="text-muted">{t.strategy}</td>
                    <td className={`text-mono ${pnlColor}`}>
                      {formatMoney(t.pnl, true)}
                    </td>
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

/*
  Compute a drawdown series from daily equity data.
  Drawdown = how far the equity has fallen from its peak at each point.
*/
function computeDrawdown(dailyResults) {
  if (!dailyResults || dailyResults.length === 0) return []

  let peak = dailyResults[0].equity
  return dailyResults.map((d) => {
    if (d.equity > peak) peak = d.equity
    const dd = ((d.equity - peak) / peak) * 100
    return { date: d.date, equity: dd }
  })
}
