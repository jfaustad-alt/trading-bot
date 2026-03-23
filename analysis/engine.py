"""Analysis engine — rule-based performance analysis.

This module crunches the bot's trade data from SQLite and produces
structured insights. It answers questions like:

    - Which strategy makes the most money? Which loses the most?
    - Does momentum work in trending markets but fail in range-bound?
    - Do I lose more on Mondays?
    - Do losses cluster around specific stocks?
    - After a losing day, does the bot tend to lose again?
    - Am I getting better over time?

HOW IT WORKS:
    Each function queries the database, processes the trades, and returns
    a structured dict that the API serves as JSON to the frontend.

    Rule-based checks run these analyses automatically. Later (Phase 5),
    the Claude API will analyze the results for deeper patterns.

Usage:
    from analysis.engine import (
        get_strategy_breakdown,
        get_heatmap,
        get_day_of_week_patterns,
        get_streak_analysis,
        get_overview,
    )

    overview = get_overview(source="live")
    heatmap = get_heatmap(source="live")
"""

from datetime import datetime
from typing import Any

from database.db import get_connection, get_daily_summaries, get_trades


def get_overview(source: str = "live") -> dict[str, Any]:
    """High-level performance overview.

    Returns the "big picture" stats that appear at the top of the
    Analysis tab. Gives you an instant sense of how the bot is doing.

    Args:
        source: "live" or "backtest".

    Returns:
        A dict with: total_pnl, total_trades, win_rate, best_day,
        worst_day, avg_daily_pnl, current_streak, improving (bool).
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Get all sell trades with P&L.
    cursor.execute(
        "SELECT * FROM trades WHERE source = ? AND action = 'sell' AND pnl IS NOT NULL "
        "ORDER BY timestamp",
        (source,),
    )
    trades = [dict(r) for r in cursor.fetchall()]

    # Get daily summaries for daily stats.
    if source == "live":
        cursor.execute("SELECT * FROM daily_summaries ORDER BY date")
        daily = [dict(r) for r in cursor.fetchall()]
    else:
        # For backtest, aggregate from backtest_daily_results.
        cursor.execute(
            "SELECT date, daily_pnl, strategy, market_condition "
            "FROM backtest_daily_results ORDER BY date"
        )
        daily = [dict(r) for r in cursor.fetchall()]

    conn.close()

    if not trades:
        return {
            "total_pnl": 0, "total_trades": 0, "win_rate": 0,
            "best_day": None, "worst_day": None, "avg_daily_pnl": 0,
            "current_streak": 0, "improving": False,
        }

    total_pnl = sum(t["pnl"] for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    win_rate = (wins / len(trades) * 100) if trades else 0

    # Best and worst days.
    best_day = None
    worst_day = None
    if daily:
        best = max(daily, key=lambda d: d.get("daily_pnl", 0))
        worst = min(daily, key=lambda d: d.get("daily_pnl", 0))
        best_day = {"date": best["date"], "pnl": best.get("daily_pnl", 0)}
        worst_day = {"date": worst["date"], "pnl": worst.get("daily_pnl", 0)}

    avg_daily = (
        sum(d.get("daily_pnl", 0) for d in daily) / len(daily) if daily else 0
    )

    # Current streak (consecutive profitable days from the end).
    streak = 0
    for d in reversed(daily):
        if d.get("daily_pnl", 0) > 0:
            streak += 1
        else:
            break

    # Are we improving? Compare last 10 trades' win rate vs. first 10.
    improving = False
    if len(trades) >= 20:
        first_10_wr = sum(1 for t in trades[:10] if t["pnl"] > 0) / 10
        last_10_wr = sum(1 for t in trades[-10:] if t["pnl"] > 0) / 10
        improving = last_10_wr > first_10_wr

    return {
        "total_pnl": round(total_pnl, 2),
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "best_day": best_day,
        "worst_day": worst_day,
        "avg_daily_pnl": round(avg_daily, 2),
        "current_streak": streak,
        "improving": improving,
    }


def get_strategy_breakdown(source: str = "live") -> list[dict[str, Any]]:
    """Performance breakdown by strategy.

    Shows how each strategy (momentum, mean_reversion, breakout,
    etf_rotation) performs independently. Helps you see which strategies
    are making money and which are losing.

    Args:
        source: "live" or "backtest".

    Returns:
        A list of dicts, one per strategy:
            { name, trades, wins, losses, win_rate, total_pnl,
              avg_pnl, best_trade, worst_trade }
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT strategy, pnl FROM trades "
        "WHERE source = ? AND action = 'sell' AND pnl IS NOT NULL",
        (source,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Group by strategy.
    strategies: dict[str, list[float]] = {}
    for row in rows:
        strat = row.get("strategy") or "unknown"
        strategies.setdefault(strat, []).append(row["pnl"])

    result = []
    for name, pnls in strategies.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        result.append({
            "name": name,
            "trades": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "best_trade": round(max(pnls), 2) if pnls else 0,
            "worst_trade": round(min(pnls), 2) if pnls else 0,
        })

    # Sort by total P&L descending (best strategy first).
    result.sort(key=lambda x: x["total_pnl"], reverse=True)
    return result


def get_heatmap(source: str = "live") -> dict[str, Any]:
    """Strategy vs. market condition heatmap.

    This is a 2D grid showing the win rate (or avg P&L) for each
    strategy in each market condition. It answers: "Does momentum work
    in trending markets? Does mean reversion fail in breakouts?"

    Green cells = profitable combination, red cells = losing combination.

    Args:
        source: "live" or "backtest".

    Returns:
        A dict with:
            strategies: list of strategy names (rows)
            conditions: list of market conditions (columns)
            cells: 2D dict { strategy: { condition: { win_rate, avg_pnl, trades } } }
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT strategy, market_condition, pnl FROM trades "
        "WHERE source = ? AND action = 'sell' AND pnl IS NOT NULL",
        (source,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Group by (strategy, market_condition).
    cells: dict[str, dict[str, list[float]]] = {}
    all_strategies: set[str] = set()
    all_conditions: set[str] = set()

    for row in rows:
        strat = row.get("strategy") or "unknown"
        cond = row.get("market_condition") or "unknown"
        all_strategies.add(strat)
        all_conditions.add(cond)
        cells.setdefault(strat, {}).setdefault(cond, []).append(row["pnl"])

    # Convert to summary stats.
    heatmap: dict[str, dict[str, dict]] = {}
    for strat in all_strategies:
        heatmap[strat] = {}
        for cond in all_conditions:
            pnls = cells.get(strat, {}).get(cond, [])
            if pnls:
                wins = sum(1 for p in pnls if p > 0)
                heatmap[strat][cond] = {
                    "trades": len(pnls),
                    "win_rate": round(wins / len(pnls) * 100, 1),
                    "avg_pnl": round(sum(pnls) / len(pnls), 2),
                    "total_pnl": round(sum(pnls), 2),
                }
            else:
                heatmap[strat][cond] = {
                    "trades": 0, "win_rate": 0, "avg_pnl": 0, "total_pnl": 0,
                }

    return {
        "strategies": sorted(all_strategies),
        "conditions": sorted(all_conditions),
        "cells": heatmap,
    }


def get_day_of_week_patterns(source: str = "live") -> list[dict[str, Any]]:
    """Performance patterns by day of the week.

    Shows whether the bot performs better on certain weekdays.
    For example, Mondays might be consistently unprofitable due to
    weekend gap volatility.

    Args:
        source: "live" or "backtest".

    Returns:
        A list of 5 dicts (Mon-Fri):
            { day, day_name, trades, win_rate, avg_pnl, total_pnl }
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT timestamp, pnl FROM trades "
        "WHERE source = ? AND action = 'sell' AND pnl IS NOT NULL",
        (source,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Group by weekday (0=Monday, 4=Friday).
    days: dict[int, list[float]] = {i: [] for i in range(5)}
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    for row in rows:
        try:
            # Parse the timestamp to get the day of the week.
            ts = row["timestamp"]
            # Handle both date-only and full datetime formats.
            if len(ts) == 10:
                dt = datetime.strptime(ts, "%Y-%m-%d")
            else:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            weekday = dt.weekday()
            if weekday < 5:  # Skip weekend data (shouldn't exist but just in case).
                days[weekday].append(row["pnl"])
        except (ValueError, TypeError):
            continue

    result = []
    for i in range(5):
        pnls = days[i]
        wins = sum(1 for p in pnls if p > 0) if pnls else 0
        result.append({
            "day": i,
            "day_name": day_names[i],
            "trades": len(pnls),
            "win_rate": round(wins / len(pnls) * 100, 1) if pnls else 0,
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "total_pnl": round(sum(pnls), 2) if pnls else 0,
        })

    return result


def get_symbol_breakdown(source: str = "live") -> list[dict[str, Any]]:
    """Performance breakdown by stock symbol.

    Shows which stocks the bot trades well and which ones it loses on.
    Helps identify if losses cluster around specific sectors or tickers.

    Args:
        source: "live" or "backtest".

    Returns:
        A list of dicts sorted by total P&L:
            { symbol, trades, win_rate, total_pnl, avg_pnl }
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT symbol, pnl FROM trades "
        "WHERE source = ? AND action = 'sell' AND pnl IS NOT NULL",
        (source,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    symbols: dict[str, list[float]] = {}
    for row in rows:
        symbols.setdefault(row["symbol"], []).append(row["pnl"])

    result = []
    for symbol, pnls in symbols.items():
        wins = sum(1 for p in pnls if p > 0)
        result.append({
            "symbol": symbol,
            "trades": len(pnls),
            "win_rate": round(wins / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
        })

    result.sort(key=lambda x: x["total_pnl"], reverse=True)
    return result


def get_streak_analysis(source: str = "live") -> dict[str, Any]:
    """Analyze winning and losing streaks.

    Answers: "After a losing day, does the bot tend to lose again the
    next day?" This reveals whether losses are random or tend to cluster.

    Args:
        source: "live" or "backtest".

    Returns:
        A dict with:
            max_winning_streak, max_losing_streak,
            current_streak (positive = winning, negative = losing),
            after_win_win_rate, after_loss_win_rate,
            streaks: list of { type, length, start_date, end_date }
    """
    conn = get_connection()
    cursor = conn.cursor()

    if source == "live":
        cursor.execute("SELECT date, daily_pnl FROM daily_summaries ORDER BY date")
    else:
        cursor.execute(
            "SELECT date, daily_pnl FROM backtest_daily_results ORDER BY date"
        )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        return {
            "max_winning_streak": 0, "max_losing_streak": 0,
            "current_streak": 0, "after_win_win_rate": 0,
            "after_loss_win_rate": 0, "streaks": [],
        }

    # Track streaks.
    streaks: list[dict] = []
    current_type = "win" if rows[0]["daily_pnl"] > 0 else "loss"
    current_start = rows[0]["date"]
    current_length = 1

    for i in range(1, len(rows)):
        is_win = rows[i]["daily_pnl"] > 0
        new_type = "win" if is_win else "loss"

        if new_type == current_type:
            current_length += 1
        else:
            streaks.append({
                "type": current_type,
                "length": current_length,
                "start_date": current_start,
                "end_date": rows[i - 1]["date"],
            })
            current_type = new_type
            current_start = rows[i]["date"]
            current_length = 1

    # Don't forget the last streak.
    streaks.append({
        "type": current_type,
        "length": current_length,
        "start_date": current_start,
        "end_date": rows[-1]["date"],
    })

    max_win = max((s["length"] for s in streaks if s["type"] == "win"), default=0)
    max_loss = max((s["length"] for s in streaks if s["type"] == "loss"), default=0)

    # Current streak.
    last_streak = streaks[-1] if streaks else {"type": "none", "length": 0}
    current = last_streak["length"] if last_streak["type"] == "win" else -last_streak["length"]

    # After-win and after-loss win rates.
    after_win_wins = 0
    after_win_total = 0
    after_loss_wins = 0
    after_loss_total = 0

    for i in range(1, len(rows)):
        prev_win = rows[i - 1]["daily_pnl"] > 0
        curr_win = rows[i]["daily_pnl"] > 0
        if prev_win:
            after_win_total += 1
            if curr_win:
                after_win_wins += 1
        else:
            after_loss_total += 1
            if curr_win:
                after_loss_wins += 1

    return {
        "max_winning_streak": max_win,
        "max_losing_streak": max_loss,
        "current_streak": current,
        "after_win_win_rate": round(
            after_win_wins / after_win_total * 100, 1
        ) if after_win_total > 0 else 0,
        "after_loss_win_rate": round(
            after_loss_wins / after_loss_total * 100, 1
        ) if after_loss_total > 0 else 0,
        "streaks": streaks[-20:],  # Last 20 streaks for the chart.
    }


def run_daily_checks(source: str = "live") -> list[dict[str, Any]]:
    """Run automatic rule-based checks and generate observations.

    These are the cheap, fast checks that run daily. They flag
    obvious issues like a strategy's win rate dropping below 40%,
    or a symbol consistently losing money.

    Each observation has a severity (info, warning, alert) and a
    message that the bot journal displays.

    Args:
        source: "live" or "backtest".

    Returns:
        A list of observation dicts:
            { severity, title, message, data }
    """
    observations: list[dict[str, Any]] = []

    # --- Check 1: Strategy win rates ---
    strategies = get_strategy_breakdown(source)
    for s in strategies:
        if s["trades"] >= 10 and s["win_rate"] < 40:
            observations.append({
                "severity": "warning",
                "title": f"{s['name']} underperforming",
                "message": (
                    f"{s['name']} has a {s['win_rate']}% win rate over "
                    f"{s['trades']} trades (total P&L: ${s['total_pnl']:,.2f}). "
                    f"Consider reviewing this strategy."
                ),
                "data": s,
            })
        elif s["trades"] >= 10 and s["win_rate"] >= 65:
            observations.append({
                "severity": "info",
                "title": f"{s['name']} performing well",
                "message": (
                    f"{s['name']} has a {s['win_rate']}% win rate over "
                    f"{s['trades']} trades (total P&L: ${s['total_pnl']:,.2f})."
                ),
                "data": s,
            })

    # --- Check 2: Losing symbols ---
    symbols = get_symbol_breakdown(source)
    for sym in symbols:
        if sym["trades"] >= 5 and sym["win_rate"] < 30:
            observations.append({
                "severity": "alert",
                "title": f"{sym['symbol']} consistently losing",
                "message": (
                    f"{sym['symbol']} has only {sym['win_rate']}% win rate over "
                    f"{sym['trades']} trades, losing ${abs(sym['total_pnl']):,.2f} total. "
                    f"Consider removing from watchlist."
                ),
                "data": sym,
            })

    # --- Check 3: Day-of-week weaknesses ---
    dow = get_day_of_week_patterns(source)
    for d in dow:
        if d["trades"] >= 5 and d["win_rate"] < 35:
            observations.append({
                "severity": "warning",
                "title": f"{d['day_name']}s are weak",
                "message": (
                    f"Only {d['win_rate']}% win rate on {d['day_name']}s "
                    f"({d['trades']} trades, ${d['total_pnl']:,.2f} total). "
                    f"The bot might benefit from reduced activity on {d['day_name']}s."
                ),
                "data": d,
            })

    # --- Check 4: Heatmap mismatches ---
    heatmap = get_heatmap(source)
    for strat, conditions in heatmap["cells"].items():
        for cond, stats in conditions.items():
            if stats["trades"] >= 5 and stats["win_rate"] < 30:
                observations.append({
                    "severity": "alert",
                    "title": f"{strat} fails in {cond} markets",
                    "message": (
                        f"{strat} has only {stats['win_rate']}% win rate in "
                        f"{cond} conditions ({stats['trades']} trades, "
                        f"${stats['total_pnl']:,.2f}). The strategy selector "
                        f"may be choosing this strategy for the wrong conditions."
                    ),
                    "data": {"strategy": strat, "condition": cond, **stats},
                })

    # --- Check 5: Losing streaks ---
    streaks = get_streak_analysis(source)
    if streaks["max_losing_streak"] >= 5:
        observations.append({
            "severity": "warning",
            "title": f"Long losing streak detected",
            "message": (
                f"The bot had a {streaks['max_losing_streak']}-day losing streak. "
                f"After a loss, the bot wins {streaks['after_loss_win_rate']}% of the time."
            ),
            "data": streaks,
        })

    # Sort: alerts first, then warnings, then info.
    severity_order = {"alert": 0, "warning": 1, "info": 2}
    observations.sort(key=lambda x: severity_order.get(x["severity"], 3))

    return observations
