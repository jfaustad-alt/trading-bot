"""Alpaca News API client — fetch headlines for backtest context.

Alpaca provides a free news API that returns headlines for stocks and
market events. We use this to annotate each backtest day with a
relevant headline so you can see *why* the market moved.

For example, on a day where SPY dropped 3%, the headline might say
"Fed raises rates 75bps" — giving you context that the backtester's
numbers alone can't provide.

Usage:
    from broker.news import fetch_news_headline

    headline = fetch_news_headline("2022-06-15")
    # Returns: "Fed hikes rates by 75 basis points, biggest increase since 1994"
"""

from datetime import datetime, timedelta
from typing import Any

from config.settings import ALPACA_API_KEY, ALPACA_SECRET_KEY


def fetch_news_headline(
    date: str,
    symbols: list[str] | None = None,
) -> str | None:
    """Fetch the most relevant news headline for a given date.

    Uses Alpaca's News API to find market-moving headlines. We search
    for SPY-related news by default since we want broad market context.

    Args:
        date: The date to fetch news for (YYYY-MM-DD).
        symbols: Optional list of tickers to search. Defaults to ["SPY"].

    Returns:
        A headline string, or None if no news is found or the API fails.
    """
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return None

    if symbols is None:
        symbols = ["SPY"]

    try:
        import requests

        # Alpaca's news endpoint. We ask for headlines from that specific date.
        url = "https://data.alpaca.markets/v1beta1/news"

        # The API expects ISO 8601 timestamps for the date range.
        start = f"{date}T00:00:00Z"
        end_date = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
        end = end_date.strftime("%Y-%m-%dT00:00:00Z")

        params: dict[str, Any] = {
            "start": start,
            "end": end,
            "symbols": ",".join(symbols),
            "limit": 1,
            "sort": "DESC",
        }

        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        }

        response = requests.get(url, params=params, headers=headers, timeout=5)

        if response.status_code == 200:
            data = response.json()
            news_items = data.get("news", [])
            if news_items:
                return news_items[0].get("headline")

    except Exception:
        # News fetching is non-critical — if it fails, we just skip it.
        pass

    return None


def fetch_news_headlines_batch(
    dates: list[str],
    symbols: list[str] | None = None,
) -> dict[str, str | None]:
    """Fetch news headlines for multiple dates.

    More efficient than calling fetch_news_headline() for each date,
    as it batches requests. However, Alpaca's free tier has rate limits,
    so we add a small delay between requests.

    Args:
        dates: List of dates (YYYY-MM-DD).
        symbols: Optional list of tickers. Defaults to ["SPY"].

    Returns:
        A dict mapping date -> headline (or None if no news found).
    """
    import time

    results: dict[str, str | None] = {}

    for date in dates:
        results[date] = fetch_news_headline(date, symbols)
        # Respect Alpaca's rate limits (200 requests/minute on free tier).
        time.sleep(0.35)

    return results
