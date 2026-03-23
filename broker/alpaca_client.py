"""
Alpaca broker client — our connection to the stock market.

This module wraps the Alpaca API so the rest of the bot can buy/sell stocks
without worrying about the raw API details. Think of it as a translator:
our bot speaks Python, and this module converts that into Alpaca API calls.

We use Alpaca's *paper trading* environment, which is a simulated market.
Real prices, fake money — perfect for testing strategies without risk.

Usage:
    from broker.alpaca_client import AlpacaClient

    client = AlpacaClient()
    print(client.get_account_info())
    client.place_market_buy("AAPL", qty=1)
"""

from datetime import datetime, timedelta
from typing import Any

import alpaca_trade_api as tradeapi
import pandas as pd

from config.settings import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL


class AlpacaClient:
    """Wrapper around the Alpaca trading API for paper trading.

    This class handles all communication with Alpaca. Every trading action
    the bot takes — checking prices, placing orders, closing positions —
    goes through this class.

    Attributes:
        api: The underlying alpaca-trade-api REST client that makes
             the actual HTTP requests to Alpaca's servers.
    """

    def __init__(self) -> None:
        """Initialize the Alpaca API connection.

        Reads credentials from config/settings.py (which loads them from
        the .env file). The api_version='v2' tells Alpaca which version
        of their API we want to use — v2 is the current stable version.
        """
        self.api = tradeapi.REST(
            key_id=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            base_url=ALPACA_BASE_URL,
            # v2 is the latest stable API version from Alpaca
            api_version="v2",
        )

    # ------------------------------------------------------------------
    # Account information
    # ------------------------------------------------------------------

    def get_account_info(self) -> dict[str, Any]:
        """Fetch the current account details from Alpaca.

        Returns key financial metrics so the bot (and you) can see
        how the portfolio is doing at a glance.

        Returns:
            A dictionary with these keys:
                - buying_power: How much cash is available to buy stocks.
                - equity: Total account value (cash + value of all holdings).
                - cash: Cash balance (not tied up in positions).
                - portfolio_value: Same as equity — total portfolio worth.
                - currency: The account currency (usually 'USD').
        """
        # The Alpaca API returns an Account object; we pull out the
        # fields we care about and return a plain dict for simplicity.
        account = self.api.get_account()

        return {
            "buying_power": float(account.buying_power),
            "equity": float(account.equity),
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "currency": account.currency,
        }

    # ------------------------------------------------------------------
    # Market data — current prices and historical bars
    # ------------------------------------------------------------------

    def get_latest_price(self, symbol: str) -> float:
        """Get the most recent trade price for a stock.

        Args:
            symbol: The stock ticker, e.g. "AAPL" for Apple.

        Returns:
            The latest trade price as a float, e.g. 187.42.
        """
        # A "trade" is an actual executed transaction on the exchange.
        # The latest trade price is the closest thing to a "current price".
        # We use feed="iex" because free Alpaca accounts can't access SIP data.
        trade = self.api.get_latest_trade(symbol, feed="iex")
        return float(trade.price)

    def get_latest_bar(self, symbol: str) -> dict[str, Any]:
        """Get the most recent price bar (OHLCV) for a stock.

        A "bar" (also called a "candlestick") summarises price action
        over a time period. OHLCV stands for:
            O = Open   — price at the start of the period
            H = High   — highest price during the period
            L = Low    — lowest price during the period
            C = Close  — price at the end of the period
            V = Volume — number of shares traded

        Args:
            symbol: The stock ticker, e.g. "AAPL".

        Returns:
            A dictionary with keys: open, high, low, close, volume, timestamp.
        """
        bar = self.api.get_latest_bar(symbol, feed="iex")

        return {
            "open": float(bar.o),
            "high": float(bar.h),
            "low": float(bar.l),
            "close": float(bar.c),
            "volume": int(bar.v),
            "timestamp": bar.t,
        }

    def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 100,
    ) -> pd.DataFrame:
        """Fetch historical price bars for calculating indicators.

        The bot's strategies need past price data to compute things like
        moving averages and ATR (Average True Range). This method fetches
        that history and returns it as a pandas DataFrame — a table-like
        structure that's easy to do math on.

        Args:
            symbol: The stock ticker, e.g. "AAPL".
            timeframe: The bar size. Common values:
                       "1Min"  — one bar per minute  (intraday)
                       "5Min"  — one bar per 5 minutes
                       "1Hour" — one bar per hour
                       "1Day"  — one bar per trading day (default)
            limit: How many bars to fetch. Default is 100, which gives
                   roughly 5 months of daily data (there are ~21 trading
                   days per month).

        Returns:
            A pandas DataFrame with columns:
                open, high, low, close, volume, trade_count, vwap
            indexed by timestamp. Each row is one bar.
        """
        # TimeFrame objects tell Alpaca how big each bar should be.
        # We map the user-friendly string to the library's TimeFrame.
        timeframe_map = {
            "1Min": tradeapi.TimeFrame.Minute,
            "5Min": tradeapi.TimeFrame(5, tradeapi.TimeFrameUnit.Minute),
            "15Min": tradeapi.TimeFrame(15, tradeapi.TimeFrameUnit.Minute),
            "1Hour": tradeapi.TimeFrame.Hour,
            "1Day": tradeapi.TimeFrame.Day,
        }

        tf = timeframe_map.get(timeframe, tradeapi.TimeFrame.Day)

        # Calculate a start date based on the limit and timeframe.
        # We add extra buffer days to account for weekends/holidays
        # when the market is closed (no bars generated on those days).
        days_needed = limit * 2  # 2x buffer for weekends/holidays
        if timeframe in ("1Min", "5Min", "15Min"):
            days_needed = limit // 50 + 5  # intraday: ~390 min bars per day
        elif timeframe == "1Hour":
            days_needed = limit // 7 + 5   # ~6.5 trading hours per day

        end = datetime.now()
        start = end - timedelta(days=days_needed)

        # We use feed="iex" because free Alpaca accounts don't have access
        # to SIP (the premium consolidated feed). IEX data is free and good
        # enough for paper trading. SIP requires a paid subscription.
        bars = self.api.get_bars(
            symbol,
            tf,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            feed="iex",
        ).df

        return bars

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def place_market_buy(self, symbol: str, qty: int) -> dict[str, Any]:
        """Place a market buy order (buy shares at the current price).

        A "market order" means: buy immediately at whatever the current
        market price is. It's the simplest order type — you're guaranteed
        to get filled, but the exact price may vary slightly.

        Args:
            symbol: The stock ticker to buy, e.g. "AAPL".
            qty: Number of shares to buy. Must be a positive integer.

        Returns:
            A dictionary describing the submitted order, including:
                - id: Alpaca's unique order ID (useful for tracking).
                - symbol: The ticker.
                - qty: Number of shares.
                - side: "buy".
                - type: "market".
                - status: Order status (usually "accepted" initially).
        """
        order = self.api.submit_order(
            symbol=symbol,
            qty=qty,
            side="buy",
            type="market",
            # "gtc" = Good Till Cancelled — the order stays active until
            # it fills or we cancel it. For market orders this doesn't
            # matter much since they fill almost instantly.
            time_in_force="gtc",
        )

        return _order_to_dict(order)

    def place_market_sell(self, symbol: str, qty: int) -> dict[str, Any]:
        """Place a market sell order (sell shares at the current price).

        This sells shares you already own. If you try to sell more shares
        than you hold, Alpaca will reject the order (paper trading doesn't
        allow short selling by default).

        Args:
            symbol: The stock ticker to sell, e.g. "AAPL".
            qty: Number of shares to sell. Must be a positive integer.

        Returns:
            A dictionary describing the submitted order (same shape as
            place_market_buy).
        """
        order = self.api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="market",
            time_in_force="gtc",
        )

        return _order_to_dict(order)

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Get all currently open positions (stocks you own).

        A "position" means you hold shares of a stock. This method lists
        every stock the bot currently owns, along with how many shares,
        the average buy price, and the current profit/loss.

        Returns:
            A list of dictionaries, one per position. Each dict contains:
                - symbol: The stock ticker.
                - qty: Number of shares held.
                - avg_entry_price: Average price paid per share.
                - current_price: The stock's current price.
                - market_value: Total current value of this position.
                - unrealized_pl: Profit/loss if you sold right now
                                 (negative means a loss).
                - unrealized_plpc: Same as above but as a percentage.
        """
        positions = self.api.list_positions()

        return [
            {
                "symbol": pos.symbol,
                "qty": int(pos.qty),
                "avg_entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "market_value": float(pos.market_value),
                "unrealized_pl": float(pos.unrealized_pl),
                "unrealized_plpc": float(pos.unrealized_plpc),
            }
            for pos in positions
        ]

    def close_position(self, symbol: str) -> dict[str, Any]:
        """Close (sell) an entire position in a single stock.

        This sells ALL shares of the given symbol. Alpaca handles the
        order creation behind the scenes — you don't need to know how
        many shares you hold; it sells everything.

        Args:
            symbol: The stock ticker to close, e.g. "AAPL".

        Returns:
            A dictionary describing the closing order.
        """
        order = self.api.close_position(symbol)
        return _order_to_dict(order)

    def close_all_positions(self) -> list[dict[str, Any]]:
        """Close ALL open positions immediately — the panic button.

        Use this when something goes wrong or the bot needs to shut down.
        It sells every stock the bot owns in one call. Alpaca creates a
        separate market sell order for each position.

        Returns:
            A list of dictionaries, one per closing order. Each dict has
            the same shape as the return from place_market_sell.
            Returns an empty list if there are no open positions.
        """
        # close_all_positions returns a list of order responses.
        # Each element is a dict-like object with 'status' and 'body'.
        responses = self.api.close_all_positions()

        results: list[dict[str, Any]] = []
        for response in responses:
            # Each response has a 'body' attribute containing the order.
            # We extract the useful fields for consistency.
            body = response.get("body", response) if isinstance(response, dict) else response
            results.append({
                "symbol": getattr(body, "symbol", str(body)),
                "status": getattr(body, "status", "submitted"),
            })

        return results

    # ------------------------------------------------------------------
    # Market status
    # ------------------------------------------------------------------

    def is_market_open(self) -> bool:
        """Check whether the US stock market is currently open for trading.

        The market is open weekdays 9:30 AM – 4:00 PM Eastern Time,
        excluding holidays. The bot should only place trades when the
        market is open — orders submitted while closed will queue until
        the next open, which can lead to unexpected fills.

        Returns:
            True if the market is open right now, False otherwise.
        """
        clock = self.api.get_clock()
        return clock.is_open


# ----------------------------------------------------------------------
# Helper functions (module-level, not part of the class)
# ----------------------------------------------------------------------

def _order_to_dict(order: Any) -> dict[str, Any]:
    """Convert an Alpaca Order object into a plain dictionary.

    We use a helper function to avoid repeating the same conversion
    logic in every method that returns order data.

    Args:
        order: An Alpaca Order object returned by the API.

    Returns:
        A dictionary with the most useful order fields.
    """
    return {
        "id": order.id,
        "symbol": order.symbol,
        "qty": order.qty,
        "side": order.side,
        "type": order.type,
        "status": order.status,
    }
