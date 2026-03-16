"""Abstract base class for all trading strategies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

import pandas as pd


class SignalType(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    type: SignalType
    confidence: float          # 0.0 – 1.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.type != SignalType.HOLD


class BaseStrategy(ABC):
    """
    All concrete strategies inherit from this class.
    Each strategy must implement `generate_signal` and declare
    its required indicator lookback via `min_candles`.
    """

    def __init__(self, name: str, params: Dict[str, Any]):
        self.name = name
        self.params = dict(params)
        self.capital: float = 0.0
        self.is_active: bool = False

        # Running counters – updated by PortfolioManager
        self.total_trades: int = 0
        self.winning_trades: int = 0

    # ─── Abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """
        Analyse the most recent candles and return a Signal.
        `df` always contains at least `min_candles` rows with all indicators
        pre-computed by `utils.indicators.add_all_indicators`.
        """

    @property
    @abstractmethod
    def min_candles(self) -> int:
        """Minimum number of candles needed for reliable signals."""

    @property
    @abstractmethod
    def candle_interval(self) -> str:
        """Binance interval string, e.g. '1h', '4h', '1d'."""

    @property
    def max_hold_candles(self) -> int:
        """
        Maximum number of candles to hold a position before forced exit.
        Default is 48 (2 days on 1h, 8 days on 4h, 48 days on 1d).
        Override in daily strategies that need to capture longer trends.
        """
        return 48

    # ─── Convenience helpers ──────────────────────────────────────────────────

    def update_params(self, new_params: Dict[str, Any]):
        self.params.update(new_params)

    def set_capital(self, capital: float):
        self.capital = capital

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    def record_trade_outcome(self, won: bool):
        self.total_trades += 1
        if won:
            self.winning_trades += 1

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} capital={self.capital:.2f} active={self.is_active}>"
