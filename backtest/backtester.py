"""
Backtester — replay the bot's strategy on historical data.

This module lets you answer the question: "What would the bot have done
last week / last month / last year?" It replays historical market data
day by day, running the same strategies and risk management as the live
bot, and produces a performance report at the end.

HOW BACKTESTING WORKS:
    1. Pick a date range (e.g., "2025-03-10" to "2025-03-14" for last week).
    2. Download historical data for all symbols the bot would trade.
    3. For each trading day in that range:
       a. Set the simulated broker's clock to that day.
       b. Run the screener to find candidates (using only past data).
       c. Assess market condition and pick a strategy.
       d. Generate signals and "execute" trades (simulated).
       e. Check stop-losses and take-profits on open positions.
       f. Record daily P&L.
    4. After all days are done, print a performance summary.

WHY BACKTEST?
    - See if the strategy would have been profitable.
    - Spot weaknesses (does it lose money in choppy markets?).
    - Build confidence before risking real money.
    - Compare different strategy settings.

IMPORTANT LIMITATIONS:
    - Backtesting uses daily bars, so it can't capture intraday moves
      perfectly. A real day trader would see minute-by-minute prices.
    - We assume orders fill at the closing price, which isn't always
      realistic (in real life, there's slippage).
    - Past performance does NOT guarantee future results.

Usage:
    python3 -m backtest.backtester --start 2025-03-10 --end 2025-03-14
    python3 -m backtest.backtester --start 2025-03-21 --end 2025-03-21  # single day
"""

import argparse
import time as time_module
from datetime import datetime, timedelta

import pytz

from backtest.simulated_broker import SimulatedBroker
from broker.alpaca_client import AlpacaClient
from database.db import (
    init_db,
    insert_backtest_daily_result,
    insert_backtest_run,
    insert_trade,
    update_backtest_run,
)
from risk.risk_manager import RiskManager
from screener.stock_screener import LIQUID_STOCKS, MARKET_ETFS, SECTOR_ETFS, StockScreener
from strategies.breakout import BreakoutStrategy
from strategies.etf_rotation import ETFRotationStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from utils.logger import TradingLogger


def run_backtest(
    start_date: str,
    end_date: str,
    starting_capital: float = 100_000.0,
    name: str | None = None,
    run_id: int | None = None,
    market: str = "us",
    params_override: dict | None = None,
) -> dict:
    """Run a full backtest over a date range.

    This is the main function. It downloads data, simulates each trading
    day, and returns a performance summary.

    Args:
        start_date: First day of the backtest, "YYYY-MM-DD".
        end_date: Last day of the backtest, "YYYY-MM-DD".
        starting_capital: How much fake money to start with.
        name: Optional human-readable name for this run.
        run_id: Optional pre-created database run ID. If provided, the
            backtest uses this existing record instead of creating a new
            one. This is used by the async runner (runner.py) which
            creates the record upfront so the frontend has an ID to poll.
        market: Which market to backtest on. "us" uses Alpaca data for
            US stocks. "oslo" uses Yahoo Finance for Oslo Børs stocks.
        params_override: Optional dict of risk/strategy parameters to
            override for this run. Used by the optimizer to test different
            parameter combinations. Keys can include:
            - stop_loss_pct: stop-loss threshold (e.g. 0.02 for 2%)
            - take_profit_pct: take-profit threshold (e.g. 0.015 for 1.5%)
            - risk_per_trade_pct: risk budget per trade
            - max_open_positions: max simultaneous positions
            - daily_loss_limit: daily loss limit in dollars

    Returns:
        A dict with performance metrics (total return, win rate, etc.).
    """
    logger = TradingLogger()

    logger.log_info(f"Backtest: {start_date} to {end_date}")
    logger.log_info(f"Starting capital: ${starting_capital:,.2f}")
    print()

    # --- Initialize database and create a backtest run record ---
    # This lets us track the backtest in the app and save results permanently.
    # If a run_id was passed in (from the async runner), we reuse it.
    # Otherwise we create a new record (for CLI / direct usage).
    init_db()
    backtest_start_time = time_module.time()
    if run_id is None:
        run_id = insert_backtest_run(
            start_date=start_date,
            end_date=end_date,
            starting_capital=starting_capital,
            name=name,
        )

    # --- Step 1: Download historical data ---
    sim_broker = SimulatedBroker(starting_capital=starting_capital)

    if market == "oslo":
        # Oslo Børs: use Yahoo Finance for Norwegian stocks.
        from config.oslo_stocks import OSLO_BENCHMARK, OSLO_STOCKS
        all_symbols = list(set(OSLO_STOCKS + [OSLO_BENCHMARK]))
        sim_broker.load_yahoo_data(all_symbols, start_date, end_date)
        benchmark_symbol = OSLO_BENCHMARK
    else:
        # US market: use Alpaca for data download.
        real_broker = AlpacaClient()
        all_symbols = list(set(SECTOR_ETFS + MARKET_ETFS + LIQUID_STOCKS))
        sim_broker.load_data(real_broker, all_symbols, start_date, end_date)
        benchmark_symbol = "SPY"
    print()

    # --- Step 2: Build list of trading days ---
    # We look at the benchmark's data to figure out which days the
    # market was open. If it has a bar on a date, the market was open.
    trading_days = _get_trading_days(
        sim_broker, start_date, end_date, benchmark=benchmark_symbol
    )

    if not trading_days:
        logger.log_error("No trading days found in the given date range.")
        update_backtest_run(run_id, {
            "status": "failed",
            "error_message": "No trading days found in the given date range.",
        })
        return {}

    logger.log_info(f"Found {len(trading_days)} trading days to simulate.")
    print()

    # --- Step 3: Initialize components ---
    # If params_override is provided (from the optimizer), pass it to
    # the risk manager so it uses custom risk settings for this run.
    risk_manager = RiskManager(overrides=params_override)
    screener = StockScreener(sim_broker)

    # Extract exit thresholds from params_override (or use defaults).
    # These control when positions are closed in _check_position_exits().
    stop_loss_pct = 0.02     # default: exit at -2%
    take_profit_pct = 0.015  # default: exit at +1.5%
    if params_override:
        stop_loss_pct = params_override.get("stop_loss_pct", stop_loss_pct)
        take_profit_pct = params_override.get("take_profit_pct", take_profit_pct)

    # Track daily results for the summary.
    daily_results: list[dict] = []
    equity_curve: list[float] = [starting_capital]

    # Track the number of trades in sim_broker BEFORE each day, so we
    # can figure out which trades were new (for saving to the database).
    prev_trade_count = 0

    try:
        # --- Step 4: Simulate each trading day ---
        for day_num, trading_day in enumerate(trading_days, 1):
            sim_broker.set_current_date(trading_day)
            date_str = trading_day.strftime("%Y-%m-%d")

            logger.log_info(f"Day {day_num}/{len(trading_days)}: {date_str}")

            # Record starting equity for the day.
            day_start_equity = sim_broker.get_account_info()["equity"]

            # --- Check stop-losses and take-profits on open positions ---
            _check_position_exits(
                sim_broker, risk_manager, logger,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )

            # --- Assess market condition ---
            try:
                market_condition = screener.assess_market_condition()
            except Exception:
                market_condition = "range_bound"

            # --- Calculate SPY's daily % change for context ---
            spy_change_pct = _get_benchmark_daily_change(
                sim_broker, benchmark=benchmark_symbol
            )

            # --- Select strategy ---
            strategy, strategy_name = _select_strategy(
                market_condition, sim_broker, risk_manager
            )
            logger.log_market_condition(
                market_condition, f"Using {strategy_name}"
            )

            # --- Screen candidates ---
            try:
                candidates = screener.screen_candidates(max_candidates=10)
            except Exception:
                candidates = []

            # --- Generate and execute signals (main strategy) ---
            if risk_manager.can_trade() and candidates:
                try:
                    signals = strategy.generate_signals(candidates)
                    if signals:
                        executed = strategy.execute_signals(signals)
                        _process_executed_trades(
                            executed, strategy_name, risk_manager, logger
                        )
                except Exception as e:
                    logger.log_warning(f"Strategy error: {e}")

            # --- Run ETF rotation ---
            if risk_manager.can_trade():
                try:
                    etf_strategy = ETFRotationStrategy(sim_broker, risk_manager)
                    etf_signals = etf_strategy.generate_signals([])
                    if etf_signals:
                        executed = etf_strategy.execute_signals(etf_signals)
                        _process_executed_trades(
                            executed, "etf_rotation", risk_manager, logger
                        )
                except Exception as e:
                    logger.log_warning(f"ETF rotation error: {e}")

            # --- End of day: record results ---
            day_end_equity = sim_broker.get_account_info()["equity"]
            day_pnl = day_end_equity - day_start_equity

            daily_results.append({
                "date": date_str,
                "equity": day_end_equity,
                "daily_pnl": day_pnl,
                "market_condition": market_condition,
                "strategy": strategy_name,
                "trades": risk_manager.trade_count,
            })

            equity_curve.append(day_end_equity)

            # --- Save this day's results to the database ---
            insert_backtest_daily_result(
                backtest_run_id=run_id,
                date=date_str,
                equity=day_end_equity,
                daily_pnl=day_pnl,
                market_condition=market_condition,
                strategy=strategy_name,
                trade_count=risk_manager.trade_count,
                spy_change_pct=spy_change_pct,
                elo_rating=risk_manager.elo.rating,
            )

            # --- Save new trades from this day to the database ---
            new_trades = sim_broker.trade_history[prev_trade_count:]
            for t in new_trades:
                insert_trade(
                    symbol=t["symbol"],
                    action=t["action"],
                    qty=t["qty"],
                    price=t["price"],
                    timestamp=date_str,
                    pnl=t.get("pnl"),
                    strategy=strategy_name,
                    market_condition=market_condition,
                    source="backtest",
                    backtest_run_id=run_id,
                )
            prev_trade_count = len(sim_broker.trade_history)

            # Reset risk manager for next day.
            risk_manager.end_of_day_reset()

        # --- Step 5: Close all remaining positions ---
        logger.log_info("Backtest complete. Closing remaining positions...")
        sim_broker.close_all_positions()

        # --- Step 6: Generate performance report ---
        final_equity = sim_broker.get_account_info()["equity"]
        report = _generate_report(
            starting_capital, final_equity, daily_results,
            sim_broker.trade_history, equity_curve, logger,
            risk_manager,
        )

        # --- Step 7: Save final results to the database ---
        duration = time_module.time() - backtest_start_time
        elo_history = risk_manager.elo.rating_history

        update_backtest_run(run_id, {
            **report,
            "status": "completed",
            "duration_seconds": round(duration, 2),
            "elo_start": elo_history[0] if elo_history else 1000,
            "elo_end": elo_history[-1] if elo_history else 1000,
            "elo_peak": max(elo_history) if elo_history else 1000,
            "elo_lowest": min(elo_history) if elo_history else 1000,
        })

        # --- Step 8: Fetch news headlines for each day (post-processing) ---
        # This runs AFTER the backtest finishes so it doesn't slow down
        # the simulation. News headlines add context to the daily timeline.
        _fetch_and_save_news(run_id, daily_results, logger)

        # Add the run_id to the report so the caller knows where to find it.
        report["run_id"] = run_id

        return report

    except Exception as e:
        # If anything goes wrong, mark the backtest as failed in the DB.
        duration = time_module.time() - backtest_start_time
        update_backtest_run(run_id, {
            "status": "failed",
            "error_message": str(e),
            "duration_seconds": round(duration, 2),
        })
        logger.log_error(f"Backtest failed: {e}")
        raise


def _fetch_and_save_news(
    run_id: int,
    daily_results: list[dict],
    logger: TradingLogger,
) -> None:
    """Fetch news headlines for each backtest day and save to the database.

    This is called after the backtest finishes. It makes one API call per
    day, with a small delay to respect rate limits. Headlines are saved
    to the backtest_daily_results table's news_headline column.

    Args:
        run_id: The backtest run ID.
        daily_results: List of daily result dicts (need the "date" key).
        logger: The logger for status output.
    """
    try:
        from broker.news import fetch_news_headline
        from database.db import get_connection

        dates = [d["date"] for d in daily_results]
        logger.log_info(f"Fetching news headlines for {len(dates)} days...")

        conn = get_connection()
        import time as _time

        fetched = 0
        for date in dates:
            headline = fetch_news_headline(date)
            if headline:
                conn.execute(
                    "UPDATE backtest_daily_results SET news_headline = ? "
                    "WHERE backtest_run_id = ? AND date = ?",
                    (headline, run_id, date),
                )
                fetched += 1
            # Rate limit: Alpaca free tier allows 200 req/min.
            _time.sleep(0.35)

        conn.commit()
        conn.close()
        logger.log_info(f"Fetched {fetched}/{len(dates)} news headlines.")

    except Exception as e:
        # News is non-critical — don't fail the backtest over it.
        logger.log_warning(f"News fetch skipped: {e}")


def _get_benchmark_daily_change(
    sim_broker: SimulatedBroker,
    benchmark: str = "SPY",
) -> float | None:
    """Calculate the benchmark index's daily percentage change for context.

    This is saved alongside each backtest day so the results can show
    what the broader market did (e.g. "SPY -3.2%" or "OSEBX -1.5%")
    next to the bot's performance. Helps you see if the bot lost money
    because the whole market crashed, or because the strategy made a bad call.

    Args:
        sim_broker: The simulated broker with loaded data.
        benchmark: The benchmark ticker (e.g. "SPY" for US, "OSEBX.OL" for Oslo).

    Returns:
        The benchmark's daily % change, or None if data isn't available.
    """
    try:
        bars = sim_broker.get_historical_bars(benchmark, limit=2)
        if len(bars) >= 2:
            prev_close = float(bars["close"].iloc[-2])
            today_close = float(bars["close"].iloc[-1])
            return round((today_close - prev_close) / prev_close * 100, 2)
    except Exception:
        pass
    return None


def _get_trading_days(
    sim_broker: SimulatedBroker,
    start_date: str,
    end_date: str,
    benchmark: str = "SPY",
) -> list[datetime]:
    """Get a list of dates when the market was open.

    We use a benchmark's data as the reference — if the benchmark has
    a bar on a date, the market was open that day.

    Args:
        sim_broker: The simulated broker with loaded data.
        start_date: Start date as "YYYY-MM-DD".
        end_date: End date as "YYYY-MM-DD".
        benchmark: The benchmark ticker to check for trading days
            (e.g. "SPY" for US, "OSEBX.OL" for Oslo Børs).

    Returns:
        A list of datetime objects for each trading day.
    """
    if benchmark not in sim_broker.data:
        return []

    bench_data = sim_broker.data[benchmark]
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # Make timezone-aware to match the data index.
    start = pytz.utc.localize(start)
    # End of the end date (include the full day).
    end = pytz.utc.localize(end + timedelta(days=1))

    # Filter to only dates within our range.
    mask = (bench_data.index >= start) & (bench_data.index < end)
    trading_dates = bench_data.index[mask].tolist()

    return trading_dates


def _select_strategy(market_condition, sim_broker, risk_manager):
    """Pick the best strategy based on market conditions.

    Same logic as the live bot — just using the simulated broker.

    Args:
        market_condition: "trending", "range_bound", or "breakout".
        sim_broker: The simulated broker.
        risk_manager: The risk manager.

    Returns:
        A tuple of (strategy_instance, strategy_name).
    """
    if market_condition == "trending":
        return MomentumStrategy(sim_broker, risk_manager), "momentum"
    elif market_condition == "breakout":
        return BreakoutStrategy(sim_broker, risk_manager), "breakout"
    else:
        return MeanReversionStrategy(sim_broker, risk_manager), "mean_reversion"


def _check_position_exits(
    sim_broker: SimulatedBroker,
    risk_manager: RiskManager,
    logger: TradingLogger,
    stop_loss_pct: float = 0.02,
    take_profit_pct: float = 0.015,
) -> None:
    """Check open positions against their stop-loss and take-profit.

    For backtesting with daily bars, we check if the day's low hit the
    stop-loss or the day's high hit the take-profit. This is a simplification
    — in real life, we'd check on a minute-by-minute basis.

    The thresholds are configurable so the optimizer can test different
    values (e.g. tighter stops at 1.5% vs wider stops at 3%).

    Args:
        sim_broker: The simulated broker.
        risk_manager: The risk manager.
        logger: The console logger.
        stop_loss_pct: Exit when unrealized loss exceeds this percentage
            (e.g. 0.02 = sell if down 2%). Default: 0.02.
        take_profit_pct: Exit when unrealized gain exceeds this percentage
            (e.g. 0.015 = sell if up 1.5%). Default: 0.015.
    """
    positions = sim_broker.get_open_positions()

    for pos in positions:
        symbol = pos["symbol"]
        unrealized_pl = pos["unrealized_pl"]
        unrealized_pct = pos["unrealized_plpc"]

        # Exit if unrealized loss exceeds the stop-loss threshold.
        if unrealized_pct < -stop_loss_pct:
            logger.log_trade_exit(
                symbol=symbol,
                action="SELL",
                shares=pos["qty"],
                entry_price=pos["avg_entry_price"],
                exit_price=pos["current_price"],
                pnl=unrealized_pl,
            )
            sim_broker.close_position(symbol)
            risk_manager.record_trade(unrealized_pl)

        # Exit if unrealized gain exceeds the take-profit threshold.
        elif unrealized_pct > take_profit_pct:
            logger.log_trade_exit(
                symbol=symbol,
                action="SELL",
                shares=pos["qty"],
                entry_price=pos["avg_entry_price"],
                exit_price=pos["current_price"],
                pnl=unrealized_pl,
            )
            sim_broker.close_position(symbol)
            risk_manager.record_trade(unrealized_pl)


def _process_executed_trades(
    executed: list[dict],
    strategy_name: str,
    risk_manager: RiskManager,
    logger: TradingLogger,
) -> None:
    """Log executed trades from a strategy run.

    Args:
        executed: List of trade dicts from execute_signals().
        strategy_name: Name of the strategy.
        risk_manager: The risk manager.
        logger: The console logger.
    """
    for trade in executed:
        if trade["status"] == "executed":
            logger.log_trade_entry(
                symbol=trade["symbol"],
                action=trade["action"],
                shares=trade["qty"],
                price=trade["entry_price"],
                stop_loss=trade["stop_loss"],
                take_profit=trade["take_profit"],
                strategy=strategy_name,
            )


def _generate_report(
    starting_capital: float,
    final_equity: float,
    daily_results: list[dict],
    trade_history: list[dict],
    equity_curve: list[float],
    logger: TradingLogger,
    risk_manager: RiskManager | None = None,
) -> dict:
    """Generate and print a performance report.

    This calculates key metrics that traders use to evaluate a strategy:
    - Total return: how much money was made/lost overall.
    - Win rate: percentage of profitable trades.
    - Max drawdown: the worst peak-to-trough decline (how bad did it get?).
    - Sharpe ratio: return divided by risk (higher = better risk-adjusted).

    Args:
        starting_capital: Initial cash.
        final_equity: Ending portfolio value.
        daily_results: List of daily P&L records.
        trade_history: List of all individual trades.
        equity_curve: List of equity values over time.
        logger: The console logger.

    Returns:
        A dict with all performance metrics.
    """
    total_return = final_equity - starting_capital
    total_return_pct = (total_return / starting_capital) * 100

    # --- Trade statistics ---
    # Filter to only sell trades (they have P&L).
    sell_trades = [t for t in trade_history if t.get("action") == "sell"]
    winning_trades = [t for t in sell_trades if t.get("pnl", 0) > 0]
    losing_trades = [t for t in sell_trades if t.get("pnl", 0) <= 0]

    total_trades = len(sell_trades)
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0

    avg_win = (
        sum(t["pnl"] for t in winning_trades) / len(winning_trades)
        if winning_trades else 0
    )
    avg_loss = (
        sum(t["pnl"] for t in losing_trades) / len(losing_trades)
        if losing_trades else 0
    )

    # --- Daily statistics ---
    profitable_days = sum(1 for d in daily_results if d["daily_pnl"] > 0)
    losing_days = sum(1 for d in daily_results if d["daily_pnl"] <= 0)
    avg_daily_pnl = (
        sum(d["daily_pnl"] for d in daily_results) / len(daily_results)
        if daily_results else 0
    )

    # --- Max drawdown ---
    # Drawdown measures how much the portfolio dropped from its peak.
    # It answers: "What was the worst losing streak?"
    max_drawdown, max_drawdown_pct = _calculate_max_drawdown(equity_curve)

    # --- Strategy usage ---
    strategy_counts: dict[str, int] = {}
    for d in daily_results:
        s = d["strategy"]
        strategy_counts[s] = strategy_counts.get(s, 0) + 1

    # --- Print report ---
    print()
    print("=" * 60)
    print("  BACKTEST RESULTS")
    print("=" * 60)
    print()
    print(f"  Period:           {daily_results[0]['date']} to {daily_results[-1]['date']}" if daily_results else "")
    print(f"  Trading Days:     {len(daily_results)}")
    print()
    print("  --- RETURNS ---")
    print(f"  Starting Capital: ${starting_capital:>12,.2f}")
    print(f"  Final Equity:     ${final_equity:>12,.2f}")
    print(f"  Total Return:     ${total_return:>12,.2f} ({total_return_pct:+.2f}%)")
    print(f"  Avg Daily P&L:    ${avg_daily_pnl:>12,.2f}")
    print()
    print("  --- TRADES ---")
    print(f"  Total Trades:     {total_trades}")
    print(f"  Win Rate:         {win_rate:.1f}%")
    print(f"  Avg Win:          ${avg_win:>12,.2f}")
    print(f"  Avg Loss:         ${avg_loss:>12,.2f}")
    print()
    print("  --- RISK ---")
    print(f"  Max Drawdown:     ${max_drawdown:>12,.2f} ({max_drawdown_pct:.2f}%)")
    print(f"  Profitable Days:  {profitable_days}")
    print(f"  Losing Days:      {losing_days}")
    print()
    print("  --- STRATEGIES USED ---")
    for s, count in strategy_counts.items():
        print(f"  {s:20s} {count} day(s)")

    # --- ELO Rating ---
    if risk_manager is not None:
        print()
        print("  --- ELO RATING ---")
        print(f"  Final Rating:     {risk_manager.elo.get_rank_display()}")
        elo_history = risk_manager.elo.rating_history
        if len(elo_history) > 1:
            start_rating = elo_history[0]
            end_rating = elo_history[-1]
            change = end_rating - start_rating
            print(f"  Rating Change:    {start_rating:.0f} -> {end_rating:.0f} ({change:+.0f})")
            peak = max(elo_history)
            trough = min(elo_history)
            print(f"  Peak Rating:      {peak:.0f}")
            print(f"  Lowest Rating:    {trough:.0f}")

    print()
    print("=" * 60)
    print()

    return {
        "starting_capital": starting_capital,
        "final_equity": final_equity,
        "total_return": total_return,
        "total_return_pct": total_return_pct,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_daily_pnl": avg_daily_pnl,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown_pct,
        "profitable_days": profitable_days,
        "losing_days": losing_days,
        "daily_results": daily_results,
        "equity_curve": equity_curve,
    }


def _calculate_max_drawdown(equity_curve: list[float]) -> tuple[float, float]:
    """Calculate the maximum drawdown from an equity curve.

    "Drawdown" is the drop from a peak (highest point) to a trough
    (lowest point after that peak). Max drawdown is the WORST such drop
    during the entire backtest.

    This is one of the most important risk metrics — it tells you the
    worst-case scenario. If max drawdown is $5,000, that means at some
    point the bot lost $5,000 from its best day before recovering.

    Args:
        equity_curve: A list of equity values over time.

    Returns:
        A tuple of (max_drawdown_dollars, max_drawdown_percent).
    """
    if not equity_curve:
        return 0.0, 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0

    for equity in equity_curve:
        # Track the highest equity we've seen so far.
        if equity > peak:
            peak = equity

        # Calculate the current drawdown from the peak.
        drawdown = peak - equity
        drawdown_pct = (drawdown / peak) * 100 if peak > 0 else 0

        # Track the worst drawdown.
        if drawdown > max_dd:
            max_dd = drawdown
            max_dd_pct = drawdown_pct

    return max_dd, max_dd_pct


# ------------------------------------------------------------------
# Command-line interface
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backtest the trading bot on historical data."
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start date (YYYY-MM-DD). Example: 2025-03-10",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End date (YYYY-MM-DD). Example: 2025-03-14",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="Starting capital in dollars (default: 100000)",
    )
    parser.add_argument(
        "--market",
        choices=["us", "oslo"],
        default="us",
        help="Market to backtest on: 'us' (Alpaca) or 'oslo' (Yahoo/Oslo Børs)",
    )

    args = parser.parse_args()

    run_backtest(
        start_date=args.start,
        end_date=args.end,
        starting_capital=args.capital,
        market=args.market,
    )
