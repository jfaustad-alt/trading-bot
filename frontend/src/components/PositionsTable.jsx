import { formatMoney, formatPct } from '../utils/format'

/*
  PositionsTable — shows currently held stocks with unrealized P&L.

  Each row is a stock the bot owns right now. Green means it's up,
  red means it's down since the bot bought it.

  Props:
    positions: Array of { symbol, qty, entry_price, current_price, unrealized_pl, change_pct }
*/

export default function PositionsTable({ positions }) {
  if (!positions || positions.length === 0) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '24px' }}>
        <span className="text-muted">No open positions</span>
      </div>
    )
  }

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Qty</th>
            <th>Entry</th>
            <th>Current</th>
            <th>P&L</th>
            <th>%</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const isPositive = pos.unrealized_pl >= 0
            const color = isPositive ? 'text-green' : 'text-red'
            return (
              <tr key={pos.symbol}>
                <td style={{ fontWeight: 600 }}>{pos.symbol}</td>
                <td className="text-mono">{pos.qty}</td>
                <td className="text-mono">{formatMoney(pos.entry_price)}</td>
                <td className="text-mono">{formatMoney(pos.current_price)}</td>
                <td className={`text-mono ${color}`}>
                  {formatMoney(pos.unrealized_pl, true)}
                </td>
                <td className={`text-mono ${color}`}>
                  {formatPct(pos.change_pct)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
