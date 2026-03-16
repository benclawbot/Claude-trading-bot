"""
Strategy 4: 25-Day Close-to-Close Price Momentum
──────────────────────────────────────────────────
Research source: Quantified Strategies – 25-day momentum on Bitcoin
Backtested CAGR: ~115%  |  Max drawdown: ~66%

Signal logic (daily candles):
  Entry LONG  : today's close > close 25 days ago  (positive 25d momentum)
  Entry SHORT : today's close < close 25 days ago  (negative 25d momentum)
  Exit        : SL/TP hit or max-hold reached

Dead-simple rule – no external indicators needed. Works because crypto has
strong price autocorrelation: recent winners tend to keep winning, recent
losers tend to keep losing (momentum persistence).

Win rate is intentionally low (39–55%); the edge comes from letting winners
run. ATR-based SL/TP enforces the asymmetric payoff.
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class PriceMomentum25Strategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("PriceMomentum_25", {
            "lookback":        25,
            "atr_sl_mult":     1.5,
            "atr_tp_mult":     4.0,
            "candle_interval": "1d",
        })
        if params:
            defaults.update(params)
        super().__init__("PriceMomentum_25", defaults)

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        return int(self.params["lookback"]) + 5   # need 25 + warm-up

    @property
    def max_hold_candles(self) -> int:
        return 60   # 60 daily candles ≈ 2 months; trend can persist this long

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "1d")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        lb = int(self.params["lookback"])
        close = df["close"]

        cur_close  = float(close.iloc[-1])
        ref_close  = float(close.iloc[-1 - lb])       # close exactly `lb` candles ago
        prv_close  = float(close.iloc[-2])
        prv_ref    = float(close.iloc[-2 - lb])

        atr = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else cur_close * 0.02

        # Current and previous momentum sign
        mom_now  = cur_close - ref_close     # > 0 → positive momentum
        mom_prev = prv_close - prv_ref

        if (mom_now > 0) == (mom_prev > 0):   # no crossover → hold
            return Signal(SignalType.HOLD, 0.0)

        # Confidence scales with magnitude of the 25-day return
        ret_pct    = abs(mom_now) / (ref_close + 1e-10)
        confidence = min(0.90, 0.48 + ret_pct * 2.5)

        sl_m = float(self.params["atr_sl_mult"])
        tp_m = float(self.params["atr_tp_mult"])

        # ── Momentum flipped positive ─────────────────────────────────────────
        if mom_now > 0:
            sl = cur_close - sl_m * atr
            tp = cur_close + tp_m * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"ret_25d": mom_now / (ref_close + 1e-10), "ref_close": ref_close},
            )

        # ── Momentum flipped negative ─────────────────────────────────────────
        sl = cur_close + sl_m * atr
        tp = cur_close - tp_m * atr
        return Signal(
            SignalType.SELL, confidence,
            stop_loss=sl, take_profit=tp,
            metadata={"ret_25d": mom_now / (ref_close + 1e-10), "ref_close": ref_close},
        )
