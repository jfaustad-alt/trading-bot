/*
  StatCard — a single metric card (equity, P&L, win rate, etc.)

  Props:
    label: The small header text (e.g. "EQUITY")
    value: The main number to display
    sub: Optional secondary text below the value
    color: Optional color class ("text-green", "text-red")
*/

export default function StatCard({ label, value, sub, color }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className={`card-value ${color || ''}`}>{value}</div>
      {sub && <div className="card-sub">{sub}</div>}
    </div>
  )
}
