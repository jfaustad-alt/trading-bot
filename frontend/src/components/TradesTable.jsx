import { formatMoney } from '../utils/format'

/*
  TradesTable — shows recent trades executed by the bot.

  Props:
    trades: Array of { time, symbol, action, qty, price, strategy, pnl }
*/

export default function TradesTable({ trades }) {
  if (!trades || trades.length === 0) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '24px' }}>
        <span className="text-muted">No trades today</span>
      </div>
    )
  }

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Symbol</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Price</th>
            <th>Strategy</th>
            <th>P&L</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, i) => {
            const isBuy = trade.action === 'BUY'
            const hasPnl = trade.pnl != null
            const pnlColor = hasPnl
              ? trade.pnl >= 0 ? 'text-green' : 'text-red'
              : ''
            return (
              <tr key={`${trade.time}-${trade.symbol}-${i}`}>
                <td className="text-mono text-muted">{trade.time}</td>
                <td style={{ fontWeight: 600 }}>{trade.symbol}</td>
                <td>
                  <span className={`badge ${isBuy ? 'badge-green' : 'badge-red'}`}>
                    {trade.action}
                  </span>
                </td>
                <td className="text-mono">{trade.qty}</td>
                <td className="text-mono">{formatMoney(trade.price)}</td>
                <td className="text-muted">{trade.strategy}</td>
                <td className={`text-mono ${pnlColor}`}>
                  {hasPnl ? formatMoney(trade.pnl, true) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
