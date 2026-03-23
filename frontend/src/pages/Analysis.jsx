import { useState, useCallback } from 'react'
import { useApi } from '../hooks/useApi'
import StatCard from '../components/StatCard'
import { formatMoney } from '../utils/format'
import { Bar } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Tooltip,
} from 'chart.js'
import './Analysis.css'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

/*
  Analysis page — layered UI for understanding bot performance.

  Sections (top to bottom):
    1. Source toggle (Live / Backtest)
    2. Overview stat cards
    3. Strategy breakdown bars
    4. Strategy x Market Condition heatmap
    5. Day-of-week pattern chart
    6. Symbol breakdown table
    7. Streak analysis
    8. Bot journal (observations from rule-based checks)
*/

export default function Analysis() {
  const [source, setSource] = useState('live')
  const [analyzing, setAnalyzing] = useState(false)
  const [deepResult, setDeepResult] = useState(null)

  const { data: overview } = useApi(`/api/analysis/overview?source=${source}`)
  const { data: stratData } = useApi(`/api/analysis/strategies?source=${source}`)
  const { data: heatmapData } = useApi(`/api/analysis/heatmap?source=${source}`)
  const { data: patterns } = useApi(`/api/analysis/patterns?source=${source}`)
  const { data: journal } = useApi(`/api/analysis/journal?source=${source}`)
  const { data: proposalsData, refetch: refetchProposals } = useApi('/api/proposals')

  const strategies = stratData?.strategies || []
  const dayOfWeek = patterns?.day_of_week || []
  const symbols = patterns?.symbols || []
  const streaks = patterns?.streaks || {}
  const observations = journal?.observations || []
  const proposals = proposalsData?.proposals || []

  // Trigger Claude deep analysis.
  const runDeepAnalysis = useCallback(async () => {
    setAnalyzing(true)
    setDeepResult(null)
    try {
      const res = await fetch('/api/analysis/deep', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
      })
      const data = await res.json()
      setDeepResult(data)
      refetchProposals()
    } catch (err) {
      setDeepResult({ error: err.message, observations: [], proposals: [] })
    } finally {
      setAnalyzing(false)
    }
  }, [source, refetchProposals])

  // Handle proposal actions (approve/reject/backtest).
  const handleProposalAction = useCallback(async (proposalId, action) => {
    try {
      await fetch(`/api/proposals/${proposalId}/${action}`, { method: 'POST' })
      refetchProposals()
    } catch (err) {
      console.error(`Failed to ${action} proposal:`, err)
    }
  }, [refetchProposals])

  return (
    <div className="page fade-in">
      <div className="analysis-header">
        <h1 className="page-title">Analysis</h1>
        <div className="source-toggle">
          <button
            className={`toggle-btn ${source === 'live' ? 'toggle-active' : ''}`}
            onClick={() => setSource('live')}
          >
            Live
          </button>
          <button
            className={`toggle-btn ${source === 'backtest' ? 'toggle-active' : ''}`}
            onClick={() => setSource('backtest')}
          >
            Backtest
          </button>
        </div>
      </div>

      {/* --- Overview --- */}
      <div className="grid-4" style={{ marginBottom: 12 }}>
        <StatCard
          label="Total P&L"
          value={formatMoney(overview?.total_pnl, true)}
          color={(overview?.total_pnl || 0) >= 0 ? 'text-green' : 'text-red'}
        />
        <StatCard
          label="Win Rate"
          value={overview ? `${overview.win_rate}%` : '—'}
          sub={`${overview?.total_trades || 0} trades`}
        />
        <StatCard
          label="Avg Daily P&L"
          value={formatMoney(overview?.avg_daily_pnl, true)}
          color={(overview?.avg_daily_pnl || 0) >= 0 ? 'text-green' : 'text-red'}
        />
        <StatCard
          label="Streak"
          value={overview ? `${overview.current_streak} days` : '—'}
          sub={overview?.improving ? 'Improving' : 'Needs work'}
          color={overview?.improving ? 'text-green' : 'text-muted'}
        />
      </div>

      {/* --- Best / Worst Day --- */}
      {overview?.best_day && (
        <div className="grid-2" style={{ marginBottom: 12 }}>
          <div className="card">
            <div className="card-label">Best Day</div>
            <div className="card-value text-green">{formatMoney(overview.best_day.pnl, true)}</div>
            <div className="card-sub">{overview.best_day.date}</div>
          </div>
          <div className="card">
            <div className="card-label">Worst Day</div>
            <div className="card-value text-red">{formatMoney(overview.worst_day?.pnl, true)}</div>
            <div className="card-sub">{overview.worst_day?.date}</div>
          </div>
        </div>
      )}

      {/* --- Strategy Breakdown --- */}
      <div className="section-header">
        <span className="section-title">Strategy Performance</span>
      </div>
      {strategies.length > 0 ? (
        <div className="strategy-cards">
          {strategies.map((s) => (
            <div key={s.name} className="card strategy-card">
              <div className="strategy-name">{s.name}</div>
              <div className="strategy-stats">
                <div>
                  <span className="card-label">P&L</span>
                  <span className={`text-mono ${s.total_pnl >= 0 ? 'text-green' : 'text-red'}`}>
                    {formatMoney(s.total_pnl, true)}
                  </span>
                </div>
                <div>
                  <span className="card-label">Win Rate</span>
                  <span className="text-mono">{s.win_rate}%</span>
                </div>
                <div>
                  <span className="card-label">Trades</span>
                  <span className="text-mono">{s.trades}</span>
                </div>
                <div>
                  <span className="card-label">Avg</span>
                  <span className={`text-mono ${s.avg_pnl >= 0 ? 'text-green' : 'text-red'}`}>
                    {formatMoney(s.avg_pnl, true)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="card text-muted" style={{ textAlign: 'center', padding: 20 }}>
          No strategy data yet
        </div>
      )}

      {/* --- Heatmap --- */}
      <div className="section-header">
        <span className="section-title">Strategy × Market Condition</span>
      </div>
      {heatmapData && heatmapData.strategies?.length > 0 ? (
        <div className="table-container" style={{ marginBottom: 12 }}>
          <table className="heatmap-table">
            <thead>
              <tr>
                <th></th>
                {heatmapData.conditions.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {heatmapData.strategies.map((strat) => (
                <tr key={strat}>
                  <td style={{ fontWeight: 600 }}>{strat}</td>
                  {heatmapData.conditions.map((cond) => {
                    const cell = heatmapData.cells[strat]?.[cond] || {}
                    const wr = cell.win_rate || 0
                    const trades = cell.trades || 0
                    // Color: green for >55%, red for <45%, neutral otherwise.
                    let bgColor = 'transparent'
                    if (trades >= 3) {
                      if (wr >= 55) bgColor = 'var(--green-dim)'
                      else if (wr <= 45) bgColor = 'var(--red-dim)'
                    }
                    return (
                      <td
                        key={cond}
                        className="heatmap-cell"
                        style={{ background: bgColor }}
                        title={`${trades} trades, $${cell.total_pnl?.toFixed(2) || 0} total`}
                      >
                        {trades > 0 ? (
                          <>
                            <span className={wr >= 50 ? 'text-green' : 'text-red'}>
                              {wr}%
                            </span>
                            <span className="heatmap-trades">{trades}t</span>
                          </>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="card text-muted" style={{ textAlign: 'center', padding: 20, marginBottom: 12 }}>
          No heatmap data yet
        </div>
      )}

      {/* --- Day of Week --- */}
      <div className="section-header">
        <span className="section-title">Day of Week Performance</span>
      </div>
      {dayOfWeek.some((d) => d.trades > 0) ? (
        <div className="chart-container" style={{ height: 200, marginBottom: 12 }}>
          <Bar
            data={{
              labels: dayOfWeek.map((d) => d.day_name.substring(0, 3)),
              datasets: [{
                label: 'Total P&L',
                data: dayOfWeek.map((d) => d.total_pnl),
                backgroundColor: dayOfWeek.map((d) =>
                  d.total_pnl >= 0 ? '#00e67640' : '#ff525240'
                ),
                borderColor: dayOfWeek.map((d) =>
                  d.total_pnl >= 0 ? '#00e676' : '#ff5252'
                ),
                borderWidth: 1,
                borderRadius: 4,
              }],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                tooltip: {
                  backgroundColor: '#1a1a3e',
                  titleColor: '#e8e8f0',
                  bodyColor: '#e8e8f0',
                  callbacks: {
                    afterLabel: (ctx) => {
                      const d = dayOfWeek[ctx.dataIndex]
                      return `Win Rate: ${d.win_rate}% (${d.trades} trades)`
                    },
                  },
                },
              },
              scales: {
                x: { ticks: { color: '#606080' }, grid: { display: false } },
                y: {
                  ticks: { color: '#606080', font: { family: 'JetBrains Mono', size: 10 } },
                  grid: { color: '#2a2a4e' },
                },
              },
            }}
          />
        </div>
      ) : (
        <div className="card text-muted" style={{ textAlign: 'center', padding: 20, marginBottom: 12 }}>
          No day-of-week data yet
        </div>
      )}

      {/* --- Symbol Breakdown (top 10) --- */}
      <div className="section-header">
        <span className="section-title">Top Symbols</span>
      </div>
      {symbols.length > 0 ? (
        <div className="table-container" style={{ marginBottom: 12 }}>
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Trades</th>
                <th>Win Rate</th>
                <th>Total P&L</th>
                <th>Avg P&L</th>
              </tr>
            </thead>
            <tbody>
              {symbols.slice(0, 10).map((s) => (
                <tr key={s.symbol}>
                  <td style={{ fontWeight: 600 }}>{s.symbol}</td>
                  <td className="text-mono">{s.trades}</td>
                  <td className={`text-mono ${s.win_rate >= 50 ? 'text-green' : 'text-red'}`}>
                    {s.win_rate}%
                  </td>
                  <td className={`text-mono ${s.total_pnl >= 0 ? 'text-green' : 'text-red'}`}>
                    {formatMoney(s.total_pnl, true)}
                  </td>
                  <td className={`text-mono ${s.avg_pnl >= 0 ? 'text-green' : 'text-red'}`}>
                    {formatMoney(s.avg_pnl, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="card text-muted" style={{ textAlign: 'center', padding: 20, marginBottom: 12 }}>
          No symbol data yet
        </div>
      )}

      {/* --- Streak Analysis --- */}
      <div className="section-header">
        <span className="section-title">Streak Analysis</span>
      </div>
      <div className="grid-4" style={{ marginBottom: 12 }}>
        <StatCard label="Max Win Streak" value={`${streaks.max_winning_streak || 0} days`} color="text-green" />
        <StatCard label="Max Loss Streak" value={`${streaks.max_losing_streak || 0} days`} color="text-red" />
        <StatCard label="After Win" value={`${streaks.after_win_win_rate || 0}% win`} sub="Next day win rate" />
        <StatCard label="After Loss" value={`${streaks.after_loss_win_rate || 0}% win`} sub="Next day win rate" />
      </div>

      {/* --- Bot Journal --- */}
      <div className="section-header">
        <span className="section-title">Bot Journal</span>
        <span className="text-muted" style={{ fontSize: 11 }}>
          {observations.length} observation{observations.length !== 1 ? 's' : ''}
        </span>
      </div>
      {observations.length > 0 ? (
        <div className="journal-list">
          {observations.map((obs, i) => (
            <div key={i} className={`card journal-entry journal-${obs.severity}`}>
              <div className="journal-header">
                <span className={`badge badge-${obs.severity === 'alert' ? 'red' : obs.severity === 'warning' ? 'gold' : 'green'}`}>
                  {obs.severity}
                </span>
                <span className="journal-title">{obs.title}</span>
              </div>
              <p className="journal-message">{obs.message}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="card text-muted" style={{ textAlign: 'center', padding: 24 }}>
          No observations yet — the bot needs trade data to analyze.
          {source === 'live' ? ' Run some live trades first.' : ' Run a backtest first.'}
        </div>
      )}

      {/* --- Deep Analysis (Claude AI) --- */}
      <div className="section-header" style={{ marginTop: 16 }}>
        <span className="section-title">Deep Analysis</span>
        <button
          className="deep-analysis-btn"
          onClick={runDeepAnalysis}
          disabled={analyzing}
        >
          {analyzing ? 'Analyzing...' : 'Run Deep Analysis'}
        </button>
      </div>

      {analyzing && (
        <div className="card" style={{ textAlign: 'center', padding: 24 }}>
          <div className="spinner" />
          <p className="text-muted" style={{ marginTop: 8 }}>
            Claude is analyzing your trading data...
          </p>
        </div>
      )}

      {deepResult && !analyzing && (
        <div className="journal-list" style={{ marginBottom: 12 }}>
          {deepResult.observations?.map((obs, i) => (
            <div key={`deep-${i}`} className={`card journal-entry journal-${obs.severity}`}>
              <div className="journal-header">
                <span className={`badge badge-${obs.severity === 'alert' ? 'red' : obs.severity === 'warning' ? 'gold' : 'green'}`}>
                  {obs.severity}
                </span>
                <span className="badge badge-blue">AI</span>
                <span className="journal-title">{obs.title}</span>
              </div>
              <p className="journal-message">{obs.message}</p>
            </div>
          ))}
        </div>
      )}

      {/* --- Proposals --- */}
      <div className="section-header">
        <span className="section-title">Proposals</span>
        <span className="text-muted" style={{ fontSize: 11 }}>
          {proposals.filter(p => p.status === 'pending').length} pending
        </span>
      </div>

      {proposals.length > 0 ? (
        <div className="proposals-list">
          {proposals.map((p) => (
            <div key={p.id} className={`card proposal-card proposal-${p.status}`}>
              <div className="proposal-header">
                <span className={`badge badge-${p.source === 'claude' ? 'blue' : 'gold'}`}>
                  {p.source === 'claude' ? 'AI' : 'Rule'}
                </span>
                <span className="proposal-title">{p.title}</span>
                <span className={`badge badge-${
                  p.status === 'approved' ? 'green' :
                  p.status === 'rejected' ? 'red' :
                  p.status === 'tested' ? 'blue' : 'gold'
                }`}>
                  {p.status}
                </span>
              </div>
              <p className="proposal-description">{p.description}</p>

              {p.parameter_changes && (
                <div className="proposal-changes">
                  {Object.entries(p.parameter_changes).map(([key, value]) => (
                    <div key={key} className="proposal-change">
                      <span className="text-muted">{key}:</span>
                      {p.current_values?.[key] != null && (
                        <span className="text-red">{String(p.current_values[key])}</span>
                      )}
                      <span className="change-arrow">&rarr;</span>
                      <span className="text-green">{String(value)}</span>
                    </div>
                  ))}
                </div>
              )}

              {p.status === 'pending' && (
                <div className="proposal-actions">
                  <button
                    className="btn-approve"
                    onClick={() => handleProposalAction(p.id, 'approve')}
                  >
                    Approve
                  </button>
                  <button
                    className="btn-reject"
                    onClick={() => handleProposalAction(p.id, 'reject')}
                  >
                    Reject
                  </button>
                  <button
                    className="btn-backtest"
                    onClick={() => handleProposalAction(p.id, 'backtest')}
                  >
                    Backtest First
                  </button>
                </div>
              )}

              {p.status === 'tested' && p.backtest_run_id && (
                <div className="proposal-test-link">
                  <a href={`/backtests`} className="text-blue">
                    View backtest results →
                  </a>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="card text-muted" style={{ textAlign: 'center', padding: 24 }}>
          No proposals yet. Run a deep analysis or wait for the bot to generate suggestions.
        </div>
      )}
    </div>
  )
}
