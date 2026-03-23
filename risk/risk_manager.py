"""
Risk management module for the trading bot.

This module is the "safety net" of the bot. Before any trade is placed,
the risk manager checks whether the trade is allowed and how large it
should be. It enforces daily profit targets and loss limits so the bot
doesn't overtrade or blow up the account.

Key concepts:
    - Position sizing: deciding HOW MANY shares to buy per trade.
    - Stop loss: a price level where we exit a losing trade to cap our loss.
    - ATR (Average True Range): a measure of how much a stock's price
      typically moves in a day. We use it to set stop losses at a
      distance that accounts for normal price fluctuations.
    - P&L (Profit and Loss): how much money a trade or trading day made
      or lost.
    - ELO rating: A chess-inspired rating system that tracks the bot's
      performance over time. The rating determines BOTH the daily target
      AND the risk parameters (position size, max positions, loss limit,
      stop-loss width). See risk/elo_rating.py for full details.

Risk parameters that change with rank:
    Bronze  → 0.5% risk/trade, 3 positions, $50 loss limit, tight stops
    Silver  → 0.75%, 5 positions, $75 limit
    Gold    → 1%, 8 positions, $100 limit (starting tier)
    Platinum→ 1.25%, 10 positions, $150 limit
    Diamond → 1.5%, 12 positions, $200 limit
    Master  → 1.75%, 14 positions, $250 limit
    GM      → 2%, 16 positions, $300 limit, wide stops

The bot must prove itself at each level before it earns more freedom.
If it starts losing, the rank drops and risk is automatically reduced.
"""

import logging
import math

from config.settings import (
    STOP_LOSS_ATR_MULTIPLIERS,
    TARGET_INCREASE_AMOUNT,
    TARGET_INCREASE_STREAK,
)
from risk.elo_rating import EloRating

# Logger for this module — used to output ELO rating updates at end of day.
logger = logging.getLogger(__name__)


class RiskManager:
    """Manages all risk controls for the trading bot.

    This class tracks daily profit/loss, enforces trading limits, and
    calculates safe position sizes. All risk parameters are driven by
    the ELO rank — as the bot proves itself, it earns bigger position
    sizes and more open positions. If it starts losing, risk is
    automatically reduced.

    Attributes:
        daily_pnl: Running total of profit/loss for the current day.
        daily_wins: Number of profitable trades today.
        daily_losses: Number of losing trades today.
        consecutive_profitable_days: How many days in a row the bot
            has ended the day with a profit.
        trade_count: Number of trades executed today.
        elo: The ELO rating system that tracks performance and drives
            both daily targets AND risk parameters.
    """

    def __init__(self, overrides: dict | None = None) -> None:
        """Initialise the risk manager with default values.

        Args:
            overrides: Optional dict of parameter overrides, used by the
                optimizer to test different risk settings. Supported keys:
                - risk_per_trade_pct (float)
                - max_open_positions (int)
                - daily_loss_limit (float)
                When provided, these override the ELO-derived values.
        """
        # Store overrides for use in properties.
        self._overrides: dict = overrides or {}

        # Daily P&L starts at zero each day
        self.daily_pnl: float = 0.0

        # Track wins and losses separately so we can calculate win rate.
        # Win rate is a key input to the ELO scoring — a bot that wins
        # more than 50% of its trades is making good decisions and should
        # be rewarded, even if the dollar P&L is modest.
        self.daily_wins: int = 0
        self.daily_losses: int = 0

        # Track how many days in a row have been profitable
        self.consecutive_profitable_days: int = 0

        # Count trades today so we can report it in status
        self.trade_count: int = 0

        # ELO rating system — drives BOTH daily targets AND risk parameters.
        # The bot starts at Gold tier (rating 1000).
        self.elo: EloRating = EloRating()

    # -- Risk parameters (all driven by ELO tier) -----------------------

    @property
    def risk_per_trade_pct(self) -> float:
        """Max percentage of portfolio to risk on a single trade.

        If an override is set (from the optimizer), use that.
        Otherwise, scale with ELO rank: Bronze 0.5% → Grandmaster 2%.

        Returns:
            A float like 0.01 (meaning 1%).
        """
        if "risk_per_trade_pct" in self._overrides:
            return self._overrides["risk_per_trade_pct"]
        return self.elo.get_risk_parameters()["risk_pct"]

    @property
    def max_open_positions(self) -> int:
        """Maximum number of positions the bot can hold at once.

        If an override is set (from the optimizer), use that.
        Otherwise, scale with ELO rank.

        Returns:
            An integer like 8 (for Gold tier).
        """
        if "max_open_positions" in self._overrides:
            return self._overrides["max_open_positions"]
        return self.elo.get_risk_parameters()["max_positions"]

    @property
    def daily_loss_limit(self) -> float:
        """The dollar amount of loss that shuts trading down for the day.

        If an override is set (from the optimizer), use that.
        Otherwise, scale with ELO rank.

        Returns:
            A float like 100.0 (meaning $100).
        """
        if "daily_loss_limit" in self._overrides:
            return self._overrides["daily_loss_limit"]
        return self.elo.get_risk_parameters()["loss_limit"]

    @property
    def atr_scale(self) -> float:
        """Scaling factor applied to ATR stop-loss distances.

        Higher-ranked bots get wider stops (atr_scale > 1.0) because
        they've proven they can handle more volatility. Lower-ranked
        bots get tighter stops (atr_scale < 1.0) to cut losses early.

        This multiplies the base ATR multiplier per strategy. For
        example, momentum's base multiplier is 1.5. A Gold bot
        (atr_scale=1.0) uses 1.5. A Diamond bot (atr_scale=1.2) uses
        1.5 * 1.2 = 1.8 — giving the trade more room to breathe.

        Returns:
            A float like 1.0 (Gold) or 1.2 (Diamond).
        """
        return self.elo.get_risk_parameters()["atr_scale"]

    # -- Position sizing ------------------------------------------------

    def calculate_position_size(
        self,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
    ) -> int:
        """Calculate how many shares to buy for a given trade.

        We risk a percentage of the account on each trade, determined by
        the current ELO rank (e.g. Gold = 1%, Diamond = 1.5%). The number
        of shares is determined by how far the stop loss is from the entry.

        Example (Gold tier, 1% risk):
            Account equity = $100,000 => we risk $1,000 per trade.
            Entry price = $50, stop loss = $48 => $2 risk per share.
            Shares = $1,000 / $2 = 500 shares.

        Example (Bronze tier, 0.5% risk):
            Same setup => we risk $500 per trade.
            Shares = $500 / $2 = 250 shares (half the position).

        Args:
            account_equity: Total value of the trading account in dollars.
            entry_price: The price at which we plan to buy the stock.
            stop_loss_price: The price at which we would sell to cut losses.

        Returns:
            The number of shares to buy, rounded down to a whole number.
            Returns 0 if the inputs are invalid (e.g., stop loss is above
            the entry price, which would make no sense for a long trade).
        """
        # Guard against bad inputs: stop loss must be below entry price
        # for a long (buy) trade. If it's not, something is wrong, so
        # we return 0 shares to avoid placing a broken trade.
        risk_per_share: float = entry_price - stop_loss_price
        if risk_per_share <= 0:
            return 0

        # Guard against zero or negative equity
        if account_equity <= 0:
            return 0

        # Dollar amount we're willing to lose on this single trade.
        # Uses the ELO tier's risk percentage instead of a fixed value.
        risk_budget: float = account_equity * self.risk_per_trade_pct

        # Divide the budget by the per-share risk to get the share count.
        # math.floor rounds DOWN so we never risk more than the budget.
        shares: int = math.floor(risk_budget / risk_per_share)

        return shares

    def calculate_stop_loss(
        self,
        entry_price: float,
        atr_value: float,
        strategy_name: str,
    ) -> float:
        """Calculate the stop loss price for a trade.

        The stop loss is placed a certain distance below the entry price.
        That distance is based on the stock's ATR (Average True Range)
        multiplied by TWO factors:
            1. The strategy's base multiplier (from settings).
            2. The ELO rank's atr_scale (from the current tier).

        Higher-ranked bots get wider stops (more room), while lower-ranked
        bots get tighter stops (cut losses faster).

        Example (Gold, momentum strategy):
            Base multiplier = 1.5, atr_scale = 1.0 → effective = 1.5
            ATR = $2, entry = $50 → stop = $50 - ($2 * 1.5) = $47.00

        Example (Diamond, momentum strategy):
            Base multiplier = 1.5, atr_scale = 1.2 → effective = 1.8
            ATR = $2, entry = $50 → stop = $50 - ($2 * 1.8) = $46.40

        Args:
            entry_price: The price at which we plan to buy the stock.
            atr_value: The stock's current ATR value (average daily range).
            strategy_name: Name of the strategy (e.g. "momentum", "breakout").
                Used to look up the correct base ATR multiplier.

        Returns:
            The stop loss price, rounded to two decimal places (cents).

        Raises:
            ValueError: If the strategy_name is not found in the configured
                ATR multipliers.
        """
        # Look up the base multiplier for this strategy.
        if strategy_name not in STOP_LOSS_ATR_MULTIPLIERS:
            valid_strategies = ", ".join(STOP_LOSS_ATR_MULTIPLIERS.keys())
            raise ValueError(
                f"Unknown strategy '{strategy_name}'. "
                f"Valid strategies: {valid_strategies}"
            )

        base_multiplier: float = STOP_LOSS_ATR_MULTIPLIERS[strategy_name]

        # Scale by the ELO tier's atr_scale.
        # Gold (1.0) leaves the multiplier unchanged.
        # Diamond (1.2) widens it by 20%.
        # Bronze (0.8) tightens it by 20%.
        effective_multiplier: float = base_multiplier * self.atr_scale

        # Stop loss = entry price minus (ATR * effective multiplier).
        stop_loss: float = entry_price - (atr_value * effective_multiplier)

        # Round to cents — stock prices are quoted in dollars and cents
        return round(stop_loss, 2)

    def can_trade(self) -> bool:
        """Check whether the bot is allowed to place new trades right now.

        Trading is halted for the rest of the day if either:
        1. The daily profit target has been reached (we've made enough).
        2. The daily loss limit has been hit (we've lost enough).

        Both the target and the loss limit come from the ELO tier, so they
        scale with the bot's proven performance.

        Returns:
            True if the bot is allowed to trade, False if it must stop.
        """
        # Use the ELO-derived daily target as the profit ceiling.
        elo_target = self.elo.get_daily_target()

        # Check if we hit the profit target
        if self.daily_pnl >= elo_target:
            return False

        # Check if we hit the loss limit (also from ELO tier)
        if self.daily_pnl <= -self.daily_loss_limit:
            return False

        return True

    def record_trade(self, pnl: float) -> None:
        """Record a completed trade's profit or loss.

        Each time a trade closes, call this method with the dollar amount
        gained or lost. It updates the running daily total AND tracks
        whether the trade was a win or loss (for win rate calculation).

        Args:
            pnl: The profit (positive) or loss (negative) from the trade,
                in dollars. For example, +50.0 means we made $50,
                -30.0 means we lost $30.
        """
        self.daily_pnl += pnl
        self.trade_count += 1

        # Track wins and losses separately.
        # This lets us calculate win rate at end of day, which feeds
        # into the ELO score. A bot with >50% win rate is making good
        # decisions and should be rewarded.
        if pnl > 0:
            self.daily_wins += 1
        else:
            self.daily_losses += 1

    def end_of_day_reset(self) -> None:
        """Reset daily tracking and update the ELO rating.

        Call this once at the end of each trading day. It:
        1. Updates the ELO rating using BOTH daily P&L AND win rate.
        2. Updates the consecutive profitable day streak.
        3. Resets all daily counters for the next day.

        The ELO update is the key step — it determines the bot's rank
        for tomorrow, which sets the daily target, risk per trade, max
        positions, loss limit, and stop-loss width.
        """
        # --- ELO rating update ---
        # Pass both P&L and win/loss counts so the ELO system can
        # factor in win rate. A bot with a high win rate (>50%) gets
        # a bigger score boost, even if the dollar P&L is modest.
        elo_result = self.elo.update_rating(
            daily_pnl=self.daily_pnl,
            wins=self.daily_wins,
            losses=self.daily_losses,
        )

        # Log the ELO update so we can track the bot's progression.
        logger.info(
            "ELO update: %s | Rating: %.0f -> %.0f (%+.1f) | "
            "Win rate: %.0f%% | Target: $%.0f/day | Risk: %.2f%%",
            elo_result["rank_name"],
            elo_result["old_rating"],
            elo_result["new_rating"],
            elo_result["change"],
            elo_result["win_rate"],
            elo_result["daily_target"],
            self.risk_per_trade_pct * 100,
        )

        # Log promotions and demotions — these are notable events.
        if elo_result["promoted"]:
            logger.info(
                "PROMOTED to %s! New target: $%.0f | Risk: %.2f%% | "
                "Max positions: %d",
                elo_result["rank_name"],
                elo_result["daily_target"],
                self.risk_per_trade_pct * 100,
                self.max_open_positions,
            )
        elif elo_result["demoted"]:
            logger.warning(
                "DEMOTED to %s. Target: $%.0f | Risk: %.2f%% | "
                "Max positions: %d",
                elo_result["rank_name"],
                elo_result["daily_target"],
                self.risk_per_trade_pct * 100,
                self.max_open_positions,
            )

        # --- Streak tracking ---
        if self.daily_pnl > 0:
            self.consecutive_profitable_days += 1
        else:
            self.consecutive_profitable_days = 0

        # Reset daily counters for the next trading day
        self.daily_pnl = 0.0
        self.daily_wins = 0
        self.daily_losses = 0
        self.trade_count = 0

    def get_status(self) -> dict:
        """Return a snapshot of the current risk management state.

        This is useful for logging, dashboards, or debugging. It gives
        a quick overview of where the bot stands for the day, including
        all rank-derived risk parameters.

        Returns:
            A dictionary containing all current risk state.
        """
        risk_params = self.elo.get_risk_parameters()
        total_trades = self.daily_wins + self.daily_losses
        win_rate = (
            (self.daily_wins / total_trades * 100) if total_trades > 0 else 0.0
        )

        return {
            "daily_pnl": self.daily_pnl,
            "daily_wins": self.daily_wins,
            "daily_losses": self.daily_losses,
            "win_rate": round(win_rate, 1),
            "elo_daily_target": self.elo.get_daily_target(),
            "daily_profit_target": self.elo.get_daily_target(),
            "daily_loss_limit": risk_params["loss_limit"],
            "can_trade": self.can_trade(),
            "consecutive_profitable_days": self.consecutive_profitable_days,
            "trade_count": self.trade_count,
            "max_open_positions": risk_params["max_positions"],
            "risk_per_trade_pct": risk_params["risk_pct"],
            "atr_scale": risk_params["atr_scale"],
            "elo_rating": self.elo.rating,
            "rank_name": self.elo.rank_name,
        }
