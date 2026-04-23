from .base_strategy import BaseStrategy, Signal, SignalType
from .ema5_momentum import EMA5MomentumStrategy
from .dual_ma_crossover import DualMACrossoverStrategy
from .regime_riskoff import RegimeRiskOffStrategy
from .price_momentum_25 import PriceMomentum25Strategy
from .residual_mean_reversion import ResidualMeanReversionStrategy
from .donchian_breakout import DonchianBreakoutStrategy
from .blended_momentum_mr import BlendedMomentumMRStrategy
from .btc_momentum_breakout import BTCMomentumBreakoutStrategy

ALL_STRATEGIES = [
    EMA5MomentumStrategy,           # 1 – Short-window EMA momentum     (~145% CAGR)
    DualMACrossoverStrategy,        # 2 – 100/250 SMA dual crossover     (~115% CAGR)
    RegimeRiskOffStrategy,          # 3 – Risk-On/Off regime model       (variable, high)
    PriceMomentum25Strategy,        # 4 – 25-day close-to-close momentum (~115% CAGR)
    ResidualMeanReversionStrategy,  # 5 – Residual mean reversion        (Sharpe ~2.3)
    DonchianBreakoutStrategy,        # 6 – Donchian breakout + inverse ADX (competitive)
    BlendedMomentumMRStrategy,      # 7 – 50/50 momentum + MR blend      (best risk-adj)
    BTCMomentumBreakoutStrategy,    # 8 – BTC momentum breakout          (+42% CAGR vault)
]
