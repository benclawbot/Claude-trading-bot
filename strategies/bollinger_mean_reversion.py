"""
Strategy 14: Hourly Bollinger-Band Mean Reversion
──────────────────────────────────────────────────
Research source : 2025 thesis, Bitcoin hourly data (31 Oct 2020 – 3 Nov 2025)
Original benchmarks (gross, 0 % fees):
  Mean reversion : €382,096  (3,720.96 % gross return)
  Buy-and-hold    : €79,792   (697.92 %)
  Momentum        : €49,413

Reported hourly mean-reversion metrics (from thesis):
  Annual return : 106.8%
  Volatility    : 44.35%
  Sharpe        : 1.86
  Max drawdown  : -35.6%

With 0.1 % fee per trade (realistic Binance spot):
  Annual return drops to ~74.8%
  Terminal value ~€221,000 (still ~2.8× buy-and-hold)

Rules applied (exact from thesis):
  1. Use hourly candles.
  2. Compute 20-period Bollinger Bands with 2 standard deviations.
  3. Enter LONG when the hourly closing price falls below the lower band.
  4. Exit when price crosses back above the middle band (20-period SMA).
  5. Long only. No shorting.

Fee warning (from thesis):
  The edge is highly fee-sensitive. At 0.4 % per trade the edge nearly
  disappears. This strategy is best run on Binance spot (0.1 % maker/taker)
  or a venue with similarly low fees.

The bot implements ATR-based stop-loss and take-profit since the original
thesis does not specify them; levels are tuned for live trading.
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class BollingerMeanRevStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("Bollinger_MeanRev", {
            # ── Bollinger Band parameters (from thesis) ─────────────────────────
            "bb_period":      20,      # 20-period BB (exact from thesis)
            "bb_std":         2.0,     # 2 std dev (exact from thesis)
            # ── Risk: ATR-based SL/TP ──────────────────────────────────────────
            "atr_sl_mult":    2.5,     # stop-loss  : entry − 2.5 × ATR(14)
            "atr_tp_mult":    5.0,     # take-profit: entry + 5.0 × ATR(14)
            # ── Execution interval ─────────────────────────────────────────────
            "candle_interval": "1h",   # hourly candles (exact from thesis)
        })
        if params:
            defaults.update(params)
        super().__init__("Bollinger_MeanRev", defaults)

    # ── Interface ──────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        # Need at least bb_period candles for the BB middle band to exist,
        # plus a few extras for cross-back check
        return int(self.params["bb_period"]) + 5

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "1h")

    @property
    def max_hold_candles(self) -> int:
        # Thesis traded ~423 times over 5 years on hourly data ≈ 1 trade / 83 h
        # Max hold of 144 candles (6 days on hourly) prevents indefinite holding
        return 144

    # ── Signal generation ──────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        bb_period = int(self.params["bb_period"])

        # Current candle
        cur  = df.iloc[-1]
        prev = df.iloc[-2]

        close      = float(cur["close"])
        bb_upper   = float(cur.get("bb_upper", close * 1.02))
        bb_middle  = float(cur.get("bb_middle", close))
        bb_lower   = float(cur.get("bb_lower", close * 0.98))

        prev_close = float(prev["close"])

        # ATR for SL/TP sizing
        atr = float(cur.get("atr_14", close * 0.015))
        sl_mult = float(self.params["atr_sl_mult"])
        tp_mult = float(self.params["atr_tp_mult"])

        # ── Entry LONG: close crosses below lower band ────────────────────────
        # (exact rule 3 from thesis)
        if close < bb_lower and prev_close >= bb_lower:
            # Confidence based on how far below the lower band we are
            band_width = bb_upper - bb_lower + 1e-10
            overshoot   = (bb_lower - close) / band_width  # 0 = at band, 1 = deep below
            # Scale confidence: deeper below band → higher confidence
            confidence  = min(0.90, 0.50 + overshoot * 0.30)
            # Cap SL to avoid being stopped on normal volatility
            sl  = close - sl_mult * atr
            tp  = close + tp_mult * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={
                    "bb_lower":   bb_lower,
                    "bb_middle":  bb_middle,
                    "bb_upper":   bb_upper,
                    "overshoot":  round(overshoot, 4),
                    "atr_14":     atr,
                },
            )

        # ── Exit LONG: close crosses back above middle band ───────────────────
        # (exact rule 4 from thesis)
        if close > bb_middle and prev_close <= bb_middle:
            # No confidence needed for exit – market has spoken
            return Signal(
                SignalType.SELL, 1.0,
                metadata={
                    "exit_reason": "bb_middle_cross",
                    "bb_middle":   bb_middle,
                },
            )

        return Signal(SignalType.HOLD, 0.0)
