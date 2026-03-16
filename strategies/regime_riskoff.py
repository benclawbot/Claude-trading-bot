"""
Strategy 3: Risk-On / Risk-Off Regime Model
────────────────────────────────────────────
Research source: Menthor Q – Binary risk signal on ETH (long/short ~100-200% over 1 year)
Backtested CAGR: variable, high (beats buy-and-hold significantly in bear markets)

Signal logic (4h candles):
  Regime = RISK-ON  when price > EMA200 AND MACD histogram > 0 AND RSI > 50
  Regime = RISK-OFF when price < EMA200 AND MACD histogram < 0 AND RSI < 50

  Entry LONG  : regime switches to RISK-ON
  Entry SHORT : regime switches to RISK-OFF
  Exit        : SL/TP or opposite regime switch

NOTE: The research paper uses on-chain metrics (funding rates, active addresses,
NVT ratio) as the binary risk signal. Those are NOT available via the standard
Binance REST API. This implementation uses a multi-indicator price-based proxy
that captures the same bull/bear regime switching behaviour:
  • EMA-200 is the canonical trend filter (price above = structural bull)
  • MACD histogram captures recent momentum direction
  • RSI-14 measures short-term momentum bias
All three must agree before a regime change is declared, reducing false flips.
"""

import pandas as pd

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class RegimeRiskOffStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("Regime_RiskOnOff", {
            "ema_trend":       200,
            "rsi_bull_min":    50,
            "rsi_bear_max":    50,
            "atr_sl_mult":     2.0,
            "atr_tp_mult":     4.5,
            "candle_interval": "4h",
        })
        if params:
            defaults.update(params)
        super().__init__("Regime_RiskOnOff", defaults)

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        return 210   # EMA-200 needs ≥200 candles + warm-up

    @property
    def max_hold_candles(self) -> int:
        return 120   # 120 × 4h = 480 hours ≈ 20 days per position

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "4h")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        close      = float(last["close"])
        ema200     = float(last.get("ema_200", close))
        macd_h     = float(last.get("macd_hist", 0.0))
        rsi        = float(last.get("rsi_14", 50.0))
        atr        = float(last.get("atr_14", close * 0.015))

        prv_close  = float(prev["close"])
        prv_ema200 = float(prev.get("ema_200", prv_close))
        prv_macd_h = float(prev.get("macd_hist", 0.0))
        prv_rsi    = float(prev.get("rsi_14", 50.0))

        rsi_bull = float(self.params["rsi_bull_min"])
        rsi_bear = float(self.params["rsi_bear_max"])

        # ── Current and previous regime score (0=bear, 1=bull per condition) ─
        bull_conditions_now  = sum([close > ema200, macd_h > 0, rsi > rsi_bull])
        bull_conditions_prev = sum([prv_close > prv_ema200, prv_macd_h > 0, prv_rsi > rsi_bull])

        regime_now  = "RISK_ON"  if bull_conditions_now  >= 3 else (
                      "RISK_OFF" if bull_conditions_now  <= 0 else "NEUTRAL")
        regime_prev = "RISK_ON"  if bull_conditions_prev >= 3 else (
                      "RISK_OFF" if bull_conditions_prev <= 0 else "NEUTRAL")

        if regime_now == regime_prev or regime_now == "NEUTRAL":
            return Signal(SignalType.HOLD, 0.0)

        # Confidence scales with how extreme the RSI and MACD histogram are
        rsi_dist   = abs(rsi - 50) / 50.0
        macd_score = min(abs(macd_h) / (close * 0.001 + 1e-10), 1.0)
        ema_dist   = abs(close - ema200) / (ema200 + 1e-10)
        confidence = min(0.90, 0.52 + 0.18 * rsi_dist + 0.15 * macd_score + 0.15 * ema_dist)

        sl_m = float(self.params["atr_sl_mult"])
        tp_m = float(self.params["atr_tp_mult"])

        # ── Regime switches to RISK-ON ─────────────────────────────────────
        if regime_now == "RISK_ON":
            sl = close - sl_m * atr
            tp = close + tp_m * atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={
                    "regime": "RISK_ON", "bull_score": bull_conditions_now,
                    "ema200": ema200, "rsi": rsi, "macd_hist": macd_h,
                },
            )

        # ── Regime switches to RISK-OFF ────────────────────────────────────
        sl = close + sl_m * atr
        tp = close - tp_m * atr
        return Signal(
            SignalType.SELL, confidence,
            stop_loss=sl, take_profit=tp,
            metadata={
                "regime": "RISK_OFF", "bull_score": bull_conditions_now,
                "ema200": ema200, "rsi": rsi, "macd_hist": macd_h,
            },
        )
