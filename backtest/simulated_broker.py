"""
Simulated broker — a fake broker that replays historical data.

WHY DO WE NEED THIS?
    The real AlpacaClient connects to a live market. But for backtesting,
    we want to "rewind time" and see what would have happened last week
    or last year. This simulated broker pretends to be the real broker:
    it has the same methods (get_historical_bars, get_latest_price, etc.)
    but instead of hitting the API, it looks up pre-downloaded data.

    The strategies don't know the difference — they call the same methods
    and get the same data format. This is why we built the bot with a
    clean separation between the broker and the strategies.

HOW IT WORKS:
    1. Before the simulation starts, we download ALL the historical data
       we need from Alpaca (using the real broker).
    2. We store that data indexed by symbol and date.
    3. During the simulation, the backtester advances day by day. On each
       day, the simulated broker only returns data up to that date — as
       if that day were "today." This prevents "lookahead bias" (using
       future data to make past decisions, which would be cheating).
    4. When a strategy places a "buy" or "sell" order, we don't actually
       send it to Alpaca. Instead, we record it in a simulated portfolio
       and track the P&L ourselves.

Usage:
    from backtest.simulated_broker import SimulatedBroker

    sim_broker = SimulatedBroker(starting_capital=100000)
    sim_broker.load_data(real_broker, symbols, start_date, end_date)
    sim_broker.set_current_date("2025-03-15")
    price = sim_broker.get_latest_price("AAPL")
"""

from datetime import datetime
from typing import Any

import pandas as pd


class SimulatedBroker:
    """A fake broker that replays historical data for backtesting.

    This class mimics the AlpacaClient interface but works with
    pre-loaded historical data instead of live market data. It tracks
    a simulated portfolio with fake money.

    Attributes:
        starting_capital: The initial cash amount.
        cash: Current cash balance.
        positions: Dict mapping symbol -> {qty, avg_entry_price}.
        trade_history: List of all trades executed during the simulation.
        current_date: The date the simulation is currently on.
        data: Dict mapping symbol -> DataFrame of historical bars.
    """

    def __init__(self, starting_capital: float = 100_000.0) -> None:
        """Initialize the simulated broker with a starting cash balance.

        Args:
            starting_capital: How much fake money to start with.
        """
        self.starting_capital = starting_capital
        self.cash = starting_capital

        # Positions: {symbol: {"qty": int, "avg_entry_price": float}}
        self.positions: dict[str, dict[str, Any]] = {}

        # Every trade gets recorded here for later analysis.
        self.trade_history: list[dict] = []

        # The simulated "current date" — strategies only see data up to this.
        self.current_date: datetime | None = None

        # Historical data: {symbol: DataFrame with OHLCV bars}
        self.data: dict[str, pd.DataFrame] = {}

    def load_data(
        self,
        real_broker,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> None:
        """Download historical data from Alpaca for all symbols.

        This is called once before the simulation starts. We fetch all the
        data upfront so the backtest runs fast (no API calls during the sim).

        Args:
            real_broker: A real AlpacaClient to download data from.
            symbols: List of ticker symbols to download.
            start_date: Start date as "YYYY-MM-DD".
            end_date: End date as "YYYY-MM-DD".
        """
        import alpaca_trade_api as tradeapi
        from datetime import timedelta

        # We need extra historical data BEFORE the start date for indicator
        # warm-up. For example, a 20-period Bollinger Band needs 20 prior
        # bars to produce its first value. We fetch 100 extra days.
        warmup_start = (
            datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=150)
        ).strftime("%Y-%m-%d")

        print(f"Downloading data for {len(symbols)} symbols...")
        print(f"  Date range: {warmup_start} to {end_date} (includes warm-up)")

        for symbol in symbols:
            try:
                bars = real_broker.api.get_bars(
                    symbol,
                    tradeapi.TimeFrame.Day,
                    start=warmup_start,
                    end=end_date,
                    feed="iex",
                ).df

                if not bars.empty:
                    self.data[symbol] = bars
                    print(f"  {symbol}: {len(bars)} bars loaded")
                else:
                    print(f"  {symbol}: no data available")

            except Exception as e:
                print(f"  {symbol}: failed ({e})")

        print(f"Data loaded for {len(self.data)} symbols.")

    def load_yahoo_data(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> None:
        """Download historical data from Yahoo Finance for backtesting.

        This is the alternative to load_data() for markets that Alpaca
        doesn't cover, like Oslo Børs. Yahoo Finance is free and doesn't
        need an API key.

        The data format is normalised to match Alpaca's output, so the
        rest of the bot (strategies, indicators, etc.) works unchanged.

        Args:
            symbols: List of Yahoo Finance tickers (e.g. ["EQNR.OL"]).
            start_date: Backtest start date as "YYYY-MM-DD".
            end_date: Backtest end date as "YYYY-MM-DD".
        """
        from datetime import timedelta

        from broker.yahoo_data import YahooDataProvider

        # Extra days before the start date for indicator warm-up
        # (e.g. a 20-period moving average needs 20 prior bars).
        warmup_start = (
            datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=150)
        ).strftime("%Y-%m-%d")

        print(f"Downloading Yahoo data for {len(symbols)} symbols...")
        print(f"  Date range: {warmup_start} to {end_date} (includes warm-up)")

        provider = YahooDataProvider()
        data = provider.fetch_multiple(symbols, warmup_start, end_date)

        for symbol, df in data.items():
            self.data[symbol] = df
            print(f"  {symbol}: {len(df)} bars loaded")

        failed = len(symbols) - len(data)
        if failed > 0:
            print(f"  ({failed} symbols had no data)")

        print(f"Data loaded for {len(self.data)} symbols.")

    def set_current_date(self, date: datetime) -> None:
        """Advance the simulation to a specific date.

        After calling this, all data methods will only return data up to
        (and including) this date — preventing lookahead bias.

        Args:
            date: The date to set as "today" in the simulation.
        """
        self.current_date = date

    # ------------------------------------------------------------------
    # Methods that match AlpacaClient's interface
    # ------------------------------------------------------------------

    def get_account_info(self) -> dict[str, Any]:
        """Get simulated account info (equity, cash, positions value).

        Returns:
            A dictionary matching the AlpacaClient format.
        """
        # Calculate total value of all positions.
        positions_value = 0.0
        for symbol, pos in self.positions.items():
            current_price = self.get_latest_price(symbol)
            positions_value += current_price * pos["qty"]

        equity = self.cash + positions_value

        return {
            "buying_power": self.cash,
            "equity": equity,
            "cash": self.cash,
            "portfolio_value": equity,
            "currency": "USD",
        }

    def get_latest_price(self, symbol: str) -> float:
        """Get the closing price on the current simulation date.

        Args:
            symbol: The stock ticker.

        Returns:
            The closing price on the current date.

        Raises:
            ValueError: If no data is available for this symbol/date.
        """
        bars = self._get_bars_up_to_current_date(symbol)

        if bars.empty:
            raise ValueError(
                f"No data for {symbol} on or before {self.current_date}"
            )

        return float(bars["close"].iloc[-1])

    def get_latest_bar(self, symbol: str) -> dict[str, Any]:
        """Get the most recent bar on the current simulation date.

        Args:
            symbol: The stock ticker.

        Returns:
            A dict with open, high, low, close, volume, timestamp.
        """
        bars = self._get_bars_up_to_current_date(symbol)

        if bars.empty:
            raise ValueError(f"No data for {symbol}")

        last = bars.iloc[-1]
        return {
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
            "volume": int(last["volume"]),
            "timestamp": bars.index[-1],
        }

    def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 100,
    ) -> pd.DataFrame:
        """Get historical bars up to the current simulation date.

        Only returns data up to (and including) self.current_date, so
        strategies can't accidentally peek into the future.

        Args:
            symbol: The stock ticker.
            timeframe: Ignored (we only have daily data for backtesting).
            limit: Maximum number of bars to return.

        Returns:
            A DataFrame with OHLCV data.
        """
        bars = self._get_bars_up_to_current_date(symbol)

        # Return only the last 'limit' bars (same as the real broker).
        if len(bars) > limit:
            bars = bars.iloc[-limit:]

        return bars

    def place_market_buy(self, symbol: str, qty: int) -> dict[str, Any]:
        """Simulate buying shares at the current price.

        Instead of sending an order to Alpaca, we:
        1. Look up the current price.
        2. Check if we have enough cash.
        3. Deduct the cost from our cash balance.
        4. Add the shares to our position tracker.

        Args:
            symbol: The stock ticker to buy.
            qty: Number of shares to buy.

        Returns:
            A dict describing the simulated order.
        """
        price = self.get_latest_price(symbol)
        cost = price * qty

        if cost > self.cash:
            return {
                "id": "sim-rejected",
                "symbol": symbol,
                "qty": str(qty),
                "side": "buy",
                "type": "market",
                "status": "rejected",
                "reason": f"Insufficient cash (${self.cash:.2f} < ${cost:.2f})",
            }

        # Deduct cost from cash.
        self.cash -= cost

        # Update or create position.
        if symbol in self.positions:
            # Average up: recalculate the average entry price.
            existing = self.positions[symbol]
            total_qty = existing["qty"] + qty
            total_cost = (existing["avg_entry_price"] * existing["qty"]) + cost
            existing["avg_entry_price"] = total_cost / total_qty
            existing["qty"] = total_qty
        else:
            self.positions[symbol] = {
                "qty": qty,
                "avg_entry_price": price,
            }

        # Record the trade.
        trade_record = {
            "date": str(self.current_date),
            "symbol": symbol,
            "action": "buy",
            "qty": qty,
            "price": price,
            "cost": cost,
        }
        self.trade_history.append(trade_record)

        return {
            "id": f"sim-{len(self.trade_history)}",
            "symbol": symbol,
            "qty": str(qty),
            "side": "buy",
            "type": "market",
            "status": "filled",
        }

    def place_market_sell(self, symbol: str, qty: int) -> dict[str, Any]:
        """Simulate selling shares at the current price.

        Args:
            symbol: The stock ticker to sell.
            qty: Number of shares to sell.

        Returns:
            A dict describing the simulated order.
        """
        if symbol not in self.positions or self.positions[symbol]["qty"] < qty:
            return {
                "id": "sim-rejected",
                "symbol": symbol,
                "qty": str(qty),
                "side": "sell",
                "type": "market",
                "status": "rejected",
                "reason": f"Not enough shares of {symbol} to sell",
            }

        price = self.get_latest_price(symbol)
        revenue = price * qty

        # Calculate P&L for this trade.
        entry_price = self.positions[symbol]["avg_entry_price"]
        pnl = (price - entry_price) * qty

        # Add revenue to cash.
        self.cash += revenue

        # Update position.
        self.positions[symbol]["qty"] -= qty
        if self.positions[symbol]["qty"] == 0:
            del self.positions[symbol]

        # Record the trade.
        trade_record = {
            "date": str(self.current_date),
            "symbol": symbol,
            "action": "sell",
            "qty": qty,
            "price": price,
            "revenue": revenue,
            "pnl": pnl,
        }
        self.trade_history.append(trade_record)

        return {
            "id": f"sim-{len(self.trade_history)}",
            "symbol": symbol,
            "qty": str(qty),
            "side": "sell",
            "type": "market",
            "status": "filled",
        }

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Get all currently held simulated positions.

        Returns:
            A list of position dicts matching the AlpacaClient format.
        """
        result = []

        for symbol, pos in self.positions.items():
            try:
                current_price = self.get_latest_price(symbol)
            except ValueError:
                continue

            market_value = current_price * pos["qty"]
            unrealized_pl = (current_price - pos["avg_entry_price"]) * pos["qty"]
            unrealized_plpc = (
                (current_price - pos["avg_entry_price"]) / pos["avg_entry_price"]
                if pos["avg_entry_price"] > 0
                else 0.0
            )

            result.append({
                "symbol": symbol,
                "qty": pos["qty"],
                "avg_entry_price": pos["avg_entry_price"],
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pl": unrealized_pl,
                "unrealized_plpc": unrealized_plpc,
            })

        return result

    def close_position(self, symbol: str) -> dict[str, Any]:
        """Close an entire simulated position.

        Args:
            symbol: The stock ticker to close.

        Returns:
            A dict describing the closing order.
        """
        if symbol not in self.positions:
            return {"symbol": symbol, "status": "no_position"}

        qty = self.positions[symbol]["qty"]
        return self.place_market_sell(symbol, qty)

    def close_all_positions(self) -> list[dict[str, Any]]:
        """Close all simulated positions (panic button).

        Returns:
            A list of closing order dicts.
        """
        results = []
        # Copy keys to list since we're modifying the dict during iteration.
        for symbol in list(self.positions.keys()):
            result = self.close_position(symbol)
            results.append(result)
        return results

    def is_market_open(self) -> bool:
        """In backtesting, the market is always 'open' on trading days.

        Returns:
            True (backtesting simulates market-open conditions).
        """
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_bars_up_to_current_date(self, symbol: str) -> pd.DataFrame:
        """Filter stored data to only include bars up to current_date.

        This is the key to preventing lookahead bias. Even though we have
        all the data loaded, we only show the strategy data that it would
        have had access to on the current simulation date.

        Args:
            symbol: The stock ticker.

        Returns:
            A DataFrame with bars up to and including current_date.
        """
        if symbol not in self.data:
            return pd.DataFrame()

        df = self.data[symbol]

        if self.current_date is None:
            return df

        # The index is timezone-aware (UTC), so we need to make our
        # comparison date timezone-aware too.
        import pytz
        current_dt = self.current_date
        if current_dt.tzinfo is None:
            current_dt = pytz.utc.localize(current_dt)

        # Filter: only keep bars on or before the current date.
        return df[df.index <= current_dt]
