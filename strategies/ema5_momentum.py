"""
Strategy 1: Short-Window EMA Momentum
──────────────────────────────────────
Research source: Quantified Strategies – Best EMA period for Bitcoin
Backtested CAGR: ~145%  |  Max drawdown: ~39%

Signal logic (daily candles):
  Entry LONG  : close crosses ABOVE 5-day EMA  (momentum turns up)
  Entry SHORT : close crosses BELOW 5-day EMA  (momentum turns down)
  Exit        : SL/TP hit or max-hold reached

The 5-day EMA gives recent price action more weight than an SMA, making
it especially responsive in fast-moving crypto markets.
"""

import numpy as np
import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class EMA5MomentumStrategy(BaseStrategy):

    def __init__(self, params: dict = None, name: str = None):
        defaults = config.STRATEGY_PARAMS.get("EMA5_Momentum", {
            "ema_period":      3,
            "atr_sl_mult":     0.75,
            "atr_tp_mult":     1.5,
            "candle_interval": "1d",
        })
        if params:
            defaults.update(params)
        super().__init__(name or "EMA5_Momentum", defaults)

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        return 20   # 5-period EMA needs ~15 warm-up candles + buffer

    @property
    def max_hold_candles(self) -> int:
        return 48   # 48 days on 1d – captures medium-term momentum swings

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "1d")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        close  = df["close"]
        period = int(self.params["ema_period"])
        ema5   = close.ewm(span=period, adjust=False).mean()
        atr    = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else float(close.iloc[-1] * 0.015)

        cur_close = float(close.iloc[-1])
        cur_ema   = float(ema5.iloc[-1])
        prv_close = float(close.iloc[-2])
        prv_ema   = float(ema5.iloc[-2])

        above_now  = cur_close > cur_ema
        above_prev = prv_close > prv_ema

        dist_pct   = abs(cur_close - cur_ema) / (cur_ema + 1e-10)
        confidence = min(0.90, 0.52 + dist_pct * 8.0)   # more distance → more confident

        sl_m = float(self.params["atr_sl_mult"])
        tp_m = float(self.params["atr_tp_mult"])

        # ── Golden: price just crossed above EMA5 ────────────────────────────
        if above_now and not above_prev:
            sl = cur_close - sl_m * atr
            tp = cur_close + tp_m * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"ema5": cur_ema, "atr": atr, "dist_pct": dist_pct},
            )

        # ── Death: price just crossed below EMA5 ─────────────────────────────
        if not above_now and above_prev:
            sl = cur_close + sl_m * atr
            tp = cur_close - tp_m * atr
            return Signal(
                SignalType.SELL, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"ema5": cur_ema, "atr": atr, "dist_pct": dist_pct},
            )

        return Signal(SignalType.HOLD, 0.0)
