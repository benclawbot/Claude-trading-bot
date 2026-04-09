from .base_strategy import BaseStrategy, Signal, SignalType
from .ema5_momentum import EMA5MomentumStrategy
from .dual_ma_crossover import DualMACrossoverStrategy
from .regime_riskoff import RegimeRiskOffStrategy
from .price_momentum_25 import PriceMomentum25Strategy
from .residual_mean_reversion import ResidualMeanReversionStrategy
from .donchian_breakout import DonchianBreakoutStrategy
from .blended_momentum_mr import BlendedMomentumMRStrategy
from .rsi_bollinger import RSIBollingerStrategy
from .breakout import BreakoutStrategy
from .macd_momentum import MACDMomentumStrategy
from .ema_crossover import EMACrossoverStrategy

ALL_STRATEGIES = [
    EMA5MomentumStrategy,           # 1 – Short-window EMA momentum     (~145% CAGR)
    DualMACrossoverStrategy,        # 2 – 100/250 SMA dual crossover   (~115% CAGR)
    RegimeRiskOffStrategy,          # 3 – Risk-On/Off regime model     (variable, high)
    PriceMomentum25Strategy,        # 4 – 25-day close-to-close momentum (~115% CAGR)
    ResidualMeanReversionStrategy,  # 5 – Residual mean reversion      (Sharpe ~2.3)
    DonchianBreakoutStrategy,       # 6 – Donchian breakout + inverse ADX (competitive)
    BlendedMomentumMRStrategy,     # 7 – 50/50 momentum + MR blend    (best risk-adj)
    RSIBollingerStrategy,          # 8 – RSI + Bollinger mean reversion (chop-friendly)
    BreakoutStrategy,              # 9 – Volume-confirmed breakout     (volatile regimes)
    MACDMomentumStrategy,          # 10 – MACD crossover + EMA200 filter (trend)
    EMACrossoverStrategy,         # 11 – EMA9/21 crossover + EMA50 filter (moderate trend)
]
