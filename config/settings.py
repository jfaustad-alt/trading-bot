"""
Bot configuration settings.

This file holds all the knobs and dials for the trading bot.
Instead of scattering magic numbers throughout the code, we keep
them here in one place so they're easy to find and adjust.

HOW SETTINGS WORK:
    1. Defaults are defined here as Python constants.
    2. The Settings page in the app can override these via a JSON file
       (data/settings_overrides.json).
    3. When the bot starts, it loads overrides on top of defaults.
    4. API keys always come from the .env file (never stored in JSON).

We use python-dotenv to load API keys from the .env file,
keeping secrets out of the code.
"""

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load environment variables from .env file
# This reads the .env file and makes its values available via os.getenv()
load_dotenv()


# --- Alpaca API credentials ---
ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


# --- Default values ---
# These are the "factory defaults." The Settings page can override them.

# Trading schedule — the bot only trades during these windows.
# Times are in US Eastern Time (ET).
TRADING_WINDOWS: list[dict[str, str]] = [
    {"start": "09:30", "end": "10:30"},  # First hour after market open
    {"start": "15:00", "end": "16:00"},  # Last hour before market close
]

# Risk management
STARTING_CAPITAL: float = 100_000.00       # Paper trading starting balance
RISK_PER_TRADE_PCT: float = 0.01           # 1% of portfolio max risk per trade
MAX_OPEN_POSITIONS: int = 10               # Maximum simultaneous positions
DAILY_PROFIT_TARGET: float = 100.00        # Stop trading after making this much
DAILY_LOSS_LIMIT: float = 100.00           # Stop trading after losing this much
TARGET_INCREASE_AMOUNT: float = 25.00      # Increase daily target by this amount...
TARGET_INCREASE_STREAK: int = 5            # ...after this many consecutive profitable days

# Stop-loss settings (ATR-based)
# ATR = Average True Range, a measure of how much a stock typically moves.
# We multiply ATR by these factors to set stop-losses per strategy.
STOP_LOSS_ATR_MULTIPLIERS: dict[str, float] = {
    "mean_reversion": 1.0,    # Tight stop — expects quick reversion
    "momentum": 1.5,          # Standard stop
    "breakout": 2.0,          # Wide stop — breakouts need room
    "etf_rotation": 1.5,      # Standard stop
}


# ---------------------------------------------------------------------------
# Settings overrides — persisted to JSON file
# ---------------------------------------------------------------------------
# The Settings page saves user changes to a JSON file. On startup, the bot
# loads these overrides and applies them on top of the defaults above.
# This way, the user's changes survive bot restarts.
# ---------------------------------------------------------------------------

# Factory defaults — these NEVER change. Used by get_all_settings() and
# reset_settings() to know what the original values were.
_FACTORY_DEFAULTS: dict[str, Any] = {
    "risk_per_trade_pct": 0.01,
    "max_open_positions": 10,
    "daily_profit_target": 100.00,
    "daily_loss_limit": 100.00,
    "target_increase_amount": 25.00,
    "target_increase_streak": 5,
    "stop_loss_atr_multipliers": {
        "mean_reversion": 1.0,
        "momentum": 1.5,
        "breakout": 2.0,
        "etf_rotation": 1.5,
    },
    "trading_windows": [
        {"start": "09:30", "end": "10:30"},
        {"start": "15:00", "end": "16:00"},
    ],
}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_OVERRIDES_PATH = _PROJECT_ROOT / "data" / "settings_overrides.json"


def _load_overrides() -> dict[str, Any]:
    """Load settings overrides from the JSON file.

    Returns an empty dict if the file doesn't exist or is invalid.

    Returns:
        A dictionary of setting overrides.
    """
    if not _OVERRIDES_PATH.exists():
        return {}

    try:
        with open(_OVERRIDES_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_overrides(overrides: dict[str, Any]) -> None:
    """Save settings overrides to the JSON file.

    Creates the data/ directory if it doesn't exist.

    Args:
        overrides: Dictionary of setting overrides to persist.
    """
    _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OVERRIDES_PATH, "w") as f:
        json.dump(overrides, f, indent=2)


def get_all_settings() -> dict[str, Any]:
    """Return all current settings as a dictionary.

    Merges defaults with any user overrides. This is what the
    Settings page displays and what the bot should use.

    Returns:
        A dict with all editable settings and their current values.
    """
    overrides = _load_overrides()
    defaults = _FACTORY_DEFAULTS

    return {
        "risk_per_trade_pct": overrides.get("risk_per_trade_pct", defaults["risk_per_trade_pct"]),
        "max_open_positions": overrides.get("max_open_positions", defaults["max_open_positions"]),
        "daily_profit_target": overrides.get("daily_profit_target", defaults["daily_profit_target"]),
        "daily_loss_limit": overrides.get("daily_loss_limit", defaults["daily_loss_limit"]),
        "target_increase_amount": overrides.get("target_increase_amount", defaults["target_increase_amount"]),
        "target_increase_streak": overrides.get("target_increase_streak", defaults["target_increase_streak"]),
        "stop_loss_atr_multipliers": {
            **defaults["stop_loss_atr_multipliers"],
            **overrides.get("stop_loss_atr_multipliers", {}),
        },
        "trading_windows": overrides.get("trading_windows", defaults["trading_windows"]),
    }


def update_settings(changes: dict[str, Any]) -> dict[str, Any]:
    """Apply setting changes and persist them.

    Only updates the keys provided in `changes`. Other settings
    remain unchanged.

    Args:
        changes: Dict of settings to update, e.g.
            {"risk_per_trade_pct": 0.02, "max_open_positions": 5}.

    Returns:
        The full settings dict after applying changes.
    """
    overrides = _load_overrides()

    # Apply each change to the overrides.
    for key, value in changes.items():
        if key == "stop_loss_atr_multipliers" and isinstance(value, dict):
            # Merge ATR multipliers instead of replacing.
            existing = overrides.get("stop_loss_atr_multipliers", {})
            existing.update(value)
            overrides["stop_loss_atr_multipliers"] = existing
        else:
            overrides[key] = value

    _save_overrides(overrides)

    # Also update the module-level variables so the bot picks up
    # the changes immediately (without restart).
    global RISK_PER_TRADE_PCT, MAX_OPEN_POSITIONS, DAILY_PROFIT_TARGET
    global DAILY_LOSS_LIMIT, TARGET_INCREASE_AMOUNT, TARGET_INCREASE_STREAK
    global STOP_LOSS_ATR_MULTIPLIERS, TRADING_WINDOWS

    settings = get_all_settings()
    RISK_PER_TRADE_PCT = settings["risk_per_trade_pct"]
    MAX_OPEN_POSITIONS = settings["max_open_positions"]
    DAILY_PROFIT_TARGET = settings["daily_profit_target"]
    DAILY_LOSS_LIMIT = settings["daily_loss_limit"]
    TARGET_INCREASE_AMOUNT = settings["target_increase_amount"]
    TARGET_INCREASE_STREAK = settings["target_increase_streak"]
    STOP_LOSS_ATR_MULTIPLIERS = settings["stop_loss_atr_multipliers"]
    TRADING_WINDOWS = settings["trading_windows"]

    return settings


def reset_settings() -> dict[str, Any]:
    """Reset all settings to factory defaults.

    Deletes the overrides file so all settings revert to the
    hardcoded defaults at the top of this file. Also updates the
    module-level variables so the bot picks up changes immediately.

    Returns:
        The default settings dict.
    """
    if _OVERRIDES_PATH.exists():
        _OVERRIDES_PATH.unlink()

    # Update module-level variables to factory defaults.
    global RISK_PER_TRADE_PCT, MAX_OPEN_POSITIONS, DAILY_PROFIT_TARGET
    global DAILY_LOSS_LIMIT, TARGET_INCREASE_AMOUNT, TARGET_INCREASE_STREAK
    global STOP_LOSS_ATR_MULTIPLIERS, TRADING_WINDOWS

    settings = get_all_settings()
    RISK_PER_TRADE_PCT = settings["risk_per_trade_pct"]
    MAX_OPEN_POSITIONS = settings["max_open_positions"]
    DAILY_PROFIT_TARGET = settings["daily_profit_target"]
    DAILY_LOSS_LIMIT = settings["daily_loss_limit"]
    TARGET_INCREASE_AMOUNT = settings["target_increase_amount"]
    TARGET_INCREASE_STREAK = settings["target_increase_streak"]
    STOP_LOSS_ATR_MULTIPLIERS = settings["stop_loss_atr_multipliers"]
    TRADING_WINDOWS = settings["trading_windows"]

    return settings
