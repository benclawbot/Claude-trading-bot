"""
Strategy 2: MACD Momentum
─────────────────────────
Entry LONG  : MACD line crosses ABOVE signal AND price > EMA200 (uptrend filter)
Entry SHORT : MACD line crosses BELOW signal AND price < EMA200 (downtrend filter)
Exit        : Opposite crossover OR trailing stop hit
Stop-loss   : 1.5× ATR below/above entry
Take-profit : 3× ATR above/below entry (favourable R:R)
Best suited for: trending markets (ADX > 25)
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class MACDMomentumStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS["MACD_Momentum"].copy()
        if params:
            defaults.update(params)
        super().__init__("MACD_Momentum", defaults)

    @property
    def min_candles(self) -> int:
        return self.params["trend_ema"] + 50

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "1h")

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        close = float(last["close"])
        atr   = float(last.get("atr_14", close * 0.015))

        macd_now   = float(last.get("macd", 0))
        signal_now = float(last.get("macd_signal", 0))
        macd_prev  = float(prev.get("macd", 0))
        signal_prev = float(prev.get("macd_signal", 0))
        hist_now   = float(last.get("macd_hist", 0))

        ema200 = float(last.get("ema_200", close))
        adx    = float(last.get("adx", 20))

        # Require some trend strength
        if adx < 18:
            return Signal(SignalType.HOLD, 0.2, metadata={"reason": "Low ADX, weak trend"})

        # ── Bullish crossover ─────────────────────────────────────────────────
        bullish_cross = (macd_prev <= signal_prev) and (macd_now > signal_now)
        if bullish_cross and close > ema200:
            confidence = self._confidence_from_histogram(hist_now, close, adx, long=True)
            sl = close - 1.5 * atr
            tp = close + 3.0 * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"macd": macd_now, "macd_signal": signal_now,
                          "histogram": hist_now, "adx": adx}
            )

        # ── Bearish crossover ─────────────────────────────────────────────────
        bearish_cross = (macd_prev >= signal_prev) and (macd_now < signal_now)
        if bearish_cross and close < ema200:
            confidence = self._confidence_from_histogram(hist_now, close, adx, long=False)
            sl = close + 1.5 * atr
            tp = close - 3.0 * atr
            return Signal(
                SignalType.SELL, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"macd": macd_now, "macd_signal": signal_now,
                          "histogram": hist_now, "adx": adx}
            )

        return Signal(SignalType.HOLD, 0.0)

    @staticmethod
    def _confidence_from_histogram(hist: float, close: float,
                                   adx: float, long: bool) -> float:
        """Stronger histogram divergence + higher ADX = more confidence."""
        hist_pct = abs(hist) / (close * 0.001 + 1e-8)          # normalize
        hist_score = min(hist_pct / 3.0, 1.0)
        adx_score  = min((adx - 18) / 40.0, 1.0)
        confidence = 0.50 + 0.30 * hist_score + 0.20 * adx_score
        return min(confidence, 0.93)
