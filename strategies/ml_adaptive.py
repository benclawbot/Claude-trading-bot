"""
Strategy 5: ML-Adaptive (Random Forest)
─────────────────────────────────────────
Uses features from all other strategies combined with market-regime features.
A RandomForestClassifier is trained on past trades (outcome = 1 if profitable).
When fewer than MIN_TRADES_FOR_LEARNING trades exist it uses a rule-based
ensemble of the other four strategies as a "warm-start".

The model retrain is triggered every RETRAIN_INTERVAL new trades.
Position size is scaled by win_probability from the classifier.

Changes:
  - Added ML model persistence (save/load from disk)
  - Added method to learn from past journal entries/lessons
  - Added pattern recognition for regime-specific failures
"""

import logging
import os
import pickle
import threading
import numpy as np
import pandas as pd

import config
from utils.indicators import get_feature_vector, compute_market_regime
from .base_strategy import BaseStrategy, Signal, SignalType

try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import cross_val_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

logger = logging.getLogger(__name__)

# Model persistence path
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "ml_adaptive_model.pkl")
METADATA_PATH = os.path.join(MODEL_DIR, "ml_adaptive_meta.pkl")


class MLAdaptiveStrategy(BaseStrategy):

    def __init__(self, params: dict = None):
        defaults = config.STRATEGY_PARAMS["ML_Adaptive"].copy()
        if params:
            defaults.update(params)
        super().__init__("ML_Adaptive", defaults)

        self._model: object = None
        self._model_lock = threading.Lock()
        self._feature_history: list = []  # list of (features, outcome)
        self._trained_on: int = 0
        self._last_features: list = []
        self._retrain_counter: int = 0
        
        # Learned patterns from journal entries
        self._regime_failure_patterns: dict = {}  # regime -> list of failed feature combinations
        self._lesson_insights: list = []  # accumulated lessons
        
        # Load persisted model on startup
        self._ensure_model_dir()
        self._load_model()

    def _ensure_model_dir(self):
        """Create models directory if it doesn't exist."""
        os.makedirs(MODEL_DIR, exist_ok=True)

    # ─── Abstract overrides ───────────────────────────────────────────────────

    @property
    def min_candles(self) -> int:
        return 250

    @property
    def candle_interval(self) -> str:
        return self.params.get("candle_interval", "1h")

    # ─── Signal generation ────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal(SignalType.HOLD, 0.0)

        features = get_feature_vector(df)
        self._last_features = features
        regime  = compute_market_regime(df)

        # ── ML path ──────────────────────────────────────────────────────────
        win_prob = self._predict_win_prob(features)

        if win_prob is not None:
            return self._signal_from_ml(df, features, win_prob, regime)

        # ── Ensemble fallback (rule-based) ────────────────────────────────────
        return self._ensemble_signal(df, regime)

    # ─── ML helpers ──────────────────────────────────────────────────────────

    def _predict_win_prob(self, features: list) -> float | None:
        with self._model_lock:
            if self._model is None:
                return None
            try:
                X = np.array(features).reshape(1, -1)
                prob = float(self._model.predict_proba(X)[0][1])
                return prob
            except Exception as e:
                logger.debug(f"ML prediction error: {e}")
                return None

    def _signal_from_ml(self, df: pd.DataFrame, features: list,
                        win_prob: float, regime: str) -> Signal:
        last  = df.iloc[-1]
        close = float(last["close"])
        atr   = float(last.get("atr_14", close * 0.015))

        ema9   = float(last.get("ema_9",  close))
        ema21  = float(last.get("ema_21", close))
        ema200 = float(last.get("ema_200", close))
        rsi    = float(last.get("rsi_14", 50))
        macd_h = float(last.get("macd_hist", 0))

        # Get learned caution level from past failures in this regime
        caution_level = self.get_regime_caution_level(regime)
        
        # Adjust confidence threshold based on learned caution
        adjusted_threshold = config.CONFIDENCE_THRESHOLD + (caution_level * 0.15)
        
        if win_prob < adjusted_threshold:
            return Signal(SignalType.HOLD, win_prob,
                          metadata={
                              "win_prob": win_prob, 
                              "reason": f"Below adjusted threshold ({adjusted_threshold:.2f})",
                              "caution_level": caution_level,
                              "regime": regime,
                          })

        # Directional signal: combine ML confidence with direction indicators
        long_score  = 0.0
        short_score = 0.0

        # EMA alignment
        if ema9 > ema21 > close * 0.99:
            long_score  += 0.3
        if ema9 < ema21:
            short_score += 0.3

        # MACD histogram
        if macd_h > 0:
            long_score  += 0.25
        else:
            short_score += 0.25

        # RSI
        if 40 < rsi < 60:           # neutral – small bias
            if close > ema200:
                long_score += 0.1
            else:
                short_score += 0.1
        elif rsi < 35:
            long_score  += 0.35
        elif rsi > 65:
            short_score += 0.35

        # Regime adjustment
        if regime == "TRENDING_UP":
            long_score  += 0.2
        elif regime == "TRENDING_DOWN":
            short_score += 0.2

        # Apply learned caution - reduce scores based on past failures
        if caution_level > 0.3:
            reduction = caution_level * 0.2
            long_score *= (1 - reduction)
            short_score *= (1 - reduction)

        sl_pct = config.DEFAULT_STOP_LOSS_PCT * 0.9   # slightly tighter (ML filtered)
        tp_pct = config.DEFAULT_TAKE_PROFIT_PCT * 1.1

        if long_score >= short_score + 0.15:
            sl = close - 1.5 * atr
            tp = close + 3.5 * atr
            return Signal(
                SignalType.BUY, win_prob,
                stop_loss=sl, take_profit=tp,
                metadata={
                    "win_prob": win_prob, 
                    "regime": regime,
                    "caution_level": caution_level,
                    "long_score": long_score, 
                    "short_score": short_score,
                    "applicable_lessons": self.get_applicable_lessons(regime) if caution_level > 0.3 else [],
                })
        elif short_score >= long_score + 0.15:
            sl = close + 1.5 * atr
            tp = close - 3.5 * atr
            return Signal(
                SignalType.SELL, win_prob,
                stop_loss=sl, take_profit=tp,
                metadata={"win_prob": win_prob, "regime": regime,
                          "long_score": long_score, "short_score": short_score}
            )

        return Signal(SignalType.HOLD, win_prob,
                      metadata={"reason": "Directional conflict", "win_prob": win_prob})

    def _ensemble_signal(self, df: pd.DataFrame, regime: str) -> Signal:
        """Simple rule-based warm-start before ML is ready."""
        last  = df.iloc[-1]
        close = float(last["close"])
        atr   = float(last.get("atr_14", close * 0.015))
        rsi   = float(last.get("rsi_14", 50))
        ema9  = float(last.get("ema_9",  close))
        ema21 = float(last.get("ema_21", close))
        ema50 = float(last.get("ema_50", close))

        sl_pct = config.DEFAULT_STOP_LOSS_PCT
        tp_pct = config.DEFAULT_TAKE_PROFIT_PCT

        # Very conservative entry: three confirmations
        if rsi < 35 and ema9 > ema21 and close > ema50 * 0.995:
            return Signal(SignalType.BUY, 0.55,
                          stop_loss=close * (1-sl_pct), take_profit=close * (1+tp_pct),
                          metadata={"mode": "ensemble_fallback"})
        if rsi > 65 and ema9 < ema21 and close < ema50 * 1.005:
            return Signal(SignalType.SELL, 0.55,
                          stop_loss=close * (1+sl_pct), take_profit=close * (1-tp_pct),
                          metadata={"mode": "ensemble_fallback"})
        return Signal(SignalType.HOLD, 0.0)

    # ─── Training interface ───────────────────────────────────────────────────

    def add_training_sample(self, features: list, outcome: float):
        """Called by LearningEngine after each trade closes."""
        self._feature_history.append((features, float(outcome)))
        self._retrain_counter += 1
        retrain_every = int(self.params.get("retrain_interval", 20))
        if (self._retrain_counter >= retrain_every and
                len(self._feature_history) >= config.MIN_TRADES_FOR_LEARNING):
            self._retrain_counter = 0
            threading.Thread(target=self._retrain, daemon=True).start()

    def _retrain(self):
        """Retrain the RandomForest on accumulated trade outcomes."""
        if not SKLEARN_AVAILABLE:
            logger.warning("scikit-learn not available – ML model disabled.")
            return

        samples = list(self._feature_history[-500:])   # cap at last 500
        if len(samples) < config.MIN_TRADES_FOR_LEARNING:
            return

        X = np.array([s[0] for s in samples])
        y = np.array([s[1] for s in samples])

        # Minimum class diversity required
        if len(set(y)) < 2:
            return

        try:
            model = Pipeline([
                ("scaler", StandardScaler()),
                ("clf", RandomForestClassifier(
                    n_estimators=int(self.params.get("n_estimators", 100)),
                    max_depth=6,
                    min_samples_leaf=3,
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=-1,
                ))
            ])
            model.fit(X, y)
            with self._model_lock:
                self._model = model
                self._trained_on = len(samples)
            logger.info(f"ML_Adaptive model retrained on {len(samples)} samples.")
            
            # Save the model to disk
            self._save_model()
            
        except Exception as e:
            logger.error(f"ML retraining error: {e}")

    @property
    def model_trained(self) -> bool:
        return self._model is not None

    @property
    def training_samples(self) -> int:
        return len(self._feature_history)

    # ─── Model persistence ────────────────────────────────────────────────────

    def _save_model(self) -> bool:
        """Persist the trained model to disk."""
        if self._model is None:
            return False
        try:
            with self._model_lock:
                # Save model
                with open(MODEL_PATH, 'wb') as f:
                    pickle.dump(self._model, f)
                # Save metadata
                metadata = {
                    "trained_on": self._trained_on,
                    "feature_history_count": len(self._feature_history),
                    "regime_failure_patterns": self._regime_failure_patterns,
                    "lesson_insights": self._lesson_insights,
                }
                with open(METADATA_PATH, 'wb') as f:
                    pickle.dump(metadata, f)
            logger.info(f"ML model saved to {MODEL_PATH}")
            return True
        except Exception as e:
            logger.error(f"Failed to save ML model: {e}")
            return False

    def _load_model(self) -> bool:
        """Load persisted model from disk."""
        if not os.path.exists(MODEL_PATH):
            return False
        try:
            with open(MODEL_PATH, 'rb') as f:
                self._model = pickle.load(f)
            # Load metadata
            if os.path.exists(METADATA_PATH):
                with open(METADATA_PATH, 'rb') as f:
                    metadata = pickle.load(f)
                    self._trained_on = metadata.get("trained_on", 0)
                    self._regime_failure_patterns = metadata.get("regime_failure_patterns", {})
                    self._lesson_insights = metadata.get("lesson_insights", [])
            logger.info(f"ML model loaded from {MODEL_PATH} (trained on {self._trained_on} samples)")
            return True
        except Exception as e:
            logger.error(f"Failed to load ML model: {e}")
            return False

    # ─── Learning from journal entries ────────────────────────────────────────

    def learn_from_lessons(self, journal_entries: list):
        """
        Process past journal entries to learn patterns.
        
        This extracts actionable insights from the journal and applies them
        to improve future trade decisions.
        
        Args:
            journal_entries: List of dicts with keys: regime, exit_reason, won, 
                           lessons, reflection, strategy_name
        """
        if not journal_entries:
            return
            
        for entry in journal_entries:
            regime = entry.get("market_regime", "UNKNOWN")
            won = entry.get("won", False)
            raw_lessons = entry.get("lessons", [])
            # Normalise to list (back-compat: may be a string from older data)
            if isinstance(raw_lessons, list):
                lesson_list = raw_lessons
            elif isinstance(raw_lessons, str):
                try:
                    parsed = json.loads(raw_lessons)
                    lesson_list = parsed if isinstance(parsed, list) else [parsed]
                except Exception:
                    lesson_list = [p.strip() for p in raw_lessons.split(" | ") if p.strip()]
            else:
                lesson_list = []
            strategy = entry.get("strategy_name", "")

            if not won:
                # Learn from failures
                if regime not in self._regime_failure_patterns:
                    self._regime_failure_patterns[regime] = []

                # Extract failure patterns — store each lesson individually
                for lesson_text in lesson_list:
                    failure_info = {
                        "strategy": strategy,
                        "exit_reason": entry.get("exit_reason", ""),
                        "lesson": lesson_text,
                    }
                    self._regime_failure_patterns[regime].append(failure_info)

                # Keep only recent patterns (last 50 per regime)
                if len(self._regime_failure_patterns[regime]) > 50:
                    self._regime_failure_patterns[regime] = self._regime_failure_patterns[regime][-50:]

            # Store individual lesson insights (deduplicated)
            for lesson_text in lesson_list:
                if lesson_text and lesson_text not in self._lesson_insights:
                    self._lesson_insights.append(lesson_text)
            # Keep only recent insights (last 100)
            if len(self._lesson_insights) > 100:
                self._lesson_insights = self._lesson_insights[-100:]
        
        # Save updated patterns
        self._save_model()
        logger.info(f"Learned from {len(journal_entries)} journal entries. "
                   f"Failure patterns: {sum(len(v) for v in self._regime_failure_patterns.values())}")

    def get_regime_caution_level(self, regime: str) -> float:
        """
        Get caution level (0-1) for a given regime based on past failures.
        Higher values mean more caution needed.
        """
        failures = self._regime_failure_patterns.get(regime, [])
        if not failures:
            return 0.0
        
        # More failures = higher caution
        failure_count = len(failures)
        caution = min(1.0, failure_count / 20.0)  # Max out at 20 failures
        
        # Check recent performance
        recent_failures = [f for f in failures[-10:] if f.get("exit_reason") == "STOP_LOSS"]
        if len(recent_failures) >= 5:
            caution = min(1.0, caution + 0.3)
        
        return caution

    def get_applicable_lessons(self, regime: str) -> list:
        """Get relevant lessons for the current market regime."""
        failures = self._regime_failure_patterns.get(regime, [])
        lessons = [f.get("lesson", "") for f in failures[-5:] if f.get("lesson")]
        return lessons

    @property
    def insights_count(self) -> int:
        """Number of accumulated lesson insights."""
        return len(self._lesson_insights)


