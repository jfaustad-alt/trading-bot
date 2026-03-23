"""
ETF Rotation Strategy — invest in the strongest sectors, sell the weakest.

WHAT IS ETF ROTATION?
    Instead of picking individual stocks, this strategy picks entire SECTORS
    of the economy by trading sector ETFs. An ETF (Exchange-Traded Fund) is
    a basket of stocks that tracks a particular group — for example, XLK
    holds all the big tech companies (Apple, Microsoft, etc.).

    The idea: different sectors lead the market at different times. Tech
    might dominate for a year, then energy takes over, then healthcare.
    This strategy tries to always be in the WINNING sectors.

    "Rotation" means we periodically re-evaluate which sectors are strongest
    and shift our money accordingly — rotating out of weak sectors and into
    strong ones.

HOW IT WORKS:
    1. Relative Strength
       - We rank sector ETFs by their recent performance (how much they've
         gone up over the last N days).
       - "Relative strength" means comparing each ETF's performance to the
         others, not to an absolute number.

    2. Buy the Winners
       - We buy the top 3 performing sector ETFs.
       - Concentrating on the top 3 (not top 5 or top 10) gives us focused
         exposure to the strongest trends.

    3. Sell When They Weaken
       - If a held ETF drops out of the top 5, we sell it.
       - We use top 5 (not top 3) as the sell threshold to avoid excessive
         "churning" (buying and selling too frequently). A sector might drop
         from #2 to #4 temporarily — that's normal. But dropping to #6
         means the trend has genuinely weakened.

    4. Risk Management
       - Stop loss: 1.5x ATR below entry.
       - We rebalance periodically (the bot's main loop controls when).

    DEFAULT SECTOR ETFs:
        XLK  = Technology        XLV  = Health Care
        XLF  = Financials        XLY  = Consumer Discretionary
        XLP  = Consumer Staples  XLE  = Energy
        XLI  = Industrials       XLB  = Materials
        XLU  = Utilities         XLRE = Real Estate
        XLC  = Communication Services

Usage:
    from strategies.etf_rotation import ETFRotationStrategy

    strategy = ETFRotationStrategy(broker_client, risk_manager)
    signals = strategy.generate_signals(candidates)
    trades = strategy.execute_signals(signals)
"""

from typing import Any

import pandas as pd
import pandas_ta as ta  # noqa: F401 — enables df.ta.atr()

from strategies.base_strategy import BaseStrategy

# The 11 S&P 500 sector ETFs — these cover the entire US stock market
# broken down by industry sector.
DEFAULT_SECTOR_ETFS: list[str] = [
    "XLK",   # Technology (Apple, Microsoft, Nvidia)
    "XLF",   # Financials (JPMorgan, Berkshire Hathaway)
    "XLV",   # Health Care (UnitedHealth, Johnson & Johnson)
    "XLY",   # Consumer Discretionary (Amazon, Tesla)
    "XLP",   # Consumer Staples (Procter & Gamble, Coca-Cola)
    "XLE",   # Energy (ExxonMobil, Chevron)
    "XLI",   # Industrials (Caterpillar, Union Pacific)
    "XLB",   # Materials (Linde, Sherwin-Williams)
    "XLU",   # Utilities (NextEra Energy, Duke Energy)
    "XLRE",  # Real Estate (Prologis, American Tower)
    "XLC",   # Communication Services (Meta, Google)
]


class ETFRotationStrategy(BaseStrategy):
    """Rotates into the strongest sector ETFs and out of the weakest.

    This strategy ranks sector ETFs by their recent price performance
    (relative strength) and maintains positions in the top performers.
    When a held ETF weakens, it gets replaced by a stronger one.

    Attributes:
        broker_client: The AlpacaClient for placing orders and fetching data.
        risk_manager:  Controls position sizing and trade approval.
        sector_etfs:   List of sector ETF tickers to track.
        top_n_buy:     Number of top ETFs to hold (default 3).
        top_n_hold:    An ETF must stay in the top N to keep holding (default 5).
        lookback_period: Number of days to measure performance (default 60).
        atr_length:    Period for ATR calculation (default 14).
        atr_multiplier: ATR multiplier for stop loss (default 1.5).
    """

    def __init__(
        self,
        broker_client: Any,
        risk_manager: Any,
        sector_etfs: list[str] | None = None,
        top_n_buy: int = 3,
        top_n_hold: int = 5,
        lookback_period: int = 60,
        atr_length: int = 14,
        atr_multiplier: float = 1.5,
    ) -> None:
        """Initialize the ETF Rotation strategy.

        Args:
            broker_client: The AlpacaClient for market data and order placement.
            risk_manager:  The risk manager that approves trades and sizes positions.
            sector_etfs:   List of ETF tickers to track. Defaults to the 11
                           S&P 500 sector ETFs.
            top_n_buy:     How many top-ranked ETFs to buy.
            top_n_hold:    An ETF must stay in the top N to avoid being sold.
                           Using a wider threshold than top_n_buy prevents
                           excessive trading (buying at #3, selling at #4).
            lookback_period: How many days back to measure performance.
            atr_length:    Lookback for ATR (used in stop loss).
            atr_multiplier: How many ATRs for the stop loss distance.
        """
        super().__init__(broker_client, risk_manager)
        self.sector_etfs = sector_etfs if sector_etfs is not None else DEFAULT_SECTOR_ETFS
        self.top_n_buy = top_n_buy
        self.top_n_hold = top_n_hold
        self.lookback_period = lookback_period
        self.atr_length = atr_length
        self.atr_multiplier = atr_multiplier

    def generate_signals(self, candidates: list[dict]) -> list[dict]:
        """Rank sector ETFs and generate buy/sell signals for rotation.

        Steps:
            1. Fetch historical data for all sector ETFs.
            2. Calculate each ETF's return over the lookback period.
            3. Rank ETFs by return (highest = strongest relative strength).
            4. Buy top N ETFs that we don't already hold.
            5. Sell held ETFs that have fallen out of the top hold threshold.

        Note: The candidates parameter is accepted for interface consistency
        with BaseStrategy but is not used. This strategy always evaluates
        its own fixed list of sector ETFs.

        Args:
            candidates: Accepted for API compatibility but not used.
                        The strategy evaluates self.sector_etfs instead.

        Returns:
            A list of signal dicts with: symbol, action, entry_price,
            stop_loss, take_profit, confidence.
        """
        # Step 1: Calculate relative strength (performance) for each ETF.
        rankings = _rank_etfs_by_performance(
            broker_client=self.broker_client,
            etf_symbols=self.sector_etfs,
            lookback_period=self.lookback_period,
            atr_length=self.atr_length,
        )

        # If we couldn't rank enough ETFs, skip this cycle.
        if len(rankings) < self.top_n_buy:
            return []

        # Step 2: Figure out what we currently hold.
        held_symbols = _get_held_symbols(self.broker_client, self.sector_etfs)

        # Step 3: Determine which ETFs are in the top tiers.
        top_buy_symbols = {r["symbol"] for r in rankings[:self.top_n_buy]}
        top_hold_symbols = {r["symbol"] for r in rankings[:self.top_n_hold]}

        signals: list[dict] = []

        # Step 4: Generate SELL signals for held ETFs that dropped out of top N.
        for rank_info in rankings:
            symbol = rank_info["symbol"]

            if symbol in held_symbols and symbol not in top_hold_symbols:
                # This ETF was in our portfolio but has weakened — sell it.
                signals.append({
                    "symbol": symbol,
                    "action": "sell",
                    "entry_price": rank_info["close"],
                    # For a sell, stop loss is above entry (protects against
                    # price rising after we decide to sell).
                    "stop_loss": rank_info["close"] + (rank_info["atr"] * self.atr_multiplier),
                    # Take profit doesn't really apply to a rotation sell,
                    # but we set it to close price (immediate execution).
                    "take_profit": rank_info["close"],
                    "confidence": 0.7,
                })

        # Step 5: Generate BUY signals for top ETFs we don't already hold.
        for rank_info in rankings[:self.top_n_buy]:
            symbol = rank_info["symbol"]

            if symbol not in held_symbols:
                # This is a top performer and we don't own it yet — buy it.
                # Confidence is based on rank (top 1 = most confident).
                rank_position = rankings.index(rank_info)
                confidence = round(0.9 - (rank_position * 0.1), 2)

                signals.append({
                    "symbol": symbol,
                    "action": "buy",
                    "entry_price": rank_info["close"],
                    "stop_loss": rank_info["close"] - (rank_info["atr"] * self.atr_multiplier),
                    # Take profit: we hold until the ETF drops out of the
                    # top hold threshold. We set a nominal target here, but
                    # the real exit is the rotation sell signal above.
                    "take_profit": rank_info["close"] * 1.10,  # 10% target as placeholder
                    "confidence": confidence,
                })

        return signals


def _rank_etfs_by_performance(
    broker_client: Any,
    etf_symbols: list[str],
    lookback_period: int,
    atr_length: int,
) -> list[dict]:
    """Fetch data and rank ETFs by their recent price performance.

    "Performance" here means total return over the lookback period:
        return = (current_price - price_N_days_ago) / price_N_days_ago

    Args:
        broker_client: The AlpacaClient for fetching historical bars.
        etf_symbols: List of ETF tickers to evaluate.
        lookback_period: Number of bars to measure performance over.
        atr_length: Period for ATR calculation.

    Returns:
        A list of dicts sorted by performance (best first). Each dict:
            - symbol (str): The ETF ticker.
            - performance (float): Return over the lookback period (e.g. 0.15 = 15%).
            - close (float): Current closing price.
            - atr (float): Current ATR value.
    """
    rankings: list[dict] = []

    for symbol in etf_symbols:
        result = _calculate_etf_performance(
            broker_client=broker_client,
            symbol=symbol,
            lookback_period=lookback_period,
            atr_length=atr_length,
        )
        if result is not None:
            rankings.append(result)

    # Sort by performance, highest first. The ETF with the best return
    # over the lookback period gets rank #1.
    rankings.sort(key=lambda r: r["performance"], reverse=True)

    return rankings


def _calculate_etf_performance(
    broker_client: Any,
    symbol: str,
    lookback_period: int,
    atr_length: int,
) -> dict | None:
    """Calculate one ETF's performance and ATR.

    Performance = (current_close - close_N_bars_ago) / close_N_bars_ago.
    This tells us the percentage return over the lookback period.

    Args:
        broker_client: The AlpacaClient for fetching data.
        symbol: The ETF ticker (e.g. "XLK").
        lookback_period: Number of bars to look back.
        atr_length: Period for ATR.

    Returns:
        A dict with symbol, performance, close, and atr — or None if we
        can't get enough data.
    """
    # Fetch enough bars to cover the lookback period.
    df = broker_client.get_historical_bars(symbol, limit=lookback_period + 10)

    if len(df) < lookback_period:
        return None

    # Current (most recent) closing price.
    current_close = df["close"].iloc[-1]

    # Price at the start of the lookback period.
    past_close = df["close"].iloc[-lookback_period]

    # Calculate return as a decimal (0.15 = 15% return).
    if past_close == 0:
        return None
    performance = (current_close - past_close) / past_close

    # Calculate ATR.
    atr = df.ta.atr(length=atr_length)
    if atr is None or atr.empty:
        return None

    current_atr = atr.iloc[-1]
    if pd.isna(current_atr):
        return None

    return {
        "symbol": symbol,
        "performance": float(performance),
        "close": float(current_close),
        "atr": float(current_atr),
    }


def _get_held_symbols(broker_client: Any, etf_symbols: list[str]) -> set[str]:
    """Get the set of sector ETF symbols currently held in the portfolio.

    We only care about positions that are in our sector ETF list — the
    portfolio might hold other stocks from other strategies.

    Args:
        broker_client: The AlpacaClient for fetching current positions.
        etf_symbols: The list of ETF tickers this strategy manages.

    Returns:
        A set of ticker strings for ETFs we currently own.
    """
    # Get all open positions from the broker.
    positions = broker_client.get_open_positions()

    # Filter to only include positions that are in our sector ETF list.
    etf_set = set(etf_symbols)
    held = {pos["symbol"] for pos in positions if pos["symbol"] in etf_set}

    return held
