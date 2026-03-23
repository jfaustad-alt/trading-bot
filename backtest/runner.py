"""Async backtest runner — manages background backtest execution.

This module lets the React frontend trigger backtests via an API call
and poll for progress. Instead of blocking until the backtest finishes
(which could take minutes), it:

    1. Starts the backtest in a background thread.
    2. Returns immediately with a run_id.
    3. The frontend polls /api/backtests/<run_id> to check status.
    4. When done, the results are in the database.

It also tracks running backtests and estimates completion time based
on the number of trading days (after a few runs, we know roughly how
long each simulated day takes).

Usage:
    from backtest.runner import start_backtest, get_running_backtests

    run_id = start_backtest("2022-01-01", "2022-06-30", capital=100000)
    # Frontend polls /api/backtests/<run_id> until status == "completed"
"""

import threading
import time
from typing import Any

from database.db import get_backtest_run


# ---------------------------------------------------------------------------
# In-memory tracking of running backtests
# ---------------------------------------------------------------------------
# We keep a dict of currently running backtests so the frontend can show
# a "Running..." indicator with progress. Once a backtest finishes, it
# gets removed from this dict (results are in the database).
# ---------------------------------------------------------------------------

_running_backtests: dict[int, dict[str, Any]] = {}
_lock = threading.Lock()

# Average time per simulated trading day (updated after each run).
# Starts with a rough estimate; gets more accurate over time.
_avg_seconds_per_day: float = 0.5


def start_backtest(
    start_date: str,
    end_date: str,
    starting_capital: float = 100_000.0,
    name: str | None = None,
    market: str = "us",
    params_override: dict | None = None,
) -> int:
    """Start a backtest in a background thread.

    This function returns immediately with a run_id. The actual backtest
    runs in a separate thread. The frontend can poll the database for
    status updates.

    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        end_date: Backtest end date (YYYY-MM-DD).
        starting_capital: Starting capital in dollars.
        name: Optional human-readable name for this run.
        market: "us" for Alpaca/US stocks, "oslo" for Oslo Børs via Yahoo.
        params_override: Optional parameter overrides for the optimizer.

    Returns:
        The backtest run_id (from the database).
    """
    # Import here to avoid circular imports.
    from backtest.backtester import run_backtest
    from database.db import init_db, insert_backtest_run

    init_db()

    # Create the DB record first (status='pending') so we have a run_id.
    run_id = insert_backtest_run(
        start_date=start_date,
        end_date=end_date,
        starting_capital=starting_capital,
        name=name,
    )

    # Estimate how long this will take.
    estimated_days = _estimate_trading_days(start_date, end_date)
    estimated_seconds = estimated_days * _avg_seconds_per_day

    # Track this run.
    with _lock:
        _running_backtests[run_id] = {
            "run_id": run_id,
            "start_date": start_date,
            "end_date": end_date,
            "name": name,
            "market": market,
            "status": "running",
            "started_at": time.time(),
            "estimated_seconds": round(estimated_seconds, 1),
            "estimated_days": estimated_days,
        }

    # Start the backtest in a background thread.
    thread = threading.Thread(
        target=_run_backtest_thread,
        args=(
            run_id, start_date, end_date, starting_capital,
            name, market, params_override,
        ),
        daemon=True,
    )
    thread.start()

    return run_id


def get_running_backtests() -> list[dict[str, Any]]:
    """Get a list of all currently running backtests.

    Returns:
        A list of dicts with run_id, status, progress info, etc.
    """
    with _lock:
        result = []
        for info in _running_backtests.values():
            elapsed = time.time() - info["started_at"]
            result.append({
                **info,
                "elapsed_seconds": round(elapsed, 1),
            })
        return result


def get_backtest_status(run_id: int) -> dict[str, Any] | None:
    """Get the status of a specific backtest (running or completed).

    First checks in-memory running state, then falls back to the database.

    Args:
        run_id: The backtest run ID.

    Returns:
        A status dict, or None if the run doesn't exist.
    """
    # Check if it's still running in memory.
    with _lock:
        if run_id in _running_backtests:
            info = _running_backtests[run_id]
            elapsed = time.time() - info["started_at"]
            return {
                **info,
                "elapsed_seconds": round(elapsed, 1),
            }

    # Otherwise check the database.
    run = get_backtest_run(run_id)
    if run:
        return {
            "run_id": run_id,
            "status": run["status"],
            "name": run.get("name"),
        }

    return None


def _run_backtest_thread(
    run_id: int,
    start_date: str,
    end_date: str,
    starting_capital: float,
    name: str | None,
    market: str = "us",
    params_override: dict | None = None,
) -> None:
    """Background thread function that actually runs the backtest.

    Args:
        run_id: The pre-created backtest_runs.id.
        start_date: Backtest start date.
        end_date: Backtest end date.
        starting_capital: Starting capital.
        name: Optional name.
        market: "us" or "oslo".
        params_override: Optional parameter overrides for the optimizer.
    """
    global _avg_seconds_per_day

    start_time = time.time()

    try:
        from backtest.backtester import run_backtest

        # Pass our pre-created run_id so run_backtest() reuses it
        # instead of creating a duplicate record.
        result = run_backtest(
            start_date=start_date,
            end_date=end_date,
            starting_capital=starting_capital,
            name=name,
            run_id=run_id,
            market=market,
            params_override=params_override,
        )

        # Update the time estimate for future runs.
        duration = time.time() - start_time
        if result and result.get("daily_results"):
            days = len(result["daily_results"])
            if days > 0:
                new_avg = duration / days
                # Exponential moving average so it adapts but doesn't
                # swing wildly from one unusual run.
                _avg_seconds_per_day = (_avg_seconds_per_day * 0.7) + (new_avg * 0.3)

    except Exception as e:
        # If the backtest failed, make sure the DB reflects that.
        # run_backtest should handle this, but just in case.
        import traceback
        traceback.print_exc()

    finally:
        # Remove from running backtests tracker.
        with _lock:
            _running_backtests.pop(run_id, None)


def _estimate_trading_days(start_date: str, end_date: str) -> int:
    """Estimate the number of trading days in a date range.

    The stock market is open roughly 252 days per year, or about 21 days
    per month. This gives a rough estimate without actually checking
    the calendar.

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).

    Returns:
        Estimated number of trading days.
    """
    from datetime import datetime

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    calendar_days = (end - start).days

    # Roughly 5/7 of calendar days are weekdays, and ~95% of weekdays
    # are trading days (excluding holidays).
    return max(1, int(calendar_days * 5 / 7 * 0.95))
