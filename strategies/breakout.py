"""
Breakout Strategy — catch stocks as they break through resistance levels.

WHAT IS A BREAKOUT?
    A "breakout" happens when a stock's price pushes above a level it has
    struggled to get past (called "resistance"). Think of resistance like a
    ceiling — the price keeps bumping into it and falling back. When it
    finally punches through, it often moves fast and far.

    Why does this happen? When a stock breaks resistance, traders who were
    waiting on the sidelines jump in (FOMO — fear of missing out), and
    traders who were betting against the stock (short sellers) are forced to
    buy to cover their losses. This creates a surge of buying pressure.

HOW IT WORKS:
    1. Resistance Level
       - We define resistance as the highest price over the last 20 periods.
       - If today's price breaks above that high, we have a potential breakout.

    2. Volume Confirmation
       - Not all breakouts are real. Sometimes price pokes above resistance
         but there's no conviction behind the move (a "false breakout").
       - We require volume to be at least 1.5x the average volume. High
         volume means lots of traders are participating — the move is real.

    3. ATR (Average True Range)
       - Used for both stop loss and take profit.
       - Stop loss: 2.0x ATR below entry (wider than other strategies because
         breakout stocks are volatile — we need room to breathe).
       - Take profit: 2.0x ATR above entry (we want at least a 1:1
         risk-to-reward ratio).

    BUY SIGNAL:  price > 20-period high AND volume > 1.5x average volume.
    STOP LOSS:   2.0x ATR below entry.
    TAKE PROFIT: 2.0x ATR above entry (ATR-based target).

Usage:
    from strategies.breakout import BreakoutStrategy

    strategy = BreakoutStrategy(broker_client, risk_manager)
    signals = strategy.generate_signals(candidates)
    trades = strategy.execute_signals(signals)
"""

from typing import Any

import pandas as pd
import pandas_ta as ta  # noqa: F401 — enables df.ta.atr()

from strategies.base_strategy import BaseStrategy


class BreakoutStrategy(BaseStrategy):
    """Detects price breakouts above resistance with volume confirmation.

    This strategy looks for stocks breaking above their recent highs (which
    act as resistance) with strong volume, indicating genuine buying interest
    rather than a false breakout.

    Attributes:
        broker_client: The AlpacaClient for placing orders and fetching data.
        risk_manager:  Controls position sizing and trade approval.
        lookback_period: Number of periods to look back for the high (default 20).
        volume_multiplier: Required volume relative to average (default 1.5).
                           Volume must be at least this many times the average.
        atr_length: Period for ATR calculation (default 14).
        atr_stop_multiplier: ATR multiplier for stop loss (default 2.0).
        atr_target_multiplier: ATR multiplier for take profit (default 2.0).
    """

    def __init__(
        self,
        broker_client: Any,
        risk_manager: Any,
        lookback_period: int = 20,
        volume_multiplier: float = 1.5,
        atr_length: int = 14,
        atr_stop_multiplier: float = 2.0,
        atr_target_multiplier: float = 2.0,
    ) -> None:
        """Initialize the Breakout strategy with configurable parameters.

        Args:
            broker_client: The AlpacaClient for market data and order placement.
            risk_manager:  The risk manager that approves trades and sizes positions.
            lookback_period: How many bars back to look for the resistance level.
                            20 is roughly one month of daily bars.
            volume_multiplier: Minimum ratio of current volume to average volume.
                               1.5 means volume must be 50% above average.
            atr_length: Lookback period for ATR.
            atr_stop_multiplier: ATR multiplier for stop loss distance.
            atr_target_multiplier: ATR multiplier for take profit distance.
        """
        super().__init__(broker_client, risk_manager)
        self.lookback_period = lookback_period
        self.volume_multiplier = volume_multiplier
        self.atr_length = atr_length
        self.atr_stop_multiplier = atr_stop_multiplier
        self.atr_target_multiplier = atr_target_multiplier

    def generate_signals(self, candidates: list[dict]) -> list[dict]:
        """Scan candidates for breakout opportunities.

        For each candidate:
            1. Fetch historical bars.
            2. Find the 20-period high (resistance level).
            3. Check if the current price has broken above it.
            4. Confirm with above-average volume.
            5. Calculate ATR-based stop loss and take profit.

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

            # We need lookback_period + a few extra bars for ATR warm-up.
            df = self.broker_client.get_historical_bars(symbol, limit=100)

            if len(df) < self.lookback_period + 1:
                continue

            # Calculate breakout indicators.
            indicators = _compute_breakout_indicators(
                df,
                lookback_period=self.lookback_period,
                atr_length=self.atr_length,
            )

            if indicators is None:
                continue

            # Check for breakout signal.
            signal = _check_breakout_signal(
                symbol=symbol,
                indicators=indicators,
                volume_multiplier=self.volume_multiplier,
                atr_stop_multiplier=self.atr_stop_multiplier,
                atr_target_multiplier=self.atr_target_multiplier,
            )

            if signal is not None:
                signals.append(signal)

        return signals


def _compute_breakout_indicators(
    df: pd.DataFrame,
    lookback_period: int,
    atr_length: int,
) -> dict[str, float] | None:
    """Calculate breakout-related indicators: resistance level, volume, ATR.

    We need:
        - The highest price over the lookback period (excluding the current bar)
          to establish the resistance level.
        - Current volume and average volume for confirmation.
        - ATR for stop loss and take profit distances.

    Args:
        df: DataFrame with OHLCV columns.
        lookback_period: Number of bars to look back for the high.
        atr_length: Period for ATR.

    Returns:
        A dict with indicator values, or None if calculation fails.
    """
    # --- Resistance Level (20-period high) ---
    # We look at the "high" column over the last lookback_period bars,
    # EXCLUDING the current bar. We exclude the current bar because if
    # today's high IS the 20-period high, that means price just broke out.
    #
    # .iloc[-lookback_period - 1 : -1] gets the bars from 21 bars ago up to
    # (but not including) the current bar.
    past_highs = df["high"].iloc[-lookback_period - 1: -1]
    resistance_level = past_highs.max()

    # --- Current bar data ---
    current_close = df["close"].iloc[-1]
    current_high = df["high"].iloc[-1]
    current_volume = df["volume"].iloc[-1]

    # --- Average Volume ---
    # Average volume over the lookback period (excluding current bar).
    # This is our baseline for "normal" volume.
    past_volumes = df["volume"].iloc[-lookback_period - 1: -1]
    average_volume = past_volumes.mean()

    # --- ATR ---
    atr = df.ta.atr(length=atr_length)
    if atr is None or atr.empty:
        return None

    current_atr = atr.iloc[-1]

    # Check for NaN or zero values.
    values = [resistance_level, current_close, current_high,
              current_volume, average_volume, current_atr]
    if any(pd.isna(v) for v in values):
        return None
    if average_volume == 0:
        return None

    return {
        "resistance_level": float(resistance_level),
        "close": float(current_close),
        "high": float(current_high),
        "volume": float(current_volume),
        "average_volume": float(average_volume),
        "atr": float(current_atr),
    }


def _check_breakout_signal(
    symbol: str,
    indicators: dict[str, float],
    volume_multiplier: float,
    atr_stop_multiplier: float,
    atr_target_multiplier: float,
) -> dict | None:
    """Check if price has broken above resistance with volume confirmation.

    Two conditions must be met:
        1. The current high must be above the resistance level (20-period high).
        2. Current volume must exceed average_volume * volume_multiplier.

    Args:
        symbol: The stock ticker.
        indicators: Dict with resistance_level, close, high, volume,
                    average_volume, and atr.
        volume_multiplier: Required ratio of current to average volume.
        atr_stop_multiplier: ATR multiplier for stop loss.
        atr_target_multiplier: ATR multiplier for take profit.

    Returns:
        A signal dict if conditions are met, or None.
    """
    close = indicators["close"]
    high = indicators["high"]
    resistance = indicators["resistance_level"]
    volume = indicators["volume"]
    avg_volume = indicators["average_volume"]
    atr = indicators["atr"]

    # --- BREAKOUT CHECK ---
    # Condition 1: Has price broken above resistance?
    # We check the HIGH, not the close, because a breakout can happen
    # intraday even if the close pulls back slightly.
    price_breakout = high > resistance

    # Condition 2: Is volume strong enough?
    # High volume confirms that many traders believe in the breakout.
    # Low volume breakouts often fail (the price falls back below resistance).
    volume_ratio = volume / avg_volume
    volume_confirmed = volume_ratio >= volume_multiplier

    if price_breakout and volume_confirmed:
        # Confidence is based on how far above resistance we've broken and
        # how strong the volume is. Both contribute equally.
        #
        # Price strength: how far above resistance (as % of resistance).
        price_strength = (high - resistance) / resistance
        price_score = min(price_strength * 20, 0.5)  # cap contribution at 0.5

        # Volume strength: how much above the required threshold.
        volume_score = min((volume_ratio - volume_multiplier) * 0.25, 0.5)

        confidence = round(0.5 + price_score + volume_score, 2)
        confidence = min(confidence, 1.0)

        return {
            "symbol": symbol,
            "action": "buy",
            "entry_price": close,
            # Wider stop loss for breakouts — these stocks are volatile.
            # 2x ATR gives enough room to avoid getting stopped out by
            # normal volatility.
            "stop_loss": close - (atr * atr_stop_multiplier),
            # Take profit at 2x ATR above entry — this gives us a 1:1
            # risk-reward ratio (risking 2 ATR to make 2 ATR).
            "take_profit": close + (atr * atr_target_multiplier),
            "confidence": confidence,
        }

    # No breakout detected.
    return None
