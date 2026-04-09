"""
Strategy 2: Dual Moving Average Crossover (100/250 SMA)
────────────────────────────────────────────────────────
Research source: Quantified Strategies – 100/250 SMA crossover on Bitcoin
Backtested CAGR: ~115%  |  Max drawdown: ~39%

Signal logic (daily candles):
  Entry LONG  : SMA-100 crosses ABOVE SMA-250  (golden cross – long-term bull)
  Entry SHORT : SMA-100 crosses BELOW SMA-250  (death  cross – long-term bear)
  Exit        : SL/TP hit, or opposite crossover

More stable than the 5-day EMA: fewer signals, less whipsaw risk.
Requires BACKTEST_DAYS >= 300 to warm up SMA-250 properly.
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class DualMACrossoverStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("DualMA_Crossover", {
            "fast_period":     20,
            "slow_period":     60,
            "atr_sl_mult":     2.0,
            "atr_tp_mult":     4.5,
            "candle_interval": "4h",
        })
        if params:
            defaults.update(params)
        super().__init__("DualMA_Crossover", defaults)

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        return int(self.params["slow_period"]) + 5   # SMA-250 needs 250 candles + buffer

    @property
    def max_hold_candles(self) -> int:
        return 180   # 180 daily candles ≈ 6 months – captures full trend moves

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "1d")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        close = df["close"]
        fast  = int(self.params["fast_period"])
        slow  = int(self.params["slow_period"])

        sma_fast = close.rolling(fast).mean()
        sma_slow = close.rolling(slow).mean()

        cur_close  = float(close.iloc[-1])
        cur_fast   = float(sma_fast.iloc[-1])
        cur_slow   = float(sma_slow.iloc[-1])
        prv_fast   = float(sma_fast.iloc[-2])
        prv_slow   = float(sma_slow.iloc[-2])

        atr = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else cur_close * 0.015

        # Check current and previous MA relationship
        fast_above_now  = cur_fast > cur_slow
        fast_above_prev = prv_fast > prv_slow

        # Spread as % of price – used for confidence
        spread_pct = abs(cur_fast - cur_slow) / (cur_slow + 1e-10)
        confidence = min(0.90, 0.50 + spread_pct * 20.0)

        sl_m = float(self.params["atr_sl_mult"])
        tp_m = float(self.params["atr_tp_mult"])

        # ── Golden Cross: SMA100 just crossed above SMA250 ───────────────────
        if fast_above_now and not fast_above_prev:
            sl = cur_close - sl_m * atr
            tp = cur_close + tp_m * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={
                    "sma_fast": cur_fast, "sma_slow": cur_slow,
                    "spread_pct": spread_pct,
                },
            )

        # ── Death Cross: SMA100 just crossed below SMA250 ────────────────────
        if not fast_above_now and fast_above_prev:
            sl = cur_close + sl_m * atr
            tp = cur_close - tp_m * atr
            return Signal(
                SignalType.SELL, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={
                    "sma_fast": cur_fast, "sma_slow": cur_slow,
                    "spread_pct": spread_pct,
                },
            )

        return Signal(SignalType.HOLD, 0.0)
