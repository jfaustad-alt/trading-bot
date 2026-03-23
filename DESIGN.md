# Trading Bot App — Design Document

## Overview
Mobile-friendly React PWA with Flask backend, SQLite database, and Claude API integration.
Rebuilds the existing dashboard into a professional, interactive app while preserving all existing bot logic.

## App Structure
Bottom tab navigation: **Live | Backtests | Analysis | History | Settings**

---

## Live (Home Tab)
- Stat cards: equity, cash, daily P&L, win rate, ELO badge with rank
- Market status, active strategy, market condition
- Equity curve + ELO history charts
- Open positions table with unrealized P&L
- **Tap any stock** → intraday line chart with entry/exit points marked
- Rolling 7-day window of detailed intraday data, auto-cleaned
- Recent trades list
- Panic button (close all positions)
- Auto-refresh, push notifications for daily target hit + ELO rank changes

## Backtests Tab
- **Date picker**: manual start/end dates + preset scenario buttons (COVID Crash Feb-Apr 2020, 2022 Bear Market, 2023 Bull Run, war/geopolitical periods, etc.)
- **Async queue**: kick off multiple backtests, time estimate per run, notification when done
- **Results view**: summary stats, equity curve, drawdown chart, daily timeline (strategy picked + SPY % change + volatility + news headline from Alpaca), filterable/sortable trade log
- **"Sit out" analysis**: flags days that would have been skipped under extreme volatility, shows what-if comparison (analysis only — bot still trades those days so you can compare)
- **Compare mode**: overlay up to 4 backtests on the same chart with side-by-side stats

## Analysis Tab
- **Layered UI**: high-level summary → tap to drill down into details
- Strategy performance breakdown (which strategies make/lose money)
- Strategy vs. market condition heatmap (green/red)
- Pattern detection: day-of-week, sector clustering, losing streaks, time-based trends
- **Rule-based checks** run daily (automatic, cheap)
- **Claude-powered deep analysis** on demand or weekly (via Claude API)
- **Bot journal**: observations feed — like a diary of what the bot noticed
- **Formal proposals**: "Change X because Y" with **[Approve] [Reject] [Backtest First]** buttons
- **Single-day replay**: bot suggests "this strategy would've been better on March 5th" → tap "Test it" → simple line chart + P&L comparison + trade list (lightweight, not full detail)
- Works on both live trading data and backtest data
- Can compare live performance vs. backtest for the same period ("I made $400 live but backtest says $600 — why?")

## History Tab
- All live trades logged to SQLite
- All backtest results saved
- Searchable, filterable
- Compare live performance vs. backtest for the same period

## Settings Tab
- All parameters editable: risk %, max positions, daily target, loss limit, ATR multipliers per strategy, trading windows, stock watchlist
- **Every change triggers a comparison backtest** (old vs. new settings) before applying
- Shows results → confirmation required before applying
- Flow: change setting → auto-backtest old vs new → show comparison → [Apply / Cancel]

---

## Notifications
- Daily profit target reached
- ELO rank change (up or down)

## Technical Stack
- **Frontend**: React (PWA — installable on phone home screen)
- **Backend**: Flask API server
- **Database**: SQLite (trades, backtests, bot proposals, 7-day intraday data cache)
- **Data source**: Alpaca API (prices, bars, news headlines)
- **AI**: Claude API (deep analysis — weekly or on-demand)
- **Charts**: Chart.js, line charts as default, option to dig deeper

## Design Direction
- **Dark theme**: Bloomberg meets fintech — data-rich but polished with good spacing
- Clean typography, rounded cards, smooth transitions
- Mobile-first layout, responsive
- Professional but not cluttered — whitespace matters
- Green/red for profit/loss, gold for ELO, dark grays and blues for background

## Key Constraints
- **Do not break existing bot logic** — all strategies, risk management, screener, broker client must remain unchanged
- Existing Flask routes can be extended, not replaced
- Bot's `bot_state` dict continues to work as before
- New features (SQLite persistence, async backtests, Claude analysis) are additions, not rewrites
- Alpaca only — no other brokers

## Self-Learning Loop
- Rule-based checks flag obvious issues automatically (e.g. win rate drops below 40% for a strategy)
- Claude API analyzes trade data for deeper patterns on demand or weekly
- Observations go to the bot journal (always visible)
- High-confidence findings become formal proposals requiring user approval
- Proposals can be backtested before accepting
- **The bot never changes its own parameters without user approval**

## Single-Day Replay
- Bot identifies days where a different approach might have worked better
- User taps "Test it" → re-runs that single day with the suggested change
- Shows: simple line chart, P&L difference, trade list
- Lightweight — not full backtest detail

## Intraday Charts (Live)
- Line chart showing price action with entry/exit markers
- 5-minute bars from Alpaca IEX feed
- Rolling 7-day cache — older data auto-deleted to save storage
- Tap a stock in positions/trades → see its chart
