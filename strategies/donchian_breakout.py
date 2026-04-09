"""
Strategy 6: Donchian Channel Breakout + Inverse ADX Filter
────────────────────────────────────────────────────────────
Research source: Quantified Strategies – Donchian breakout on BTC/USD (back to 2015)
Key finding: 15-day lookback offers the best risk/reward; ALL lookback periods
             5–100 days were profitable.
INVERSE ADX FILTER: enter when ADX < threshold (market is CALM / consolidating),
contrary to the typical "trade only in trends" usage. This catches breakouts
EARLY – before the trend fully develops and ADX rises. This uniquely improved
backtested results vs standard ADX filters.

Signal logic (daily candles):
  Entry LONG  : close > previous Donchian upper  AND  ADX < adx_calm_max
  Entry SHORT : close < previous Donchian lower  AND  ADX < adx_calm_max
  Exit        : SL/TP hit or max-hold reached

Using the PREVIOUS candle's Donchian levels avoids look-ahead bias.
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class DonchianBreakoutStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("Donchian_Breakout", {
            "dc_period":       20,     # Donchian channel lookback (days)
            "adx_calm_max":    99,     # effectively disabled
            "atr_sl_mult":     2.0,
            "atr_tp_mult":     5.0,
            "candle_interval": "1d",
        })
        if params:
            defaults.update(params)
        super().__init__("Donchian_Breakout", defaults)

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        return int(self.params["dc_period"]) + 20   # Donchian + ADX warm-up

    @property
    def max_hold_candles(self) -> int:
        return 60   # 60 daily candles ≈ 2 months

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "1d")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        dc  = int(self.params["dc_period"])
        adx_max = float(self.params["adx_calm_max"])

        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        # Donchian channel using PREVIOUS candle's window (no look-ahead)
        # upper = max of [high] over dc candles ending at -2 (exclude current)
        dc_upper = float(high.iloc[-1 - dc: -1].max())
        dc_lower = float(low.iloc[-1 - dc: -1].min())

        cur_close = float(close.iloc[-1])
        prv_close = float(close.iloc[-2])
        adx       = float(df["adx"].iloc[-1]) if "adx" in df.columns else 20.0
        atr       = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else cur_close * 0.02

        # Inverse ADX filter: only trade when market is calm (low ADX)
        if adx >= adx_max:
            return Signal(SignalType.HOLD, 0.0,
                          metadata={"reason": f"ADX {adx:.1f} too high (inverse filter)"})

        sl_m = float(self.params["atr_sl_mult"])
        tp_m = float(self.params["atr_tp_mult"])

        # ── Upside breakout: close > previous Donchian upper ─────────────────
        if cur_close > dc_upper and prv_close <= dc_upper:
            breakout_pct = (cur_close - dc_upper) / (dc_upper + 1e-10)
            # Less ADX = quieter market = potentially bigger breakout to come
            adx_bonus  = max(0.0, (adx_max - adx) / adx_max)
            confidence = min(0.90, 0.50 + breakout_pct * 10 + 0.15 * adx_bonus)

            sl = cur_close - sl_m * atr
            tp = cur_close + tp_m * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={
                    "dc_upper": dc_upper, "dc_lower": dc_lower,
                    "adx": adx, "breakout_pct": breakout_pct,
                },
            )

        # ── Downside breakout: close < previous Donchian lower ───────────────
        if cur_close < dc_lower and prv_close >= dc_lower:
            breakdown_pct = (dc_lower - cur_close) / (dc_lower + 1e-10)
            adx_bonus     = max(0.0, (adx_max - adx) / adx_max)
            confidence    = min(0.90, 0.50 + breakdown_pct * 10 + 0.15 * adx_bonus)

            sl = cur_close + sl_m * atr
            tp = cur_close - tp_m * atr
            return Signal(
                SignalType.SELL, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={
                    "dc_upper": dc_upper, "dc_lower": dc_lower,
                    "adx": adx, "breakdown_pct": breakdown_pct,
                },
            )

        return Signal(SignalType.HOLD, 0.0)
