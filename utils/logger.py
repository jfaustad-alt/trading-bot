"""
Trading bot console logger.

Provides colorful, formatted console output so you can quickly scan
what the bot is doing.  No files, no emails — just clean terminal prints.
"""

from datetime import datetime


# ---------------------------------------------------------------------------
# ANSI escape codes — how terminal colors work
# ---------------------------------------------------------------------------
# Terminals understand special character sequences that change text color.
# Every sequence starts with "\033[" (the "escape" character) and ends with "m".
# The number in the middle picks the color.  "\033[0m" resets back to normal.
#
# Example:  print("\033[32m" + "hello" + "\033[0m")
#           ^^^^^^^^^^^^^^    ^^^^^^^   ^^^^^^^^^^^
#           turn text green   the text  reset color
# ---------------------------------------------------------------------------

# Foreground colors
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"  # turns off all formatting


class TradingLogger:
    """Formats and prints trading-bot messages to the console with colors.

    Each public method prints one kind of event (trade entry, exit, warning,
    etc.) in a consistent ``[HH:MM:SS] [CATEGORY] details …`` format so
    the output is easy to scan while the bot runs.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _timestamp() -> str:
        """Return the current time as a short ``HH:MM:SS`` string.

        Returns:
            str: Formatted time string, e.g. ``'14:32:05'``.
        """
        return datetime.now().strftime("%H:%M:%S")

    def _print(self, category: str, color: str, message: str) -> None:
        """Print a single formatted log line.

        Args:
            category: Short tag shown in brackets, e.g. ``'TRADE'``.
            color: ANSI escape code applied to the category tag.
            message: The rest of the line after the tag.
        """
        timestamp = self._timestamp()
        print(f"{DIM}[{timestamp}]{RESET} {color}[{category}]{RESET} {message}")

    # ------------------------------------------------------------------
    # Public logging methods
    # ------------------------------------------------------------------

    def log_startup(self, account_info: dict) -> None:
        """Print a startup banner with key account details.

        Args:
            account_info: Dictionary with keys ``'equity'``,
                ``'buying_power'``, and ``'daily_target'``.
        """
        equity = account_info.get("equity", 0)
        buying_power = account_info.get("buying_power", 0)
        daily_target = account_info.get("daily_target", 0)

        print()
        print(f"{BOLD}{CYAN}{'=' * 55}{RESET}")
        print(f"{BOLD}{CYAN}  TRADING BOT STARTED{RESET}")
        print(f"{BOLD}{CYAN}{'=' * 55}{RESET}")
        print(f"  Equity:       {GREEN}${equity:,.2f}{RESET}")
        print(f"  Buying Power: {GREEN}${buying_power:,.2f}{RESET}")
        print(f"  Daily Target: {GREEN}${daily_target:,.2f}{RESET}")
        print(f"{BOLD}{CYAN}{'=' * 55}{RESET}")
        print()

    def log_market_condition(self, condition: str, details: str) -> None:
        """Print the detected market condition and chosen strategy.

        Args:
            condition: Short label such as ``'trending'`` or ``'choppy'``.
            details: Extra information about why this condition was chosen.
        """
        self._print("MARKET", BLUE, f"{condition.upper()} — {details}")

    def log_trade_entry(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        stop_loss: float,
        take_profit: float,
        strategy: str,
    ) -> None:
        """Print when a new trade is opened.

        Args:
            symbol: Ticker symbol, e.g. ``'AAPL'``.
            action: ``'BUY'`` or ``'SELL'``.
            shares: Number of shares.
            price: Entry price per share.
            stop_loss: Stop-loss price.
            take_profit: Take-profit target price.
            strategy: Name of the strategy that triggered the trade.
        """
        color = GREEN if action.upper() == "BUY" else RED
        self._print(
            "TRADE",
            color,
            f"{action.upper()} {shares} shares of {symbol} @ ${price:,.2f} "
            f"| Stop: ${stop_loss:,.2f} | Target: ${take_profit:,.2f} "
            f"| Strategy: {strategy}",
        )

    def log_trade_exit(
        self,
        symbol: str,
        action: str,
        shares: int,
        entry_price: float,
        exit_price: float,
        pnl: float,
    ) -> None:
        """Print when a trade is closed, highlighting profit or loss.

        Args:
            symbol: Ticker symbol.
            action: ``'SELL'`` (closing a long) or ``'BUY'`` (closing a short).
            shares: Number of shares closed.
            entry_price: Original entry price per share.
            exit_price: Price at which the position was closed.
            pnl: Realized profit/loss in dollars (negative = loss).
        """
        if pnl >= 0:
            color = GREEN
            sign = "+"
            icon = "✓"
        else:
            color = RED
            sign = ""  # negative sign is already in the number
            icon = "✗"

        self._print(
            "TRADE",
            color,
            f"{action.upper()} {shares} shares of {symbol} @ ${exit_price:,.2f} "
            f"| P&L: {sign}${pnl:,.2f} {icon}",
        )

    def log_daily_summary(
        self,
        daily_pnl: float,
        trades_taken: int,
        wins: int,
        losses: int,
        streak: int,
    ) -> None:
        """Print an end-of-day performance summary.

        Args:
            daily_pnl: Total profit/loss for the day in dollars.
            trades_taken: Number of round-trip trades executed.
            wins: Number of winning trades.
            losses: Number of losing trades.
            streak: Consecutive winning-day streak (negative = losing streak).
        """
        color = GREEN if daily_pnl >= 0 else RED
        sign = "+" if daily_pnl >= 0 else ""

        print()
        print(f"{BOLD}{color}{'─' * 55}{RESET}")
        self._print(
            "SUMMARY",
            color,
            f"Daily P&L: {sign}${daily_pnl:,.2f} "
            f"| Trades: {trades_taken} "
            f"| Wins: {wins} "
            f"| Losses: {losses} "
            f"| Streak: {streak} days",
        )
        print(f"{BOLD}{color}{'─' * 55}{RESET}")
        print()

    def log_risk_event(self, message: str) -> None:
        """Print a risk-management event (limit hit, exposure warning, etc.).

        Args:
            message: Description of the risk event.
        """
        self._print("RISK", YELLOW, message)

    def log_override(self, action: str) -> None:
        """Print a manual-override event (panic button, forced close, etc.).

        Args:
            action: Description of the override action taken.
        """
        self._print("OVERRIDE", RED, f"{BOLD}{action}{RESET}")

    def log_info(self, message: str) -> None:
        """Print a general informational message.

        Args:
            message: The info text to display.
        """
        self._print("INFO", BLUE, message)

    def log_warning(self, message: str) -> None:
        """Print a warning message.

        Args:
            message: The warning text to display.
        """
        self._print("WARNING", YELLOW, message)

    def log_error(self, message: str) -> None:
        """Print an error message.

        Args:
            message: The error text to display.
        """
        self._print("ERROR", RED, message)
