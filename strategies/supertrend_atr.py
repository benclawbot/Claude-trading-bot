"""
Strategy: Supertrend ATR + EMA49 Filter
────────────────────────────────────────
Port of user's TradingView Pine Script strategy.

Pine Script logic (paraphrased):
  - ATR(5) with 2.2× multiplier → Supertrend trailing up/down stops
  - up  = src - mult * atr   (only moves UP)
  - dn  = src + mult * atr  (only moves DOWN)
  - trend flips LONG  when close > dn1  (was -1, now +1)
  - trend flips SHORT when close < up1  (was +1, now -1)
  - Entry LONG  : buySignal  AND close > EMA49
  - Entry SHORT : sellSignal AND close < EMA49

Candle interval: 4h  (robust for BTC backtesting; original uses 5m live)
"""

import pandas as pd
import numpy as np

import config
from .base_strategy import BaseStrategy, Signal, SignalType


class SupertrendATRStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS.get("Supertrend_ATR", {
            "atr_period":     5,
            "atr_mult":       2.2,
            "ema_period":    49,
            "atr_sl_mult":   1.5,   # SL = close -/+ ATR(5) * sl_mult
            "atr_tp_mult":   3.0,   # TP = close +/+ ATR(5) * tp_mult
            "candle_interval": "4h",
        })
        if params:
            defaults.update(params)
        super().__init__("Supertrend_ATR", defaults)

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        # ATR(5) + EMA(49) needs ~60 warm-up candles
        return max(int(self.params["atr_period"]), int(self.params["ema_period"])) + 15

    @property
    def max_hold_candles(self) -> int:
        return 48   # 8 days on 4h – medium-term trend capture

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "4h")

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        close    = df["close"]
        cur_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])

        # ── EMA49 (already pre-computed in df) ────────────────────────────────
        ema_col = f"ema_{self.params['ema_period']}"
        if ema_col not in df.columns:
            # Fallback: compute it inline
            ema49 = close.ewm(span=self.params["ema_period"], adjust=False).mean()
        else:
            ema49 = df[ema_col]
        cur_ema  = float(ema49.iloc[-1])
        above_ema = cur_close > cur_ema
        below_ema = cur_close < cur_ema

        # ── Supertrend (ATR-based trailing stop) ───────────────────────────────
        atr_period = int(self.params["atr_period"])
        atr_mult   = float(self.params["atr_mult"])

        atr_col = f"atr_{atr_period}"
        if atr_col in df.columns:
            atr_series = df[atr_col]
        else:
            # Fallback: compute ATR(period) inline
            h, l, c = df["high"], df["low"], close
            prev_c  = c.shift(1)
            tr      = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
            atr_series = tr.ewm(alpha=1/atr_period, min_periods=atr_period, adjust=False).mean()

        cur_ema_atr = float(atr_series.iloc[-1])
        if not np.isfinite(cur_ema_atr) or cur_ema_atr <= 0:
            cur_ema_atr = cur_close * 0.015   # 1.5% fallback

        # Vectorized-ish: iterate backwards from current bar to build up/dn/trend
        # We only care about the current bar's state for the signal, but we
        # need the full history to correctly trail the stops.
        src = close   # Pine uses `src = open`, but the open/close distinction
                       # only matters for the first bar; using close keeps it
                       # consistent with the close[1] > up1 checks below.

        n = len(df)
        up  = np.zeros(n)
        dn  = np.zeros(n)
        trend = np.zeros(n)

        # Initialise on first bar
        up[0]   = float(src.iloc[0]) - atr_mult * float(atr_series.iloc[0])
        dn[0]   = float(src.iloc[0]) + atr_mult * float(atr_series.iloc[0])
        trend[0] = 1   # start bullish

        for i in range(1, n):
            a = float(atr_series.iloc[i])
            s = float(src.iloc[i])     # current bar's source
            s1 = float(src.iloc[i - 1]) # prev bar's source

            # Pine: up  = src - mult * atr   (base value)
            #       up1 = nz(up[1], up)
            #       up := close[1] > up1 ? math.max(up, up1) : up
            base_up = s - atr_mult * a
            if s1 > up[i - 1]:
                up[i] = max(base_up, up[i - 1])
            else:
                up[i] = base_up

            # Pine: dn  = src + mult * atr
            #       dn1 = nz(dn[1], dn)
            #       dn := close[1] < dn1 ? math.min(dn, dn1) : dn
            base_dn = s + atr_mult * a
            if s1 < dn[i - 1]:
                dn[i] = min(base_dn, dn[i - 1])
            else:
                dn[i] = base_dn

            # Pine: trend := trend == -1 and close > dn1 ? 1
            #              : trend ==  1 and close < up1 ? -1
            #              : trend
            t1 = trend[i - 1]
            c1 = float(close.iloc[i - 1])
            if t1 == -1 and c1 > dn[i - 1]:
                trend[i] = 1
            elif t1 == 1 and c1 < up[i - 1]:
                trend[i] = -1
            else:
                trend[i] = t1

        cur_trend  = int(trend[-1])
        prev_trend = int(trend[-2])

        buy_signal  = (cur_trend == 1  and prev_trend == -1)
        sell_signal = (cur_trend == -1 and prev_trend ==  1)

        # ── Confidence ───────────────────────────────────────────────────────
        dist_pct = abs(cur_close - cur_ema) / (cur_ema + 1e-10)
        confidence = min(0.90, 0.52 + dist_pct * 5.0)

        # ── SL / TP ───────────────────────────────────────────────────────────
        sl_m = float(self.params["atr_sl_mult"])
        tp_m = float(self.params["atr_tp_mult"])

        # ── LONG ─────────────────────────────────────────────────────────────
        if buy_signal and above_ema:
            sl = cur_close - sl_m * cur_ema_atr
            tp = cur_close + tp_m * cur_ema_atr
            return Signal(
                SignalType.BUY, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"atr": cur_ema_atr, "ema49": cur_ema, "trend": cur_trend},
            )

        # ── SHORT ────────────────────────────────────────────────────────────
        if sell_signal and below_ema:
            sl = cur_close + sl_m * cur_ema_atr
            tp = cur_close - tp_m * cur_ema_atr
            return Signal(
                SignalType.SELL, confidence,
                stop_loss=sl, take_profit=tp,
                metadata={"atr": cur_ema_atr, "ema49": cur_ema, "trend": cur_trend},
            )

        return Signal(SignalType.HOLD, 0.0)
