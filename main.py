"""
Trading Bot — Main Entry Point.

This is where the bot starts and where all the pieces come together.

The main loop works like this:
    1. Connect to Alpaca and check the account.
    2. Assess market conditions (trending, range-bound, or breakout).
    3. Pick the best strategy for today's conditions.
    4. Screen for the best stocks to trade.
    5. Generate trading signals and execute them.
    6. Monitor positions and manage risk throughout the day.
    7. At end of day, close positions and print a summary.

The bot runs in a loop during trading hours, checking for new signals
every few minutes. It stops trading when the daily profit target or
loss limit is hit.
"""

import sys
import time
from datetime import datetime

import pytz

from broker.alpaca_client import AlpacaClient
from config.settings import ALPACA_API_KEY, ALPACA_SECRET_KEY, TRADING_WINDOWS
from dashboard.app import run_dashboard_in_background, update_bot_state
from database.db import init_db, insert_daily_summary, insert_trade
from risk.risk_manager import RiskManager
from screener.stock_screener import StockScreener
from strategies.breakout import BreakoutStrategy
from strategies.etf_rotation import ETFRotationStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from utils.logger import TradingLogger


# How often the bot checks for new signals (in seconds).
# 120 seconds = 2 minutes. This is a balance between reacting quickly
# and not hammering the API with too many requests.
CHECK_INTERVAL_SECONDS: int = 120


def main() -> None:
    """Start the trading bot.

    This is the entry point. It sets up all components, then runs
    the main trading loop until the market closes or the user stops it.
    """
    logger = TradingLogger()

    # --- Step 0: Initialize database ---
    # Create the SQLite database and tables if they don't exist yet.
    # This must happen before anything else so trades can be saved.
    init_db()

    # --- Step 1: Check API keys ---
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.log_error("Alpaca API keys not found!")
        logger.log_error("Make sure your .env file exists and has your keys.")
        logger.log_error("See .env.example for the format.")
        return

    # --- Step 1b: Launch web dashboard ---
    # The dashboard runs in a background thread so the bot can keep trading.
    # Open http://localhost:8080 in your browser to watch the bot.
    logger.log_info("Starting web dashboard at http://localhost:8080")
    run_dashboard_in_background(port=8080)

    # --- Step 2: Connect to Alpaca ---
    logger.log_info("Connecting to Alpaca...")
    broker = AlpacaClient()

    try:
        account_info = broker.get_account_info()
    except Exception as e:
        logger.log_error(f"Failed to connect to Alpaca: {e}")
        return

    # --- Step 3: Initialize all components ---
    risk_manager = RiskManager()
    screener = StockScreener(broker)
    logger.log_startup({
        "equity": account_info["equity"],
        "buying_power": account_info["buying_power"],
        "daily_target": risk_manager.elo.get_daily_target(),
    })

    # --- Push initial state to dashboard ---
    _push_dashboard_state(broker, risk_manager, "unknown", "starting")

    # --- Step 4: Assess market condition ---
    # The screener looks at SPY to determine if the market is trending,
    # range-bound, or breaking out. This tells us which strategy to use.
    logger.log_info("Assessing market conditions...")
    try:
        market_condition = screener.assess_market_condition()
    except Exception as e:
        logger.log_warning(f"Could not assess market condition: {e}")
        market_condition = "range_bound"  # Default to safest strategy

    # --- Step 5: Select strategy based on market condition ---
    strategy, strategy_name = _select_strategy(
        market_condition, broker, risk_manager
    )
    logger.log_market_condition(
        market_condition,
        f"Using {strategy_name} strategy",
    )

    # --- Step 6: Screen for candidates ---
    logger.log_info("Screening for trading candidates...")
    try:
        candidates = screener.screen_candidates(max_candidates=10)
    except Exception as e:
        logger.log_error(f"Screening failed: {e}")
        candidates = []

    if candidates:
        symbols = [c["symbol"] for c in candidates]
        logger.log_info(f"Found {len(candidates)} candidates: {', '.join(symbols)}")
    else:
        logger.log_warning("No candidates found. Waiting for next check...")

    # --- Step 7: Run the ETF rotation strategy (always active) ---
    # ETF rotation runs as a baseline alongside the main strategy.
    etf_strategy = ETFRotationStrategy(broker, risk_manager)
    _run_etf_rotation(etf_strategy, risk_manager, logger, market_condition)

    # --- Step 8: Main trading loop ---
    logger.log_info(
        f"Entering trading loop (checking every {CHECK_INTERVAL_SECONDS}s). "
        "Press Ctrl+C to stop."
    )

    try:
        _trading_loop(
            broker=broker,
            strategy=strategy,
            strategy_name=strategy_name,
            screener=screener,
            risk_manager=risk_manager,
            logger=logger,
            candidates=candidates,
            market_condition=market_condition,
        )
    except KeyboardInterrupt:
        # The user pressed Ctrl+C — this is the manual override / panic button.
        logger.log_override("Manual shutdown requested (Ctrl+C)")
        _handle_manual_override(broker, logger)

    # --- Step 9: End of day ---
    _end_of_day(risk_manager, logger, broker, market_condition, strategy_name)


def _select_strategy(
    market_condition: str,
    broker: AlpacaClient,
    risk_manager: RiskManager,
) -> tuple:
    """Pick the best strategy based on current market conditions.

    This is the "strategy selector" that reads the market each morning
    and decides which approach to use:
        - "trending" → Momentum (ride the trend)
        - "range_bound" → Mean Reversion (buy dips, sell rips)
        - "breakout" → Breakout (catch the explosion)

    Args:
        market_condition: One of "trending", "range_bound", "breakout".
        broker: The AlpacaClient instance.
        risk_manager: The RiskManager instance.

    Returns:
        A tuple of (strategy_instance, strategy_name_string).
    """
    if market_condition == "trending":
        return MomentumStrategy(broker, risk_manager), "momentum"
    elif market_condition == "breakout":
        return BreakoutStrategy(broker, risk_manager), "breakout"
    else:
        # Default to mean reversion — it's the safest in uncertain conditions.
        return MeanReversionStrategy(broker, risk_manager), "mean_reversion"


def _run_etf_rotation(
    etf_strategy: ETFRotationStrategy,
    risk_manager: RiskManager,
    logger: TradingLogger,
    market_condition: str = "unknown",
) -> None:
    """Run the ETF rotation strategy as a baseline allocation.

    ETF rotation runs independently of the main strategy. It manages
    sector ETF positions regardless of whether the market is trending
    or range-bound.

    Args:
        etf_strategy: The ETF rotation strategy instance.
        risk_manager: The risk manager (checked before trading).
        logger: The logger for console output.
        market_condition: Current market condition (for database record).
    """
    if not risk_manager.can_trade():
        logger.log_risk_event("Daily limit reached — skipping ETF rotation.")
        return

    logger.log_info("Running ETF rotation check...")

    try:
        # ETF rotation generates its own candidates internally,
        # so we pass an empty list (it ignores the argument).
        etf_signals = etf_strategy.generate_signals([])

        if etf_signals:
            logger.log_info(f"ETF rotation generated {len(etf_signals)} signals.")
            executed = etf_strategy.execute_signals(etf_signals)
            _log_executed_trades(
                executed, "etf_rotation", logger, risk_manager,
                market_condition,
            )
        else:
            logger.log_info("ETF rotation: no changes needed.")

    except Exception as e:
        logger.log_warning(f"ETF rotation failed: {e}")


def _trading_loop(
    broker: AlpacaClient,
    strategy,
    strategy_name: str,
    screener: StockScreener,
    risk_manager: RiskManager,
    logger: TradingLogger,
    candidates: list[dict],
    market_condition: str,
) -> None:
    """The main trading loop — runs until market close or daily limit.

    Every CHECK_INTERVAL_SECONDS, the bot:
        1. Checks if we're in a trading window.
        2. Checks if we can still trade (risk limits).
        3. Monitors open positions for stop-loss / take-profit hits.
        4. Generates new signals and executes them.

    Args:
        broker: The Alpaca broker client.
        strategy: The selected trading strategy.
        strategy_name: Name of the strategy (for logging).
        screener: The stock screener.
        risk_manager: The risk manager.
        logger: The console logger.
        candidates: Pre-screened trading candidates.
        market_condition: Current market condition (e.g. "trending",
            "range_bound", "breakout"). Used for logging and database records.
    """
    # Track whether the market has been open at any point during this
    # session. This lets us distinguish between:
    #   - "Market hasn't opened yet" (pre-market/weekend) → keep waiting
    #   - "Market was open and just closed" (end of day) → exit the loop
    # Without this flag, the bot gets stuck printing "Market is closed"
    # every 60 seconds and never reaches the end-of-day logic.
    market_was_open: bool = False

    while True:
        # --- Check if market is open ---
        try:
            market_open = broker.is_market_open()
        except Exception as e:
            logger.log_warning(f"Could not check market status: {e}")
            # If we can't determine market status, wait and retry.
            # Do NOT fall through and trade — we don't know if the
            # market is actually open.
            time.sleep(60)
            continue

        if not market_open:
            if market_was_open:
                # The market WAS open and now it's closed — the trading
                # day is over. Break out so we can run end-of-day logic.
                logger.log_info("Market has closed for the day.")
                break
            else:
                # The market hasn't opened yet (pre-market, weekend, or
                # holiday). Push state to the dashboard so the UI always
                # shows current account info, even while waiting.
                logger.log_info("Market is not open yet. Waiting...")
                _push_dashboard_state(
                    broker, risk_manager, market_condition, "waiting"
                )
                time.sleep(60)
                continue

        # If we get here, the market is open. Remember this.
        market_was_open = True

        # --- Check if we're in a trading window ---
        # The bot only places NEW trades during configured windows
        # (e.g. first hour 9:30-10:30 and last hour 15:00-16:00).
        # Outside these windows, we still monitor positions but don't
        # generate new signals.
        in_window = _in_trading_window()

        # --- Check risk limits ---
        if not risk_manager.can_trade():
            status = risk_manager.get_status()
            pnl = status["daily_pnl"]
            if pnl >= 0:
                logger.log_risk_event(
                    f"Daily profit target reached (${pnl:,.2f}). Done for today!"
                )
            else:
                logger.log_risk_event(
                    f"Daily loss limit hit (${pnl:,.2f}). Stopping for today."
                )
            break

        # --- Monitor existing positions ---
        # This runs even outside trading windows — we always want to
        # know how open positions are doing.
        _monitor_positions(broker, risk_manager, logger)

        # --- Generate and execute new signals (only in trading windows) ---
        if in_window:
            try:
                signals = strategy.generate_signals(candidates)

                if signals:
                    logger.log_info(
                        f"{strategy_name} generated {len(signals)} signal(s)."
                    )
                    executed = strategy.execute_signals(signals)
                    _log_executed_trades(
                        executed, strategy_name, logger, risk_manager,
                        market_condition,
                    )

            except Exception as e:
                logger.log_error(f"Strategy error: {e}")

        # --- Push state to dashboard ---
        _push_dashboard_state(broker, risk_manager, market_condition, strategy_name)

        # --- Check for dashboard override (panic button) ---
        from dashboard.app import get_bot_state
        if get_bot_state().get("override_triggered"):
            logger.log_override("Dashboard panic button pressed!")
            _handle_manual_override(broker, logger)
            update_bot_state({"override_triggered": False})
            break

        # --- Wait before next check ---
        time.sleep(CHECK_INTERVAL_SECONDS)


def _monitor_positions(
    broker: AlpacaClient,
    risk_manager: RiskManager,
    logger: TradingLogger,
) -> None:
    """Check open positions for unrealized P&L and log status.

    In a full implementation, this would check each position against
    its stop-loss and take-profit levels and close positions that hit
    either target. For now, it logs the current state.

    Args:
        broker: The Alpaca broker client.
        risk_manager: The risk manager.
        logger: The console logger.
    """
    try:
        positions = broker.get_open_positions()
        if positions:
            total_unrealized = sum(p["unrealized_pl"] for p in positions)
            logger.log_info(
                f"Open positions: {len(positions)} | "
                f"Unrealized P&L: ${total_unrealized:,.2f}"
            )
    except Exception as e:
        logger.log_warning(f"Could not check positions: {e}")


def _log_executed_trades(
    executed: list[dict],
    strategy_name: str,
    logger: TradingLogger,
    risk_manager: RiskManager,
    market_condition: str = "unknown",
) -> None:
    """Log each executed trade, record P&L, and save to database.

    Args:
        executed: List of trade dicts from strategy.execute_signals().
        strategy_name: Name of the strategy that generated the trades.
        logger: The console logger.
        risk_manager: The risk manager to record trades with.
        market_condition: Current market condition (for database record).
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

            # Save the trade to the database for permanent history.
            try:
                insert_trade(
                    symbol=trade["symbol"],
                    action=trade["action"].lower(),
                    qty=trade["qty"],
                    price=trade["entry_price"],
                    strategy=strategy_name,
                    market_condition=market_condition,
                    stop_loss=trade.get("stop_loss"),
                    take_profit=trade.get("take_profit"),
                    source="live",
                )
            except Exception:
                pass  # Database writes are non-critical
        else:
            logger.log_info(
                f"Skipped {trade['symbol']}: {trade.get('skip_reason', 'unknown')}"
            )


def _in_trading_window() -> bool:
    """Check if the current time is within one of our trading windows.

    We only trade during the first hour (9:30-10:30 ET) and last hour
    (15:00-16:00 ET) of the market session, as defined in settings.

    Returns:
        True if we're currently in a trading window.
    """
    # Get current time in US Eastern timezone (what the stock market uses).
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern)
    current_time = now.strftime("%H:%M")

    for window in TRADING_WINDOWS:
        if window["start"] <= current_time <= window["end"]:
            return True

    return False


def _handle_manual_override(broker: AlpacaClient, logger: TradingLogger) -> None:
    """Execute the panic button — close all positions and stop.

    This is triggered when the user presses Ctrl+C. It sells everything
    the bot currently holds and shuts down cleanly.

    Args:
        broker: The Alpaca broker client.
        logger: The console logger.
    """
    positions = broker.get_open_positions()

    if positions:
        logger.log_override(f"Closing {len(positions)} open position(s)...")
        try:
            broker.close_all_positions()
            logger.log_override("All positions closed.")
        except Exception as e:
            logger.log_error(f"Error closing positions: {e}")
    else:
        logger.log_override("No open positions to close.")


def _push_dashboard_state(
    broker: AlpacaClient,
    risk_manager: RiskManager,
    market_condition: str,
    strategy_name: str,
) -> None:
    """Push the bot's current state to the web dashboard.

    This updates the shared state dict that the dashboard reads from.
    Called every loop iteration so the dashboard stays current.

    Args:
        broker: The Alpaca broker client (real or simulated).
        risk_manager: The risk manager with daily stats.
        market_condition: Current market condition string.
        strategy_name: Name of the active strategy.
    """
    try:
        account = broker.get_account_info()
        positions = broker.get_open_positions()
        status = risk_manager.get_status()
        market_open = broker.is_market_open()

        update_bot_state({
            "equity": account["equity"],
            "cash": account["cash"],
            "buying_power": account["buying_power"],
            "daily_pnl": status["daily_pnl"],
            "market_condition": market_condition,
            "active_strategy": strategy_name,
            "market_open": market_open,
            "daily_target": status.get("elo_daily_target", status["daily_profit_target"]),
            "daily_loss_limit": status["daily_loss_limit"],
            "can_trade": status["can_trade"],
            "trade_count": status["trade_count"],
            "elo_rating": status.get("elo_rating", 1000),
            "elo_rank": status.get("rank_name", "Gold"),
            "positions": [
                {
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "entry_price": p["avg_entry_price"],
                    "current_price": p["current_price"],
                    "unrealized_pl": p["unrealized_pl"],
                    "change_pct": round(p["unrealized_plpc"] * 100, 2),
                }
                for p in positions
            ],
        })
    except Exception:
        pass  # Dashboard updates are non-critical — don't crash the bot


def _end_of_day(
    risk_manager: RiskManager,
    logger: TradingLogger,
    broker: AlpacaClient | None = None,
    market_condition: str = "unknown",
    strategy_name: str = "unknown",
) -> None:
    """Print the daily summary, save to database, and reset for tomorrow.

    Args:
        risk_manager: The risk manager with today's stats.
        logger: The console logger.
        broker: The Alpaca broker client (for account info).
        market_condition: Today's market condition.
        strategy_name: Today's primary strategy.
    """
    status = risk_manager.get_status()

    logger.log_daily_summary(
        daily_pnl=status["daily_pnl"],
        trades_taken=status["trade_count"],
        wins=0,   # TODO: track wins/losses separately
        losses=0,  # TODO: track wins/losses separately
        streak=status["consecutive_profitable_days"],
    )

    # --- Save daily summary to the database ---
    try:
        equity = 0.0
        cash = 0.0
        if broker:
            account = broker.get_account_info()
            equity = account["equity"]
            cash = account["cash"]

        today = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")

        insert_daily_summary(
            date=today,
            equity=equity,
            cash=cash,
            daily_pnl=status["daily_pnl"],
            trade_count=status["trade_count"],
            market_condition=market_condition,
            strategy=strategy_name,
            elo_rating=status.get("elo_rating"),
            elo_rank=status.get("rank_name"),
            daily_target=status.get("elo_daily_target"),
        )
    except Exception:
        pass  # Database writes are non-critical

    # Reset for next trading day (this also updates the ELO rating).
    risk_manager.end_of_day_reset()
    logger.log_info(f"ELO Rating: {risk_manager.elo.get_rank_display()}")
    logger.log_info("Risk manager reset for next trading day.")


if __name__ == "__main__":
    main()
