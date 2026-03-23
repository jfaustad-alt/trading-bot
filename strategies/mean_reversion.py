"""
Mean Reversion Strategy — buy low, sell high by betting on "normal" prices.

WHAT IS MEAN REVERSION?
    Prices tend to swing above and below an average (the "mean"). When a
    stock's price moves too far from its average, it often snaps back. This
    strategy tries to profit from that snap-back.

    Analogy: imagine stretching a rubber band. The further you pull it, the
    harder it snaps back. Stocks often behave similarly in the short term.

HOW IT WORKS:
    We combine two indicators to find these stretched-rubber-band moments:

    1. Bollinger Bands — a channel drawn around a moving average.
       - The MIDDLE band is a 20-period simple moving average (SMA).
       - The UPPER band is the SMA + 2 standard deviations.
       - The LOWER band is the SMA - 2 standard deviations.
       When price touches the lower band, the stock is "cheap" relative to
       recent history. When it touches the upper band, it's "expensive."

    2. RSI (Relative Strength Index) — measures how fast price has been
       going up vs. down over the last 14 periods.
       - RSI below 30 = "oversold" (price dropped too fast, might bounce).
       - RSI above 70 = "overbought" (price rose too fast, might drop).
       - RSI of 50 = neutral.

    BUY SIGNAL:  price below lower Bollinger Band AND RSI < 30.
    SELL SIGNAL: price above upper Bollinger Band AND RSI > 70.

    STOP LOSS:   1.0x ATR below entry price.
    TAKE PROFIT: price returns to the middle Bollinger Band (the SMA).

    ATR (Average True Range) measures how much a stock typically moves in a
    day. Using ATR for stop losses adapts to each stock's volatility — a
    volatile stock gets a wider stop, a calm stock gets a tighter one.

Usage:
    from strategies.mean_reversion import MeanReversionStrategy

    strategy = MeanReversionStrategy(broker_client, risk_manager)
    signals = strategy.generate_signals(candidates)
    trades = strategy.execute_signals(signals)
"""

from typing import Any

import pandas as pd
import pandas_ta as ta  # noqa: F401 — imported so we can use df.ta.bbands() etc.

from strategies.base_strategy import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    """Buy oversold stocks and sell overbought ones using Bollinger Bands + RSI.

    This strategy looks for stocks that have moved too far from their average
    price. It uses two confirming indicators (Bollinger Bands AND RSI) to
    reduce false signals — both must agree before we trade.

    Attributes:
        broker_client: The AlpacaClient for placing orders and fetching data.
        risk_manager:  Controls position sizing and trade approval.
        bb_length:     Number of periods for Bollinger Band calculation (default 20).
        bb_std:        Number of standard deviations for the bands (default 2.0).
        rsi_length:    Number of periods for RSI calculation (default 14).
        rsi_oversold:  RSI level below which we consider a stock oversold (default 30).
        rsi_overbought: RSI level above which we consider a stock overbought (default 70).
        atr_length:    Number of periods for ATR calculation (default 14).
        atr_multiplier: How many ATRs to use for the stop loss (default 1.0).
    """

    def __init__(
        self,
        broker_client: Any,
        risk_manager: Any,
        bb_length: int = 20,
        bb_std: float = 2.0,
        rsi_length: int = 14,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
        atr_length: int = 14,
        atr_multiplier: float = 1.0,
    ) -> None:
        """Initialize the Mean Reversion strategy with configurable parameters.

        Args:
            broker_client: The AlpacaClient for market data and order placement.
            risk_manager:  The risk manager that approves trades and sizes positions.
            bb_length:     Lookback period for Bollinger Bands. More periods = smoother bands.
            bb_std:        Width of bands in standard deviations. Wider = fewer signals.
            rsi_length:    Lookback period for RSI. Standard is 14.
            rsi_oversold:  RSI threshold for oversold condition.
            rsi_overbought: RSI threshold for overbought condition.
            atr_length:    Lookback period for ATR (used in stop loss calculation).
            atr_multiplier: Multiplier for ATR-based stop loss distance.
        """
        super().__init__(broker_client, risk_manager)
        self.bb_length = bb_length
        self.bb_std = bb_std
        self.rsi_length = rsi_length
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_length = atr_length
        self.atr_multiplier = atr_multiplier

    def generate_signals(self, candidates: list[dict]) -> list[dict]:
        """Scan candidates for mean reversion opportunities.

        For each candidate stock:
            1. Fetch historical price data.
            2. Calculate Bollinger Bands, RSI, and ATR.
            3. Check if the latest price is outside the bands with confirming RSI.
            4. If so, generate a buy or sell signal.

        Args:
            candidates: A list of dicts from the screener. Each must have at
                        least a "symbol" key (e.g. {"symbol": "AAPL", ...}).

        Returns:
            A list of signal dicts. Each signal has: symbol, action,
            entry_price, stop_loss, take_profit, confidence.
        """
        signals: list[dict] = []

        for candidate in candidates:
            symbol = candidate["symbol"]

            # Fetch historical price data — we need enough bars to compute
            # our indicators. 100 bars is plenty for 20-period Bollinger Bands.
            df = self.broker_client.get_historical_bars(symbol, limit=100)

            # Skip if we don't have enough data to compute indicators.
            if len(df) < self.bb_length:
                continue

            # Calculate all the indicators we need.
            indicators = _compute_indicators(
                df,
                bb_length=self.bb_length,
                bb_std=self.bb_std,
                rsi_length=self.rsi_length,
                atr_length=self.atr_length,
            )

            # If indicator calculation failed (e.g., not enough data), skip.
            if indicators is None:
                continue

            # Check if we have a buy or sell signal.
            signal = _check_for_signal(
                symbol=symbol,
                indicators=indicators,
                rsi_oversold=self.rsi_oversold,
                rsi_overbought=self.rsi_overbought,
                atr_multiplier=self.atr_multiplier,
            )

            if signal is not None:
                signals.append(signal)

        return signals


def _compute_indicators(
    df: pd.DataFrame,
    bb_length: int,
    bb_std: float,
    rsi_length: int,
    atr_length: int,
) -> dict[str, float] | None:
    """Calculate Bollinger Bands, RSI, and ATR from price data.

    This function takes raw OHLCV data and adds technical indicators.
    We extract just the most recent (latest) values since we only care
    about the current state of the market.

    Args:
        df: DataFrame with columns: open, high, low, close, volume.
        bb_length: Number of periods for Bollinger Bands.
        bb_std: Standard deviation multiplier for Bollinger Bands.
        rsi_length: Number of periods for RSI.
        atr_length: Number of periods for ATR.

    Returns:
        A dict with the latest values of each indicator, or None if
        calculation fails. Keys: close, lower_band, middle_band,
        upper_band, rsi, atr.
    """
    # --- Bollinger Bands ---
    # bbands() returns a DataFrame with columns like:
    #   BBL_20_2.0 (lower), BBM_20_2.0 (middle), BBU_20_2.0 (upper),
    #   BBB_20_2.0 (bandwidth), BBP_20_2.0 (percent)
    bbands = df.ta.bbands(length=bb_length, std=bb_std)
    if bbands is None or bbands.empty:
        return None

    # --- RSI ---
    # rsi() returns a Series named like "RSI_14"
    rsi = df.ta.rsi(length=rsi_length)
    if rsi is None or rsi.empty:
        return None

    # --- ATR (Average True Range) ---
    # atr() returns a Series named like "ATRr_14"
    atr = df.ta.atr(length=atr_length)
    if atr is None or atr.empty:
        return None

    # Build column names — pandas_ta names them based on parameters.
    # The naming format can vary between versions (e.g. "BBL_20_2.0" or
    # "BBL_20_2.0_2.0"), so we search for the right column by prefix.
    bb_lower_col = _find_column(bbands, "BBL_")
    bb_middle_col = _find_column(bbands, "BBM_")
    bb_upper_col = _find_column(bbands, "BBU_")

    if bb_lower_col is None or bb_middle_col is None or bb_upper_col is None:
        return None

    # Get the latest (most recent) row of each indicator.
    # .iloc[-1] means "the last row."
    latest_close = df["close"].iloc[-1]
    latest_lower = bbands[bb_lower_col].iloc[-1]
    latest_middle = bbands[bb_middle_col].iloc[-1]
    latest_upper = bbands[bb_upper_col].iloc[-1]
    latest_rsi = rsi.iloc[-1]
    latest_atr = atr.iloc[-1]

    # Check for NaN (Not a Number) — this happens when there isn't enough
    # data for the indicator. pd.isna() returns True if the value is NaN.
    values = [latest_close, latest_lower, latest_middle, latest_upper,
              latest_rsi, latest_atr]
    if any(pd.isna(v) for v in values):
        return None

    return {
        "close": float(latest_close),
        "lower_band": float(latest_lower),
        "middle_band": float(latest_middle),
        "upper_band": float(latest_upper),
        "rsi": float(latest_rsi),
        "atr": float(latest_atr),
    }


def _check_for_signal(
    symbol: str,
    indicators: dict[str, float],
    rsi_oversold: float,
    rsi_overbought: float,
    atr_multiplier: float,
) -> dict | None:
    """Check whether the latest indicator values trigger a buy or sell signal.

    BUY when:  price is below the lower Bollinger Band AND RSI < oversold level.
    SELL when: price is above the upper Bollinger Band AND RSI > overbought level.

    Args:
        symbol: The stock ticker.
        indicators: Dict with keys: close, lower_band, middle_band,
                    upper_band, rsi, atr.
        rsi_oversold: The RSI threshold for oversold (e.g. 30).
        rsi_overbought: The RSI threshold for overbought (e.g. 70).
        atr_multiplier: How many ATRs to use for the stop loss.

    Returns:
        A signal dict if conditions are met, or None if no signal.
    """
    close = indicators["close"]
    lower_band = indicators["lower_band"]
    middle_band = indicators["middle_band"]
    upper_band = indicators["upper_band"]
    rsi = indicators["rsi"]
    atr = indicators["atr"]

    # --- BUY SIGNAL ---
    # Price below lower band = stock is unusually cheap.
    # RSI < 30 = selling pressure is exhausted (oversold).
    # Both conditions together give us higher confidence.
    if close < lower_band and rsi < rsi_oversold:
        # Confidence is higher when RSI is further below 30 (more oversold).
        # We map RSI 0-30 to confidence 0.5-1.0.
        confidence = _calculate_buy_confidence(rsi, rsi_oversold)

        return {
            "symbol": symbol,
            "action": "buy",
            "entry_price": close,
            # Stop loss: if price drops even further, cut losses.
            # We place it 1 ATR below our entry.
            "stop_loss": close - (atr * atr_multiplier),
            # Take profit: we expect price to return to the middle band
            # (the moving average). That's the "mean" we're reverting to.
            "take_profit": middle_band,
            "confidence": confidence,
        }

    # --- SELL SIGNAL ---
    # Price above upper band = stock is unusually expensive.
    # RSI > 70 = buying pressure is exhausted (overbought).
    if close > upper_band and rsi > rsi_overbought:
        # Confidence is higher when RSI is further above 70.
        confidence = _calculate_sell_confidence(rsi, rsi_overbought)

        return {
            "symbol": symbol,
            "action": "sell",
            "entry_price": close,
            # For a sell/short, stop loss is ABOVE entry (price going up = loss).
            "stop_loss": close + (atr * atr_multiplier),
            # Take profit: price returns to the middle band.
            "take_profit": middle_band,
            "confidence": confidence,
        }

    # No signal — conditions not met.
    return None


def _find_column(df: pd.DataFrame, prefix: str) -> str | None:
    """Find a column in a DataFrame that starts with the given prefix.

    pandas_ta column names can vary between versions (e.g. "BBL_20_2.0"
    vs "BBL_20_2.0_2.0"). This helper finds the right column regardless
    of the exact naming format.

    Args:
        df: The DataFrame to search.
        prefix: The column name prefix to look for (e.g. "BBL_").

    Returns:
        The full column name, or None if no match is found.
    """
    for col in df.columns:
        if col.startswith(prefix):
            return col
    return None


def _calculate_buy_confidence(rsi: float, rsi_oversold: float) -> float:
    """Calculate confidence for a buy signal based on how oversold the RSI is.

    The further RSI is below the oversold threshold, the more confident we
    are that the stock will bounce back.

    Maps RSI from [0, oversold_threshold] to confidence [1.0, 0.5].
    RSI at 0 -> confidence 1.0 (very oversold, very confident).
    RSI at 30 -> confidence 0.5 (just barely oversold, less confident).

    Args:
        rsi: The current RSI value.
        rsi_oversold: The oversold threshold (e.g. 30).

    Returns:
        A float between 0.5 and 1.0.
    """
    # How far below the threshold is the RSI? (as a fraction of the threshold)
    depth = (rsi_oversold - rsi) / rsi_oversold
    # Scale to 0.5 - 1.0 range
    return 0.5 + (depth * 0.5)


def _calculate_sell_confidence(rsi: float, rsi_overbought: float) -> float:
    """Calculate confidence for a sell signal based on how overbought the RSI is.

    The further RSI is above the overbought threshold, the more confident we
    are that the stock will pull back.

    Maps RSI from [overbought_threshold, 100] to confidence [0.5, 1.0].
    RSI at 100 -> confidence 1.0 (extremely overbought).
    RSI at 70  -> confidence 0.5 (just barely overbought).

    Args:
        rsi: The current RSI value.
        rsi_overbought: The overbought threshold (e.g. 70).

    Returns:
        A float between 0.5 and 1.0.
    """
    # How far above the threshold? (as a fraction of the remaining range)
    excess = (rsi - rsi_overbought) / (100 - rsi_overbought)
    return 0.5 + (excess * 0.5)
