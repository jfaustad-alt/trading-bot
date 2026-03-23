import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import StatCard from '../components/StatCard'
import { formatMoney } from '../utils/format'
import './History.css'

/*
  History page — searchable, filterable trade log with daily summaries.

  Sections:
    1. Filters bar (source toggle, symbol search, date range)
    2. Summary stat cards (trades, win rate, total P&L)
    3. Daily summaries (collapsible)
    4. Full trade log table with sorting
*/

export default function History() {
  const [source, setSource] = useState('live')
  const [search, setSearch] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [sortField, setSortField] = useState('timestamp')
  const [sortDir, setSortDir] = useState('desc')
  const [page, setPage] = useState(0)
  const PAGE_SIZE = 50

  // Build query string for trades.
  const tradeParams = new URLSearchParams({ source, limit: '500' })
  if (startDate) tradeParams.set('start_date', startDate)
  if (endDate) tradeParams.set('end_date', endDate)

  const { data: tradeData } = useApi(`/api/trades?${tradeParams}`)
  const { data: summaryData } = useApi(
    source === 'live'
      ? `/api/daily-summaries?limit=365${startDate ? `&start_date=${startDate}` : ''}${endDate ? `&end_date=${endDate}` : ''}`
      : null
  )

  const allTrades = tradeData?.trades || []
  const summaries = summaryData?.summaries || []

  // Filter by search term (symbol).
  const filteredTrades = useMemo(() => {
    let trades = allTrades
    if (search.trim()) {
      const q = search.trim().toUpperCase()
      trades = trades.filter(t => t.symbol.includes(q))
    }
    return trades
  }, [allTrades, search])

  // Sort.
  const sortedTrades = useMemo(() => {
    const sorted = [...filteredTrades]
    sorted.sort((a, b) => {
      let aVal = a[sortField]
      let bVal = b[sortField]
      if (typeof aVal === 'string') aVal = aVal.toLowerCase()
      if (typeof bVal === 'string') bVal = bVal.toLowerCase()
      if (aVal < bVal) return sortDir === 'asc' ? -1 : 1
      if (aVal > bVal) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return sorted
  }, [filteredTrades, sortField, sortDir])

  // Paginate.
  const pagedTrades = sortedTrades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages = Math.ceil(sortedTrades.length / PAGE_SIZE)

  // Summary stats from filtered trades.
  const stats = useMemo(() => {
    const sells = filteredTrades.filter(t => t.action === 'sell' && t.pnl != null)
    const totalPnl = sells.reduce((sum, t) => sum + t.pnl, 0)
    const wins = sells.filter(t => t.pnl > 0).length
    return {
      totalTrades: filteredTrades.length,
      sells: sells.length,
      winRate: sells.length > 0 ? (wins / sells.length * 100).toFixed(1) : '0.0',
      totalPnl,
    }
  }, [filteredTrades])

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDir('desc')
    }
    setPage(0)
  }

  const sortIcon = (field) => {
    if (sortField !== field) return ''
    return sortDir === 'asc' ? ' ▲' : ' ▼'
  }

  return (
    <div className="page fade-in">
      <h1 className="page-title">History</h1>

      {/* --- Filters --- */}
      <div className="history-filters">
        <div className="source-toggle">
          <button
            className={`toggle-btn ${source === 'live' ? 'toggle-active' : ''}`}
            onClick={() => { setSource('live'); setPage(0) }}
          >
            Live
          </button>
          <button
            className={`toggle-btn ${source === 'backtest' ? 'toggle-active' : ''}`}
            onClick={() => { setSource('backtest'); setPage(0) }}
          >
            Backtest
          </button>
        </div>

        <input
          type="text"
          className="search-input"
          placeholder="Search symbol..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0) }}
        />

        <div className="date-filters">
          <input
            type="date"
            className="date-input"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
          <span className="date-separator">to</span>
          <input
            type="date"
            className="date-input"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
          {(startDate || endDate) && (
            <button
              className="clear-dates"
              onClick={() => { setStartDate(''); setEndDate('') }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* --- Stats --- */}
      <div className="grid-4" style={{ marginBottom: 12 }}>
        <StatCard label="Total Trades" value={stats.totalTrades} />
        <StatCard label="Closed" value={stats.sells} sub="with P&L" />
        <StatCard
          label="Win Rate"
          value={`${stats.winRate}%`}
          color={parseFloat(stats.winRate) >= 50 ? 'text-green' : 'text-red'}
        />
        <StatCard
          label="Total P&L"
          value={formatMoney(stats.totalPnl, true)}
          color={stats.totalPnl >= 0 ? 'text-green' : 'text-red'}
        />
      </div>

      {/* --- Daily Summaries (live only) --- */}
      {source === 'live' && summaries.length > 0 && (
        <>
          <div className="section-header">
            <span className="section-title">Daily Summaries</span>
            <span className="text-muted" style={{ fontSize: 11 }}>
              {summaries.length} days
            </span>
          </div>
          <div className="table-container" style={{ marginBottom: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>P&L</th>
                  <th>Trades</th>
                  <th>Win Rate</th>
                  <th>Strategy</th>
                  <th>ELO</th>
                </tr>
              </thead>
              <tbody>
                {summaries.slice(0, 30).map((s) => (
                  <tr key={s.date}>
                    <td className="text-mono">{s.date}</td>
                    <td className={`text-mono ${s.daily_pnl >= 0 ? 'text-green' : 'text-red'}`}>
                      {formatMoney(s.daily_pnl, true)}
                    </td>
                    <td className="text-mono">{s.trade_count}</td>
                    <td className={`text-mono ${(s.win_rate || 0) >= 50 ? 'text-green' : 'text-red'}`}>
                      {s.win_rate?.toFixed(1) || '0.0'}%
                    </td>
                    <td>{s.strategy || '—'}</td>
                    <td className="text-mono">{s.elo_rating?.toFixed(0) || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* --- Trade Log --- */}
      <div className="section-header">
        <span className="section-title">Trade Log</span>
        <span className="text-muted" style={{ fontSize: 11 }}>
          {sortedTrades.length} trades
          {totalPages > 1 && ` · page ${page + 1}/${totalPages}`}
        </span>
      </div>

      {sortedTrades.length > 0 ? (
        <>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th className="sortable" onClick={() => handleSort('timestamp')}>
                    Time{sortIcon('timestamp')}
                  </th>
                  <th className="sortable" onClick={() => handleSort('symbol')}>
                    Symbol{sortIcon('symbol')}
                  </th>
                  <th>Action</th>
                  <th className="sortable" onClick={() => handleSort('qty')}>
                    Qty{sortIcon('qty')}
                  </th>
                  <th className="sortable" onClick={() => handleSort('price')}>
                    Price{sortIcon('price')}
                  </th>
                  <th className="sortable" onClick={() => handleSort('pnl')}>
                    P&L{sortIcon('pnl')}
                  </th>
                  <th>Strategy</th>
                </tr>
              </thead>
              <tbody>
                {pagedTrades.map((t) => (
                  <tr key={t.id}>
                    <td className="text-mono" style={{ fontSize: 11 }}>
                      {t.timestamp?.substring(0, 16).replace('T', ' ')}
                    </td>
                    <td style={{ fontWeight: 600 }}>{t.symbol}</td>
                    <td>
                      <span className={`badge badge-${t.action === 'buy' ? 'green' : 'red'}`}>
                        {t.action.toUpperCase()}
                      </span>
                    </td>
                    <td className="text-mono">{t.qty}</td>
                    <td className="text-mono">${t.price?.toFixed(2)}</td>
                    <td className={`text-mono ${t.pnl != null ? (t.pnl >= 0 ? 'text-green' : 'text-red') : 'text-muted'}`}>
                      {t.pnl != null ? formatMoney(t.pnl, true) : '—'}
                    </td>
                    <td className="text-muted">{t.strategy || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="page-btn"
                disabled={page === 0}
                onClick={() => setPage(p => p - 1)}
              >
                Prev
              </button>
              <span className="page-info">
                {page + 1} / {totalPages}
              </span>
              <button
                className="page-btn"
                disabled={page >= totalPages - 1}
                onClick={() => setPage(p => p + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="card text-muted" style={{ textAlign: 'center', padding: 24 }}>
          No trades found.
          {search && ` No matches for "${search}".`}
          {!search && source === 'live' && ' Run some live trades first.'}
          {!search && source === 'backtest' && ' Run a backtest first.'}
        </div>
      )}
    </div>
  )
}
