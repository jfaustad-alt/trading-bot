"""
Trading strategies package.

Each strategy inherits from BaseStrategy and implements generate_signals()
to produce buy/sell signals based on different market analysis techniques.
"""

from strategies.base_strategy import BaseStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.breakout import BreakoutStrategy
from strategies.etf_rotation import ETFRotationStrategy

__all__ = [
    "BaseStrategy",
    "MeanReversionStrategy",
    "MomentumStrategy",
    "BreakoutStrategy",
    "ETFRotationStrategy",
]
