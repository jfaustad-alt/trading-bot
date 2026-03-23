"""
Stock Screener Module

Scans a universe of stocks and ETFs each morning to find the best
trading candidates for the day. It ranks them by volume, volatility,
and momentum so the bot can focus on the most promising opportunities.

Technical terms used in this module:
- ATR (Average True Range): Measures how much a stock typically moves
  per day in dollar terms. Higher ATR = more volatile = bigger moves.
- RSI (Relative Strength Index): A 0-100 score measuring momentum.
  Above 70 = overbought (might reverse down).
  Below 30 = oversold (might reverse up).
- VWAP (Volume Weighted Average Price): The average price weighted by
  volume. If price is above VWAP, buyers are in control, and vice versa.
"""

import pandas as pd
import pandas_ta as ta


# ---------------------------------------------------------------------------
# Default universe of symbols the screener will scan every morning.
# We split them into categories so each group can be used independently.
# ---------------------------------------------------------------------------

# Sector ETFs – one for each S&P 500 sector.
# Useful for "sector rotation" (moving money to the strongest sector).
SECTOR_ETFS: list[str] = [
    "XLK",   # Technology
    "XLE",   # Energy
    "XLF",   # Financials
    "XLV",   # Health Care
    "XLI",   # Industrials
    "XLC",   # Communication Services
    "XLY",   # Consumer Discretionary
    "XLP",   # Consumer Staples
    "XLB",   # Materials
    "XLRE",  # Real Estate
    "XLU",   # Utilities
]

# Broad market ETFs – used to gauge overall market conditions.
MARKET_ETFS: list[str] = ["SPY", "QQQ", "IWM"]

# High-volume individual stocks – these tend to have tight spreads
# and plenty of liquidity, which makes them easier and cheaper to trade.
LIQUID_STOCKS: list[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "TSLA", "NVDA", "JPM", "BAC", "WFC",
    "JNJ", "UNH", "XOM", "CVX", "PG",
    "KO", "DIS", "NFLX", "AMD", "INTC",
]


class StockScreener:
    """Screens a universe of stocks to find the best daily trading candidates.

    The screener pulls recent price data through a broker client, calculates
    key technical indicators (ATR, RSI, volume), and ranks symbols so the
    trading bot can focus on the most promising opportunities.

    Args:
        broker_client: An object that provides market data. Must implement:
            - get_bars(symbol, timeframe, limit) -> pd.DataFrame
            - get_latest_trade(symbol) -> trade object with a .price attribute
        universe: Optional custom list of ticker symbols to scan.
            Defaults to the combined sector ETFs, market ETFs, and liquid stocks.
    """

    def __init__(self, broker_client, universe: list[str] | None = None) -> None:
        """Initialise the screener with a broker client and symbol universe.

        Args:
            broker_client: Broker client for fetching market data.
            universe: Optional list of symbols to scan. If not provided,
                the default universe (sector ETFs + market ETFs + liquid
                stocks) is used.
        """
        self.broker = broker_client

        # Build the default universe by combining all three groups.
        if universe is None:
            self.universe = SECTOR_ETFS + MARKET_ETFS + LIQUID_STOCKS
        else:
            self.universe = universe

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def screen_candidates(self, max_candidates: int = 10) -> list[dict]:
        """Screen the full universe and return the top trading candidates.

        For each symbol we calculate volume, ATR (volatility), and RSI
        (momentum). We then rank by a simple composite score that favours
        liquid, volatile stocks with clear momentum.

        Args:
            max_candidates: Maximum number of candidates to return.

        Returns:
            A list of dicts, each containing:
                - symbol (str): Ticker symbol.
                - avg_volume (float): Average daily volume over the lookback.
                - atr (float): Average True Range (daily volatility in $).
                - relative_strength (float): RSI value (0-100).
                - volatility (float): ATR as a percentage of the current price.
        """
        candidates: list[dict] = []

        for symbol in self.universe:
            # Skip broad-market ETFs – they are used for market condition
            # assessment, not as direct trading candidates.
            if symbol in MARKET_ETFS:
                continue

            try:
                # Pull 30 days of daily bars – enough for a 14-period ATR/RSI
                # with some runway for the calculation to warm up.
                bars: pd.DataFrame = self.broker.get_historical_bars(
                    symbol, timeframe="1Day", limit=30
                )

                # Need at least 15 bars to compute 14-period indicators.
                if bars is None or len(bars) < 15:
                    continue

                atr = self.calculate_atr(bars, period=14)
                rsi = self.calculate_relative_strength(bars, period=14)
                avg_volume = float(bars["volume"].mean())

                # Get the latest price so we can express ATR as a percentage.
                price = self.broker.get_latest_price(symbol)

                # Volatility as a percentage of price.
                # e.g. ATR $2 on a $100 stock = 2 % daily volatility.
                volatility = (atr / price) * 100 if price > 0 else 0.0

                candidates.append({
                    "symbol": symbol,
                    "avg_volume": avg_volume,
                    "atr": round(atr, 4),
                    "relative_strength": round(rsi, 2),
                    "volatility": round(volatility, 2),
                })

            except Exception as exc:
                # If one symbol fails (delisted, API hiccup, etc.) we just
                # skip it and move on to the next.
                print(f"[Screener] Skipping {symbol}: {exc}")
                continue

        # ------- Rank candidates -------
        # Sort by volatility (descending) – we want stocks that *move*.
        # Ties are broken by volume (also descending) – more liquid is better.
        candidates.sort(
            key=lambda c: (c["volatility"], c["avg_volume"]),
            reverse=True,
        )

        return candidates[:max_candidates]

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate the Average True Range for a price DataFrame.

        ATR tells us how much a stock typically moves per day (in dollars).
        A higher ATR means wider swings, which creates more opportunity
        (and risk) for day trades.

        The "true range" for a single day is the greatest of:
          1. Today's high minus today's low
          2. |Today's high minus yesterday's close|
          3. |Today's low  minus yesterday's close|

        ATR is then the rolling average of true range over *period* days.

        Args:
            df: DataFrame with columns: high, low, close.
            period: Number of days for the rolling average (default 14).

        Returns:
            The most recent ATR value as a float.
        """
        # pandas_ta.atr returns a Series; we want just the latest value.
        atr_series: pd.Series = ta.atr(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            length=period,
        )

        # The first *period* values will be NaN (not enough data yet).
        # dropna() removes them so .iloc[-1] gives the latest valid ATR.
        return float(atr_series.dropna().iloc[-1])

    def calculate_relative_strength(
        self, df: pd.DataFrame, period: int = 14
    ) -> float:
        """Calculate the Relative Strength Index (RSI).

        RSI is a momentum oscillator on a 0-100 scale:
          - Above 70 → stock is *overbought* (has risen fast, may pull back).
          - Below 30 → stock is *oversold* (has fallen fast, may bounce).
          - Around 50 → neutral / no strong momentum.

        Args:
            df: DataFrame with a 'close' column.
            period: Lookback period for RSI calculation (default 14).

        Returns:
            The most recent RSI value as a float.
        """
        rsi_series: pd.Series = ta.rsi(close=df["close"], length=period)

        return float(rsi_series.dropna().iloc[-1])

    def assess_market_condition(self) -> str:
        """Look at SPY to determine the overall market condition.

        The result tells the trading bot which *type* of strategy to use:
          - "trending"    → clear directional move  → use momentum strategy
          - "range_bound" → choppy / sideways       → use mean reversion
          - "breakout"    → volatility expanding after a quiet period
                                                    → use breakout strategy

        Logic:
          1. Compare the short-term ATR (5 days) to the longer-term ATR
             (14 days).  If short-term is significantly higher, volatility
             is *expanding* → breakout.
          2. Check if the price has stayed consistently above or below
             VWAP over the last 5 bars → trending.
          3. Otherwise → range_bound.

        Returns:
            One of: "trending", "range_bound", "breakout".
        """
        # Fetch enough bars for a 14-period ATR plus warm-up room.
        bars: pd.DataFrame = self.broker.get_historical_bars(
            "SPY", timeframe="1Day", limit=30
        )

        # --- Step 1: Volatility expansion check ---
        short_atr = self.calculate_atr(bars, period=5)
        long_atr = self.calculate_atr(bars, period=14)

        # If the recent (5-day) ATR is more than 1.5× the 14-day ATR,
        # volatility is expanding – that signals a potential breakout.
        if long_atr > 0 and (short_atr / long_atr) > 1.5:
            return "breakout"

        # --- Step 2: Trend check via VWAP ---
        # VWAP = total dollar volume / total share volume.
        # If the close has been above VWAP for the last 5 bars, the market
        # is trending up.  If below for all 5, trending down.  Either way
        # we call it "trending".
        recent_bars = bars.tail(5)
        vwap_values = self._calculate_vwap(recent_bars)

        if vwap_values is not None and len(vwap_values) == len(recent_bars):
            closes = recent_bars["close"].values
            above_vwap = all(
                closes[i] > vwap_values[i] for i in range(len(closes))
            )
            below_vwap = all(
                closes[i] < vwap_values[i] for i in range(len(closes))
            )

            if above_vwap or below_vwap:
                return "trending"

        # --- Step 3: Default → range-bound ---
        return "range_bound"

    def get_etf_rankings(self) -> list[dict]:
        """Rank sector ETFs by relative strength for an ETF rotation strategy.

        ETF rotation means shifting money into whichever sector is
        currently the strongest.  This method calculates RSI and 5-day
        performance for every sector ETF and returns them sorted from
        strongest to weakest.

        Returns:
            A list of dicts sorted by relative_strength (descending):
                - symbol (str): ETF ticker.
                - relative_strength (float): RSI value.
                - performance_5d (float): 5-day return as a percentage.
        """
        rankings: list[dict] = []

        for symbol in SECTOR_ETFS:
            try:
                bars: pd.DataFrame = self.broker.get_historical_bars(
                    symbol, timeframe="1Day", limit=30
                )

                if bars is None or len(bars) < 15:
                    continue

                rsi = self.calculate_relative_strength(bars, period=14)

                # 5-day performance: (latest close / close 5 days ago - 1)
                # expressed as a percentage.
                close_now = float(bars["close"].iloc[-1])
                close_5d_ago = float(bars["close"].iloc[-5])
                performance_5d = ((close_now / close_5d_ago) - 1) * 100

                rankings.append({
                    "symbol": symbol,
                    "relative_strength": round(rsi, 2),
                    "performance_5d": round(performance_5d, 2),
                })

            except Exception as exc:
                print(f"[Screener] Skipping ETF {symbol}: {exc}")
                continue

        # Strongest sectors first.
        rankings.sort(key=lambda r: r["relative_strength"], reverse=True)

        return rankings

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _calculate_vwap(self, df: pd.DataFrame) -> list[float] | None:
        """Calculate a simple per-bar VWAP for a slice of daily bars.

        VWAP (Volume Weighted Average Price) is the average price where
        most trading volume occurred.  For daily bars we approximate it as:

            VWAP = cumulative(typical_price * volume) / cumulative(volume)

        where typical_price = (high + low + close) / 3.

        Args:
            df: DataFrame with columns: high, low, close, volume.

        Returns:
            A list of cumulative VWAP values (one per row), or None if
            required columns are missing.
        """
        required_columns = {"high", "low", "close", "volume"}
        if not required_columns.issubset(df.columns):
            return None

        # Typical price is a common shorthand for "average price of the bar".
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_tp_volume = (typical_price * df["volume"]).cumsum()
        cumulative_volume = df["volume"].cumsum()

        # Avoid division by zero.
        vwap = cumulative_tp_volume / cumulative_volume.replace(0, float("nan"))

        return vwap.tolist()
