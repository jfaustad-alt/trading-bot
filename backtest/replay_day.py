"""
Replay a single trading day minute by minute on the dashboard.

This script downloads minute-level price data for one day and steps
through it in real time (1 real second = 1 simulated minute). You
watch the dashboard update as if you were watching the bot trade live.

The bot makes its trading decisions at market open using daily bars
(same as the real bot), then you watch the positions' P&L tick up
and down as minute-by-minute prices come in.

Usage:
    python3 -m backtest.replay_day --date 2026-03-10
    python3 -m backtest.replay_day --date 2026-03-10 --speed 0.5  (faster)
    python3 -m backtest.replay_day --date 2026-03-10 --speed 2    (slower)
"""

import argparse
import time
from datetime import datetime, timedelta

import alpaca_trade_api as tradeapi
import pytz

from broker.alpaca_client import AlpacaClient
from dashboard.app import run_dashboard_in_background, update_bot_state
from risk.risk_manager import RiskManager
from screener.stock_screener import LIQUID_STOCKS, MARKET_ETFS, SECTOR_ETFS, StockScreener
from strategies.breakout import BreakoutStrategy
from strategies.etf_rotation import ETFRotationStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from utils.logger import TradingLogger

# Eastern timezone — the stock market runs on ET.
EASTERN = pytz.timezone("US/Eastern")


def replay_day(date_str: str, speed: float = 1.0) -> None:
    """Replay a single trading day minute by minute.

    Args:
        date_str: The date to replay, "YYYY-MM-DD".
        speed: Seconds of real time per simulated minute.
               1.0 = real time (1 sec per minute).
               0.5 = 2x speed. 2.0 = half speed.
    """
    logger = TradingLogger()

    # --- Launch dashboard ---
    logger.log_info("Starting dashboard at http://localhost:8080")
    run_dashboard_in_background(port=8080)
    time.sleep(1)

    logger.log_info(f"Replaying: {date_str} (speed: {speed}s per minute)")
    logger.log_info("Open http://localhost:8080 to watch!")
    print()

    # --- Connect to Alpaca and download data ---
    broker = AlpacaClient()
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    prev_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=200)).strftime("%Y-%m-%d")

    # Focus on a smaller set of symbols for faster loading.
    # SPY for market assessment + sector ETFs + top 10 liquid stocks.
    key_symbols = list(set(
        SECTOR_ETFS + MARKET_ETFS +
        ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "AMD", "INTC", "NFLX"]
    ))

    # Download daily + minute bars in one pass per symbol.
    logger.log_info(f"Downloading data for {len(key_symbols)} symbols...")
    daily_data: dict = {}
    minute_data: dict = {}

    for i, symbol in enumerate(key_symbols):
        try:
            # Daily bars for indicators.
            d_bars = broker.api.get_bars(
                symbol, tradeapi.TimeFrame.Day,
                start=prev_date, end=next_day, feed="iex",
            ).df
            if not d_bars.empty:
                daily_data[symbol] = d_bars

            # Minute bars for replay.
            m_bars = broker.api.get_bars(
                symbol, tradeapi.TimeFrame.Minute,
                start=date_str, end=next_day, feed="iex",
            ).df
            if not m_bars.empty:
                minute_data[symbol] = m_bars

            # Progress indicator.
            if (i + 1) % 5 == 0:
                logger.log_info(f"  {i + 1}/{len(key_symbols)} symbols loaded...")
        except Exception:
            pass

    logger.log_info(f"  Done: {len(daily_data)} daily, {len(minute_data)} minute")
    print()

    # --- Set up trading components ---
    risk_manager = RiskManager()
    # We need a broker-like object that returns daily data for strategies.
    # We'll use the real broker's data we already downloaded.
    sim = _DaySimBroker(daily_data, minute_data, date_str)

    screener = StockScreener(sim)

    # --- Run strategy signals at "market open" ---
    logger.log_info("Market opening... Assessing conditions...")

    try:
        market_condition = screener.assess_market_condition()
    except Exception:
        market_condition = "range_bound"

    strategy, strategy_name = _select_strategy(market_condition, sim, risk_manager)
    logger.log_market_condition(market_condition, f"Using {strategy_name}")

    try:
        candidates = screener.screen_candidates(max_candidates=10)
    except Exception:
        candidates = []

    if candidates:
        symbols = [c["symbol"] for c in candidates]
        logger.log_info(f"Candidates: {', '.join(symbols[:5])}")

    # Generate and execute signals.
    all_trades: list[dict] = []
    positions: dict = {}  # symbol -> {qty, entry_price, strategy}

    # Main strategy signals.
    if candidates:
        try:
            signals = strategy.generate_signals(candidates)
            for s in signals:
                if s["action"] == "buy" and risk_manager.can_trade():
                    account = sim.get_account_info()
                    qty = risk_manager.calculate_position_size(
                        account["equity"], s["entry_price"], s["stop_loss"]
                    )
                    if qty > 0:
                        positions[s["symbol"]] = {
                            "qty": qty,
                            "entry_price": s["entry_price"],
                            "stop_loss": s["stop_loss"],
                            "take_profit": s["take_profit"],
                            "strategy": strategy_name,
                        }
                        logger.log_trade_entry(
                            s["symbol"], "BUY", qty, s["entry_price"],
                            s["stop_loss"], s["take_profit"], strategy_name,
                        )
                        all_trades.append({
                            "time": "09:30", "symbol": s["symbol"],
                            "action": "BUY", "qty": qty,
                            "price": round(s["entry_price"], 2),
                            "strategy": strategy_name, "pnl": None,
                        })
        except Exception as e:
            logger.log_warning(f"Strategy error: {e}")

    # ETF rotation signals.
    try:
        etf = ETFRotationStrategy(sim, risk_manager)
        etf_signals = etf.generate_signals([])
        for s in etf_signals:
            if s["action"] == "buy" and risk_manager.can_trade():
                account = sim.get_account_info()
                qty = risk_manager.calculate_position_size(
                    account["equity"], s["entry_price"], s["stop_loss"]
                )
                if qty > 0:
                    positions[s["symbol"]] = {
                        "qty": qty,
                        "entry_price": s["entry_price"],
                        "stop_loss": s["stop_loss"],
                        "take_profit": s["take_profit"],
                        "strategy": "etf_rotation",
                    }
                    logger.log_trade_entry(
                        s["symbol"], "BUY", qty, s["entry_price"],
                        s["stop_loss"], s["take_profit"], "etf_rotation",
                    )
                    all_trades.append({
                        "time": "09:30", "symbol": s["symbol"],
                        "action": "BUY", "qty": qty,
                        "price": round(s["entry_price"], 2),
                        "strategy": "etf_rotation", "pnl": None,
                    })
    except Exception as e:
        logger.log_warning(f"ETF rotation error: {e}")

    logger.log_info(f"Opened {len(positions)} positions. Now watching prices tick...")
    print()

    # --- Build list of minutes to replay ---
    # Trading windows: 9:30-10:30 ET and 15:00-16:00 ET.
    # Alpaca timestamps are in UTC, ET is UTC-4 (EDT) or UTC-5 (EST).
    # March is EDT (UTC-4), so 9:30 ET = 13:30 UTC, 16:00 ET = 20:00 UTC.
    replay_minutes = _get_trading_minutes(minute_data, date_str)

    if not replay_minutes:
        logger.log_warning("No minute data in trading windows. Showing final state.")
        replay_minutes = []

    # --- Minute-by-minute replay ---
    starting_equity = 100_000.0
    equity_history = []
    closed_trades = 0
    won_trades = 0

    for i, minute_ts in enumerate(replay_minutes):
        # Convert to ET for display.
        et_time = minute_ts.astimezone(EASTERN)
        time_str = et_time.strftime("%H:%M")

        # Get current prices for all held positions.
        total_unrealized = 0.0
        position_list = []

        for symbol, pos in list(positions.items()):
            current_price = _get_minute_price(minute_data, symbol, minute_ts)
            if current_price is None:
                current_price = pos["entry_price"]

            unrealized_pl = (current_price - pos["entry_price"]) * pos["qty"]
            change_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
            total_unrealized += unrealized_pl

            position_list.append({
                "symbol": symbol,
                "qty": pos["qty"],
                "entry_price": round(pos["entry_price"], 2),
                "current_price": round(current_price, 2),
                "unrealized_pl": round(unrealized_pl, 2),
                "change_pct": round(change_pct, 2),
            })

            # Check stop-loss and take-profit.
            if current_price <= pos["stop_loss"]:
                pnl = unrealized_pl
                logger.log_trade_exit(
                    symbol, "SELL", pos["qty"],
                    pos["entry_price"], current_price, pnl,
                )
                all_trades.append({
                    "time": time_str, "symbol": symbol,
                    "action": "SELL", "qty": pos["qty"],
                    "price": round(current_price, 2),
                    "strategy": "stop_loss", "pnl": round(pnl, 2),
                })
                risk_manager.record_trade(pnl)
                closed_trades += 1
                if pnl > 0:
                    won_trades += 1
                del positions[symbol]

            elif current_price >= pos["take_profit"]:
                pnl = unrealized_pl
                logger.log_trade_exit(
                    symbol, "SELL", pos["qty"],
                    pos["entry_price"], current_price, pnl,
                )
                all_trades.append({
                    "time": time_str, "symbol": symbol,
                    "action": "SELL", "qty": pos["qty"],
                    "price": round(current_price, 2),
                    "strategy": "take_profit", "pnl": round(pnl, 2),
                })
                risk_manager.record_trade(pnl)
                closed_trades += 1
                if pnl > 0:
                    won_trades += 1
                del positions[symbol]

        current_equity = starting_equity + total_unrealized + risk_manager.daily_pnl
        daily_pnl = current_equity - starting_equity
        win_rate = (won_trades / closed_trades * 100) if closed_trades > 0 else 0

        equity_history.append({"date": time_str, "equity": round(current_equity, 2)})

        # Push to dashboard.
        update_bot_state({
            "equity": round(current_equity, 2),
            "cash": round(starting_equity - sum(
                p["entry_price"] * p["qty"] for p in positions.values()
            ), 2),
            "buying_power": round(starting_equity, 2),
            "daily_pnl": round(daily_pnl, 2),
            "market_open": True,
            "market_condition": market_condition,
            "active_strategy": strategy_name,
            "daily_target": risk_manager.elo.get_daily_target(),
            "daily_loss_limit": 100.0,
            "can_trade": risk_manager.can_trade(),
            "trade_count": len([t for t in all_trades if t["action"] == "BUY"]),
            "elo_rating": round(risk_manager.elo.rating),
            "elo_rank": risk_manager.elo.rank_name,
            "win_rate": round(win_rate, 1),
            "positions": position_list,
            "recent_trades": all_trades[-20:],
            "equity_history": equity_history,
            "elo_history": [{"date": date_str, "rating": round(risk_manager.elo.rating)}],
        })

        # Print a summary every 10 minutes.
        if i % 10 == 0:
            logger.log_info(
                f"[{time_str}] Equity: ${current_equity:,.2f} | "
                f"P&L: ${daily_pnl:+,.2f} | Positions: {len(positions)}"
            )

        time.sleep(speed)

    # --- End of day ---
    print()
    logger.log_info("Market closed!")
    risk_manager.end_of_day_reset()
    logger.log_info(f"Final ELO: {risk_manager.elo.get_rank_display()}")

    update_bot_state({"market_open": False, "active_strategy": "market closed"})

    logger.log_info("Dashboard still live at http://localhost:8080")
    logger.log_info("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")


class _DaySimBroker:
    """Minimal broker that serves pre-loaded daily data for strategies.

    The strategies need get_historical_bars() to calculate indicators.
    This gives them daily bars up to the replay date.
    """

    def __init__(self, daily_data, minute_data, date_str):
        """Initialize with pre-loaded data.

        Args:
            daily_data: Dict of symbol -> DataFrame (daily bars).
            minute_data: Dict of symbol -> DataFrame (minute bars).
            date_str: The replay date.
        """
        self.daily_data = daily_data
        self.minute_data = minute_data
        self.date_str = date_str
        self._date = pytz.utc.localize(
            datetime.strptime(date_str, "%Y-%m-%d") + timedelta(hours=23)
        )

    def get_historical_bars(self, symbol, timeframe="1Day", limit=100):
        """Return daily bars up to the replay date."""
        if symbol not in self.daily_data:
            import pandas as pd
            return pd.DataFrame()
        df = self.daily_data[symbol]
        df = df[df.index <= self._date]
        if len(df) > limit:
            df = df.iloc[-limit:]
        return df

    def get_latest_price(self, symbol):
        """Return the opening price on the replay date."""
        if symbol in self.daily_data:
            df = self.daily_data[symbol]
            df = df[df.index <= self._date]
            if not df.empty:
                return float(df["close"].iloc[-1])
        return 0.0

    def get_account_info(self):
        """Return a fake account."""
        return {
            "equity": 100_000.0,
            "buying_power": 100_000.0,
            "cash": 100_000.0,
            "portfolio_value": 100_000.0,
            "currency": "USD",
        }

    def get_open_positions(self):
        """No positions at start."""
        return []

    def is_market_open(self):
        """Always open during replay."""
        return True


def _get_trading_minutes(minute_data, date_str):
    """Get sorted list of minute timestamps within trading windows.

    Trading windows: 9:30-10:30 ET and 15:00-16:00 ET.
    In March (EDT), these are 13:30-14:30 UTC and 19:00-20:00 UTC.

    Args:
        minute_data: Dict of symbol -> minute DataFrame.
        date_str: The date string.

    Returns:
        Sorted list of timezone-aware datetime objects.
    """
    if "SPY" not in minute_data:
        # Use any available symbol.
        if not minute_data:
            return []
        symbol = next(iter(minute_data))
    else:
        symbol = "SPY"

    df = minute_data[symbol]
    eastern = pytz.timezone("US/Eastern")

    minutes = []
    for ts in df.index:
        et = ts.astimezone(eastern)
        t = et.strftime("%H:%M")
        # First window: 9:30 - 10:30
        if "09:30" <= t <= "10:30":
            minutes.append(ts)
        # Last window: 15:00 - 16:00
        elif "15:00" <= t <= "16:00":
            minutes.append(ts)

    return sorted(set(minutes))


def _get_minute_price(minute_data, symbol, timestamp):
    """Get the price for a symbol at a specific minute.

    If the exact minute isn't available (some stocks don't trade every
    minute), we use the most recent price before that minute.

    Args:
        minute_data: Dict of symbol -> minute DataFrame.
        symbol: The ticker.
        timestamp: The minute to look up.

    Returns:
        The closing price at that minute, or None if no data.
    """
    if symbol not in minute_data:
        return None

    df = minute_data[symbol]
    # Get all bars at or before this timestamp.
    available = df[df.index <= timestamp]

    if available.empty:
        return None

    return float(available["close"].iloc[-1])


def _select_strategy(condition, broker, risk_manager):
    """Pick strategy based on market condition."""
    if condition == "trending":
        return MomentumStrategy(broker, risk_manager), "momentum"
    elif condition == "breakout":
        return BreakoutStrategy(broker, risk_manager), "breakout"
    return MeanReversionStrategy(broker, risk_manager), "mean_reversion"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay one day minute by minute")
    parser.add_argument("--date", required=True, help="Date to replay YYYY-MM-DD")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Seconds per simulated minute (default: 1.0)")
    args = parser.parse_args()

    replay_day(args.date, args.speed)
