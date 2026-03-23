import { useApi } from '../hooks/useApi'
import StatCard from './StatCard'
import { formatMoney } from '../utils/format'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'
import './BacktestCompare.css'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend)

/*
  BacktestCompare — overlay up to 4 backtest equity curves on one chart.

  Shows:
    1. Overlaid equity curves (normalized to % return for fair comparison)
    2. Side-by-side stat cards for each run

  Props:
    runIds: Array of backtest run IDs to compare (2-4)
*/

const COLORS = ['#00e676', '#448aff', '#ffd740', '#ff5252']

export default function BacktestCompare({ runIds }) {
  // Fetch all backtest details in parallel by rendering a hook for each.
  // We use a wrapper component pattern to handle dynamic hook counts.
  return <CompareInner runIds={runIds} />
}

function CompareInner({ runIds }) {
  // Fetch each backtest's data.
  const results = runIds.map((id) => useApi(`/api/backtests/${id}`))

  const allLoaded = results.every((r) => !r.loading && r.data)
  if (!allLoaded) {
    return <div className="card text-muted" style={{ padding: 40, textAlign: 'center' }}>Loading comparison...</div>
  }

  const runs = results.map((r) => r.data)

  // --- Build overlaid chart data ---
  // Normalize to % return so backtests with different capital are comparable.
  const datasets = runs.map((data, i) => {
    const { run, daily_results } = data
    if (!daily_results || daily_results.length === 0) return null

    const startEquity = run.starting_capital || daily_results[0].equity
    const returns = daily_results.map((d) => ({
      date: d.date,
      pctReturn: ((d.equity - startEquity) / startEquity) * 100,
    }))

    return {
      label: run.name || `Run #${run.id}`,
      data: returns.map((r) => r.pctReturn),
      dates: returns.map((r) => r.date),
      borderColor: COLORS[i],
      backgroundColor: COLORS[i] + '15',
      fill: false,
      tension: 0.3,
      pointRadius: 0,
      pointHitRadius: 8,
      borderWidth: 2,
    }
  }).filter(Boolean)

  // Use the longest date array as labels.
  const longestDates = datasets.reduce(
    (max, ds) => (ds.dates.length > max.length ? ds.dates : max),
    [],
  )

  const chartData = {
    labels: longestDates,
    datasets: datasets.map(({ dates, ...rest }) => rest),
  }

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: 'index' },
    plugins: {
      legend: {
        display: true,
        position: 'top',
        labels: {
          color: '#9090b0',
          font: { size: 12, family: 'Inter' },
          boxWidth: 12,
          padding: 16,
        },
      },
      tooltip: {
        backgroundColor: '#1a1a3e',
        titleColor: '#e8e8f0',
        bodyColor: '#e8e8f0',
        borderColor: '#2a2a4e',
        borderWidth: 1,
        padding: 10,
        cornerRadius: 8,
        callbacks: {
          label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y >= 0 ? '+' : ''}${ctx.parsed.y.toFixed(2)}%`,
        },
      },
    },
    scales: {
      x: {
        ticks: { color: '#606080', font: { size: 10 }, maxTicksLimit: 8 },
        grid: { display: false },
      },
      y: {
        ticks: {
          color: '#606080',
          font: { size: 10, family: 'JetBrains Mono' },
          callback: (v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`,
        },
        grid: { color: '#2a2a4e', drawBorder: false },
      },
    },
  }

  return (
    <div className="fade-in">
      <h2 className="page-title">Compare Backtests</h2>

      {/* --- Overlaid Chart --- */}
      <div className="chart-container" style={{ height: 280, marginBottom: 16 }}>
        <Line data={chartData} options={chartOptions} />
      </div>

      {/* --- Side-by-side stats --- */}
      <div className="compare-grid">
        {runs.map((data, i) => {
          const { run } = data
          const returnColor = (run.total_return_pct || 0) >= 0 ? 'text-green' : 'text-red'
          return (
            <div key={run.id} className="compare-column" style={{ borderColor: COLORS[i] }}>
              <div className="compare-header" style={{ color: COLORS[i] }}>
                {run.name || `Run #${run.id}`}
              </div>
              <div className="compare-dates text-muted">
                {run.start_date} to {run.end_date}
              </div>
              <div className="compare-stats">
                <div className="compare-stat">
                  <span className="card-label">Return</span>
                  <span className={`card-value ${returnColor}`} style={{ fontSize: 18 }}>
                    {run.total_return_pct >= 0 ? '+' : ''}{run.total_return_pct?.toFixed(2)}%
                  </span>
                </div>
                <div className="compare-stat">
                  <span className="card-label">Win Rate</span>
                  <span className="card-value" style={{ fontSize: 18 }}>{run.win_rate?.toFixed(1)}%</span>
                </div>
                <div className="compare-stat">
                  <span className="card-label">Max Drawdown</span>
                  <span className="card-value text-red" style={{ fontSize: 18 }}>{run.max_drawdown_pct?.toFixed(2)}%</span>
                </div>
                <div className="compare-stat">
                  <span className="card-label">Trades</span>
                  <span className="card-value" style={{ fontSize: 18 }}>{run.total_trades}</span>
                </div>
                <div className="compare-stat">
                  <span className="card-label">ELO</span>
                  <span className="card-value" style={{ fontSize: 18 }}>
                    {run.elo_start?.toFixed(0)} → {run.elo_end?.toFixed(0)}
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
