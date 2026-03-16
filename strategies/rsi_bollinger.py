"""
Strategy 1: RSI + Bollinger Bands Mean-Reversion
────────────────────────────────────────────────
Entry LONG  : RSI < oversold_threshold AND close <= BB lower band (± 0.5%)
Entry SHORT : RSI > overbought_threshold AND close >= BB upper band (± 0.5%)
Exit        : RSI returns to 50 OR opposite BB extreme reached
Stop-loss   : 2.5% below/above entry
Take-profit : 5.5% above/below entry
Best suited for: ranging / low-ADX markets
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class RSIBollingerStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS["RSI_Bollinger"].copy()
        if params:
            defaults.update(params)
        super().__init__("RSI_Bollinger", defaults)

    @property
    def min_candles(self) -> int:
        return max(self.params["rsi_period"], self.params["bb_period"]) * 3

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "4h")

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        last    = df.iloc[-1]
        prev    = df.iloc[-2]
        close   = float(last["close"])
        rsi     = float(last.get("rsi_14", 50))
        bb_low  = float(last.get("bb_lower", close * 0.98))
        bb_high = float(last.get("bb_upper", close * 1.02))
        bb_mid  = float(last.get("bb_middle", close))
        adx     = float(last.get("adx", 20))

        oversold    = float(self.params["rsi_oversold"])
        overbought  = float(self.params["rsi_overbought"])
        sl_pct      = config.DEFAULT_STOP_LOSS_PCT
        tp_pct      = config.DEFAULT_TAKE_PROFIT_PCT

        # Avoid trading in strongly trending markets (mean-reversion works in ranging)
        if adx > 40:
            return Signal(SignalType.HOLD, 0.3, metadata={"reason": "High ADX, not ideal for mean-reversion"})

        # ── Long entry ────────────────────────────────────────────────────────
        if rsi < oversold and close <= bb_low * 1.005:
            # Stronger signal if previous candle also shows weakness then recovery
            confidence = self._calc_long_confidence(rsi, oversold, close, bb_low, bb_mid)
            sl  = close * (1 - sl_pct)
            tp  = close * (1 + tp_pct)
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"rsi": rsi, "bb_pct": float(last.get("bb_pct", 0)), "adx": adx}
            )

        # ── Short entry ───────────────────────────────────────────────────────
        if rsi > overbought and close >= bb_high * 0.995:
            confidence = self._calc_short_confidence(rsi, overbought, close, bb_high, bb_mid)
            sl  = close * (1 + sl_pct)
            tp  = close * (1 - tp_pct)
            return Signal(
                SignalType.SELL, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"rsi": rsi, "bb_pct": float(last.get("bb_pct", 0)), "adx": adx}
            )

        return Signal(SignalType.HOLD, 0.0)

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_long_confidence(rsi: float, threshold: float,
                              close: float, bb_lower: float,
                              bb_mid: float) -> float:
        rsi_score  = max(0.0, (threshold - rsi) / threshold)          # 0–1
        bb_score   = max(0.0, (bb_lower - close) / (bb_mid - bb_lower + 1e-8))
        bb_score   = min(bb_score, 1.0)
        confidence = 0.45 + 0.35 * rsi_score + 0.20 * bb_score
        return min(confidence, 0.95)

    @staticmethod
    def _calc_short_confidence(rsi: float, threshold: float,
                               close: float, bb_upper: float,
                               bb_mid: float) -> float:
        rsi_score = max(0.0, (rsi - threshold) / (100 - threshold))
        bb_score  = max(0.0, (close - bb_upper) / (bb_upper - bb_mid + 1e-8))
        bb_score  = min(bb_score, 1.0)
        confidence = 0.45 + 0.35 * rsi_score + 0.20 * bb_score
        return min(confidence, 0.95)
