"""SQLite database for persisting trading data.

SQLite is a lightweight database that stores everything in a single file.
Unlike PostgreSQL or MySQL, it doesn't require a separate server — Python
has built-in support via the `sqlite3` module. This makes it perfect for
a personal trading bot: simple, fast, and zero setup.

WHY WE NEED THIS:
    Right now, all bot data lives in memory (the `bot_state` dict) and
    disappears when the bot stops. By saving to SQLite, we get:
    - Permanent trade history (for the Analysis tab)
    - Saved backtest results (for comparison)
    - Daily summaries (for tracking performance over time)
    - A foundation for the self-learning bot (it needs historical data)

DATABASE SCHEMA (the tables):
    - trades: Every individual trade (buy/sell), both live and backtest.
    - backtest_runs: Metadata about each backtest (dates, capital, results).
    - backtest_daily_results: Day-by-day breakdown within each backtest.
    - daily_summaries: End-of-day snapshots from live trading.

HOW IT WORKS:
    1. Call init_db() once at startup — it creates the file and tables
       if they don't already exist.
    2. Use the insert_* functions to save data as the bot runs.
    3. Use the get_* functions to read data back (for the dashboard/API).

Usage:
    from database.db import init_db, insert_trade, get_trades

    init_db()  # Creates trading_bot.db if it doesn't exist
    insert_trade(symbol="AAPL", action="buy", qty=10, price=187.50, ...)
    trades = get_trades(source="live", limit=50)
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Database file location
# ---------------------------------------------------------------------------
# The database file lives in the project's data/ directory. We use Path
# to build the path so it works on any operating system (Windows, Mac, Linux).
# ---------------------------------------------------------------------------

# Go up one level from this file's directory (database/) to the project root,
# then into data/. This keeps the DB file out of the code directories.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DB_DIR = _PROJECT_ROOT / "data"
_DB_PATH = _DB_DIR / "trading_bot.db"


def get_db_path() -> Path:
    """Return the path to the SQLite database file.

    Returns:
        A Path object pointing to the database file.
    """
    return _DB_PATH


def get_connection() -> sqlite3.Connection:
    """Open a connection to the SQLite database.

    sqlite3.connect() creates the file if it doesn't exist yet.
    We set row_factory to sqlite3.Row so that query results can be
    accessed by column name (like a dict) instead of just by index.

    Returns:
        A sqlite3.Connection object.
    """
    # Ensure the data directory exists.
    _DB_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(_DB_PATH))

    # This makes rows behave like dictionaries — you can do row["symbol"]
    # instead of row[0]. Much easier to read and less error-prone.
    conn.row_factory = sqlite3.Row

    # Enable WAL mode for better concurrent read/write performance.
    # WAL (Write-Ahead Logging) lets the Flask server read the database
    # while the bot is writing to it, without blocking either one.
    conn.execute("PRAGMA journal_mode=WAL")

    return conn


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all database tables if they don't already exist.

    This is safe to call multiple times — the "IF NOT EXISTS" clause
    means it won't overwrite existing tables or data. Call this once
    at bot startup.

    The tables are:

    trades — Every individual trade (buy or sell)
        Stores both live trades and backtest trades. The `source` column
        tells you which: "live" for real trades, "backtest" for simulated.
        The `backtest_run_id` links backtest trades to their parent run.

    backtest_runs — One row per backtest execution
        Stores the parameters (dates, capital) and summary results
        (return, win rate, drawdown). This is what the "Backtest History"
        list in the app will show.

    backtest_daily_results — Day-by-day results within a backtest
        Each row is one simulated trading day. Used to draw the equity
        curve chart and the daily timeline in backtest results.

    daily_summaries — End-of-day snapshots from live trading
        One row per live trading day. Tracks equity, P&L, strategy used,
        ELO rating, and market conditions. This feeds the Analysis tab.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # --- trades table ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'live',
            backtest_run_id INTEGER,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price REAL NOT NULL,
            pnl REAL,
            strategy TEXT,
            market_condition TEXT,
            stop_loss REAL,
            take_profit REAL,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (backtest_run_id) REFERENCES backtest_runs(id)
        )
    """)

    # --- backtest_runs table ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            starting_capital REAL NOT NULL,
            final_equity REAL,
            total_return REAL,
            total_return_pct REAL,
            total_trades INTEGER,
            win_rate REAL,
            avg_win REAL,
            avg_loss REAL,
            avg_daily_pnl REAL,
            max_drawdown REAL,
            max_drawdown_pct REAL,
            profitable_days INTEGER,
            losing_days INTEGER,
            elo_start REAL,
            elo_end REAL,
            elo_peak REAL,
            elo_lowest REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            duration_seconds REAL,
            settings_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # --- backtest_daily_results table ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_daily_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backtest_run_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            equity REAL NOT NULL,
            daily_pnl REAL NOT NULL,
            market_condition TEXT,
            strategy TEXT,
            trade_count INTEGER DEFAULT 0,
            spy_change_pct REAL,
            volatility_level TEXT,
            news_headline TEXT,
            elo_rating REAL,
            sat_out_flag INTEGER DEFAULT 0,
            FOREIGN KEY (backtest_run_id) REFERENCES backtest_runs(id)
        )
    """)

    # --- daily_summaries table (live trading) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            equity REAL NOT NULL,
            cash REAL NOT NULL,
            daily_pnl REAL NOT NULL,
            daily_pnl_pct REAL,
            trade_count INTEGER DEFAULT 0,
            win_count INTEGER DEFAULT 0,
            loss_count INTEGER DEFAULT 0,
            win_rate REAL,
            market_condition TEXT,
            strategy TEXT,
            elo_rating REAL,
            elo_rank TEXT,
            daily_target REAL,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # --- bot_proposals table ---
    # Stores improvement suggestions from both the rule-based engine and
    # Claude API deep analysis. Each proposal is a concrete change the bot
    # wants to make (e.g., "lower ATR multiplier for momentum from 1.5 to 1.2").
    # The user must approve before any change takes effect.
    #
    # Statuses:
    #   pending  — new proposal, waiting for user action
    #   tested   — user clicked "Backtest First", results are linked
    #   approved — user accepted the change
    #   rejected — user declined the change
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'rule',
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            parameter_changes TEXT,
            current_values TEXT,
            backtest_run_id INTEGER,
            replay_date TEXT,
            replay_result TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at TEXT,
            FOREIGN KEY (backtest_run_id) REFERENCES backtest_runs(id)
        )
    """)

    # --- Indexes for fast lookups ---
    # Indexes speed up common queries. Without them, SQLite would have to
    # scan every row in the table to find what you're looking for.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_trades_source ON trades(source)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_trades_backtest_run "
        "ON trades(backtest_run_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_backtest_daily_run "
        "ON backtest_daily_results(backtest_run_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_daily_summaries_date "
        "ON daily_summaries(date)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_status "
        "ON bot_proposals(status)"
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Insert functions — saving data to the database
# ---------------------------------------------------------------------------

def insert_trade(
    symbol: str,
    action: str,
    qty: int,
    price: float,
    timestamp: str | None = None,
    pnl: float | None = None,
    strategy: str | None = None,
    market_condition: str | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    source: str = "live",
    backtest_run_id: int | None = None,
    notes: str | None = None,
) -> int:
    """Save a single trade to the database.

    Call this every time the bot executes a buy or sell, whether live
    or during a backtest. The `source` parameter distinguishes them.

    Args:
        symbol: Stock ticker (e.g. "AAPL").
        action: "buy" or "sell".
        qty: Number of shares.
        price: Price per share.
        timestamp: When the trade happened (ISO format string).
            Defaults to the current time if not provided.
        pnl: Profit/loss for sell trades. None for buys.
        strategy: Which strategy generated this trade.
        market_condition: Market condition at the time.
        stop_loss: Stop loss price (if set).
        take_profit: Take profit price (if set).
        source: "live" or "backtest".
        backtest_run_id: Links to backtest_runs.id (for backtest trades).
        notes: Any extra info.

    Returns:
        The ID of the newly inserted row.
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO trades (
            source, backtest_run_id, timestamp, symbol, action, qty,
            price, pnl, strategy, market_condition, stop_loss,
            take_profit, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        source, backtest_run_id, timestamp, symbol, action, qty,
        price, pnl, strategy, market_condition, stop_loss,
        take_profit, notes,
    ))

    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return trade_id


def insert_backtest_run(
    start_date: str,
    end_date: str,
    starting_capital: float,
    name: str | None = None,
    settings: dict | None = None,
) -> int:
    """Create a new backtest run record (before the backtest starts).

    We insert the row with status='running' first, then update it with
    results when the backtest finishes. This lets the frontend show
    "in progress" backtests.

    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        end_date: Backtest end date (YYYY-MM-DD).
        starting_capital: Initial capital amount.
        name: Optional human-readable name (e.g. "COVID Crash Test").
        settings: Optional dict of settings used (saved as JSON).

    Returns:
        The ID of the new backtest_runs row.
    """
    settings_json = json.dumps(settings) if settings else None

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO backtest_runs (
            name, start_date, end_date, starting_capital,
            status, settings_json
        ) VALUES (?, ?, ?, ?, 'running', ?)
    """, (name, start_date, end_date, starting_capital, settings_json))

    run_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return run_id


def update_backtest_run(
    run_id: int,
    results: dict[str, Any],
) -> None:
    """Update a backtest run with its final results.

    Called after the backtest finishes. Updates the row with all the
    computed metrics (return, win rate, drawdown, etc.).

    Args:
        run_id: The backtest_runs.id to update.
        results: A dictionary with the backtest results. Expected keys:
            final_equity, total_return, total_return_pct, total_trades,
            win_rate, avg_win, avg_loss, avg_daily_pnl, max_drawdown,
            max_drawdown_pct, profitable_days, losing_days.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE backtest_runs SET
            final_equity = ?,
            total_return = ?,
            total_return_pct = ?,
            total_trades = ?,
            win_rate = ?,
            avg_win = ?,
            avg_loss = ?,
            avg_daily_pnl = ?,
            max_drawdown = ?,
            max_drawdown_pct = ?,
            profitable_days = ?,
            losing_days = ?,
            elo_start = ?,
            elo_end = ?,
            elo_peak = ?,
            elo_lowest = ?,
            status = ?,
            error_message = ?,
            duration_seconds = ?
        WHERE id = ?
    """, (
        results.get("final_equity"),
        results.get("total_return"),
        results.get("total_return_pct"),
        results.get("total_trades"),
        results.get("win_rate"),
        results.get("avg_win"),
        results.get("avg_loss"),
        results.get("avg_daily_pnl"),
        results.get("max_drawdown"),
        results.get("max_drawdown_pct"),
        results.get("profitable_days"),
        results.get("losing_days"),
        results.get("elo_start"),
        results.get("elo_end"),
        results.get("elo_peak"),
        results.get("elo_lowest"),
        results.get("status", "completed"),
        results.get("error_message"),
        results.get("duration_seconds"),
        run_id,
    ))

    conn.commit()
    conn.close()


def insert_backtest_daily_result(
    backtest_run_id: int,
    date: str,
    equity: float,
    daily_pnl: float,
    market_condition: str | None = None,
    strategy: str | None = None,
    trade_count: int = 0,
    spy_change_pct: float | None = None,
    volatility_level: str | None = None,
    elo_rating: float | None = None,
    sat_out_flag: bool = False,
) -> int:
    """Save one day's results from a backtest.

    Called once per simulated trading day during a backtest. These rows
    are used to draw the equity curve and daily timeline in the results.

    Args:
        backtest_run_id: Links to backtest_runs.id.
        date: The simulated date (YYYY-MM-DD).
        equity: Portfolio value at end of day.
        daily_pnl: Profit/loss for the day.
        market_condition: Market condition that day.
        strategy: Strategy used that day.
        trade_count: Number of trades executed that day.
        spy_change_pct: SPY's daily % change (for context).
        volatility_level: Volatility assessment (for context).
        elo_rating: ELO rating at end of day.
        sat_out_flag: True if the bot would have sat out this day
            under extreme volatility rules (analysis-only).

    Returns:
        The ID of the new row.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO backtest_daily_results (
            backtest_run_id, date, equity, daily_pnl,
            market_condition, strategy, trade_count,
            spy_change_pct, volatility_level, elo_rating, sat_out_flag
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        backtest_run_id, date, equity, daily_pnl,
        market_condition, strategy, trade_count,
        spy_change_pct, volatility_level, elo_rating,
        1 if sat_out_flag else 0,
    ))

    row_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return row_id


def insert_daily_summary(
    date: str,
    equity: float,
    cash: float,
    daily_pnl: float,
    daily_pnl_pct: float | None = None,
    trade_count: int = 0,
    win_count: int = 0,
    loss_count: int = 0,
    market_condition: str | None = None,
    strategy: str | None = None,
    elo_rating: float | None = None,
    elo_rank: str | None = None,
    daily_target: float | None = None,
    notes: str | None = None,
) -> int:
    """Save a daily summary from live trading.

    Called once at the end of each live trading day. If a summary for
    this date already exists, it gets replaced (the date column has a
    UNIQUE constraint, so we use INSERT OR REPLACE).

    Args:
        date: The trading date (YYYY-MM-DD).
        equity: Account equity at end of day.
        cash: Cash balance at end of day.
        daily_pnl: Profit/loss for the day.
        daily_pnl_pct: Daily P&L as a percentage.
        trade_count: Number of trades executed.
        win_count: Number of winning trades.
        loss_count: Number of losing trades.
        market_condition: Market condition for the day.
        strategy: Primary strategy used.
        elo_rating: ELO rating at end of day.
        elo_rank: ELO rank name at end of day.
        daily_target: The daily profit target that was active.
        notes: Any extra info.

    Returns:
        The ID of the inserted/replaced row.
    """
    win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO daily_summaries (
            date, equity, cash, daily_pnl, daily_pnl_pct,
            trade_count, win_count, loss_count, win_rate,
            market_condition, strategy, elo_rating, elo_rank,
            daily_target, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        date, equity, cash, daily_pnl, daily_pnl_pct,
        trade_count, win_count, loss_count, win_rate,
        market_condition, strategy, elo_rating, elo_rank,
        daily_target, notes,
    ))

    row_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return row_id


# ---------------------------------------------------------------------------
# Query functions — reading data back from the database
# ---------------------------------------------------------------------------

def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Convert a list of sqlite3.Row objects to plain dictionaries.

    sqlite3.Row objects support dict-like access but aren't actual dicts.
    This helper converts them so they can be easily serialized to JSON
    (which Flask's jsonify needs).

    Args:
        rows: A list of sqlite3.Row objects from a query.

    Returns:
        A list of plain Python dictionaries.
    """
    return [dict(row) for row in rows]


def get_trades(
    source: str | None = None,
    symbol: str | None = None,
    backtest_run_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch trades from the database with optional filters.

    Args:
        source: Filter by "live" or "backtest". None returns all.
        symbol: Filter by stock ticker. None returns all symbols.
        backtest_run_id: Filter by backtest run. None returns all.
        limit: Maximum number of trades to return.
        offset: Number of trades to skip (for pagination).

    Returns:
        A list of trade dictionaries, newest first.
    """
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM trades WHERE 1=1"
    params: list[Any] = []

    if source is not None:
        query += " AND source = ?"
        params.append(source)

    if symbol is not None:
        query += " AND symbol = ?"
        params.append(symbol)

    if backtest_run_id is not None:
        query += " AND backtest_run_id = ?"
        params.append(backtest_run_id)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return _rows_to_dicts(rows)


def get_backtest_runs(
    limit: int = 50,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch backtest runs, newest first.

    Args:
        limit: Maximum number of runs to return.
        status: Filter by status ("completed", "running", "failed").
            None returns all statuses.

    Returns:
        A list of backtest run dictionaries.
    """
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM backtest_runs WHERE 1=1"
    params: list[Any] = []

    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return _rows_to_dicts(rows)


def get_backtest_run(run_id: int) -> dict[str, Any] | None:
    """Fetch a single backtest run by ID.

    Args:
        run_id: The backtest_runs.id to look up.

    Returns:
        A dictionary with the run's data, or None if not found.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def get_backtest_daily_results(
    backtest_run_id: int,
) -> list[dict[str, Any]]:
    """Fetch all daily results for a specific backtest run.

    Args:
        backtest_run_id: The backtest run to get daily results for.

    Returns:
        A list of daily result dictionaries, ordered by date.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM backtest_daily_results "
        "WHERE backtest_run_id = ? ORDER BY date",
        (backtest_run_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    return _rows_to_dicts(rows)


def get_daily_summaries(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch live trading daily summaries.

    Args:
        start_date: Filter to dates on or after this (YYYY-MM-DD).
        end_date: Filter to dates on or before this (YYYY-MM-DD).
        limit: Maximum number of rows to return.

    Returns:
        A list of daily summary dictionaries, newest first.
    """
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM daily_summaries WHERE 1=1"
    params: list[Any] = []

    if start_date is not None:
        query += " AND date >= ?"
        params.append(start_date)

    if end_date is not None:
        query += " AND date <= ?"
        params.append(end_date)

    query += " ORDER BY date DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return _rows_to_dicts(rows)


def get_trade_stats(
    source: str = "live",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Calculate aggregate trade statistics.

    This powers the Analysis tab's high-level summary cards. It computes
    win rate, average P&L, and breakdowns by strategy and symbol.

    Args:
        source: "live" or "backtest".
        start_date: Filter trades on or after this date.
        end_date: Filter trades on or before this date.

    Returns:
        A dictionary with computed stats:
            total_trades, win_rate, avg_pnl, total_pnl,
            by_strategy (dict), by_symbol (dict).
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Base filter for sell trades (they have P&L).
    query = (
        "SELECT * FROM trades "
        "WHERE source = ? AND action = 'sell' AND pnl IS NOT NULL"
    )
    params: list[Any] = [source]

    if start_date:
        query += " AND timestamp >= ?"
        params.append(start_date)
    if end_date:
        query += " AND timestamp <= ?"
        params.append(end_date)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    trades = _rows_to_dicts(rows)

    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "total_pnl": 0.0,
            "by_strategy": {},
            "by_symbol": {},
        }

    # Calculate stats.
    total = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    total_pnl = sum(t["pnl"] for t in trades)

    # Group by strategy.
    by_strategy: dict[str, dict] = {}
    for t in trades:
        strat = t.get("strategy") or "unknown"
        if strat not in by_strategy:
            by_strategy[strat] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        by_strategy[strat]["trades"] += 1
        by_strategy[strat]["total_pnl"] += t["pnl"]
        if t["pnl"] > 0:
            by_strategy[strat]["wins"] += 1

    # Add win rate to each strategy.
    for strat_stats in by_strategy.values():
        strat_stats["win_rate"] = (
            strat_stats["wins"] / strat_stats["trades"] * 100
            if strat_stats["trades"] > 0 else 0.0
        )

    # Group by symbol.
    by_symbol: dict[str, dict] = {}
    for t in trades:
        sym = t["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        by_symbol[sym]["trades"] += 1
        by_symbol[sym]["total_pnl"] += t["pnl"]
        if t["pnl"] > 0:
            by_symbol[sym]["wins"] += 1

    return {
        "total_trades": total,
        "win_rate": (wins / total * 100) if total > 0 else 0.0,
        "avg_pnl": total_pnl / total,
        "total_pnl": total_pnl,
        "by_strategy": by_strategy,
        "by_symbol": by_symbol,
    }


# ---------------------------------------------------------------------------
# Proposal functions — bot improvement suggestions
# ---------------------------------------------------------------------------

def insert_proposal(
    title: str,
    description: str,
    source: str = "rule",
    parameter_changes: dict | None = None,
    current_values: dict | None = None,
    replay_date: str | None = None,
) -> int:
    """Save a new bot proposal to the database.

    A proposal is a suggestion for improving the bot — like "lower the
    ATR multiplier for momentum" or "avoid trading on Mondays." The bot
    generates these from its analysis, but they need user approval.

    Args:
        title: Short summary (e.g. "Reduce momentum ATR multiplier").
        description: Detailed explanation of why this change is suggested.
        source: Who generated it — "rule" (automatic) or "claude" (AI).
        parameter_changes: Dict of proposed setting changes, e.g.
            {"STOP_LOSS_ATR_MULTIPLIERS.momentum": 1.2}.
        current_values: Dict of current values for those settings.
        replay_date: If this is a single-day replay suggestion, the date.

    Returns:
        The ID of the new proposal.
    """
    changes_json = json.dumps(parameter_changes) if parameter_changes else None
    current_json = json.dumps(current_values) if current_values else None

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO bot_proposals (
            source, title, description, parameter_changes,
            current_values, replay_date
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (source, title, description, changes_json, current_json, replay_date))

    proposal_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return proposal_id


def get_proposals(
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch bot proposals, newest first.

    Args:
        status: Filter by "pending", "approved", "rejected", or "tested".
            None returns all.
        limit: Maximum number of proposals to return.

    Returns:
        A list of proposal dictionaries. The parameter_changes and
        current_values fields are parsed from JSON back into dicts.
    """
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM bot_proposals WHERE 1=1"
    params: list[Any] = []

    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    proposals = _rows_to_dicts(rows)

    # Parse JSON fields back into dicts so the API can serve them.
    for p in proposals:
        if p.get("parameter_changes"):
            p["parameter_changes"] = json.loads(p["parameter_changes"])
        if p.get("current_values"):
            p["current_values"] = json.loads(p["current_values"])
        if p.get("replay_result"):
            p["replay_result"] = json.loads(p["replay_result"])

    return proposals


def get_proposal(proposal_id: int) -> dict[str, Any] | None:
    """Fetch a single proposal by ID.

    Args:
        proposal_id: The bot_proposals.id to look up.

    Returns:
        A proposal dictionary, or None if not found.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM bot_proposals WHERE id = ?", (proposal_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    proposal = dict(row)
    if proposal.get("parameter_changes"):
        proposal["parameter_changes"] = json.loads(proposal["parameter_changes"])
    if proposal.get("current_values"):
        proposal["current_values"] = json.loads(proposal["current_values"])
    if proposal.get("replay_result"):
        proposal["replay_result"] = json.loads(proposal["replay_result"])

    return proposal


def update_proposal_status(
    proposal_id: int,
    status: str,
    backtest_run_id: int | None = None,
    replay_result: dict | None = None,
) -> None:
    """Update a proposal's status (approve, reject, or mark as tested).

    Args:
        proposal_id: The proposal to update.
        status: New status — "approved", "rejected", or "tested".
        backtest_run_id: Link to a backtest run (if tested).
        replay_result: Single-day replay results (JSON-serializable dict).
    """
    conn = get_connection()
    cursor = conn.cursor()

    replay_json = json.dumps(replay_result) if replay_result else None
    resolved_at = datetime.now().isoformat() if status in ("approved", "rejected") else None

    cursor.execute("""
        UPDATE bot_proposals SET
            status = ?,
            backtest_run_id = COALESCE(?, backtest_run_id),
            replay_result = COALESCE(?, replay_result),
            resolved_at = COALESCE(?, resolved_at)
        WHERE id = ?
    """, (status, backtest_run_id, replay_json, resolved_at, proposal_id))

    conn.commit()
    conn.close()
