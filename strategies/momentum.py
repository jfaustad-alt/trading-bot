"""
Momentum Strategy — ride the trend using EMA crossovers and VWAP.

WHAT IS MOMENTUM?
    "The trend is your friend." Momentum trading bets that stocks already
    going up will KEEP going up (and vice versa). Instead of looking for
    reversals like mean reversion, we look for confirmation that a trend
    has started and hop on for the ride.

HOW IT WORKS:
    We use three tools to identify and confirm trends:

    1. EMA Crossover (Exponential Moving Average)
       - A moving average smooths out price data to show the trend direction.
       - EMA gives more weight to recent prices (reacts faster than SMA).
       - We use a FAST EMA (9 periods) and a SLOW EMA (21 periods).
       - When the fast EMA crosses ABOVE the slow EMA, it signals an uptrend
         is starting (a "golden cross").
       - When the fast EMA crosses BELOW the slow EMA, it signals a downtrend
         (a "death cross").

    2. VWAP (Volume-Weighted Average Price)
       - VWAP is the average price weighted by volume. It represents the
         "fair value" of the stock for the day.
       - Price ABOVE VWAP = buyers are in control (bullish).
       - Price BELOW VWAP = sellers are in control (bearish).
       - We use VWAP as a confirmation filter — we only buy if the EMA
         crossover happens while price is above VWAP.

    3. ATR (Average True Range)
       - Measures daily volatility. Used to set our stop loss at a distance
         that accounts for normal price swings (1.5x ATR below entry).

    BUY SIGNAL:  9-EMA crosses above 21-EMA AND price is above VWAP.
    SELL SIGNAL: 9-EMA crosses below 21-EMA OR price drops below VWAP.

    STOP LOSS:   1.5x ATR below entry price.
    TAKE PROFIT: Trailing stop — we let winners run and use the stop loss
                 to capture profits as the trend continues.

Usage:
    from strategies.momentum import MomentumStrategy

    strategy = MomentumStrategy(broker_client, risk_manager)
    signals = strategy.generate_signals(candidates)
    trades = strategy.execute_signals(signals)
"""

from typing import Any

import pandas as pd
import pandas_ta as ta  # noqa: F401 — enables df.ta.ema(), df.ta.vwap(), etc.

from strategies.base_strategy import BaseStrategy


class MomentumStrategy(BaseStrategy):
    """Trend-following strategy using EMA crossover confirmed by VWAP.

    This strategy identifies the START of a new trend (via EMA crossover)
    and confirms it with VWAP. It's designed to catch moves early and ride
    them as long as possible.

    Attributes:
        broker_client: The AlpacaClient for placing orders and fetching data.
        risk_manager:  Controls position sizing and trade approval.
        fast_ema_length: Period for the fast EMA (default 9).
        slow_ema_length: Period for the slow EMA (default 21).
        atr_length:      Period for ATR calculation (default 14).
        atr_multiplier:  ATR multiplier for stop loss distance (default 1.5).
        trailing_atr_multiplier: ATR multiplier for trailing stop / take profit
                                  target (default 3.0).
    """

    def __init__(
        self,
        broker_client: Any,
        risk_manager: Any,
        fast_ema_length: int = 9,
        slow_ema_length: int = 21,
        atr_length: int = 14,
        atr_multiplier: float = 1.5,
        trailing_atr_multiplier: float = 3.0,
    ) -> None:
        """Initialize the Momentum strategy with configurable parameters.

        Args:
            broker_client: The AlpacaClient for market data and order placement.
            risk_manager:  The risk manager that approves trades and sizes positions.
            fast_ema_length: Lookback for the fast-moving EMA (default 9).
            slow_ema_length: Lookback for the slow-moving EMA (default 21).
            atr_length: Lookback period for ATR calculation.
            atr_multiplier: How many ATRs below entry for the stop loss.
            trailing_atr_multiplier: How many ATRs for the take profit target.
                                     This is the initial target; ideally we'd
                                     use a trailing stop in production.
        """
        super().__init__(broker_client, risk_manager)
        self.fast_ema_length = fast_ema_length
        self.slow_ema_length = slow_ema_length
        self.atr_length = atr_length
        self.atr_multiplier = atr_multiplier
        self.trailing_atr_multiplier = trailing_atr_multiplier

    def generate_signals(self, candidates: list[dict]) -> list[dict]:
        """Scan candidates for momentum signals (EMA crossover + VWAP).

        For each candidate:
            1. Fetch historical bars.
            2. Calculate fast EMA, slow EMA, VWAP, and ATR.
            3. Check for EMA crossover and VWAP confirmation.
            4. Generate a buy or sell signal if conditions are met.

        Args:
            candidates: A list of dicts from the screener. Each must have
                        at least a "symbol" key.

        Returns:
            A list of signal dicts with: symbol, action, entry_price,
            stop_loss, take_profit, confidence.
        """
        signals: list[dict] = []

        for candidate in candidates:
            symbol = candidate["symbol"]

            # Fetch enough bars for the slow EMA (21) plus some extra
            # for the indicator to "warm up" (initial values are unreliable).
            df = self.broker_client.get_historical_bars(symbol, limit=100)

            # We need at least slow_ema_length + 1 bars to detect a crossover.
            if len(df) < self.slow_ema_length + 1:
                continue

            # Calculate indicators.
            indicators = _compute_momentum_indicators(
                df,
                fast_length=self.fast_ema_length,
                slow_length=self.slow_ema_length,
                atr_length=self.atr_length,
            )

            if indicators is None:
                continue

            # Check for signals.
            signal = _check_momentum_signal(
                symbol=symbol,
                indicators=indicators,
                atr_multiplier=self.atr_multiplier,
                trailing_atr_multiplier=self.trailing_atr_multiplier,
            )

            if signal is not None:
                signals.append(signal)

        return signals


def _compute_momentum_indicators(
    df: pd.DataFrame,
    fast_length: int,
    slow_length: int,
    atr_length: int,
) -> dict[str, Any] | None:
    """Calculate EMA, VWAP, and ATR indicators for momentum analysis.

    We need the current AND previous values of the EMAs to detect a
    crossover (when the fast EMA goes from below to above the slow EMA,
    or vice versa).

    Args:
        df: DataFrame with OHLCV columns (open, high, low, close, volume).
        fast_length: Period for the fast EMA (e.g. 9).
        slow_length: Period for the slow EMA (e.g. 21).
        atr_length: Period for ATR.

    Returns:
        A dict with current and previous indicator values, or None if
        calculation fails.
    """
    # --- EMAs ---
    # EMA = Exponential Moving Average. Unlike a simple average that weights
    # all periods equally, EMA gives more importance to recent prices.
    fast_ema = df.ta.ema(length=fast_length)
    slow_ema = df.ta.ema(length=slow_length)

    if fast_ema is None or slow_ema is None:
        return None
    if len(fast_ema) < 2 or len(slow_ema) < 2:
        return None

    # --- VWAP ---
    # VWAP = Volume-Weighted Average Price.
    # It tells us the average price at which shares have traded, weighted
    # by volume. Big institutional traders use VWAP as a benchmark.
    # Note: VWAP requires 'high', 'low', 'close', and 'volume' columns.
    vwap = df.ta.vwap()

    if vwap is None or vwap.empty:
        return None

    # --- ATR ---
    atr = df.ta.atr(length=atr_length)
    if atr is None or atr.empty:
        return None

    # Get the last two values for crossover detection.
    # "Current" = the most recent bar, "previous" = the bar before that.
    current_fast = fast_ema.iloc[-1]
    current_slow = slow_ema.iloc[-1]
    previous_fast = fast_ema.iloc[-2]
    previous_slow = slow_ema.iloc[-2]
    current_close = df["close"].iloc[-1]
    current_vwap = vwap.iloc[-1]
    current_atr = atr.iloc[-1]

    # Check for NaN values.
    values = [current_fast, current_slow, previous_fast, previous_slow,
              current_close, current_vwap, current_atr]
    if any(pd.isna(v) for v in values):
        return None

    return {
        "current_fast_ema": float(current_fast),
        "current_slow_ema": float(current_slow),
        "previous_fast_ema": float(previous_fast),
        "previous_slow_ema": float(previous_slow),
        "close": float(current_close),
        "vwap": float(current_vwap),
        "atr": float(current_atr),
    }


def _check_momentum_signal(
    symbol: str,
    indicators: dict[str, float],
    atr_multiplier: float,
    trailing_atr_multiplier: float,
) -> dict | None:
    """Check for EMA crossover signals confirmed by VWAP.

    A "crossover" means the fast EMA was below the slow EMA on the previous
    bar, but is now above it (bullish crossover), or vice versa (bearish).

    We only take the signal if VWAP confirms:
        - Bullish crossover + price above VWAP = BUY.
        - Bearish crossover OR price below VWAP = SELL.

    Args:
        symbol: The stock ticker.
        indicators: Dict with EMA, VWAP, ATR, and close values.
        atr_multiplier: Multiplier for stop loss distance.
        trailing_atr_multiplier: Multiplier for take profit target.

    Returns:
        A signal dict if conditions are met, or None.
    """
    close = indicators["close"]
    vwap = indicators["vwap"]
    atr = indicators["atr"]
    current_fast = indicators["current_fast_ema"]
    current_slow = indicators["current_slow_ema"]
    previous_fast = indicators["previous_fast_ema"]
    previous_slow = indicators["previous_slow_ema"]

    # --- Detect crossovers ---
    # Bullish crossover: fast EMA was BELOW slow EMA, now it's ABOVE.
    # This means short-term momentum has shifted upward.
    bullish_crossover = (previous_fast <= previous_slow) and (current_fast > current_slow)

    # Bearish crossover: fast EMA was ABOVE slow EMA, now it's BELOW.
    # Short-term momentum has shifted downward.
    bearish_crossover = (previous_fast >= previous_slow) and (current_fast < current_slow)

    # --- BUY SIGNAL ---
    # Bullish EMA crossover PLUS price above VWAP (institutional buyers active).
    if bullish_crossover and close > vwap:
        # Confidence based on how far the fast EMA is pulling away from slow.
        # A stronger separation = more momentum = higher confidence.
        ema_spread = (current_fast - current_slow) / current_slow
        confidence = min(0.5 + ema_spread * 10, 1.0)  # cap at 1.0

        return {
            "symbol": symbol,
            "action": "buy",
            "entry_price": close,
            "stop_loss": close - (atr * atr_multiplier),
            # For momentum, we use a wider target to let winners run.
            # In production, this would be a trailing stop.
            "take_profit": close + (atr * trailing_atr_multiplier),
            "confidence": round(confidence, 2),
        }

    # --- SELL SIGNAL ---
    # Bearish EMA crossover OR price has dropped below VWAP.
    # We're more aggressive with sells to protect profits — either condition
    # alone is enough (we don't need both to confirm).
    if bearish_crossover or (current_fast < current_slow and close < vwap):
        # Higher confidence if BOTH conditions are true.
        confidence = 0.8 if (bearish_crossover and close < vwap) else 0.6

        return {
            "symbol": symbol,
            "action": "sell",
            "entry_price": close,
            "stop_loss": close + (atr * atr_multiplier),
            "take_profit": close - (atr * trailing_atr_multiplier),
            "confidence": confidence,
        }

    return None
