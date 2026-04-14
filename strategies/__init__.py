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
from .scalper_5m import Scalper5mStrategy
from .supertrend_atr import SupertrendATRStrategy
from .bollinger_mean_reversion import BollingerMeanRevStrategy

# ─── Walk-Forward Validated EMA Variants ──────────────────────────────────────
# Source: Walk-forward sweep (60/40 train/test split, 365d BTCUSDT)
# All 3 pass BOTH train AND test (CAGR≥7%, WR≥43%, PF≥1.5)
# ema=10 consistently outperforms default ema=3 across all market regimes


class EMA5Momentum_Aggressive(EMA5MomentumStrategy):
    """ema=10 | sl=0.9 | tp=1.5 — Highest WR (82.4% train / 54.5% test). Tight SL locks gains fast."""
    def __init__(self):
        super().__init__(
            name="EMA5_Momentum_Aggressive",
            params={"ema_period": 10, "atr_sl_mult": 0.9, "atr_tp_mult": 1.5, "candle_interval": "1d"},
        )


class EMA5Momentum_Balanced(EMA5MomentumStrategy):
    """ema=10 | sl=0.8 | tp=2.0 — Balanced risk/reward. Best PF stability train→test."""
    def __init__(self):
        super().__init__(
            name="EMA5_Momentum_Balanced",
            params={"ema_period": 10, "atr_sl_mult": 0.8, "atr_tp_mult": 2.0, "candle_interval": "1d"},
        )


class EMA5Momentum_Conservative(EMA5MomentumStrategy):
    """ema=10 | sl=0.6 | tp=2.0 — Highest test CAGR (11.8%). Loose SL lets winners run."""
    def __init__(self):
        super().__init__(
            name="EMA5_Momentum_Conservative",
            params={"ema_period": 10, "atr_sl_mult": 0.6, "atr_tp_mult": 2.0, "candle_interval": "1d"},
        )


ALL_STRATEGIES = [
    EMA5MomentumStrategy,             # 1 – Short-window EMA momentum     (~145% CAGR, default ema=3)
    EMA5Momentum_Aggressive,         # 2 – EMA=10 | sl=0.9 | tp=1.5      (WF validated, WR 54.5% test)
    EMA5Momentum_Balanced,           # 3 – EMA=10 | sl=0.8 | tp=2.0      (WF validated, CAGR 8.4% test)
    EMA5Momentum_Conservative,      # 4 – EMA=10 | sl=0.6 | tp=2.0      (WF validated, CAGR 11.8% test)
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
    Scalper5mStrategy,            # 12 – 5m fast momentum/reversion experiment template
    SupertrendATRStrategy,         # 13 – Supertrend ATR(5)×2.2 + EMA49 filter (TradingView port)
    BollingerMeanRevStrategy,       # 14 – Hourly Bollinger-band mean reversion (2025 thesis, Sharpe 1.86)
]


