import './EloBadge.css'

/*
  EloBadge — displays the bot's ELO rating, rank, and progress bar.

  The ELO system rates the bot's trading performance like chess ratings.
  Higher rating = better performance = harder daily targets.

  Props:
    rating: The current ELO number (e.g. 1247)
    rankInfo: Object with { name, icon, color, progress, next_rank, rating_to_next }
*/

export default function EloBadge({ rating, rankInfo }) {
  if (!rankInfo) return null

  const { name, icon, color, progress, next_rank, rating_to_next } = rankInfo

  return (
    <div className="elo-badge" style={{ '--rank-color': color }}>
      <div className="elo-header">
        <span className="elo-icon">{icon}</span>
        <span className="elo-rank-name">{name}</span>
      </div>
      <div className="elo-rating" style={{ color }}>{Math.round(rating)}</div>
      {next_rank && next_rank !== 'MAX' && (
        <>
          <div className="elo-next">
            {rating_to_next} pts to {next_rank}
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${(progress * 100).toFixed(0)}%`,
                background: color,
              }}
            />
          </div>
        </>
      )}
    </div>
  )
}
