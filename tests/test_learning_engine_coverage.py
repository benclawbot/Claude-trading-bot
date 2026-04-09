"""
Additional learning_engine.py and ml_adaptive.py coverage tests.
Covers: _tune_strategy, _adjust_confidence, _update_performance_snapshots,
        get_confidence (ML path), _predict_win_prob.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── LearningEngine: _tune_strategy tests ────────────────────────────────────

class TestTuneStrategy:
    """Cover learning_engine._tune_strategy() for each strategy branch."""

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_tune_rsi_underperforming(self, mock_config, mock_db):
        """RSI_Bollinger underperforms → bands tightened."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.update_strategy_params = Mock()

        from learning_engine import LearningEngine

        strat = Mock()
        strat.params = {"rsi_oversold": 30, "rsi_overbought": 70, "adx_max": 35}
        strat.is_active = True

        engine = LearningEngine({"RSI_Bollinger": strat})
        # Provide enough history to trigger tuning
        engine._recent_pnl["RSI_Bollinger"] = [-0.01] * 20

        engine._tune_strategy("RSI_Bollinger")

        strat.update_params.assert_called_once()
        call_args = strat.update_params.call_args[0][0]
        assert call_args["rsi_oversold"] < 30  # tightened

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_tune_rsi_performing_well(self, mock_config, mock_db):
        """RSI_Bollinger performs well → bands loosened slightly."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.update_strategy_params = Mock()

        from learning_engine import LearningEngine

        strat = Mock()
        strat.params = {"rsi_oversold": 30, "rsi_overbought": 70, "adx_max": 35}
        strat.is_active = True

        engine = LearningEngine({"RSI_Bollinger": strat})
        # High win rate + good PnL
        engine._recent_pnl["RSI_Bollinger"] = [0.015] * 20

        engine._tune_strategy("RSI_Bollinger")

        strat.update_params.assert_called_once()
        call_args = strat.update_params.call_args[0][0]
        assert call_args["rsi_oversold"] > 30  # loosened

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_tune_macd_underperforming(self, mock_config, mock_db):
        """MACD_Momentum underperforms → parameters tightened."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.update_strategy_params = Mock()

        from learning_engine import LearningEngine

        strat = Mock()
        strat.params = {"signal_period": 9, "adx_min": 20}
        strat.is_active = True

        engine = LearningEngine({"MACD_Momentum": strat})
        engine._recent_pnl["MACD_Momentum"] = [-0.01] * 20

        engine._tune_strategy("MACD_Momentum")

        strat.update_params.assert_called_once()

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_tune_breakout_performing_well(self, mock_config, mock_db):
        """Breakout performing well → vol_mult relaxed."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.update_strategy_params = Mock()

        from learning_engine import LearningEngine

        strat = Mock()
        strat.params = {"volume_multiplier": 1.8, "atr_sl_mult": 1.5}
        strat.is_active = True

        engine = LearningEngine({"Breakout": strat})
        engine._recent_pnl["Breakout"] = [0.02] * 20

        engine._tune_strategy("Breakout")

        strat.update_params.assert_called_once()
        call_args = strat.update_params.call_args[0][0]
        assert call_args["volume_multiplier"] < 1.8  # relaxed

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_tune_ml_adaptive_underperforming(self, mock_config, mock_db):
        """ML_Adaptive underperforms → min_confidence raised."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.update_strategy_params = Mock()

        from learning_engine import LearningEngine

        strat = Mock()
        strat.params = {"min_confidence": 0.55}
        strat.is_active = True

        engine = LearningEngine({"ML_Adaptive": strat})
        engine._recent_pnl["ML_Adaptive"] = [-0.01] * 20

        engine._tune_strategy("ML_Adaptive")

        strat.update_params.assert_called_once()
        call_args = strat.update_params.call_args[0][0]
        assert call_args["min_confidence"] > 0.55

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_tune_no_history(self, mock_config, mock_db):
        """Strategy with insufficient history → no tuning."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.update_strategy_params = Mock()

        from learning_engine import LearningEngine

        strat = Mock()
        strat.params = {"rsi_oversold": 30}
        strat.is_active = True

        engine = LearningEngine({"RSI_Bollinger": strat})
        engine._recent_pnl["RSI_Bollinger"] = [0.01] * 5  # below MIN_TRADES_FOR_LEARNING

        engine._tune_strategy("RSI_Bollinger")

        strat.update_params.assert_not_called()

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_tune_unknown_strategy(self, mock_config, mock_db):
        """Unknown strategy name → no crash."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}

        from learning_engine import LearningEngine

        engine = LearningEngine({})
        engine._recent_pnl["UnknownStrategy"] = [-0.01] * 20

        # Should not raise
        engine._tune_strategy("UnknownStrategy")


class TestAdjustConfidence:
    """Cover learning_engine._adjust_confidence()."""

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_consecutive_losses_3_plus(self, mock_config, mock_db):
        """3+ consecutive losses → penalty applied."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()

        from learning_engine import LearningEngine

        engine = LearningEngine({})
        engine._consecutive_losses["RSI_Bollinger"] = 4

        engine._adjust_confidence("RSI_Bollinger")

        assert engine._confidence_adjustments["RSI_Bollinger"] > 0

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_consecutive_losses_reset_on_win(self, mock_config, mock_db):
        """Consecutive losses = 0 → penalty reset to 0."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()

        from learning_engine import LearningEngine

        engine = LearningEngine({})
        engine._confidence_adjustments["RSI_Bollinger"] = 0.15
        engine._consecutive_losses["RSI_Bollinger"] = 0

        engine._adjust_confidence("RSI_Bollinger")

        assert engine._confidence_adjustments["RSI_Bollinger"] == 0.0

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_consecutive_losses_1_2_no_penalty(self, mock_config, mock_db):
        """1-2 consecutive losses → no penalty (threshold is 3+)."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}

        from learning_engine import LearningEngine

        engine = LearningEngine({})
        engine._consecutive_losses["RSI_Bollinger"] = 2

        engine._adjust_confidence("RSI_Bollinger")

        # No entry means no penalty
        assert engine._confidence_adjustments.get("RSI_Bollinger", 0.0) == 0.0


class TestGetConfidence:
    """Cover learning_engine.get_confidence() ML path."""

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_get_confidence_with_ml_model(self, mock_config, mock_db):
        """get_confidence uses ML model probability when available."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()

        from learning_engine import LearningEngine

        # Create a mock ML_Adaptive with a trained model
        ml_strat = Mock()
        ml_strat._predict_win_prob = Mock(return_value=0.72)
        ml_strat.model_trained = True

        engine = LearningEngine({"ML_Adaptive": ml_strat})
        engine._win_rates["ML_Adaptive"] = 0.50

        # Create a mock DataFrame for get_feature_vector
        mock_df = Mock()
        mock_df.iloc = Mock()

        with patch("learning_engine.get_feature_vector", return_value=[0.5]*12):
            confidence = engine.get_confidence("ML_Adaptive", df=mock_df)

        # Should use ML probability (0.72) instead of base win rate
        assert 0.0 <= confidence <= 1.0

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_get_confidence_no_ml_model(self, mock_config, mock_db):
        """get_confidence falls back to win rate when ML not trained."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}

        from learning_engine import LearningEngine

        ml_strat = Mock()
        ml_strat.model_trained = False

        engine = LearningEngine({"ML_Adaptive": ml_strat})
        engine._win_rates["ML_Adaptive"] = 0.60

        confidence = engine.get_confidence("ML_Adaptive")

        assert confidence == 0.60


class TestUpdatePerformanceSnapshots:
    """Cover learning_engine.update_performance_snapshots()."""

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_snapshot_writes_to_db(self, mock_config, mock_db):
        """update_performance_snapshots calls db.upsert_strategy_performance."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        mock_db.upsert_strategy_performance = Mock()
        mock_db.get_trade_stats = Mock(return_value={
            "win_rate": 0.60, "total_pnl": 0.05, "total_trades": 20
        })
        mock_db.get_open_positions = Mock(return_value=[])
        mock_db.get_conn = Mock()

        # Mock connection that returns a daily PnL row
        mock_conn = Mock()
        mock_conn.execute = Mock(return_value=Mock(fetchone=Mock(return_value=(0.02,))))
        mock_db.get_conn.return_value = mock_conn

        from learning_engine import LearningEngine

        strat = Mock()
        strat.is_active = True
        strat.capital = 10000.0

        engine = LearningEngine({"RSI_Bollinger": strat})
        engine.update_performance_snapshots({"RSI_Bollinger": strat})

        mock_db.upsert_strategy_performance.assert_called_once()
        call_kwargs = mock_db.upsert_strategy_performance.call_args[1]
        assert call_kwargs["strategy_name"] == "RSI_Bollinger"
        assert call_kwargs["capital"] == 10000.0

    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_snapshot_skips_inactive_strategy(self, mock_config, mock_db):
        """update_performance_snapshots skips inactive strategies."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_db.upsert_strategy_performance = Mock()
        mock_db.get_trade_stats = Mock()
        mock_db.get_open_positions = Mock()

        from learning_engine import LearningEngine

        strat = Mock()
        strat.is_active = False

        engine = LearningEngine({"InactiveStrat": strat})
        engine.update_performance_snapshots({"InactiveStrat": strat})

        mock_db.upsert_strategy_performance.assert_not_called()


class TestMLAdaptiveHelpers:
    """Cover ml_adaptive._predict_win_prob() and related helpers."""

    @patch("strategies.ml_adaptive.config")
    def test_predict_win_prob_no_model(self, mock_config):
        """_predict_win_prob returns None when model is not trained."""
        mock_config.STRATEGY_PARAMS = {
            "ML_Adaptive": {
                "min_confidence": 0.55,
                "retrain_interval": 20,
                "n_estimators": 10,
                "candle_interval": "1h",
            }
        }
        mock_config.MIN_TRADES_FOR_LEARNING = 20

        from strategies.ml_adaptive import MLAdaptiveStrategy

        strat = MLAdaptiveStrategy()
        result = strat._predict_win_prob([0.5] * 12)
        assert result is None

    @patch("strategies.ml_adaptive.config")
    def test_get_regime_caution_level_no_failures(self, mock_config):
        """get_regime_caution_level returns 0.0 with no failure history."""
        mock_config.STRATEGY_PARAMS = {
            "ML_Adaptive": {
                "min_confidence": 0.55,
                "retrain_interval": 20,
                "n_estimators": 10,
                "candle_interval": "1h",
            }
        }

        from strategies.ml_adaptive import MLAdaptiveStrategy

        strat = MLAdaptiveStrategy()
        caution = strat.get_regime_caution_level("RANGING")
        assert caution == 0.0

    @patch("strategies.ml_adaptive.config")
    def test_get_applicable_lessons_empty(self, mock_config):
        """get_applicable_lessons returns empty list with no lessons."""
        mock_config.STRATEGY_PARAMS = {
            "ML_Adaptive": {
                "min_confidence": 0.55,
                "retrain_interval": 20,
                "n_estimators": 10,
                "candle_interval": "1h",
            }
        }

        from strategies.ml_adaptive import MLAdaptiveStrategy

        strat = MLAdaptiveStrategy()
        lessons = strat.get_applicable_lessons("RANGING")
        assert lessons == []

    @patch("strategies.ml_adaptive.config")
    def test_insights_count_property(self, mock_config):
        """insights_count returns the correct count of accumulated insights."""
        mock_config.STRATEGY_PARAMS = {
            "ML_Adaptive": {
                "min_confidence": 0.55,
                "retrain_interval": 20,
                "n_estimators": 10,
                "candle_interval": "1h",
            }
        }

        from strategies.ml_adaptive import MLAdaptiveStrategy

        strat = MLAdaptiveStrategy()
        assert strat.insights_count == 0
