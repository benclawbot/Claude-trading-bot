"""
Strategy 8: BTC Momentum Breakout
──────────────────────────────────
Source  : Vault — BTC momentum breakout (backtested 2018-2026)
          https://www.obsidian.md/claude#BTC+momentum+breakout

Edge hypothesis:
  BTC's best repeatable edge is NOT predicting tops/bottoms, but capturing
  confirmed bullish breakouts where BOTH trend direction AND momentum confirm.
  Specifically:
    1. Trend filter     → only enter when above 200d SMA (bull regime)
    2. Breakout confirm → price must break 20d high (structural breakout)
    3. Volume confirm   → volume > 1.2× its 20d moving average

Exit rules (any triggers close the position):
    • Close < 10d low  (trailing stop — locks in gains fast)
    • Close < 50d SMA  (trend exit — trend is over)
    • Hard stop at -8% (risk cap — max loss per trade)

Backtest results (2018-01-01 → 2026-04-22):
    Total return : +1748%  vs B&H +487%
    CAGR         : +42.1%  vs B&H ~33%
    Max drawdown : -34.6%
    Out-of-sample (2023+): positive but underperforms B&H in pure return
                           — compensated by much lower drawdown

Notes:
  • LONG-only (no short entries — aligns with bull-regime filter)
  • Daily candles (1d) — captures multi-day trend moves
  • Confidence is a blend of volume excess + ATR momentum + trend alignment
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class BTCMomentumBreakoutStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("BTC_MomentumBreakout", {
            # ── Entry filters ───────────────────────────────────────────────
            "sma_trend":          200,   # trend filter: close must be above this SMA
            "breakout_lookback":   20,   # breakout: close must exceed N-day rolling high
            "volume_ma_period":    20,   # volume confirm: volume > N-day volume MA
            "volume_mult":        1.2,   # volume must exceed N × its MA
            # ── Exit triggers ───────────────────────────────────────────────
            "exit_low_period":    10,   # exit if close < N-day rolling low
            "sma_exit_period":    50,   # exit if close < N-day SMA
            "hard_stop_pct":     0.08,   # -8% hard stop from entry
            # ── Risk / reward ────────────────────────────────────────────────
            "atr_tp_mult":       3.0,   # take-profit = entry + N × ATR
            "atr_sl_mult":       1.5,   # supplementary ATR-based SL (tighter than hard stop)
            "candle_interval":  "1d",
        })
        if params:
            defaults.update(params)
        super().__init__("BTC_MomentumBreakout", defaults)
        self._in_position: bool = False   # track whether we hold a live position

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        p = self.params
        return max(
            int(p["sma_trend"]) + 5,
            int(p["breakout_lookback"]) + 2,
            int(p["exit_low_period"]) + 2,
            int(p["sma_exit_period"]) + 2,
        )

    @property
    def max_hold_candles(self) -> int:
        """60 daily candles ≈ 2 months — long enough for trend trades."""
        return 60

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "1d")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        p       = self.params
        close   = float(df["close"].iloc[-1])
        prev_cl = float(df["close"].iloc[-2])
        high    = float(df["high"].iloc[-1])
        low     = float(df["low"].iloc[-1])
        volume  = float(df["volume"].iloc[-1])

        sma_trend   = float(df["ema_200"].iloc[-1])   if "ema_200"  in df.columns else float("nan")
        sma_exit    = float(df["sma_50"].iloc[-1])    if "sma_50"   in df.columns else float("nan")
        vol_ma      = float(df["volume_sma_20"].iloc[-1]) if "volume_sma_20" in df.columns else float("nan")
        rh_20       = float(df["rolling_close_high_20"].iloc[-1]) if "rolling_close_high_20" in df.columns else float("nan")
        prev_rh_20  = float(df["rolling_close_high_20"].iloc[-2]) if "rolling_close_high_20" in df.columns else float("nan")
        rl_10       = float(df["rolling_low_10"].iloc[-1])  if "rolling_low_10"  in df.columns else float("nan")
        atr         = float(df["atr_14"].iloc[-1])   if "atr_14"  in df.columns else close * 0.02
        vol_ratio   = float(df["volume_ratio"].iloc[-1]) if "volume_ratio" in df.columns else 1.0

        atr_tp_mult = float(p["atr_tp_mult"])
        atr_sl_mult = float(p["atr_sl_mult"])
        vol_mult    = float(p["volume_mult"])

        # ── EXIT SIGNAL ────────────────────────────────────────────────────
        if self._in_position:
            exit_triggered = False
            exit_reason    = ""

            # Rule 1: close < 10-day rolling low
            if not pd.isna(rl_10) and close < rl_10:
                exit_triggered = True
                exit_reason    = f"close {close:.0f} < 10d-low {rl_10:.0f}"

            # Rule 2: close < 50-day SMA
            elif not pd.isna(sma_exit) and close < sma_exit:
                exit_triggered = True
                exit_reason    = f"close {close:.0f} < 50d-SMA {sma_exit:.0f}"

            if exit_triggered:
                self._in_position = False
                return Signal(
                    SignalType.SELL, 0.95,
                    metadata={"exit_reason": exit_reason},
                )

        # ── ENTRY SIGNAL ────────────────────────────────────────────────────
        if not self._in_position:
            # Trend filter: close must be above 200d SMA
            if pd.isna(sma_trend) or close <= sma_trend:
                return Signal(SignalType.HOLD, 0.0,
                              metadata={"reason": f"below 200d SMA {sma_trend:.0f}"})

            # Breakout: close exceeds the 20d close-high from PRIOR candle (= max close ending yesterday)
            # (prev_rh_20 is rolling max of closes over 20 days ending yesterday)
            if pd.isna(prev_rh_20):
                return Signal(SignalType.HOLD, 0.0,
                              metadata={"reason": "rolling_close_high_20 not available"})

            if close <= prev_rh_20:
                return Signal(SignalType.HOLD, 0.0,
                              metadata={"reason": f"close {close:.0f} <= 20d-close-high {prev_rh_20:.0f}"})

            # Volume confirmation: volume > 1.2 × 20d volume MA
            if vol_ratio < vol_mult:
                return Signal(SignalType.HOLD, 0.0,
                              metadata={"reason": f"vol_ratio {vol_ratio:.2f} < {vol_mult}× MA"})

            # ── Build signal ────────────────────────────────────────────────
            self._in_position = True

            # Hard stop at -8% (primary risk control)
            hard_sl   = close * (1 - float(p["hard_stop_pct"]))
            # Supplementary ATR-based SL (usually tighter than -8%)
            atr_sl    = close - atr_sl_mult * atr
            stop_loss = max(hard_sl, atr_sl)   # use the one that gives MORE room

            take_profit = close + atr_tp_mult * atr

            # Confidence scoring
            vol_excess   = min((vol_ratio - vol_mult) / vol_mult, 1.0)
            atr_score    = min(atr / (close * 0.015), 1.0)
            trend_score  = min((close - sma_trend) / (sma_trend * 0.05), 1.0) if sma_trend > 0 else 0.0
            confidence   = min(0.88, 0.45 + 0.25 * vol_excess + 0.20 * atr_score + 0.10 * trend_score)

            return Signal(
                SignalType.BUY, confidence,
                stop_loss=stop_loss,
                take_profit=take_profit,
                metadata={
                    "ema_200":      sma_trend,
                    "prev_rh_20":   prev_rh_20,
                    "vol_ratio":    vol_ratio,
                    "atr":          atr,
                    "breakout_pct": (close - prev_rh_20) / (prev_rh_20 + 1e-10),
                    "sl_hard":      hard_sl,
                    "atr_sl":       atr_sl,
                    "tp_atr_mult":  atr_tp_mult,
                },
            )

        # In position, no exit triggered
        return Signal(SignalType.HOLD, 0.0)

    # ── Called by portfolio manager after trade is recorded ──────────────────
    def record_trade_outcome(self, won: bool):
        super().record_trade_outcome(won)
        self._in_position = False
