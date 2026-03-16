"""
Strategy 4: Volume-Confirmed Breakout
──────────────────────────────────────
Entry LONG  : Close breaks above rolling 24-candle HIGH with volume > N× average
Entry SHORT : Close breaks below rolling 24-candle LOW  with volume > N× average
Stop-loss   : ATR-based (below the breakout candle low / above high)
Take-profit : 2.5× ATR from entry (momentum trade)
Avoid       : Re-testing after a failed breakout within 3 candles
Best suited for: volatile breakout phases with high volume confirmation.
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class BreakoutStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS["Breakout"].copy()
        if params:
            defaults.update(params)
        super().__init__("Breakout", defaults)
        self._last_signal_candle: int = -999   # prevent re-entry

    @property
    def min_candles(self) -> int:
        return self.params["lookback"] + self.params["atr_period"] + 10

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "4h")

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        lb   = int(self.params["lookback"])
        vmul = float(self.params["volume_multiplier"])

        last  = df.iloc[-1]
        prev  = df.iloc[-2]          # candle just before current
        close = float(last["close"])
        high  = float(last["high"])
        low   = float(last["low"])
        atr   = float(last.get("atr_14", close * 0.015))
        vol_r = float(last.get("volume_ratio", 1.0))

        # Rolling high/low over the lookback window EXCLUDING the current candle
        rolling_high = float(df["high"].iloc[-(lb+1):-1].max())
        rolling_low  = float(df["low"].iloc[-(lb+1):-1].min())

        current_idx = len(df)
        since_last  = current_idx - self._last_signal_candle

        # Cool-down: no new signals within 3 candles of last signal
        if since_last < 3:
            return Signal(SignalType.HOLD, 0.0, metadata={"reason": "Cool-down period"})

        # Volume must be elevated
        if vol_r < vmul:
            return Signal(SignalType.HOLD, 0.0, metadata={"reason": "Insufficient volume"})

        # ── Upside Breakout ────────────────────────────────────────────────────
        if close > rolling_high and prev["close"] <= rolling_high:
            self._last_signal_candle = current_idx
            confidence = self._calc_confidence(vol_r, vmul, atr, close, long=True)
            sl = low - 0.5 * atr               # just below candle low
            tp = close + 2.5 * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"rolling_high": rolling_high, "volume_ratio": vol_r,
                          "atr": atr, "breakout_pct": (close - rolling_high) / rolling_high}
            )

        # ── Downside Breakdown ─────────────────────────────────────────────────
        if close < rolling_low and prev["close"] >= rolling_low:
            self._last_signal_candle = current_idx
            confidence = self._calc_confidence(vol_r, vmul, atr, close, long=False)
            sl = high + 0.5 * atr              # just above candle high
            tp = close - 2.5 * atr
            return Signal(
                SignalType.SELL, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"rolling_low": rolling_low, "volume_ratio": vol_r,
                          "atr": atr, "breakout_pct": (rolling_low - close) / rolling_low}
            )

        return Signal(SignalType.HOLD, 0.0)

    @staticmethod
    def _calc_confidence(vol_ratio: float, vol_threshold: float,
                         atr: float, close: float, long: bool) -> float:
        vol_excess = min((vol_ratio - vol_threshold) / vol_threshold, 1.0)
        atr_score  = min(atr / (close * 0.02), 1.0)    # higher vol = more momentum
        confidence = 0.52 + 0.30 * vol_excess + 0.18 * atr_score
        return min(confidence, 0.91)
