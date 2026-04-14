# Tests for learning_engine.py

import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLearningEngine:
    """Test LearningEngine class."""
    
    @patch("learning_engine.config")
    @patch("learning_engine.db")
    def test_init(self, mock_db, mock_config):
        """Test LearningEngine initialization."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.STRATEGY_PARAMS = {}
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        assert engine.strategies == strategies
        assert engine._recent_pnl == {}
        assert engine._win_rates == {}
        assert engine._confidence_adjustments == {}
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_on_trade_closed_win(self, mock_config, mock_db):
        """Test on_trade_closed for a winning trade."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        # Create a minimal df
        dates = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
        close = 50000 + np.cumsum(np.random.randn(100) * 100)
        df = pd.DataFrame({"close": close}, index=dates)
        df = df.astype(float)
        
        # Add minimal required columns for add_all_indicators
        df["open"] = df["close"] + np.random.randn(100) * 50
        df["high"] = df["close"] + np.abs(np.random.randn(100) * 100)
        df["low"] = df["close"] - np.abs(np.random.randn(100) * 100)
        df["volume"] = np.random.rand(100) * 1000 + 500
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        # Mock compute_market_regime and get_feature_vector
        with patch("learning_engine.compute_market_regime", return_value="RANGING"):
            with patch("learning_engine.get_feature_vector", return_value=[0.5]*12):
                engine.on_trade_closed(
                    trade_id=1,
                    strategy_name="TestStrategy",
                    entry_price=50000,
                    exit_price=51000,
                    pnl=100,
                    pnl_pct=0.02,
                    side="LONG",
                    duration_hours=2.0,
                    exit_reason="TAKE_PROFIT",
                    entry_features={},
                    df=df,
                )
        
        # Check that recent_pnl was updated
        assert "TestStrategy" in engine._recent_pnl
        assert len(engine._recent_pnl["TestStrategy"]) == 1
        assert engine._recent_pnl["TestStrategy"][0] == 0.02
        
        # Win rate should be 100%
        assert engine._win_rates["TestStrategy"] == 1.0
        
        # Consecutive losses should be reset
        assert engine._consecutive_losses["TestStrategy"] == 0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_on_trade_closed_loss(self, mock_config, mock_db):
        """Test on_trade_closed for a losing trade."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        dates = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
        close = 50000 + np.cumsum(np.random.randn(100) * 100)
        df = pd.DataFrame({"close": close, "open": close + np.random.randn(100) * 50,
                           "high": close + np.abs(np.random.randn(100) * 100),
                           "low": close - np.abs(np.random.randn(100) * 100),
                           "volume": np.random.rand(100) * 1000 + 500}, index=dates)
        df = df.astype(float)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        with patch("learning_engine.compute_market_regime", return_value="RANGING"):
            with patch("learning_engine.get_feature_vector", return_value=[0.5]*12):
                engine.on_trade_closed(
                    trade_id=1,
                    strategy_name="TestStrategy",
                    entry_price=50000,
                    exit_price=49000,
                    pnl=-100,
                    pnl_pct=-0.02,
                    side="LONG",
                    duration_hours=2.0,
                    exit_reason="STOP_LOSS",
                    entry_features={},
                    df=df,
                )
        
        # Consecutive losses should be 1
        assert engine._consecutive_losses["TestStrategy"] == 1
        # Win rate should be 0%
        assert engine._win_rates["TestStrategy"] == 0.0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_consecutive_losses_penalty(self, mock_config, mock_db):
        """Test that consecutive losses apply a confidence penalty."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        # Simulate 3 consecutive losses
        engine._consecutive_losses["TestStrategy"] = 3
        engine._adjust_confidence("TestStrategy")
        
        assert engine._confidence_adjustments["TestStrategy"] > 0
        
        # 4 consecutive losses should give a larger penalty
        engine._confidence_adjustments["TestStrategy"] = 0.0
        engine._consecutive_losses["TestStrategy"] = 4
        engine._adjust_confidence("TestStrategy")
        
        assert engine._confidence_adjustments["TestStrategy"] > 0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_consecutive_losses_reset_on_win(self, mock_config, mock_db):
        """Test that consecutive losses reset on a winning trade."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        # Set up consecutive losses
        engine._consecutive_losses["TestStrategy"] = 3
        engine._confidence_adjustments["TestStrategy"] = 0.10
        
        # Now win
        dates = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
        close = 50000 + np.cumsum(np.random.randn(100) * 100)
        df = pd.DataFrame({"close": close, "open": close + np.random.randn(100) * 50,
                           "high": close + np.abs(np.random.randn(100) * 100),
                           "low": close - np.abs(np.random.randn(100) * 100),
                           "volume": np.random.rand(100) * 1000 + 500}, index=dates)
        df = df.astype(float)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        with patch("learning_engine.compute_market_regime", return_value="RANGING"):
            with patch("learning_engine.get_feature_vector", return_value=[0.5]*12):
                engine.on_trade_closed(
                    trade_id=2,
                    strategy_name="TestStrategy",
                    entry_price=50000,
                    exit_price=51000,
                    pnl=100,
                    pnl_pct=0.02,
                    side="LONG",
                    duration_hours=2.0,
                    exit_reason="TAKE_PROFIT",
                    entry_features={},
                    df=df,
                )
        
        # Consecutive losses should be reset to 0
        assert engine._consecutive_losses["TestStrategy"] == 0
        # Confidence adjustment should be reset
        assert engine._confidence_adjustments["TestStrategy"] == 0.0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_confidence_adjustment_penalty(self, mock_config, mock_db):
        """Test confidence adjustment penalty calculation."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        # Test penalty for 3 consecutive losses
        engine._consecutive_losses["TestStrategy"] = 3
        engine._adjust_confidence("TestStrategy")
        penalty = engine._confidence_adjustments["TestStrategy"]
        
        # Penalty should be between 0 and 0.15
        assert 0 < penalty <= 0.15
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_get_confidence(self, mock_config, mock_db):
        """Test get_confidence method."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        # Set a known win rate
        engine._win_rates["TestStrategy"] = 0.60
        engine._confidence_adjustments["TestStrategy"] = 0.0
        
        conf = engine.get_confidence("TestStrategy")
        assert 0 <= conf <= 1
        assert conf == 0.60
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_get_confidence_with_penalty(self, mock_config, mock_db):
        """Test get_confidence with a penalty applied."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        engine._win_rates["TestStrategy"] = 0.60
        engine._confidence_adjustments["TestStrategy"] = 0.10
        
        conf = engine.get_confidence("TestStrategy")
        # Should be 0.60 - 0.10 = 0.50
        assert conf == 0.50
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_get_confidence_unknown_strategy(self, mock_config, mock_db):
        """Test get_confidence for unknown strategy returns default."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {}
        engine = LearningEngine(strategies)
        
        conf = engine.get_confidence("UnknownStrategy")
        # Should return default of 0.55
        assert conf == 0.55


class TestJournalEntryBuilder:
    """Test journal entry building and lessons derivation."""
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_build_journal_entry(self, mock_config, mock_db):
        """Test _build_journal_entry creates proper structure."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        mock_db.get_journal_entries = Mock(return_value=[])
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        journal = engine._build_journal_entry(
            trade_id=1,
            strategy_name="TestStrategy",
            entry_price=50000,
            exit_price=51000,
            pnl=100,
            pnl_pct=0.02,
            side="LONG",
            duration_hours=2.0,
            exit_reason="TAKE_PROFIT",
            regime="RANGING",
            won=True,
            feature_vec=[0.5]*12,
        )
        
        assert journal["trade_id"] == 1
        assert journal["strategy_name"] == "TestStrategy"
        assert "reflection" in journal
        assert "lessons" in journal
        assert "setup_summary" in journal
        assert "outcome_analysis" in journal
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_low_win_rate(self, mock_config, mock_db):
        """Test _derive_lessons with low win rate."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"RSI_Bollinger": Mock()}
        engine = LearningEngine(strategies)
        
        lessons = engine._derive_lessons(
            strategy_name="RSI_Bollinger",
            won=False,
            regime="TRENDING_UP",
            exit_reason="STOP_LOSS",
            feature_vec=[0.5]*12,
        )

        assert isinstance(lessons, list)
        assert len(lessons) > 0
        assert any("RSI_Bollinger" in l for l in lessons)
        assert any("trending" in l.lower() for l in lessons)
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_consecutive_losses(self, mock_config, mock_db):
        """Test _derive_lessons with consecutive losses."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        lessons = engine._derive_lessons(
            strategy_name="TestStrategy",
            won=False,
            regime="RANGING",
            exit_reason="STOP_LOSS",
            feature_vec=[0.5]*12,
        )

        assert isinstance(lessons, list)
        assert len(lessons) > 0
        assert any("stopped out" in l.lower() or "stop" in l.lower() for l in lessons)
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_stop_loss(self, mock_config, mock_db):
        """Test _derive_lessons for stop loss exit."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        lessons = engine._derive_lessons(
            strategy_name="TestStrategy",
            won=False,
            regime="RANGING",
            exit_reason="STOP_LOSS",
            feature_vec=[0.5]*12,
        )

        assert isinstance(lessons, list)
        assert any("stopped out" in l.lower() or "stop" in l.lower() for l in lessons)
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_take_profit_win(self, mock_config, mock_db):
        """Test _derive_lessons for winning take profit."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrategy": Mock()}
        engine = LearningEngine(strategies)
        
        lessons = engine._derive_lessons(
            strategy_name="TestStrategy",
            won=True,
            regime="RANGING",
            exit_reason="TAKE_PROFIT",
            feature_vec=[0.5]*12,
        )

        assert isinstance(lessons, list)
        assert any("trailing" in l.lower() or "take" in l.lower() for l in lessons)


class TestStreakInfo:
    """Test streak information utility."""
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_streak_info_empty(self, mock_config, mock_db):
        """Test streak info with empty history."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {}
        engine = LearningEngine(strategies)
        
        info = engine._streak_info([])
        assert "No trade history" in info
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_streak_info_winning_streak(self, mock_config, mock_db):
        """Test streak info for winning streak."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {}
        engine = LearningEngine(strategies)
        
        history = [0.01, 0.02, 0.015, -0.005, 0.01, 0.03, 0.02]
        info = engine._streak_info(history)
        
        assert "winning streak" in info
        assert "3" in info  # Current winning streak of 3
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_streak_info_losing_streak(self, mock_config, mock_db):
        """Test streak info for losing streak."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {}
        engine = LearningEngine(strategies)
        
        history = [0.01, -0.02, -0.015, -0.01, -0.03]
        info = engine._streak_info(history)
        
        assert "losing streak" in info




