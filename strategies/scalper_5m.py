"""
Strategy template: 5m Scalper (experiment lane)
──────────────────────────────────────────────
Entry LONG  : EMA fast above EMA slow, RSI < threshold, volume expansion.
Entry SHORT : EMA fast below EMA slow, RSI > threshold, volume expansion.
Exit        : ATR-based SL/TP.
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class Scalper5mStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS["Scalper_5m"].copy()
        if params:
            defaults.update(params)
        super().__init__("Scalper_5m", defaults)

    @property
    def min_candles(self) -> int:
        return max(self.params.get("ema_slow", 21) + 20, 60)

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "5m")

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        last = df.iloc[-1]
        close = float(last["close"])
        atr = float(last.get("atr_14", close * 0.004))

        ema_fast = float(last.get(f"ema_{self.params['ema_fast']}", close))
        ema_slow = float(last.get(f"ema_{self.params['ema_slow']}", close))
        rsi = float(last.get("rsi_14", 50.0))
        vol_ratio = float(last.get("volume_ratio", 1.0))

        trend_bias = (ema_fast - ema_slow) / (abs(ema_slow) + 1e-8)
        volume_ok = vol_ratio >= float(self.params.get("volume_ratio_min", 1.15))

        if ema_fast > ema_slow and rsi <= float(self.params.get("rsi_long_max", 45)) and volume_ok:
            confidence = min(0.45 + max(0.0, trend_bias) * 30 + (vol_ratio - 1.0) * 0.2, 0.88)
            return Signal(
                SignalType.BUY,
                confidence,
                stop_loss=close - atr * float(self.params.get("atr_sl_mult", 0.8)),
                take_profit=close + atr * float(self.params.get("atr_tp_mult", 1.2)),
                metadata={"rsi": rsi, "volume_ratio": vol_ratio, "trend_bias": trend_bias},
            )

        if ema_fast < ema_slow and rsi >= float(self.params.get("rsi_short_min", 55)) and volume_ok:
            confidence = min(0.45 + max(0.0, -trend_bias) * 30 + (vol_ratio - 1.0) * 0.2, 0.88)
            return Signal(
                SignalType.SELL,
                confidence,
                stop_loss=close + atr * float(self.params.get("atr_sl_mult", 0.8)),
                take_profit=close - atr * float(self.params.get("atr_tp_mult", 1.2)),
                metadata={"rsi": rsi, "volume_ratio": vol_ratio, "trend_bias": trend_bias},
            )

        return Signal(SignalType.HOLD, 0.0)
