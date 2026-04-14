"""
Learning Engine
──────────────────
After each closed trade:
  1. Feeds features + outcome to ML_Adaptive strategy
  2. Analyzes recent trade patterns (streak, regime, drawdown)
  3. Tunes strategy parameters based on performance data
  4. Generates journal entry using Claude AI (if API key set) or rich templates
  5. Records a reusable lessons database that feeds future strategy decisions

Self-improvement loop:
  - Win rate drops below 40% over 20 trades → tighten entry filters
  - Win rate rises above 65% → slightly relax filters to catch more trades
  - Consecutive losses → raise confidence threshold temporarily
  - Regime changes detected → bias toward regime-appropriate strategies
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

import config
import database as db
from utils.indicators import get_feature_vector, compute_market_regime

logger = logging.getLogger(__name__)


def _call_claude_api(prompt: str, max_tokens: int = 400) -> Optional[str]:
    """
    Generate journal reflection using Claude API.
    Falls back to template-based generation if API is unavailable.
    """
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import requests
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        logger.debug(f"Claude API call failed: {e}")
        return None


class LearningEngine:

    def __init__(self, strategies: dict):
        self.strategies = strategies
        self._lock = threading.Lock()

        # Per-strategy running stats
        self._recent_pnl: Dict[str, List[float]] = {}
        self._win_rates: Dict[str, float] = {}
        self._confidence_adjustments: Dict[str, float] = {}  # temporary boosts/penalties
        self._consecutive_losses: Dict[str, int] = {}

        # Cross-strategy regime tracking
        self._regime_history: List[str] = []

        # Generic journal-lesson memory (applies to ALL active strategies,
        # not only ML_Adaptive)
        self._journal_by_strategy: Dict[str, List[dict]] = {}
        self._lesson_bias: Dict[str, float] = {}

    # ─── Called after every closed trade ──────────────────────────────────────

    def on_trade_closed(self, trade_id: int, strategy_name: str,
                        entry_price: float, exit_price: float,
                        pnl: float, pnl_pct: float, side: str,
                        duration_hours: float, exit_reason: str,
                        entry_features: dict, df=None):
        """
        Primary hook — called by PortfolioManager immediately after a trade closes.
        """
        won = pnl > 0
        regime = "UNKNOWN"
        feature_vec = []

        if df is not None and hasattr(df, "iloc") and len(df) >= 20:
            try:
                regime = compute_market_regime(df)
                feature_vec = get_feature_vector(df)
            except Exception as e:
                logger.warning(f"Could not compute market features: {e}")

        # ── Update running stats ───────────────────────────────────────────────
        with self._lock:
            history = self._recent_pnl.setdefault(strategy_name, [])
            history.append(pnl_pct)
            if len(history) > 50:
                history.pop(0)

            recent_20 = history[-20:]
            wins = sum(1 for x in recent_20 if x > 0)
            self._win_rates[strategy_name] = wins / len(recent_20)

            # Consecutive loss tracking
            if not won:
                self._consecutive_losses[strategy_name] = \
                    self._consecutive_losses.get(strategy_name, 0) + 1
            else:
                self._consecutive_losses[strategy_name] = 0

        # ── Feed ML_Adaptive strategy ──────────────────────────────────────────
        ml_strat = self.strategies.get("ML_Adaptive")
        if ml_strat and feature_vec:
            ml_strat.add_training_sample(feature_vec, float(won))
            try:
                db.record_ml_features(
                    trade_id=trade_id,
                    strategy_name=strategy_name,
                    features=feature_vec,
                    outcome=float(won),
                    pnl_pct=pnl_pct,
                )
            except Exception:
                pass

        # ── Tune strategy parameters ───────────────────────────────────────────
        self._tune_strategy(strategy_name)

        # ── Adjust confidence thresholds ───────────────────────────────────────
        self._adjust_confidence(strategy_name)

        # ── Write journal entry ────────────────────────────────────────────────
        journal = self._build_journal_entry(
            trade_id=trade_id,
            strategy_name=strategy_name,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            side=side,
            duration_hours=duration_hours,
            exit_reason=exit_reason,
            regime=regime,
            won=won,
            feature_vec=feature_vec,
        )
        try:
            db.record_journal_entry(**journal)
            logger.info(f"[Journal] Entry written for trade #{trade_id} ({strategy_name})")
            
            # ── Learn from journal entries ─────────────────────────────────────
            # After writing, also update the ML strategy's learned patterns
            self._learn_from_new_journal_entry(journal)
            
        except Exception as e:
            logger.error(f"Failed to write journal entry: {e}")

    def _normalize_journal_entry(self, entry: dict) -> dict:
        """Normalize journal entry shape for downstream learning."""
        pnl = float(entry.get("pnl", 0.0) or 0.0)
        won = bool(entry.get("won")) if "won" in entry else (pnl > 0)
        out = dict(entry)
        out["won"] = won
        out["pnl"] = pnl
        out["strategy_name"] = out.get("strategy_name", "")
        out["market_regime"] = out.get("market_regime", "UNKNOWN")
        out["exit_reason"] = out.get("exit_reason", "")
        raw_lessons = out.get("lessons", [])
        if isinstance(raw_lessons, list):
            out["lessons"] = raw_lessons
        elif isinstance(raw_lessons, str):
            try:
                parsed = json.loads(raw_lessons)
                out["lessons"] = parsed if isinstance(parsed, list) else []
            except Exception:
                out["lessons"] = [p.strip() for p in raw_lessons.split(" | ") if p.strip()]
        else:
            out["lessons"] = []
        return out

    def _recompute_lesson_bias(self, strategy_name: str):
        """
        Compute lesson-derived confidence bias for a strategy.
        Positive values increase caution (lower confidence).
        """
        history = self._journal_by_strategy.get(strategy_name, [])
        if not history:
            self._lesson_bias[strategy_name] = 0.0
            return

        recent = history[-20:]
        losses = sum(1 for e in recent if not e.get("won", False))
        loss_rate = losses / len(recent)

        # Baseline penalty from observed loss rate over recent journal entries.
        penalty = max(0.0, loss_rate - 0.50) * 0.30  # up to +0.15

        # Extra caution if there is a recent STOP_LOSS cluster.
        stop_losses = sum(
            1 for e in recent[-5:]
            if str(e.get("exit_reason", "")).upper() == "STOP_LOSS"
        )
        if stop_losses >= 3:
            penalty += 0.05

        # Small boost when recent outcomes are consistently positive.
        recent10 = recent[-10:]
        if recent10:
            wins10 = sum(1 for e in recent10 if e.get("won", False))
            if wins10 / len(recent10) >= 0.70:
                penalty -= 0.05

        self._lesson_bias[strategy_name] = max(-0.10, min(0.25, penalty))

    def _ingest_journal_entry_for_all_strategies(self, journal_entry: dict):
        """Apply journal-learning effects that should impact all strategies."""
        e = self._normalize_journal_entry(journal_entry)
        name = e.get("strategy_name", "")
        if not name:
            return

        bucket = self._journal_by_strategy.setdefault(name, [])
        bucket.append(e)
        if len(bucket) > 500:
            del bucket[:-500]

        self._recompute_lesson_bias(name)

    def _learn_from_new_journal_entry(self, journal_entry: dict):
        """
        Process a new journal entry:
        1) Update generic lesson bias for all strategies.
        2) Feed ML_Adaptive pattern learner (when enabled).
        """
        self._ingest_journal_entry_for_all_strategies(journal_entry)

        ml_strat = self.strategies.get("ML_Adaptive")
        if not ml_strat or not hasattr(ml_strat, "learn_from_lessons"):
            return

        try:
            ml_strat.learn_from_lessons([self._normalize_journal_entry(journal_entry)])
        except Exception as e:
            logger.warning(f"Failed to learn from journal entry: {e}")

    def learn_from_all_journal_entries(self):
        """
        Fetch recent journal entries and restore lesson effects on startup.
        Applies to all strategies; ML_Adaptive gets extra pattern learning when present.
        """
        try:
            # Include archived/backtest-marked trades so historical lessons persist after trade-history resets.
            entries = db.get_journal_entries(limit=500, include_backtest=True)
            if not entries:
                return

            normalized = [self._normalize_journal_entry(e) for e in entries]
            # Preserve chronological order for streak/bias reconstruction.
            for e in reversed(normalized):
                self._ingest_journal_entry_for_all_strategies(e)

            ml_strat = self.strategies.get("ML_Adaptive")
            if ml_strat and hasattr(ml_strat, "learn_from_lessons"):
                ml_strat.learn_from_lessons(normalized)

            logger.info(
                f"Loaded {len(entries)} journal entries for learning "
                f"across {len(self._journal_by_strategy)} strategies"
            )
        except Exception as e:
            logger.warning(f"Failed to load journal entries: {e}")

    # ─── Parameter tuning ─────────────────────────────────────────────────────

    def _tune_strategy(self, strategy_name: str):
        """
        Gradient-free parameter adaptation based on recent performance.
        Changes are logged and persisted to the database.
        """
        history = self._recent_pnl.get(strategy_name, [])
        if len(history) < config.MIN_TRADES_FOR_LEARNING:
            return

        recent = history[-20:]
        win_rate = sum(1 for x in recent if x > 0) / len(recent)
        avg_pnl  = sum(recent) / len(recent)

        strat = self.strategies.get(strategy_name)
        if strat is None:
            return

        params = dict(strat.params)
        changed = False
        reason = ""

        if win_rate < 0.38 or avg_pnl < -0.008:
            logger.info(
                f"[Learning] {strategy_name} underperforming "
                f"(WR={win_rate:.1%}, avgPnL={avg_pnl:.3%}) — tightening filters"
            )
            if strategy_name == "RSI_Bollinger":
                params["rsi_oversold"]    = max(20, params.get("rsi_oversold", 30) - 2)
                params["rsi_overbought"]  = min(82, params.get("rsi_overbought", 70) + 2)
                params["adx_max"]         = max(25, params.get("adx_max", 35) - 3)
                reason = f"RSI band tightened to [{params['rsi_oversold']},{params['rsi_overbought']}]"
                changed = True

            elif strategy_name == "MACD_Momentum":
                params["signal_period"] = min(14, params.get("signal_period", 9) + 1)
                params["adx_min"]       = min(30, params.get("adx_min", 20) + 3)
                reason = f"signal_period={params['signal_period']}, adx_min={params['adx_min']}"
                changed = True

            elif strategy_name == "EMA_Crossover":
                params["fast_ema"] = min(15, params.get("fast_ema", 9) + 1)
                reason = f"fast_ema slowed to {params['fast_ema']}"
                changed = True

            elif strategy_name == "Breakout":
                params["volume_multiplier"] = min(3.0, params.get("volume_multiplier", 1.8) + 0.2)
                params["atr_sl_mult"]       = min(2.5, params.get("atr_sl_mult", 1.5) + 0.2)
                reason = f"vol_mult={params['volume_multiplier']:.1f}, sl_mult={params['atr_sl_mult']:.1f}"
                changed = True

            elif strategy_name == "ML_Adaptive":
                params["min_confidence"] = min(0.70, params.get("min_confidence", 0.55) + 0.03)
                reason = f"min_confidence raised to {params['min_confidence']:.2f}"
                changed = True

        elif win_rate > 0.65 and avg_pnl > 0.010:
            logger.info(
                f"[Learning] {strategy_name} performing well "
                f"(WR={win_rate:.1%}, avgPnL={avg_pnl:.3%}) — relaxing slightly"
            )
            if strategy_name == "RSI_Bollinger":
                params["rsi_oversold"]   = min(35, params.get("rsi_oversold", 30) + 1)
                params["rsi_overbought"] = max(65, params.get("rsi_overbought", 70) - 1)
                reason = f"RSI band loosened to [{params['rsi_oversold']},{params['rsi_overbought']}]"
                changed = True

            elif strategy_name == "Breakout":
                params["volume_multiplier"] = max(1.4, params.get("volume_multiplier", 1.8) - 0.1)
                reason = f"vol_mult relaxed to {params['volume_multiplier']:.1f}"
                changed = True

            elif strategy_name == "ML_Adaptive":
                params["min_confidence"] = max(0.45, params.get("min_confidence", 0.55) - 0.02)
                reason = f"min_confidence relaxed to {params['min_confidence']:.2f}"
                changed = True

        if changed:
            strat.update_params(params)
            try:
                db.update_strategy_params(strategy_name, params)
            except Exception:
                pass
            logger.info(f"[Learning] {strategy_name} params updated: {reason}")

    # ─── Confidence adjustment ─────────────────────────────────────────────────

    def _adjust_confidence(self, strategy_name: str):
        """
        Raise the effective confidence threshold if we're on a losing streak.
        This acts as a circuit breaker during drawdowns.
        """
        consec_losses = self._consecutive_losses.get(strategy_name, 0)
        if consec_losses >= 3:
            penalty = min(0.15, 0.04 * (consec_losses - 2))
            self._confidence_adjustments[strategy_name] = penalty
            logger.info(
                f"[Learning] {strategy_name} on {consec_losses}-loss streak — "
                f"raising confidence threshold by {penalty:.2f}"
            )
        elif consec_losses == 0:
            # Reset on first win
            self._confidence_adjustments[strategy_name] = 0.0

    # ─── Confidence score for upcoming trades ─────────────────────────────────

    def get_confidence(self, strategy_name: str, df=None) -> float:
        """
        Return an ML confidence score (0–1) for the next potential trade.
        Incorporates: recent win rate, ML model probability, and streak adjustment.
        """
        base_win_rate = self._win_rates.get(strategy_name, 0.55)

        # Pull RF probability from ML_Adaptive model
        ml_strat = self.strategies.get("ML_Adaptive")
        if strategy_name == "ML_Adaptive" and ml_strat and \
                getattr(ml_strat, "model_trained", False) and df is not None:
            try:
                feat = get_feature_vector(df)
                prob = ml_strat._predict_win_prob(feat)
                if prob is not None:
                    base_win_rate = float(prob)
            except Exception:
                pass

        # Apply streak penalty + journal-lesson penalty (for all strategies)
        streak_penalty = self._confidence_adjustments.get(strategy_name, 0.0)
        lesson_penalty = self._lesson_bias.get(strategy_name, 0.0)
        return max(0.0, min(1.0, base_win_rate - streak_penalty - lesson_penalty))

    # ─── Journal entry builder ─────────────────────────────────────────────────

    def _build_journal_entry(self, trade_id: int, strategy_name: str,
                             entry_price: float, exit_price: float,
                             pnl: float, pnl_pct: float, side: str,
                             duration_hours: float, exit_reason: str,
                             regime: str, won: bool,
                             feature_vec: list) -> dict:
        """
        Build a rich journal entry. Tries Claude API first, falls back to
        rule-based templates that analyze actual trade patterns.
        """
        history = self._recent_pnl.get(strategy_name, [])
        win_rate = self._win_rates.get(strategy_name, 0.5)
        streak = self._streak_info(history)
        consec_losses = self._consecutive_losses.get(strategy_name, 0)
        recent_avg_pnl = sum(history[-10:]) / max(len(history[-10:]), 1)

        # ── Try Claude AI reflection ───────────────────────────────────────────
        reflection = self._claude_reflection(
            strategy_name=strategy_name,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            duration_hours=duration_hours,
            regime=regime,
            exit_reason=exit_reason,
            won=won,
            win_rate=win_rate,
            streak=streak,
            consec_losses=consec_losses,
            recent_avg_pnl=recent_avg_pnl,
        )

        # ── Fallback: rich template-based reflection ───────────────────────────
        if not reflection:
            reflection = self._template_reflection(
                strategy_name=strategy_name,
                side=side, entry_price=entry_price, exit_price=exit_price,
                pnl_pct=pnl_pct, duration_hours=duration_hours,
                regime=regime, exit_reason=exit_reason, won=won,
                win_rate=win_rate, streak=streak,
            )

        # ── Setup summary ──────────────────────────────────────────────────────
        setup_summary = (
            f"{side} {strategy_name} | Entry: ${entry_price:,.2f} → Exit: ${exit_price:,.2f} | "
            f"Regime: {regime} | Duration: {duration_hours:.1f}h"
        )

        # ── Outcome analysis with real numbers ────────────────────────────────
        pct_move = (exit_price - entry_price) / entry_price * 100
        outcome_analysis = (
            f"Trade {'WON ✓' if won else 'LOST ✗'} | "
            f"Price move: {pct_move:+.2f}% | Net PnL: ${pnl:+.2f} ({pnl_pct*100:+.2f}%) | "
            f"Exit: {exit_reason} | "
            f"Running win rate ({strategy_name}): {win_rate:.1%} over last 20 trades"
        )

        # ── Actionable lessons ────────────────────────────────────────────────
        lessons = self._derive_lessons(
            strategy_name=strategy_name,
            won=won,
            regime=regime,
            exit_reason=exit_reason,
            feature_vec=feature_vec,
        )

        return dict(
            trade_id=trade_id,
            strategy_name=strategy_name,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            side=side,
            duration_hours=duration_hours,
            market_regime=regime,
            setup_summary=setup_summary,
            outcome_analysis=outcome_analysis,
            reflection=reflection,
            lessons=lessons,
        )

    def _claude_reflection(self, **kwargs) -> Optional[str]:
        """Ask Claude to write a concise trading journal reflection."""
        prompt = f"""You are a quantitative trading analyst reviewing a closed paper trade.
Write a concise, insightful journal entry (3-4 sentences max) that:
1. Explains what happened and why (based on market regime and strategy logic)
2. Identifies what worked or what failed
3. Suggests one specific actionable improvement

Trade data:
- Strategy: {kwargs['strategy_name']}
- Direction: {kwargs['side']}
- Entry: ${kwargs['entry_price']:,.2f} → Exit: ${kwargs['exit_price']:,.2f}
- PnL: {kwargs['pnl_pct']*100:+.2f}%
- Duration: {kwargs['duration_hours']:.1f} hours
- Outcome: {'WIN' if kwargs['won'] else 'LOSS'}
- Exit reason: {kwargs['exit_reason']}
- Market regime: {kwargs['regime']}
- Recent win rate: {kwargs['win_rate']:.1%} over last 20 trades
- {kwargs['streak']}
- Consecutive losses before this trade: {kwargs['consec_losses']}

Be specific and data-driven. No generic platitudes. Speak as if reviewing your own trade."""

        return _call_claude_api(prompt, max_tokens=250)

    def _template_reflection(self, strategy_name: str, side: str,
                             entry_price: float, exit_price: float,
                             pnl_pct: float, duration_hours: float,
                             regime: str, exit_reason: str, won: bool,
                             win_rate: float, streak: str) -> str:
        """
        Rich template-based reflection that references actual strategy logic.
        """
        strategy_context = {
            "RSI_Bollinger": {
                "win":  "RSI extreme + Bollinger Band touch converged correctly — mean reversion played out as expected in this {regime} environment.",
                "loss": "Mean reversion signal fired but market continued trending. RSI oversold/overbought conditions extended further — classic regime mismatch.",
                "key_note": "This strategy thrives in RANGING regimes (ADX < 35). Signal during TRENDING_UP/DOWN regime should be flagged.",
            },
            "MACD_Momentum": {
                "win":  "MACD cross with EMA200 trend filter aligned. Momentum carried price in the signal direction for {hours:.1f}h.",
                "loss": "MACD cross proved to be a whipsaw. Low histogram momentum at the crossover point suggests insufficient directional conviction.",
                "key_note": "Strong MACD crosses show large histogram magnitude at crossover. Weak ones reverse quickly.",
            },
            "EMA_Crossover": {
                "win":  "EMA9/21 golden cross confirmed by EMA50 slope direction. Multi-EMA alignment provided reliable trend-following entry.",
                "loss": "EMA cross fired in a ranging market — price was oscillating around the slow EMA, creating a false directional signal.",
                "key_note": "EMA crosses have highest reliability when ADX > 25 and price is cleanly above/below all three EMAs.",
            },
            "Breakout": {
                "win":  "Volume-confirmed breakout held. Volume spike ({regime} context) attracted follow-through buyers/sellers.",
                "loss": "Breakout failed — low follow-through volume on subsequent candles. Likely a bull/bear trap from retail stop runs.",
                "key_note": "Strongest breakouts show 2× volume at the break AND sustained volume on next 2-3 candles.",
            },
            "ML_Adaptive": {
                "win":  "ML model prediction aligned with market outcome. Feature vector captured the directional edge correctly.",
                "loss": "ML model predicted incorrectly — likely regime shift mid-trade that the training data hadn't seen recently.",
                "key_note": "Model accuracy improves as trade history grows. Retrain triggered automatically every 5 closed trades.",
            },
        }

        ctx = strategy_context.get(strategy_name, {
            "win": "Setup executed as planned.",
            "loss": "Setup did not play out — review entry conditions.",
            "key_note": "Continue monitoring.",
        })

        template = ctx["win"] if won else ctx["loss"]
        main_text = template.format(regime=regime, hours=duration_hours)
        key_note = ctx["key_note"]

        result_str = f"{'✓ Win' if won else '✗ Loss'}: {pnl_pct*100:+.2f}% in {duration_hours:.1f}h. "
        result_str += main_text + f" Market regime: {regime}. "
        result_str += f"Exit triggered by: {exit_reason}. "
        result_str += f"Note: {key_note}. "
        result_str += f"Running win rate: {win_rate:.1%}. {streak}"

        return result_str

    def _derive_lessons(self, strategy_name: str, won: bool, regime: str,
                        exit_reason: str, feature_vec: list) -> List[str]:
        """
        Derive specific, actionable lessons from THIS trade only.
        Returns a list of lesson strings (allows multiple lessons per trade).
        Uses per-trade factors: strategy name, market regime at time of trade,
        exit reason, and whether this specific trade won or lost.
        Aggregate rolling stats (win rate, consecutive losses, avg PnL) belong
        in performance monitoring — not in per-trade lesson generation.
        """
        lessons = []

        # ── Regime-specific insights (per-trade: strategy + regime + outcome) ──
        if strategy_name == "RSI_Bollinger" and regime in ("TRENDING_UP", "TRENDING_DOWN") and not won:
            lessons.append(
                "Lesson: RSI_Bollinger mean reversion signal fired during a "
                "trending regime — strategies underperform when ADX > 35. "
                "Consider pausing this strategy during confirmed trends."
            )
        elif strategy_name == "RSI_Bollinger" and regime == "RANGING" and won:
            lessons.append(
                "Lesson: RSI_Bollinger worked correctly in a ranging regime. "
                "Mean reversion signals align well with low-ADX environments."
            )

        if strategy_name in ("EMA_Crossover", "MACD_Momentum") and regime == "RANGING" and not won:
            lessons.append(
                "Lesson: Trend-following strategy signaled in a ranging market. "
                "Add ADX filter: require ADX > 25 before entering trend signals."
            )
        elif strategy_name in ("EMA_Crossover", "MACD_Momentum") and regime in ("TRENDING_UP", "TRENDING_DOWN") and won:
            lessons.append(
                "Lesson: Trend-following signal aligned with market direction. "
                "Confirm regime via ADX to validate trend strength before entry."
            )

        if strategy_name == "Breakout" and regime == "RANGING" and won:
            lessons.append(
                "Lesson: Breakout from range preceded a strong move. "
                "Confirm volume surge at breakout for higher signal reliability."
            )
        elif strategy_name == "Breakout" and regime in ("TRENDING_UP", "TRENDING_DOWN") and not won:
            lessons.append(
                "Lesson: Breakout failed — market was already in a strong trend. "
                "Wait for pullbacks to key levels rather than chasing extended moves."
            )

        if strategy_name == "ML_Adaptive" and won:
            lessons.append(
                "Lesson: ML model prediction confirmed by market outcome. "
                "Feature vector captured directional edge for this regime."
            )
        elif strategy_name == "ML_Adaptive" and not won:
            lessons.append(
                "Lesson: ML prediction failed — possible regime shift mid-trade "
                "or insufficient recent training data for current conditions."
            )

        # ── Exit reason analysis (per-trade, multiple reasons can apply) ──────
        if exit_reason == "STOP_LOSS":
            lessons.append(
                "Trade stopped out. Review: was the stop too tight for the ATR "
                "of the entry candle? Consider ATR-based stops instead of fixed %."
            )
        elif exit_reason == "TAKE_PROFIT" and won:
            lessons.append(
                "Take-profit hit successfully. Consider trailing stops on "
                "momentum trades to capture extended moves beyond initial target."
            )
        elif exit_reason == "TAKE_PROFIT" and not won:
            lessons.append(
                "Take-profit hit but trade still lost — entry was likely late "
                "or position size was too large relative to move magnitude."
            )
        elif exit_reason == "TRAILING_STOP" and won:
            lessons.append(
                "Trailing stop captured an extended move. Good trade management "
                "for momentum-driven strategies."
            )
        elif exit_reason == "TIME_EXIT" and not won:
            lessons.append(
                "Trade timed out without hitting TP/SL. Time exits can cut winners "
                "short in strong trends — consider tightening trailing stop instead."
            )

        # ── Regime warning for Scalper_5m (most active in recent trades) ───────
        if strategy_name == "Scalper_5m" and regime in ("TRENDING_UP", "TRENDING_DOWN") and not won:
            lessons.append(
                "Lesson: Scalper_5m signals in a strong trend often get stopped "
                "out by momentum reversals. Use a wider stop or wait for pullback."
            )
        elif strategy_name == "Scalper_5m" and won:
            lessons.append(
                "Lesson: Scalper_5m captured a short-term move successfully. "
                "Confirm volume and RSI divergence at entry for better timing."
            )

        # ── Fallback: no per-trade lesson triggered ───────────────────────────
        if not lessons:
            lessons.append(
                f"Trade executed within normal parameters. "
                f"Strategy: {strategy_name} | Regime: {regime} | "
                f"Exit: {exit_reason} | {'Win' if won else 'Loss'}."
            )

        return lessons

    # ─── Performance snapshots ─────────────────────────────────────────────────

    def update_performance_snapshots(self, strategies: dict):
        """Write periodic performance snapshots for each active strategy."""
        for name, strat in strategies.items():
            if not strat.is_active:
                continue
            try:
                stats    = db.get_trade_stats(name)
                capital  = strat.capital
                win_rate = float(stats.get("win_rate") or 0)
                cum_pnl  = float(stats.get("total_pnl") or 0)
                n_trades = int(stats.get("total_trades") or 0)
                open_p   = len(db.get_open_positions(name))

                from datetime import date
                today = date.today().isoformat()
                conn  = db.get_conn()
                row   = conn.execute(
                    "SELECT SUM(pnl) FROM trades WHERE strategy_name=? AND DATE(closed_at)=?",
                    (name, today),
                ).fetchone()
                daily_pnl = float(row[0] or 0)

                db.upsert_strategy_performance(
                    strategy_name=name,
                    capital=capital,
                    daily_pnl=daily_pnl,
                    cumulative_pnl=cum_pnl,
                    win_rate=win_rate,
                    total_trades=n_trades,
                    open_positions=open_p,
                )
            except Exception as e:
                logger.warning(f"Performance snapshot failed for {name}: {e}")

    def get_lesson_bias_snapshot(self) -> Dict[str, float]:
        """Debug helper: return current lesson penalty per strategy."""
        return dict(self._lesson_bias)

    # ─── Utility ──────────────────────────────────────────────────────────────

    @staticmethod
    def _streak_info(history: list) -> str:
        if not history:
            return "No trade history yet."
        streak = 1
        last = history[-1] > 0
        for v in reversed(history[:-1]):
            if (v > 0) == last:
                streak += 1
            else:
                break
        word = "winning" if last else "losing"
        return f"Current {word} streak: {streak} trade(s)."



