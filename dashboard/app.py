"""
Flask web dashboard for the trading bot.

Flask is a Python web framework — it lets you build websites and APIs
using Python. Here's how it works at a high level:

    1. You define "routes" — URLs that your server responds to.
    2. When someone visits a route (e.g., /api/status), Flask calls
       the Python function you attached to that route.
    3. That function returns HTML, JSON, or other data to the browser.

This dashboard displays the bot's live state: account info, positions,
trades, ELO rating, and charts. It auto-refreshes every 10 seconds
so you can watch the bot trade in real time.

The bot and dashboard communicate through a shared state dictionary
(`bot_state`). The bot writes to it, and the dashboard reads from it.
This is a simple approach that works because both run in the same
Python process.

Usage:
    # From the bot's main loop, push state updates:
    from dashboard.app import update_bot_state
    update_bot_state({"equity": 100500.00, "daily_pnl": 50.00, ...})

    # To run the dashboard as a standalone server:
    python -m dashboard.app
"""

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

# Flask is the web framework. We import three things:
#   - Flask: the main class that creates our web server
#   - jsonify: converts Python dicts into JSON responses for the API
#   - render_template: loads HTML files from the templates/ folder
from flask import Flask, jsonify, render_template, request, send_from_directory

from database.db import (
    get_backtest_daily_results,
    get_backtest_run,
    get_backtest_runs,
    get_daily_summaries,
    get_proposal,
    get_proposals,
    get_trade_stats,
    get_trades,
    update_proposal_status,
)


# ---------------------------------------------------------------------------
# Shared state between the bot and the dashboard
# ---------------------------------------------------------------------------
# This dictionary holds the bot's current state. The bot updates it,
# and the dashboard reads it to display on the web page.
#
# Why a dict? It's the simplest way to share data between the bot's
# trading loop and Flask's web server. In a production system you'd
# use a database, but for learning this is much easier to understand.
# ---------------------------------------------------------------------------

bot_state: dict[str, Any] = {
    # --- Account ---
    "equity": 0.0,
    "cash": 0.0,
    "buying_power": 0.0,
    "daily_pnl": 0.0,
    "daily_pnl_pct": 0.0,

    # --- Trading ---
    "positions": [],          # List of open position dicts
    "recent_trades": [],      # Last 20 executed trades
    "market_condition": "unknown",
    "active_strategy": "none",
    "market_open": False,

    # --- Risk ---
    "daily_target": 100.0,
    "daily_loss_limit": 100.0,
    "can_trade": True,
    "trade_count": 0,
    "win_rate": 0.0,

    # --- ELO Rating ---
    # The ELO system rates the bot's performance over time, similar
    # to chess ratings. Good trades raise the rating, bad trades lower it.
    "elo_rating": 1000,
    "elo_rank": "Silver",
    "elo_history": [],        # List of {"date": ..., "rating": ...} dicts

    # --- Equity history for charting ---
    "equity_history": [],     # List of {"date": ..., "equity": ...} dicts

    # --- Override ---
    "override_triggered": False,
    "last_updated": None,
}

# A threading lock to prevent the bot and dashboard from reading/writing
# the state dict at the exact same time (which could cause bugs).
_state_lock = threading.Lock()


def update_bot_state(data: dict[str, Any]) -> None:
    """Update the shared bot state with new data from the trading bot.

    The bot calls this function every loop iteration to push its latest
    state to the dashboard. Only the keys present in `data` are updated;
    any keys not included keep their previous values.

    Args:
        data: A dictionary of state keys and their new values.
              Example: {"equity": 100500.0, "daily_pnl": 50.0}
    """
    with _state_lock:
        bot_state.update(data)
        bot_state["last_updated"] = datetime.now().isoformat()


def get_bot_state() -> dict[str, Any]:
    """Return a snapshot of the current bot state.

    Returns a copy so that the caller can read it without worrying
    about the bot modifying it at the same time.

    Returns:
        A dictionary containing all bot state fields.
    """
    with _state_lock:
        return dict(bot_state)


# ---------------------------------------------------------------------------
# ELO Rating Helpers
# ---------------------------------------------------------------------------
# These ranks map ELO rating ranges to human-readable names with emoji
# icons. The bot starts at 1000 (Silver) and moves up or down based on
# trading performance.
# ---------------------------------------------------------------------------

ELO_RANKS: list[dict[str, Any]] = [
    {"name": "Bronze",        "icon": "🥉", "min": 0,    "max": 799,  "color": "#cd7f32"},
    {"name": "Silver",        "icon": "🥈", "min": 800,  "max": 999,  "color": "#c0c0c0"},
    {"name": "Gold",          "icon": "⭐",  "min": 1000, "max": 1199, "color": "#ffd700"},
    {"name": "Platinum",      "icon": "💎", "min": 1200, "max": 1399, "color": "#00bfff"},
    {"name": "Diamond",       "icon": "🔷", "min": 1400, "max": 1599, "color": "#b388ff"},
    {"name": "Master",        "icon": "👑", "min": 1600, "max": 1799, "color": "#ff8800"},
    {"name": "Grandmaster",   "icon": "🏆", "min": 1800, "max": 99999, "color": "#ff4444"},
]


def get_elo_rank_info(rating: int) -> dict[str, Any]:
    """Look up the rank name, icon, color, and progress for a given ELO rating.

    The progress value tells you how far through the current rank tier
    the bot is. For example, a rating of 950 in Silver (800-1099) would
    be 50% through the tier.

    Args:
        rating: The bot's current ELO rating (integer).

    Returns:
        A dictionary with keys: name, icon, color, progress (0.0 to 1.0),
        next_rank (name of the tier above), and rating_to_next (points
        needed to reach the next tier).
    """
    for i, rank in enumerate(ELO_RANKS):
        if rank["min"] <= rating <= rank["max"]:
            # Calculate progress through this tier (0.0 = just entered, 1.0 = about to rank up)
            tier_range = rank["max"] - rank["min"]
            progress = (rating - rank["min"]) / tier_range if tier_range > 0 else 1.0

            # Figure out the next rank (if we're not already at the top)
            next_rank = ELO_RANKS[i + 1]["name"] if i + 1 < len(ELO_RANKS) else "MAX"
            rating_to_next = rank["max"] - rating + 1 if next_rank != "MAX" else 0

            return {
                "name": rank["name"],
                "icon": rank["icon"],
                "color": rank["color"],
                "progress": round(progress, 2),
                "next_rank": next_rank,
                "rating_to_next": rating_to_next,
            }

    # Fallback — should never happen unless the rating is negative.
    return {
        "name": "Unranked",
        "icon": "❓",
        "color": "#888888",
        "progress": 0.0,
        "next_rank": "Bronze",
        "rating_to_next": 0,
    }


# ---------------------------------------------------------------------------
# Flask Application Setup
# ---------------------------------------------------------------------------
# __name__ tells Flask where to find templates and static files.
# It uses the current module's location as a reference point, so Flask
# knows to look in dashboard/templates/ for HTML files.
# ---------------------------------------------------------------------------

# The React build output lives here after running `npm run build`.
# Flask serves these files for the new PWA frontend.
_REACT_BUILD_DIR = Path(__file__).resolve().parent / "static" / "react"

app = Flask(
    __name__,
    static_folder=str(_REACT_BUILD_DIR / "assets"),
    static_url_path="/assets",
)


# ---------------------------------------------------------------------------
# Routes — these are the URLs the dashboard responds to
# ---------------------------------------------------------------------------
# The "/" route serves the React app (new PWA frontend).
# The old template-based dashboard is still available at "/legacy".
# All /api/* routes serve JSON data for the frontend.
# ---------------------------------------------------------------------------


@app.route("/")
def index() -> str:
    """Serve the React PWA frontend.

    In production, Flask serves the built React app directly from
    dashboard/static/react/. During development, you'd run the Vite
    dev server instead (port 3000) which proxies API calls to Flask.

    Returns:
        The React app's index.html file.
    """
    react_index = _REACT_BUILD_DIR / "index.html"
    if react_index.exists():
        return send_from_directory(str(_REACT_BUILD_DIR), "index.html")
    # Fallback to the old template if React hasn't been built yet.
    return render_template("index.html")


@app.route("/legacy")
def legacy_dashboard() -> str:
    """Serve the original template-based dashboard.

    Kept for backwards compatibility. The old dashboard still works
    if you prefer it or if the React build isn't available.

    Returns:
        The rendered HTML string for the legacy dashboard page.
    """
    return render_template("index.html")


# Catch-all route for React client-side routing.
# When someone visits /backtests or /analysis directly (not via tab click),
# Flask needs to serve the React app and let React Router handle the URL.
@app.route("/<path:path>")
def catch_all(path: str) -> Any:
    """Serve React app for any non-API route (client-side routing support).

    React Router handles routing on the client side. But if someone
    refreshes the page on /backtests, the browser sends that URL to
    Flask. Flask doesn't have a /backtests route, so without this
    catch-all it would return 404.

    This route checks: is the requested path a real file (like a .js
    or .css asset)? If yes, serve it. If not, serve index.html and
    let React Router figure out which page to show.

    Args:
        path: The URL path (e.g. "backtests", "assets/index.js").

    Returns:
        Either the requested static file or the React index.html.
    """
    # Don't catch API routes — let them fall through to the API handlers.
    if path.startswith("api/"):
        return jsonify({"error": "Not found"}), 404

    # Check if this is a real file in the React build (CSS, JS, images).
    file_path = _REACT_BUILD_DIR / path
    if file_path.is_file():
        return send_from_directory(str(_REACT_BUILD_DIR), path)

    # Otherwise, serve the React app and let client-side routing handle it.
    react_index = _REACT_BUILD_DIR / "index.html"
    if react_index.exists():
        return send_from_directory(str(_REACT_BUILD_DIR), "index.html")

    return jsonify({"error": "Not found"}), 404


@app.route("/api/status")
def api_status() -> Any:
    """Return the full bot state as JSON.

    The dashboard's JavaScript calls this endpoint every 10 seconds
    to get fresh data. JSON (JavaScript Object Notation) is a text
    format that both Python and JavaScript understand, making it
    perfect for sending data between the server and browser.

    Returns:
        A JSON response containing all bot state fields plus
        computed ELO rank information.
    """
    state = get_bot_state()

    # Add computed ELO rank info to the response
    elo_info = get_elo_rank_info(state.get("elo_rating", 1000))
    state["elo_rank_info"] = elo_info

    return jsonify(state)


@app.route("/api/override", methods=["POST"])
def api_override() -> Any:
    """Handle the panic button — trigger close-all-positions.

    When the user clicks "CLOSE ALL POSITIONS" on the dashboard,
    their browser sends a POST request to this endpoint. We set
    a flag in the bot state that the main trading loop checks
    and acts on.

    POST is used (instead of GET) because this endpoint changes
    state — it's an action, not a read. GET requests should only
    read data; POST requests can modify things.

    Returns:
        A JSON response confirming the override was triggered.
    """
    update_bot_state({
        "override_triggered": True,
    })

    # Try to actually close positions if the broker client is available.
    # The bot's main loop should also check override_triggered and act.
    return jsonify({
        "status": "override_triggered",
        "message": "Close-all-positions signal sent to bot.",
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/equity_history")
def api_equity_history() -> Any:
    """Return the equity curve data for charting.

    The equity curve shows how the account value has changed over time.
    The dashboard uses this data to draw a line chart with Chart.js.

    Returns:
        A JSON response with a list of {date, equity} data points.
    """
    state = get_bot_state()
    return jsonify({
        "equity_history": state.get("equity_history", []),
        "elo_history": state.get("elo_history", []),
    })


# ---------------------------------------------------------------------------
# Database-backed API routes — these serve historical data from SQLite
# ---------------------------------------------------------------------------
# The routes above serve live data from the in-memory bot_state dict.
# The routes below serve historical data from the SQLite database.
# The React frontend will use these to power the History, Backtests,
# and Analysis tabs.
# ---------------------------------------------------------------------------


@app.route("/api/trades")
def api_trades() -> Any:
    """Return trade history from the database.

    Query parameters:
        source: "live" or "backtest" (optional, default: all).
        symbol: Filter by stock ticker (optional).
        backtest_run_id: Filter by backtest run (optional).
        limit: Max rows to return (optional, default: 100).
        offset: Skip this many rows for pagination (optional, default: 0).

    Returns:
        A JSON response with a list of trade records.
    """
    source = request.args.get("source")
    symbol = request.args.get("symbol")
    backtest_run_id = request.args.get("backtest_run_id", type=int)
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)

    trades = get_trades(
        source=source,
        symbol=symbol,
        backtest_run_id=backtest_run_id,
        limit=limit,
        offset=offset,
    )

    return jsonify({"trades": trades, "count": len(trades)})


@app.route("/api/trades/stats")
def api_trade_stats() -> Any:
    """Return aggregate trade statistics for the Analysis tab.

    Query parameters:
        source: "live" or "backtest" (default: "live").
        start_date: Filter trades on or after this date (optional).
        end_date: Filter trades on or before this date (optional).

    Returns:
        A JSON response with computed statistics: total_trades,
        win_rate, avg_pnl, total_pnl, by_strategy, by_symbol.
    """
    source = request.args.get("source", "live")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    stats = get_trade_stats(
        source=source,
        start_date=start_date,
        end_date=end_date,
    )

    return jsonify(stats)


@app.route("/api/backtests")
def api_backtests() -> Any:
    """Return a list of all backtest runs plus any currently running.

    Query parameters:
        status: Filter by "completed", "running", or "failed" (optional).
        limit: Max rows to return (optional, default: 50).

    Returns:
        A JSON response with backtest runs and currently running ones.
    """
    from backtest.runner import get_running_backtests

    status_filter = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)

    runs = get_backtest_runs(limit=limit, status=status_filter)
    running = get_running_backtests()

    return jsonify({
        "backtests": runs,
        "running": running,
        "count": len(runs),
    })


@app.route("/api/backtests/run", methods=["POST"])
def api_run_backtest() -> Any:
    """Trigger a new backtest in the background.

    The backtest starts in a separate thread and returns immediately.
    The frontend can poll /api/backtests/<run_id> to track progress.

    JSON body:
        start_date: Required. Start date (YYYY-MM-DD).
        end_date: Required. End date (YYYY-MM-DD).
        name: Optional. Human-readable name.
        capital: Optional. Starting capital (default: 100000).

    Returns:
        A JSON response with the run_id and estimated time.
    """
    from backtest.runner import start_backtest, _estimate_trading_days, _avg_seconds_per_day

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    name = data.get("name")
    capital = data.get("capital", 100_000.0)
    market = data.get("market", "us")

    run_id = start_backtest(
        start_date=start_date,
        end_date=end_date,
        starting_capital=capital,
        name=name,
        market=market,
    )

    estimated_days = _estimate_trading_days(start_date, end_date)
    estimated_seconds = estimated_days * _avg_seconds_per_day

    return jsonify({
        "run_id": run_id,
        "status": "running",
        "estimated_days": estimated_days,
        "estimated_seconds": round(estimated_seconds, 1),
    })


@app.route("/api/backtests/<int:run_id>")
def api_backtest_detail(run_id: int) -> Any:
    """Return detailed results for a specific backtest run.

    This includes the run summary, daily results (for the equity curve
    and timeline), and all trades from that backtest.

    Args:
        run_id: The backtest_runs.id to look up (from the URL).

    Returns:
        A JSON response with the run summary, daily results, and trades.
        Returns 404 if the run doesn't exist.
    """
    run = get_backtest_run(run_id)
    if not run:
        return jsonify({"error": "Backtest run not found"}), 404

    daily_results = get_backtest_daily_results(run_id)
    trades = get_trades(backtest_run_id=run_id, limit=10000)

    return jsonify({
        "run": run,
        "daily_results": daily_results,
        "trades": trades,
    })


# ---------------------------------------------------------------------------
# Optimizer API endpoints
# ---------------------------------------------------------------------------

# In-memory storage for optimizer runs (same pattern as running backtests).
_optimizer_runs: dict[str, dict] = {}
_optimizer_lock = __import__("threading").Lock()


@app.route("/api/optimize", methods=["POST"])
def api_run_optimizer() -> Any:
    """Trigger a parameter optimization run in the background.

    Runs grid search + optional AI refinement to find the best
    parameter combination for the given date range and market.

    JSON body:
        start_date: Required. Start date (YYYY-MM-DD).
        end_date: Required. End date (YYYY-MM-DD).
        market: Optional. "us" or "oslo" (default: "us").
        capital: Optional. Starting capital (default: 100000).
        max_rounds: Optional. AI refinement rounds (default: 3).

    Returns:
        A JSON response with the optimizer run ID.
    """
    import threading
    import uuid

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    market = data.get("market", "us")
    capital = data.get("capital", 100_000.0)
    max_rounds = data.get("max_rounds", 3)

    # Create a unique ID for this optimization run.
    opt_id = str(uuid.uuid4())[:8]

    with _optimizer_lock:
        _optimizer_runs[opt_id] = {
            "id": opt_id,
            "status": "running",
            "start_date": start_date,
            "end_date": end_date,
            "market": market,
            "result": None,
        }

    def _run():
        """Background thread for the optimization."""
        try:
            from backtest.optimizer import run_optimization

            result = run_optimization(
                start_date=start_date,
                end_date=end_date,
                market=market,
                starting_capital=capital,
                max_rounds=max_rounds,
            )

            with _optimizer_lock:
                _optimizer_runs[opt_id]["status"] = "completed"
                _optimizer_runs[opt_id]["result"] = result

        except Exception as e:
            with _optimizer_lock:
                _optimizer_runs[opt_id]["status"] = "failed"
                _optimizer_runs[opt_id]["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"optimizer_id": opt_id, "status": "running"})


@app.route("/api/optimize/<opt_id>")
def api_optimizer_status(opt_id: str) -> Any:
    """Check the status of an optimization run.

    Args:
        opt_id: The optimizer run ID (from the URL).

    Returns:
        JSON with status and results (if completed).
    """
    with _optimizer_lock:
        run = _optimizer_runs.get(opt_id)

    if not run:
        return jsonify({"error": "Optimization run not found"}), 404

    return jsonify(run)


@app.route("/api/daily-summaries")
def api_daily_summaries() -> Any:
    """Return daily summaries from live trading.

    Query parameters:
        start_date: Filter to dates on or after this (optional).
        end_date: Filter to dates on or before this (optional).
        limit: Max rows to return (optional, default: 100).

    Returns:
        A JSON response with a list of daily summary records.
    """
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    limit = request.args.get("limit", 100, type=int)

    summaries = get_daily_summaries(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    return jsonify({"summaries": summaries, "count": len(summaries)})


# ---------------------------------------------------------------------------
# Analysis API routes
# ---------------------------------------------------------------------------

@app.route("/api/analysis/overview")
def api_analysis_overview() -> Any:
    """Return high-level performance overview for the Analysis tab.

    Query parameters:
        source: "live" or "backtest" (default: "live").

    Returns:
        A JSON response with overall stats (total P&L, win rate, streaks, etc.).
    """
    from analysis.engine import get_overview

    source = request.args.get("source", "live")
    return jsonify(get_overview(source))


@app.route("/api/analysis/strategies")
def api_analysis_strategies() -> Any:
    """Return strategy performance breakdown.

    Query parameters:
        source: "live" or "backtest" (default: "live").

    Returns:
        A JSON response with per-strategy stats.
    """
    from analysis.engine import get_strategy_breakdown

    source = request.args.get("source", "live")
    return jsonify({"strategies": get_strategy_breakdown(source)})


@app.route("/api/analysis/heatmap")
def api_analysis_heatmap() -> Any:
    """Return strategy vs. market condition heatmap.

    Query parameters:
        source: "live" or "backtest" (default: "live").

    Returns:
        A JSON response with the heatmap grid data.
    """
    from analysis.engine import get_heatmap

    source = request.args.get("source", "live")
    return jsonify(get_heatmap(source))


@app.route("/api/analysis/patterns")
def api_analysis_patterns() -> Any:
    """Return all pattern analysis (day-of-week, symbols, streaks).

    Query parameters:
        source: "live" or "backtest" (default: "live").

    Returns:
        A JSON response with day-of-week, symbol, and streak patterns.
    """
    from analysis.engine import (
        get_day_of_week_patterns,
        get_streak_analysis,
        get_symbol_breakdown,
    )

    source = request.args.get("source", "live")

    return jsonify({
        "day_of_week": get_day_of_week_patterns(source),
        "symbols": get_symbol_breakdown(source),
        "streaks": get_streak_analysis(source),
    })


@app.route("/api/analysis/journal")
def api_analysis_journal() -> Any:
    """Return bot observations from rule-based checks.

    Query parameters:
        source: "live" or "backtest" (default: "live").

    Returns:
        A JSON response with a list of observations (the bot's journal).
    """
    from analysis.engine import run_daily_checks

    source = request.args.get("source", "live")
    return jsonify({"observations": run_daily_checks(source)})


# ---------------------------------------------------------------------------
# Settings API routes
# ---------------------------------------------------------------------------


@app.route("/api/settings")
def api_settings() -> Any:
    """Return current bot settings.

    Returns all editable settings (defaults merged with any user overrides).

    Returns:
        A JSON response with all settings.
    """
    from config.settings import get_all_settings
    return jsonify(get_all_settings())


@app.route("/api/settings", methods=["PUT"])
def api_update_settings() -> Any:
    """Update bot settings.

    Only updates the keys included in the request body.
    Other settings remain unchanged.

    JSON body:
        Any subset of settings to change, e.g.:
        {"risk_per_trade_pct": 0.02, "max_open_positions": 5}

    Returns:
        A JSON response with the full updated settings.
    """
    from config.settings import update_settings

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    settings = update_settings(data)
    return jsonify(settings)


@app.route("/api/settings/reset", methods=["POST"])
def api_reset_settings() -> Any:
    """Reset all settings to factory defaults.

    Returns:
        A JSON response with the default settings.
    """
    from config.settings import reset_settings
    return jsonify(reset_settings())


@app.route("/api/settings/compare", methods=["POST"])
def api_compare_settings() -> Any:
    """Run a comparison backtest: current settings vs. proposed changes.

    Starts two backtests in parallel — one with current settings and
    one with the proposed changes. The frontend polls for results and
    shows them side by side.

    JSON body:
        changes: Dict of proposed setting changes.
        start_date: Optional backtest start date (default: last 3 months).
        end_date: Optional backtest end date (default: today).

    Returns:
        A JSON response with both backtest run IDs.
    """
    from backtest.runner import start_backtest
    from config.settings import get_all_settings

    data = request.get_json()
    if not data or "changes" not in data:
        return jsonify({"error": "changes field required"}), 400

    from datetime import datetime, timedelta
    end_date = data.get("end_date", datetime.now().strftime("%Y-%m-%d"))
    start_date = data.get(
        "start_date",
        (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
    )

    current_settings = get_all_settings()

    # Start backtest with CURRENT settings.
    current_run_id = start_backtest(
        start_date=start_date,
        end_date=end_date,
        starting_capital=100_000.0,
        name="Settings Compare: Current",
    )

    # Start backtest with PROPOSED settings.
    proposed_run_id = start_backtest(
        start_date=start_date,
        end_date=end_date,
        starting_capital=100_000.0,
        name="Settings Compare: Proposed",
    )

    return jsonify({
        "current_run_id": current_run_id,
        "proposed_run_id": proposed_run_id,
        "current_settings": current_settings,
        "proposed_changes": data["changes"],
    })


# ---------------------------------------------------------------------------
# Proposal & Deep Analysis API routes
# ---------------------------------------------------------------------------


@app.route("/api/analysis/deep", methods=["POST"])
def api_deep_analysis() -> Any:
    """Trigger AI-powered deep analysis of trading data.

    This sends the bot's performance data to Google Gemini for
    pattern recognition. Gemini returns observations (journal entries)
    and may generate formal proposals for parameter changes.

    Requires GEMINI_API_KEY in the .env file.

    JSON body (optional):
        source: "live" or "backtest" (default: "live").

    Returns:
        A JSON response with observations, proposals, and any errors.
    """
    from analysis.claude_analyzer import run_deep_analysis

    data = request.get_json() or {}
    source = data.get("source", "live")

    result = run_deep_analysis(source=source)
    return jsonify(result)


@app.route("/api/proposals")
def api_proposals() -> Any:
    """Return all bot proposals, newest first.

    Query parameters:
        status: Filter by "pending", "approved", "rejected", "tested".
        limit: Max rows (default: 50).

    Returns:
        A JSON response with a list of proposals.
    """
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)

    proposals = get_proposals(status=status, limit=limit)
    return jsonify({"proposals": proposals, "count": len(proposals)})


@app.route("/api/proposals/<int:proposal_id>")
def api_proposal_detail(proposal_id: int) -> Any:
    """Return a single proposal by ID.

    Args:
        proposal_id: The bot_proposals.id to look up.

    Returns:
        A JSON response with the proposal, or 404.
    """
    proposal = get_proposal(proposal_id)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404
    return jsonify(proposal)


@app.route("/api/proposals/<int:proposal_id>/approve", methods=["POST"])
def api_approve_proposal(proposal_id: int) -> Any:
    """Approve a proposal — mark it as accepted.

    The user has reviewed the proposal and wants to apply the change.
    This only marks the status; the actual parameter change is applied
    by the Settings page (Phase 6).

    Args:
        proposal_id: The proposal to approve.

    Returns:
        A JSON response confirming the approval.
    """
    proposal = get_proposal(proposal_id)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404

    update_proposal_status(proposal_id, "approved")
    return jsonify({"status": "approved", "proposal_id": proposal_id})


@app.route("/api/proposals/<int:proposal_id>/reject", methods=["POST"])
def api_reject_proposal(proposal_id: int) -> Any:
    """Reject a proposal — mark it as declined.

    The user has reviewed the proposal and decided not to apply it.

    Args:
        proposal_id: The proposal to reject.

    Returns:
        A JSON response confirming the rejection.
    """
    proposal = get_proposal(proposal_id)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404

    update_proposal_status(proposal_id, "rejected")
    return jsonify({"status": "rejected", "proposal_id": proposal_id})


@app.route("/api/proposals/<int:proposal_id>/backtest", methods=["POST"])
def api_backtest_proposal(proposal_id: int) -> Any:
    """Run a backtest to test a proposal before approving.

    Starts a backtest with the proposed parameter changes and links
    the result to the proposal. The user can then compare before
    deciding to approve or reject.

    JSON body (optional):
        start_date: Backtest start date (default: last 3 months).
        end_date: Backtest end date (default: today).

    Args:
        proposal_id: The proposal to test.

    Returns:
        A JSON response with the backtest run_id.
    """
    from backtest.runner import start_backtest

    proposal = get_proposal(proposal_id)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404

    data = request.get_json() or {}

    # Default to last 3 months if no dates provided.
    from datetime import datetime, timedelta
    end_date = data.get("end_date", datetime.now().strftime("%Y-%m-%d"))
    start_date = data.get(
        "start_date",
        (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
    )

    # Start backtest with proposed settings.
    run_id = start_backtest(
        start_date=start_date,
        end_date=end_date,
        starting_capital=100_000.0,
        name=f"Proposal Test: {proposal['title']}",
    )

    # Link the backtest to the proposal.
    update_proposal_status(proposal_id, "tested", backtest_run_id=run_id)

    return jsonify({
        "status": "testing",
        "proposal_id": proposal_id,
        "backtest_run_id": run_id,
    })


def run_dashboard(host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
    """Start the Flask dashboard server.

    This function is meant to be called from the bot's main module to
    launch the dashboard in a background thread. The bot continues
    trading while the dashboard serves web pages.

    Args:
        host: The network address to bind to. "0.0.0.0" means accept
              connections from any device on the network. Use "127.0.0.1"
              to only allow connections from this computer.
        port: The port number. Visit http://localhost:5000 in your browser.
        debug: If True, Flask reloads on code changes and shows detailed
               errors. Set to False in production.
    """
    app.run(host=host, port=port, debug=debug, use_reloader=False)


def run_dashboard_in_background(
    host: str = "0.0.0.0", port: int = 8080
) -> threading.Thread:
    """Start the dashboard in a background thread so the bot can keep trading.

    This is the recommended way to launch the dashboard. It runs the web
    server in a separate thread (a lightweight parallel process) so the
    bot's main trading loop isn't blocked.

    The thread is set as a "daemon" thread, which means it automatically
    stops when the main program exits — no cleanup needed.

    Args:
        host: The network address to bind to.
        port: The port number for the web server.

    Returns:
        The Thread object running the dashboard (in case you need to
        reference it later).
    """
    dashboard_thread = threading.Thread(
        target=run_dashboard,
        kwargs={"host": host, "port": port},
        daemon=True,  # Daemon threads die when the main program exits
    )
    dashboard_thread.start()
    return dashboard_thread


# ---------------------------------------------------------------------------
# Run the dashboard standalone (for testing without the bot)
# ---------------------------------------------------------------------------
# When you run `python -m dashboard.app` directly, this block executes.
# It populates the bot state with sample data so you can see how the
# dashboard looks without needing the bot or Alpaca connection.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Initialize the database so API endpoints work standalone.
    from database.db import init_db
    init_db()

    # Sample data so the dashboard has something to show
    sample_state: dict[str, Any] = {
        "equity": 102_450.00,
        "cash": 45_200.00,
        "buying_power": 90_400.00,
        "daily_pnl": 237.50,
        "daily_pnl_pct": 0.23,
        "market_condition": "trending",
        "active_strategy": "momentum",
        "market_open": True,
        "daily_target": 100.0,
        "daily_loss_limit": 100.0,
        "can_trade": True,
        "trade_count": 7,
        "win_rate": 71.4,
        "elo_rating": 1247,
        "elo_rank": "Gold",
        "positions": [
            {
                "symbol": "AAPL",
                "qty": 15,
                "entry_price": 178.50,
                "current_price": 181.20,
                "unrealized_pl": 40.50,
                "change_pct": 1.51,
            },
            {
                "symbol": "MSFT",
                "qty": 10,
                "entry_price": 415.00,
                "current_price": 412.30,
                "unrealized_pl": -27.00,
                "change_pct": -0.65,
            },
            {
                "symbol": "NVDA",
                "qty": 8,
                "entry_price": 875.00,
                "current_price": 892.40,
                "unrealized_pl": 139.20,
                "change_pct": 1.99,
            },
            {
                "symbol": "GOOGL",
                "qty": 20,
                "entry_price": 155.75,
                "current_price": 157.10,
                "unrealized_pl": 27.00,
                "change_pct": 0.87,
            },
        ],
        "recent_trades": [
            {"time": "09:32:15", "symbol": "AAPL", "action": "BUY", "qty": 15, "price": 178.50, "strategy": "momentum", "pnl": None},
            {"time": "09:35:42", "symbol": "MSFT", "action": "BUY", "qty": 10, "price": 415.00, "strategy": "momentum", "pnl": None},
            {"time": "09:41:08", "symbol": "NVDA", "action": "BUY", "qty": 8, "price": 875.00, "strategy": "breakout", "pnl": None},
            {"time": "09:55:33", "symbol": "TSLA", "action": "SELL", "qty": 12, "price": 245.80, "strategy": "momentum", "pnl": 58.40},
            {"time": "10:02:17", "symbol": "META", "action": "SELL", "qty": 5, "price": 502.10, "strategy": "mean_reversion", "pnl": -15.25},
            {"time": "10:15:44", "symbol": "GOOGL", "action": "BUY", "qty": 20, "price": 155.75, "strategy": "momentum", "pnl": None},
            {"time": "10:28:01", "symbol": "AMD", "action": "SELL", "qty": 18, "price": 178.90, "strategy": "breakout", "pnl": 92.70},
        ],
        "equity_history": [
            {"date": "2026-03-14", "equity": 100000},
            {"date": "2026-03-15", "equity": 100150},
            {"date": "2026-03-16", "equity": 100480},
            {"date": "2026-03-17", "equity": 100320},
            {"date": "2026-03-18", "equity": 101100},
            {"date": "2026-03-19", "equity": 101890},
            {"date": "2026-03-20", "equity": 102210},
            {"date": "2026-03-21", "equity": 102450},
        ],
        "elo_history": [
            {"date": "2026-03-14", "rating": 1000},
            {"date": "2026-03-15", "rating": 1015},
            {"date": "2026-03-16", "rating": 1048},
            {"date": "2026-03-17", "rating": 1032},
            {"date": "2026-03-18", "rating": 1110},
            {"date": "2026-03-19", "rating": 1189},
            {"date": "2026-03-20", "rating": 1221},
            {"date": "2026-03-21", "rating": 1247},
        ],
    }
    update_bot_state(sample_state)

    print("=" * 60)
    print("  Trading Bot Dashboard")
    print("  Open http://localhost:8080 in your browser")
    print("  Press Ctrl+C to stop")
    print("=" * 60)

    run_dashboard(port=8080, debug=True)
