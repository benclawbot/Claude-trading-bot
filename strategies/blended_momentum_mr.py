"""
Strategy 7: Blended Momentum + Mean Reversion Portfolio
─────────────────────────────────────────────────────────
Research source: Medium – 50/50 Momentum + Mean Reversion blend
Rationale: Momentum dominated pre-2021; Mean Reversion dominated post-2021.
           Blending the two creates regime-robust performance across market cycles.

Signal logic (4h candles):
  Momentum sub-signal   : 25-period close-to-close return
    → positive return   = bull momentum
    → negative return   = bear momentum

  Mean-Reversion sub-signal : RSI + Bollinger Bands (same logic as RSI_Bollinger)
    → RSI < 38 AND close < BB lower  = oversold  (MR long)
    → RSI > 62 AND close > BB upper  = overbought (MR short)

  Combined decision (50 / 50 blend):
    STRONG BUY  : both agree → long  (momentum+ and MR says oversold)
    BUY         : only momentum says bull AND RSI < 55 (not overbought)
    STRONG SELL : both agree → short (momentum- and MR says overbought)
    SELL        : only momentum says bear AND RSI > 45 (not oversold)
    HOLD        : signals contradict with low conviction

The blended approach provides the complementary hedge: during trending markets
momentum carries it; during choppy / mean-reverting markets RSI+BB carries it.
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class BlendedMomentumMRStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("Blended_MomentumMR", {
            "momentum_period":  20,
            "rsi_oversold":     35,
            "rsi_overbought":   65,
            "bb_period":        20,
            "bb_std":           2.0,
            "atr_sl_mult":      1.5,
            "atr_tp_mult":      3.0,
            "candle_interval":  "4h",
        })
        if params:
            defaults.update(params)
        super().__init__("Blended_MomentumMR", defaults)

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        return max(int(self.params["momentum_period"]),
                   int(self.params["bb_period"])) + 20

    @property
    def max_hold_candles(self) -> int:
        return 72   # 72 × 4h = 288 hours ≈ 12 days

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "4h")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        mom_p    = int(self.params["momentum_period"])
        rsi_os   = float(self.params["rsi_oversold"])
        rsi_ob   = float(self.params["rsi_overbought"])

        last  = df.iloc[-1]
        close = float(last["close"])
        atr   = float(last.get("atr_14", close * 0.015))
        rsi   = float(last.get("rsi_14", 50.0))
        bb_lo = float(last.get("bb_lower", close * 0.98))
        bb_hi = float(last.get("bb_upper", close * 1.02))
        bb_mi = float(last.get("bb_middle", close))
        adx   = float(last.get("adx", 20.0))

        # ── Momentum sub-signal ───────────────────────────────────────────────
        ref_close  = float(df["close"].iloc[-1 - mom_p])
        momentum   = (close - ref_close) / (ref_close + 1e-10)
        mom_bull   = momentum > 0
        mom_bear   = momentum < 0
        mom_score  = min(abs(momentum) * 5.0, 1.0)   # 0–1

        # ── Mean-Reversion sub-signal ─────────────────────────────────────────
        mr_long    = rsi < rsi_os and close <= bb_lo * 1.005
        mr_short   = rsi > rsi_ob and close >= bb_hi * 0.995

        # MR confidence
        if mr_long:
            rsi_score = max(0.0, (rsi_os - rsi) / rsi_os)
            bb_score  = max(0.0, (bb_lo - close) / (bb_mi - bb_lo + 1e-8))
            mr_score  = min(rsi_score + bb_score, 1.0)
        elif mr_short:
            rsi_score = max(0.0, (rsi - rsi_ob) / (100 - rsi_ob))
            bb_score  = max(0.0, (close - bb_hi) / (bb_hi - bb_mi + 1e-8))
            mr_score  = min(rsi_score + bb_score, 1.0)
        else:
            mr_score  = 0.0

        sl_m = float(self.params["atr_sl_mult"])
        tp_m = float(self.params["atr_tp_mult"])

        # ── STRONG BUY: momentum up + MR oversold (both agree) ───────────────
        if mom_bull and mr_long:
            conf = min(0.90, 0.55 + 0.20 * mom_score + 0.25 * mr_score)
            sl = close - sl_m * atr
            tp = close + tp_m * atr
            return Signal(
                SignalType.BUY, conf, sl, tp,
                metadata={"type": "STRONG_BUY", "mom": momentum, "rsi": rsi},
            )

        # ── STRONG SELL: momentum down + MR overbought (both agree) ──────────
        if mom_bear and mr_short:
            conf = min(0.90, 0.55 + 0.20 * mom_score + 0.25 * mr_score)
            sl = close + sl_m * atr
            tp = close - tp_m * atr
            return Signal(
                SignalType.SELL, conf, sl, tp,
                metadata={"type": "STRONG_SELL", "mom": momentum, "rsi": rsi},
            )

        # ── Momentum-only BUY (MR not triggering, RSI not overbought) ────────
        if mom_bull and rsi < rsi_ob and mom_score > 0.3:
            conf = min(0.78, 0.48 + 0.20 * mom_score)
            sl = close - sl_m * atr
            tp = close + tp_m * atr
            return Signal(
                SignalType.BUY, conf, sl, tp,
                metadata={"type": "MOM_BUY", "mom": momentum, "rsi": rsi},
            )

        # ── Momentum-only SELL (MR not triggering, RSI not oversold) ─────────
        if mom_bear and rsi > rsi_os and mom_score > 0.3:
            conf = min(0.78, 0.48 + 0.20 * mom_score)
            sl = close + sl_m * atr
            tp = close - tp_m * atr
            return Signal(
                SignalType.SELL, conf, sl, tp,
                metadata={"type": "MOM_SELL", "mom": momentum, "rsi": rsi},
            )

        return Signal(SignalType.HOLD, 0.0)
