"""
Strategy 5: Residual Mean Reversion (BTC-Neutral)
───────────────────────────────────────────────────
Research source: Medium – BTC-neutral residual mean reversion, Sharpe ~2.3 (post-2021)

The original paper strips out BTC market-beta by trading altcoin residuals
relative to BTC. Since this bot trades BTCUSDT only, we approximate that
concept by:
  1. Computing BTC's own rolling log-price trend via a 60-candle OLS regression
  2. Computing the residual  =  actual log-price – OLS-predicted log-price
  3. Standardising the residual to a z-score over a 30-candle rolling window

Signal logic (4h candles):
  Entry LONG  : z-score < -THRESH  (BTC is below its own trend → oversold)
  Entry SHORT : z-score > +THRESH  (BTC is above its own trend → overbought)
  Exit        : z-score crosses back through zero, SL or TP hit

NOTE: On-chain metrics (NVT, MVRV, Glassnode data) are NOT available via the
Binance REST API. This detrended z-score is the closest practical proxy that
can be computed from price alone. It captures the same mean-reversion alpha:
BTC oscillates around its trend, and large deviations tend to revert.
"""

import numpy as np
import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


def _rolling_ols_residuals(log_prices: pd.Series, reg_window: int) -> pd.Series:
    """
    For each point i, fit OLS on log_prices[i-reg_window : i] and return
    the residual at point i  (actual – predicted last value of the regression).
    Returns a Series of the same length with NaN for the first reg_window rows.
    """
    residuals = np.full(len(log_prices), np.nan)
    x = np.arange(reg_window, dtype=float)
    x_mean = x.mean()
    x_var  = ((x - x_mean) ** 2).sum()

    for i in range(reg_window, len(log_prices)):
        y = log_prices.iloc[i - reg_window: i].values.astype(float)
        if np.isnan(y).any():
            continue
        y_mean = y.mean()
        slope  = np.dot(x - x_mean, y - y_mean) / (x_var + 1e-12)
        intercept = y_mean - slope * x_mean
        predicted = slope * (reg_window - 1) + intercept
        residuals[i] = y[-1] - predicted   # actual last – predicted last

    return pd.Series(residuals, index=log_prices.index)


class ResidualMeanReversionStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("Residual_MeanRev", {
            "reg_window":      60,     # OLS regression lookback
            "zscore_window":   30,     # window for z-score normalisation
            "entry_threshold": 1.5,    # |z| > this → signal
            "atr_sl_mult":     1.8,
            "atr_tp_mult":     3.5,
            "candle_interval": "4h",
        })
        if params:
            defaults.update(params)
        super().__init__("Residual_MeanRev", defaults)

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        return int(self.params["reg_window"]) + int(self.params["zscore_window"]) + 5

    @property
    def max_hold_candles(self) -> int:
        return 48   # 48 × 4h = 192 h ≈ 8 days; residuals mean-revert quickly

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "4h")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        reg_w   = int(self.params["reg_window"])
        zs_w    = int(self.params["zscore_window"])
        thresh  = float(self.params["entry_threshold"])

        log_px   = np.log(df["close"])
        residuals = _rolling_ols_residuals(log_px, reg_w)

        # Rolling z-score of the residuals
        roll_mean = residuals.rolling(zs_w).mean()
        roll_std  = residuals.rolling(zs_w).std()
        zscore    = (residuals - roll_mean) / (roll_std + 1e-10)

        cur_z  = float(zscore.iloc[-1])
        prv_z  = float(zscore.iloc[-2])
        close  = float(df["close"].iloc[-1])
        atr    = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else close * 0.015

        if not np.isfinite(cur_z) or not np.isfinite(prv_z):
            return Signal(SignalType.HOLD, 0.0)

        sl_m = float(self.params["atr_sl_mult"])
        tp_m = float(self.params["atr_tp_mult"])

        # Confidence: how far z-score is beyond threshold
        excess     = abs(cur_z) - thresh
        confidence = min(0.90, 0.50 + excess * 0.15)

        # ── Oversold: z < -threshold (BTC below its trend) ───────────────────
        if cur_z < -thresh and prv_z >= -thresh:
            sl = close - sl_m * atr
            tp = close + tp_m * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"zscore": cur_z, "residual": float(residuals.iloc[-1])},
            )

        # ── Overbought: z > +threshold (BTC above its trend) ─────────────────
        if cur_z > thresh and prv_z <= thresh:
            sl = close + sl_m * atr
            tp = close - tp_m * atr
            return Signal(
                SignalType.SELL, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"zscore": cur_z, "residual": float(residuals.iloc[-1])},
            )

        return Signal(SignalType.HOLD, 0.0)
