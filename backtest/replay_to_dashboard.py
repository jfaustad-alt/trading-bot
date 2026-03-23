"""
Replay a backtest through the dashboard so you can watch it visually.

This script runs a backtest over a date range, then feeds the results
into the web dashboard day by day. You open the dashboard in your
browser and see real historical data — what the bot actually would
have done.

Usage:
    python3 -m backtest.replay_to_dashboard --start 2026-03-10 --end 2026-03-14
"""

import argparse
import time
from datetime import datetime, timedelta

import pytz

from backtest.simulated_broker import SimulatedBroker
from broker.alpaca_client import AlpacaClient
from dashboard.app import run_dashboard_in_background, update_bot_state
from risk.risk_manager import RiskManager
from screener.stock_screener import LIQUID_STOCKS, MARKET_ETFS, SECTOR_ETFS, StockScreener
from strategies.breakout import BreakoutStrategy
from strategies.etf_rotation import ETFRotationStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from utils.logger import TradingLogger


def replay_backtest(start_date: str, end_date: str) -> None:
    """Run a backtest and replay results through the dashboard.

    Each trading day pauses for a few seconds so you can watch
    the dashboard update in real time.

    Args:
        start_date: First day, "YYYY-MM-DD".
        end_date: Last day, "YYYY-MM-DD".
    """
    logger = TradingLogger()

    # --- Launch dashboard ---
    logger.log_info("Starting dashboard at http://localhost:8080")
    run_dashboard_in_background(port=8080)
    time.sleep(1)

    # --- Download data ---
    logger.log_info(f"Replaying: {start_date} to {end_date}")
    real_broker = AlpacaClient()
    sim_broker = SimulatedBroker(starting_capital=100_000.0)
    all_symbols = list(set(SECTOR_ETFS + MARKET_ETFS + LIQUID_STOCKS))
    sim_broker.load_data(real_broker, all_symbols, start_date, end_date)

    # --- Get trading days ---
    trading_days = _get_trading_days(sim_broker, start_date, end_date)
    if not trading_days:
        logger.log_error("No trading days found.")
        return

    logger.log_info(f"Found {len(trading_days)} trading days. Replaying...")
    logger.log_info("Open http://localhost:8080 to watch!")
    print()

    # --- Initialize ---
    risk_manager = RiskManager()
    screener = StockScreener(sim_broker)
    equity_history = []
    elo_history = []
    all_trades = []
    total_wins = 0
    total_closed = 0

    # Push initial state.
    update_bot_state({
        "equity": 100_000.0,
        "cash": 100_000.0,
        "buying_power": 100_000.0,
        "daily_pnl": 0.0,
        "market_open": True,
        "market_condition": "loading...",
        "active_strategy": "loading...",
        "daily_target": risk_manager.elo.get_daily_target(),
        "daily_loss_limit": 100.0,
        "can_trade": True,
        "trade_count": 0,
        "elo_rating": risk_manager.elo.rating,
        "elo_rank": risk_manager.elo.rank_name,
        "positions": [],
        "recent_trades": [],
        "equity_history": [],
        "elo_history": [],
        "win_rate": 0.0,
    })

    # --- Replay each day ---
    for day_num, trading_day in enumerate(trading_days, 1):
        sim_broker.set_current_date(trading_day)
        date_str = trading_day.strftime("%Y-%m-%d")

        logger.log_info(f"=== Day {day_num}/{len(trading_days)}: {date_str} ===")

        day_start_equity = sim_broker.get_account_info()["equity"]

        # Check exits on open positions.
        _check_exits(sim_broker, risk_manager, logger, all_trades)

        # Assess market.
        try:
            market_condition = screener.assess_market_condition()
        except Exception:
            market_condition = "range_bound"

        # Select strategy.
        strategy, strategy_name = _select_strategy(
            market_condition, sim_broker, risk_manager
        )
        logger.log_market_condition(market_condition, f"Using {strategy_name}")

        # Screen candidates.
        try:
            candidates = screener.screen_candidates(max_candidates=10)
        except Exception:
            candidates = []

        # Run main strategy.
        if risk_manager.can_trade() and candidates:
            try:
                signals = strategy.generate_signals(candidates)
                if signals:
                    executed = strategy.execute_signals(signals)
                    _log_trades(executed, strategy_name, logger, all_trades)
            except Exception as e:
                logger.log_warning(f"Strategy error: {e}")

        # Run ETF rotation.
        if risk_manager.can_trade():
            try:
                etf = ETFRotationStrategy(sim_broker, risk_manager)
                etf_signals = etf.generate_signals([])
                if etf_signals:
                    executed = etf.execute_signals(etf_signals)
                    _log_trades(executed, "etf_rotation", logger, all_trades)
            except Exception as e:
                logger.log_warning(f"ETF rotation error: {e}")

        # End of day stats.
        account = sim_broker.get_account_info()
        day_pnl = account["equity"] - day_start_equity
        positions = sim_broker.get_open_positions()

        # Track equity and ELO history.
        equity_history.append({"date": date_str, "equity": round(account["equity"], 2)})
        elo_history.append({"date": date_str, "rating": round(risk_manager.elo.rating)})

        # Calculate win rate from closed trades.
        sell_trades = [t for t in all_trades if t.get("action") == "SELL"]
        total_closed = len(sell_trades)
        total_wins = sum(1 for t in sell_trades if (t.get("pnl") or 0) > 0)
        win_rate = (total_wins / total_closed * 100) if total_closed > 0 else 0

        # Push to dashboard.
        update_bot_state({
            "equity": account["equity"],
            "cash": account["cash"],
            "buying_power": account["buying_power"],
            "daily_pnl": round(day_pnl, 2),
            "market_open": True,
            "market_condition": market_condition,
            "active_strategy": strategy_name,
            "daily_target": risk_manager.elo.get_daily_target(),
            "daily_loss_limit": 100.0,
            "can_trade": risk_manager.can_trade(),
            "trade_count": risk_manager.trade_count,
            "elo_rating": round(risk_manager.elo.rating),
            "elo_rank": risk_manager.elo.rank_name,
            "win_rate": round(win_rate, 1),
            "positions": [
                {
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "entry_price": p["avg_entry_price"],
                    "current_price": p["current_price"],
                    "unrealized_pl": round(p["unrealized_pl"], 2),
                    "change_pct": round(p["unrealized_plpc"] * 100, 2),
                }
                for p in positions
            ],
            "recent_trades": all_trades[-20:],
            "equity_history": equity_history,
            "elo_history": elo_history,
        })

        risk_manager.end_of_day_reset()
        logger.log_info(f"  Equity: ${account['equity']:,.2f} | Day P&L: ${day_pnl:+,.2f} | {risk_manager.elo.get_rank_display()}")

        # Pause between days so you can watch the dashboard update.
        if day_num < len(trading_days):
            logger.log_info("  Next day in 5 seconds...")
            time.sleep(5)

    # --- Final: close all positions ---
    logger.log_info("Closing remaining positions...")
    sim_broker.close_all_positions()
    final = sim_broker.get_account_info()

    equity_history.append({"date": "final", "equity": round(final["equity"], 2)})

    update_bot_state({
        "equity": final["equity"],
        "cash": final["cash"],
        "daily_pnl": round(final["equity"] - 100_000, 2),
        "market_open": False,
        "active_strategy": "finished",
        "positions": [],
        "equity_history": equity_history,
        "elo_history": elo_history,
    })

    total_return = final["equity"] - 100_000
    logger.log_info(f"Replay complete! Total return: ${total_return:+,.2f} ({total_return/1000:+.2f}%)")
    logger.log_info(f"Final ELO: {risk_manager.elo.get_rank_display()}")
    logger.log_info("Dashboard still running — refresh your browser to see final state.")
    logger.log_info("Press Ctrl+C to stop.")

    # Keep the dashboard alive.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


def _get_trading_days(sim_broker, start_date, end_date):
    """Get trading days from SPY data."""
    if "SPY" not in sim_broker.data:
        return []
    spy = sim_broker.data["SPY"]
    start = pytz.utc.localize(datetime.strptime(start_date, "%Y-%m-%d"))
    end = pytz.utc.localize(datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1))
    mask = (spy.index >= start) & (spy.index < end)
    return spy.index[mask].tolist()


def _select_strategy(condition, broker, risk_manager):
    """Pick strategy based on market condition."""
    if condition == "trending":
        return MomentumStrategy(broker, risk_manager), "momentum"
    elif condition == "breakout":
        return BreakoutStrategy(broker, risk_manager), "breakout"
    return MeanReversionStrategy(broker, risk_manager), "mean_reversion"


def _check_exits(sim_broker, risk_manager, logger, all_trades):
    """Check positions for stop-loss / take-profit exits."""
    for pos in sim_broker.get_open_positions():
        pct = pos["unrealized_plpc"]
        if pct < -0.02 or pct > 0.015:
            pnl = pos["unrealized_pl"]
            logger.log_trade_exit(
                pos["symbol"], "SELL", pos["qty"],
                pos["avg_entry_price"], pos["current_price"], pnl,
            )
            sim_broker.close_position(pos["symbol"])
            risk_manager.record_trade(pnl)
            all_trades.append({
                "time": str(sim_broker.current_date)[:10],
                "symbol": pos["symbol"],
                "action": "SELL",
                "qty": pos["qty"],
                "price": pos["current_price"],
                "strategy": "exit",
                "pnl": round(pnl, 2),
            })


def _log_trades(executed, strategy_name, logger, all_trades):
    """Log executed trades."""
    for trade in executed:
        if trade["status"] == "executed":
            logger.log_trade_entry(
                trade["symbol"], trade["action"], trade["qty"],
                trade["entry_price"], trade["stop_loss"],
                trade["take_profit"], strategy_name,
            )
            all_trades.append({
                "time": "market open",
                "symbol": trade["symbol"],
                "action": trade["action"].upper(),
                "qty": trade["qty"],
                "price": trade["entry_price"],
                "strategy": strategy_name,
                "pnl": None,
            })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay backtest on dashboard")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    replay_backtest(args.start, args.end)
