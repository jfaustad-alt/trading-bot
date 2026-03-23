"""ELO-style rating system for the trading bot's daily performance.

This module implements a rating system inspired by chess.com's ELO ratings.
Instead of rating chess skill, it rates the bot's trading performance.

Key concepts for beginners:
    - ELO rating: A numbering system (invented by Arpad Elo for chess) that
      goes up when you win and down when you lose. Higher = better. A new
      chess player starts around 1000; grandmasters are 2500+.

    - K-factor: Controls how MUCH the rating changes after each game (or in
      our case, each trading day). A K-factor of 32 is the standard for
      intermediate chess players — it means the rating can change by up to
      32 points per day. Higher K = more volatile ratings.

    - Expected score: In chess ELO, this is the probability of winning based
      on the rating difference between two players. Here, we use a fixed
      expected score of 0.5 (50/50 chance), since we're not comparing two
      players — we're comparing the bot against its daily target.

    - Rank tiers: Like chess.com divisions (Bronze, Silver, Gold, etc.),
      the bot earns a rank title based on its rating. Higher ranks come
      with higher daily profit targets AND more aggressive risk settings.
      The bot must prove itself at lower tiers before being given more
      freedom.

How it works:
    1. The bot starts at rating 1000 (Gold tier, $100/day target).
    2. Each trading day is treated like a chess game.
    3. The score is based on TWO factors:
       a. Win rate — did more than 50% of trades make money?
       b. P&L vs target — how close did we get to the daily goal?
    4. A win rate above 50% boosts the score (good decisions).
    5. As the rating climbs, the bot gets higher targets AND is allowed
       to take on more risk (bigger positions, more open trades).
    6. As the rating falls, risk is reduced (smaller positions, fewer
       trades) to protect capital while the bot recovers.
"""


# ---------------------------------------------------------------------------
# Rank tier definitions
# ---------------------------------------------------------------------------
# Each tier defines the rating range, daily target, AND risk parameters.
# Higher tiers get more aggressive settings because the bot has proven
# it can trade consistently.
#
# Risk parameters per tier:
#   - target: daily profit target in dollars
#   - risk_pct: max % of portfolio risked per trade (higher = bigger positions)
#   - max_positions: max simultaneous open positions
#   - loss_limit: daily loss limit in dollars (how much can we lose today)
#   - atr_scale: multiplier applied to ATR stop-losses (higher = wider stops)
#
# Why scale risk by tier?
#   A Bronze bot has not proven itself — it trades small and tight.
#   A Grandmaster bot has a long track record — it earns the right to
#   take bigger swings. If it starts losing, it gets demoted and risk
#   is automatically reduced, creating a self-correcting feedback loop.
RANK_TIERS: list[dict] = [
    {
        "min": 0, "max": 799,
        "name": "Bronze", "symbol": "\U0001f949",
        "target": 50.0,
        "risk_pct": 0.005,       # 0.5% per trade — very conservative
        "max_positions": 3,
        "loss_limit": 50.0,
        "atr_scale": 0.8,        # tighter stops — cut losses early
    },
    {
        "min": 800, "max": 999,
        "name": "Silver", "symbol": "\U0001f948",
        "target": 75.0,
        "risk_pct": 0.0075,      # 0.75% per trade
        "max_positions": 5,
        "loss_limit": 75.0,
        "atr_scale": 0.9,
    },
    {
        "min": 1000, "max": 1199,
        "name": "Gold", "symbol": "\u2b50",
        "target": 100.0,
        "risk_pct": 0.01,        # 1% per trade — standard
        "max_positions": 8,
        "loss_limit": 100.0,
        "atr_scale": 1.0,        # baseline stop distance
    },
    {
        "min": 1200, "max": 1399,
        "name": "Platinum", "symbol": "\U0001f48e",
        "target": 150.0,
        "risk_pct": 0.0125,      # 1.25% per trade
        "max_positions": 10,
        "loss_limit": 150.0,
        "atr_scale": 1.1,
    },
    {
        "min": 1400, "max": 1599,
        "name": "Diamond", "symbol": "\U0001f537",
        "target": 200.0,
        "risk_pct": 0.015,       # 1.5% per trade
        "max_positions": 12,
        "loss_limit": 200.0,
        "atr_scale": 1.2,        # wider stops — more room to breathe
    },
    {
        "min": 1600, "max": 1799,
        "name": "Master", "symbol": "\U0001f451",
        "target": 300.0,
        "risk_pct": 0.0175,      # 1.75% per trade
        "max_positions": 14,
        "loss_limit": 250.0,
        "atr_scale": 1.3,
    },
    {
        "min": 1800, "max": 99999,
        "name": "Grandmaster", "symbol": "\U0001f3c6",
        "target": 500.0,
        "risk_pct": 0.02,        # 2% per trade — aggressive
        "max_positions": 16,
        "loss_limit": 300.0,
        "atr_scale": 1.4,        # widest stops — trusts the strategy
    },
]

# The standard chess K-factor for intermediate players.
# This controls the maximum rating change per day.
# 32 means: if you score 1.0 (full win) when expected was 0.5,
# the rating change is 32 * (1.0 - 0.5) = +16 points.
# If you score 0.0 (full loss) when expected was 0.5,
# the change is 32 * (0.0 - 0.5) = -16 points.
K_FACTOR: int = 32

# The minimum rating the bot can ever drop to.
# This prevents the rating from going to zero or negative, which would
# make recovery impossible and the math meaningless.
MIN_RATING: int = 100

# The expected score is fixed at 0.5 (50/50).
# In real chess, this would vary based on the opponents' ratings.
# Since we don't have an "opponent" — just a target — we assume a
# neutral expectation: the bot has a 50% chance of hitting its target.
EXPECTED_SCORE: float = 0.5

# How much weight win rate has in the overall score (0.0 to 1.0).
# At 0.4, the final score is 40% win-rate and 60% P&L-based.
# This means a bot that wins most of its trades but doesn't hit the
# dollar target still gets a meaningful boost.
WIN_RATE_WEIGHT: float = 0.4


class EloRating:
    """Tracks the trading bot's performance using an ELO-style rating.

    The rating starts at 1000 (Gold tier) and moves up or down each
    trading day based on BOTH profitability AND win rate. This creates
    a natural feedback loop:
        - Good performance raises the rating, the target, AND the risk
          allowance, letting the bot take bigger positions.
        - Poor performance lowers everything, forcing the bot to trade
          smaller and safer while it recovers.

    Attributes:
        rating: The current ELO rating (starts at 1000).
        rating_history: A list of all past ratings, useful for charting
            the bot's performance over time.
    """

    def __init__(self, initial_rating: int = 1000) -> None:
        """Initialise the ELO rating system.

        Args:
            initial_rating: The starting rating. Defaults to 1000, which
                places the bot in the Gold tier with a $100/day target.
                You might set this higher if resuming a bot that previously
                performed well.
        """
        self.rating: float = float(initial_rating)

        # Keep a full history so we can plot rating over time.
        # Starts with the initial rating as the first data point.
        self.rating_history: list[float] = [self.rating]

    # -- Properties that derive from the current rating ------------------

    @property
    def daily_target(self) -> float:
        """The daily profit target for the current rank tier.

        This is a *property* (accessed like an attribute, not a method call)
        because it's always derived from the current rating — there's no
        reason to store it separately.

        Returns:
            The daily profit target in dollars.
        """
        return self.get_daily_target()

    @property
    def rank_name(self) -> str:
        """The name of the current rank tier (e.g. 'Gold', 'Platinum').

        Returns:
            The rank name as a string.
        """
        tier = self._get_current_tier()
        return tier["name"]

    # -- Core public methods ---------------------------------------------

    def update_rating(
        self,
        daily_pnl: float,
        wins: int = 0,
        losses: int = 0,
    ) -> dict:
        """Update the rating based on one trading day's results.

        This is the heart of the ELO system. It blends TWO factors into
        a single score between 0.0 and 1.0:

            1. Win rate score — rewards consistent decision-making.
               If more than 50% of trades were winners, this is positive.
            2. P&L score — rewards hitting the dollar target.
               Meeting the target = 1.0, losing money = 0.0.

        The final score is a weighted blend:
            score = (WIN_RATE_WEIGHT * win_rate_score)
                  + ((1 - WIN_RATE_WEIGHT) * pnl_score)

        Then the standard ELO formula applies:
            rating_change = K * (score - expected_score)

        Args:
            daily_pnl: The total profit or loss for the day, in dollars.
                Positive means profit, negative means loss.
            wins: Number of trades that were profitable today.
            losses: Number of trades that lost money today.

        Returns:
            A dictionary summarising what happened:
                - old_rating: Rating before the update.
                - new_rating: Rating after the update.
                - change: How much the rating changed (positive = up).
                - rank_name: The current rank title after the update.
                - daily_target: The daily target after the update.
                - promoted: True if the bot moved UP to a new tier.
                - demoted: True if the bot moved DOWN to a new tier.
                - win_rate: The day's win rate as a percentage (0-100).
        """
        old_rating = self.rating
        old_tier_name = self.rank_name

        # --- Step 1: Calculate the blended score ---
        actual_score = self._calculate_score(daily_pnl, wins, losses)

        # --- Step 2: Apply the ELO formula ---
        # rating_change = K * (actual_score - expected_score)
        #
        # If actual_score > expected_score (0.5), the rating goes up.
        # If actual_score < expected_score, the rating goes down.
        # If they're equal, the rating doesn't change.
        rating_change = K_FACTOR * (actual_score - EXPECTED_SCORE)

        # --- Step 3: Apply the change with a floor ---
        # The rating can never drop below MIN_RATING (100). Without this
        # floor, a long losing streak could send the rating to zero or
        # negative, which breaks the math and makes recovery impossible.
        self.rating = max(MIN_RATING, self.rating + rating_change)

        # --- Step 4: Record history ---
        self.rating_history.append(self.rating)

        # --- Step 5: Check for promotion/demotion ---
        new_tier_name = self.rank_name
        promoted = self._tier_index(new_tier_name) > self._tier_index(old_tier_name)
        demoted = self._tier_index(new_tier_name) < self._tier_index(old_tier_name)

        # Calculate win rate for the return dict.
        total_trades = wins + losses
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        return {
            "old_rating": old_rating,
            "new_rating": self.rating,
            "change": rating_change,
            "rank_name": new_tier_name,
            "daily_target": self.daily_target,
            "promoted": promoted,
            "demoted": demoted,
            "win_rate": round(win_rate, 1),
        }

    def get_daily_target(self) -> float:
        """Return the daily profit target for the current rating tier.

        The target increases as the bot climbs through the ranks:
            Bronze ($50) -> Silver ($75) -> Gold ($100) -> ... -> Grandmaster ($500)

        Returns:
            The daily profit target in dollars.
        """
        tier = self._get_current_tier()
        return tier["target"]

    def get_risk_parameters(self) -> dict:
        """Return the risk management parameters for the current rank tier.

        These values control how aggressively the bot trades. Higher-ranked
        bots earn the right to take more risk, while lower-ranked bots are
        forced to trade conservatively.

        Returns:
            A dictionary containing:
                - risk_pct: max percentage of portfolio risked per trade.
                - max_positions: max number of simultaneous open positions.
                - loss_limit: daily loss limit in dollars.
                - atr_scale: multiplier applied to ATR stop-loss distances.
                    Values > 1.0 widen stops, < 1.0 tighten them.
        """
        tier = self._get_current_tier()
        return {
            "risk_pct": tier["risk_pct"],
            "max_positions": tier["max_positions"],
            "loss_limit": tier["loss_limit"],
            "atr_scale": tier["atr_scale"],
        }

    def get_rank_info(self) -> dict:
        """Return detailed information about the bot's current rank.

        Useful for dashboards and status displays. Includes everything
        needed to show the bot's progress toward the next rank.

        Returns:
            A dictionary containing:
                - rating: The current ELO rating.
                - rank_name: The current rank title (e.g. 'Gold').
                - daily_target: The current daily profit target.
                - risk_pct: Current risk per trade percentage.
                - max_positions: Current max open positions.
                - loss_limit: Current daily loss limit.
                - atr_scale: Current ATR stop-loss scaling factor.
                - next_rank_name: The name of the next tier above, or
                    None if already at Grandmaster.
                - points_to_next_rank: How many rating points needed to
                    reach the next tier, or 0 if already at the top.
                - rating_history: Full list of historical ratings.
        """
        current_tier = self._get_current_tier()
        current_index = self._tier_index(current_tier["name"])

        # Figure out the next rank above the current one.
        # If we're already at the highest tier, there's no "next".
        if current_index < len(RANK_TIERS) - 1:
            next_tier = RANK_TIERS[current_index + 1]
            next_rank_name = next_tier["name"]
            # Points needed = bottom of next tier minus current rating.
            # max(0, ...) prevents negative values if the rating
            # slightly overshoots a tier boundary due to rounding.
            points_to_next = max(0, next_tier["min"] - self.rating)
        else:
            next_rank_name = None
            points_to_next = 0

        return {
            "rating": self.rating,
            "rank_name": current_tier["name"],
            "daily_target": current_tier["target"],
            "risk_pct": current_tier["risk_pct"],
            "max_positions": current_tier["max_positions"],
            "loss_limit": current_tier["loss_limit"],
            "atr_scale": current_tier["atr_scale"],
            "next_rank_name": next_rank_name,
            "points_to_next_rank": points_to_next,
            "rating_history": list(self.rating_history),  # return a copy
        }

    def get_rank_display(self) -> str:
        """Return a human-readable string showing the bot's rank.

        Format: "<symbol> <RankName> (<rating>) — Target: $<target>/day"
        Example: "⭐ Gold (1050) — Target: $100/day"

        This is meant for console output, log messages, or simple UIs.

        Returns:
            A formatted string with the rank symbol, name, rating, and target.
        """
        tier = self._get_current_tier()
        # Use :.0f to display the rating as a whole number (no decimals)
        # and :.0f for the target too (e.g. $100 not $100.00).
        return (
            f"{tier['symbol']} {tier['name']} ({self.rating:.0f}) "
            f"\u2014 Target: ${tier['target']:.0f}/day"
        )

    # -- Private helper methods ------------------------------------------

    def _get_current_tier(self) -> dict:
        """Find the rank tier that matches the current rating.

        Iterates through RANK_TIERS to find which tier the current rating
        falls into. If somehow no tier matches (shouldn't happen), defaults
        to the first tier (Bronze).

        Returns:
            The tier dictionary with all tier parameters.
        """
        for tier in RANK_TIERS:
            if tier["min"] <= self.rating <= tier["max"]:
                return tier

        # Fallback — should never happen if RANK_TIERS covers all ratings.
        return RANK_TIERS[0]

    def _calculate_score(
        self,
        daily_pnl: float,
        wins: int = 0,
        losses: int = 0,
    ) -> float:
        """Convert a day's results into a score between 0.0 and 1.0.

        The score blends two components:

        1. **P&L score** (60% weight by default):
           - Lost money → 0.0
           - Made money but below target → proportional (e.g. $50/$100 = 0.5)
           - Hit or exceeded target → 1.0

        2. **Win rate score** (40% weight by default):
           - 0% win rate → 0.0
           - 50% win rate → 0.5
           - 100% win rate → 1.0

        Why blend both? A bot that wins 8/10 trades but misses the dollar
        target is making *good decisions* — it should be rewarded for that.
        Conversely, a bot that hits the target on one lucky trade but loses
        9/10 others is taking bad risk — it shouldn't be rewarded as much.

        If no trade counts are provided (wins=0, losses=0), the score
        falls back to P&L-only (backwards compatible with the old system).

        Args:
            daily_pnl: The day's total profit or loss in dollars.
            wins: Number of profitable trades today.
            losses: Number of losing trades today.

        Returns:
            A float between 0.0 and 1.0 representing the day's score.
        """
        target = self.get_daily_target()

        # --- P&L score component ---
        if daily_pnl <= 0:
            pnl_score = 0.0
        elif daily_pnl >= target:
            pnl_score = 1.0
        else:
            pnl_score = daily_pnl / target

        # --- Win rate score component ---
        total_trades = wins + losses
        if total_trades == 0:
            # No trades today (or no win/loss data provided).
            # Fall back to P&L-only scoring.
            return pnl_score

        # Win rate as a value between 0.0 and 1.0.
        # A 50% win rate gives a score of 0.5, which is neutral.
        # Above 50% pushes the score up; below 50% drags it down.
        win_rate_score = wins / total_trades

        # --- Blend the two components ---
        # WIN_RATE_WEIGHT controls the balance (default 0.4 = 40% win rate).
        blended = (WIN_RATE_WEIGHT * win_rate_score) + (
            (1 - WIN_RATE_WEIGHT) * pnl_score
        )

        # Clamp to [0.0, 1.0] just in case.
        return max(0.0, min(1.0, blended))

    @staticmethod
    def _tier_index(tier_name: str) -> int:
        """Return the index of a tier by name, used for promotion/demotion checks.

        A higher index means a higher tier. This lets us compare two tier
        names numerically to see if the bot moved up or down.

        Args:
            tier_name: The name of the tier (e.g. 'Gold', 'Platinum').

        Returns:
            The integer index of the tier in RANK_TIERS (0 = Bronze, 6 = Grandmaster).
            Returns -1 if the name is not found (shouldn't happen).
        """
        for i, tier in enumerate(RANK_TIERS):
            if tier["name"] == tier_name:
                return i
        return -1
