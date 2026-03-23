"""Yahoo Finance data provider — free historical stock data.

This module fetches historical price data from Yahoo Finance. It's used
for backtesting on markets that Alpaca doesn't cover, like Oslo Børs
(Euronext Oslo). Yahoo Finance is free and doesn't require an API key.

HOW IT WORKS:
    We use the `yfinance` library, which scrapes Yahoo Finance's public
    API. For each stock, we get daily OHLCV bars (Open, High, Low, Close,
    Volume) and return them as a pandas DataFrame — the same format the
    rest of the bot expects.

    Yahoo Finance ticker format for Oslo Børs:
        Equinor = "EQNR.OL"  (the ".OL" suffix means Oslo)
        DNB     = "DNB.OL"
        Mowi    = "MOWI.OL"

LIMITATIONS:
    - Data is delayed (not real-time) — fine for backtesting, not for
      live trading.
    - Yahoo occasionally changes their API, which can break yfinance.
      If downloads fail, try updating: pip install --upgrade yfinance
    - Rate limiting: too many requests too fast will get you blocked.
      We add small delays between downloads to be polite.

Usage:
    from broker.yahoo_data import YahooDataProvider

    provider = YahooDataProvider()
    bars = provider.fetch_historical_bars("EQNR.OL", "2024-01-01", "2024-06-30")
    print(bars.head())
"""

import time as time_module

import pandas as pd
import yfinance as yf


class YahooDataProvider:
    """Fetches historical stock data from Yahoo Finance.

    This is a simple wrapper that downloads OHLCV bars and normalises
    them into the same format that the rest of the trading bot uses
    (matching the column names and index format from Alpaca's API).

    Attributes:
        _cache: A dictionary that stores previously downloaded data
            so we don't re-download the same stock twice in one session.
    """

    def __init__(self) -> None:
        """Initialise the data provider with an empty cache."""
        # Cache downloaded data to avoid re-fetching the same stock.
        # Key = "SYMBOL_start_end", value = DataFrame.
        self._cache: dict[str, pd.DataFrame] = {}

    def fetch_historical_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame | None:
        """Download daily OHLCV bars for a single stock.

        Args:
            symbol: The Yahoo Finance ticker (e.g. "EQNR.OL" for
                Equinor on Oslo Børs, or "AAPL" for Apple on NASDAQ).
            start_date: First date to fetch, "YYYY-MM-DD".
            end_date: Last date to fetch, "YYYY-MM-DD".

        Returns:
            A pandas DataFrame with columns: open, high, low, close,
            volume. Indexed by timezone-aware UTC timestamps. Returns
            None if the download fails or no data is available.
        """
        # Check the cache first.
        cache_key = f"{symbol}_{start_date}_{end_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # yfinance.download() fetches data from Yahoo Finance.
            # auto_adjust=True gives us adjusted prices (accounting for
            # stock splits and dividends), which is what we want for
            # backtesting — it prevents false signals from splits.
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date)

            if df is None or df.empty:
                return None

            # Normalise column names to lowercase to match Alpaca's format.
            # Yahoo returns "Open", "High", etc. — we need "open", "high".
            df.columns = [col.lower() for col in df.columns]

            # Keep only the columns we need (Yahoo also returns
            # "dividends" and "stock splits" which we don't use).
            required_cols = ["open", "high", "low", "close", "volume"]
            available = [c for c in required_cols if c in df.columns]
            df = df[available]

            # Make the index timezone-aware (UTC) to match Alpaca's format.
            # Yahoo returns timezone-aware dates in the exchange's local
            # timezone; we convert to UTC for consistency.
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")

            # Cache the result.
            self._cache[cache_key] = df

            return df

        except Exception:
            return None

    def fetch_multiple(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        delay: float = 0.3,
    ) -> dict[str, pd.DataFrame]:
        """Download data for multiple stocks with rate-limit protection.

        Downloads each stock one at a time with a small delay between
        requests to avoid getting blocked by Yahoo Finance.

        Args:
            symbols: List of Yahoo Finance tickers to download.
            start_date: First date to fetch, "YYYY-MM-DD".
            end_date: Last date to fetch, "YYYY-MM-DD".
            delay: Seconds to wait between downloads (default 0.3s).

        Returns:
            A dictionary mapping symbol -> DataFrame. Symbols that
            failed to download are silently skipped (not in the dict).
        """
        data: dict[str, pd.DataFrame] = {}

        for i, symbol in enumerate(symbols):
            df = self.fetch_historical_bars(symbol, start_date, end_date)
            if df is not None and not df.empty:
                data[symbol] = df

            # Rate limit: pause between downloads (skip after the last one).
            if i < len(symbols) - 1:
                time_module.sleep(delay)

        return data
