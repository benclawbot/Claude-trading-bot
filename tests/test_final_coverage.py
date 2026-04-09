# Final targeted coverage tests for binance_client, learning_engine, portfolio_manager

import pytest
import pandas as pd
import numpy as np
import tempfile
import os
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── binance_client.py tests ────────────────────────────────────────────────────

class TestBinanceClientMethods:
    """Test BinanceClient public methods."""
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_get_account_balance_with_positions(self, mock_fetcher_cls, mock_config):
        """Test get_account_balance returns all assets."""
        mock_config.PAPER_TRADING = True
        mock_config.BINANCE_API_KEY = ""
        mock_config.BINANCE_API_SECRET = ""
        mock_config.USE_TESTNET = False
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0, "DEFAULT": 10.0}
        mock_config.TESTNET_REST_URL = "https://testnet.binance.vision/api"
        mock_config.ANTHROPIC_API_KEY = ""
        
        mock_fetcher = MagicMock()
        mock_fetcher.get_current_price.return_value = 50000.0
        mock_fetcher_cls.return_value = mock_fetcher
        
        from binance_client import BinanceClient
        
        with patch("binance_client.BINANCE_SDK_AVAILABLE", False):
            with patch("binance_client.WEBSOCKET_AVAILABLE", False):
                client = BinanceClient(use_websocket=False)
        
        balance = client.get_account_balance()
        assert "USDT" in balance
        assert "BTC" in balance
        assert balance["USDT"] == 10000.0
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_place_market_order_sell_side(self, mock_fetcher_cls, mock_config):
        """Test placing SELL order."""
        mock_config.PAPER_TRADING = True
        mock_config.BINANCE_API_KEY = ""
        mock_config.BINANCE_API_SECRET = ""
        mock_config.USE_TESTNET = False
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0, "DEFAULT": 10.0}
        mock_config.TESTNET_REST_URL = "https://testnet.binance.vision/api"
        mock_config.ANTHROPIC_API_KEY = ""
        
        mock_fetcher = MagicMock()
        mock_fetcher.get_current_price.return_value = 50000.0
        mock_fetcher.get_order_book_spread.return_value = 0.0005
        mock_fetcher_cls.return_value = mock_fetcher
        
        from binance_client import BinanceClient
        
        with patch("binance_client.BINANCE_SDK_AVAILABLE", False):
            with patch("binance_client.WEBSOCKET_AVAILABLE", False):
                client = BinanceClient(use_websocket=False)
        
        order = client.place_market_order("BTCUSDT", "SELL", 0.01)
        assert order is not None
        assert order["side"] == "SELL"


class TestCircuitBreakerEdge:
    """Test circuit breaker edge cases."""
    
    def test_circuit_breaker_immediate_open(self):
        """Test circuit breaker opens immediately with threshold=1."""
        from binance_client import CircuitBreaker
        
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        
        # One failure should open it
        cb.record_failure()
        assert cb.state == "open"
    
    def test_circuit_breaker_recovery_after_timeout(self):
        """Test circuit breaker recovers after timeout."""
        from binance_client import CircuitBreaker
        
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0)
        
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        
        # Force timeout to 0 (already at 0)
        cb._last_failure_time = 0
        can_proceed = cb.can_proceed()
        assert can_proceed == True
        assert cb.state == "half-open"
    
    def test_circuit_breaker_failure_count_reset(self):
        """Test that failure count resets on success."""
        from binance_client import CircuitBreaker
        
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=0)
        
        # 2 failures
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        
        # 1 success resets
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == "closed"


# ─── learning_engine.py tests ──────────────────────────────────────────────────

class TestLearningEngineJournal:
    """Test journal entry and lessons derivation."""
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_build_journal_reflection_win(self, mock_config, mock_db):
        """Test _build_journal_entry creates correct reflection for win."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"Strat": Mock()}
        engine = LearningEngine(strategies)
        
        journal = engine._build_journal_entry(
            trade_id=1, strategy_name="Strat",
            entry_price=50000, exit_price=51000,
            pnl=100, pnl_pct=0.02,
            side="LONG", duration_hours=2.0,
            exit_reason="TAKE_PROFIT",
            regime="RANGING",
            won=True,
            feature_vec=[0.5]*12,
        )
        
        assert "reflection" in journal
        assert "lessons" in journal
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_trending_up_win(self, mock_config, mock_db):
        """Test _derive_lessons for trending market with win."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        engine = LearningEngine({})
        
        lessons = engine._derive_lessons(
            strategy_name="Strat",
            won=True,
            regime="TRENDING_UP",
            exit_reason="TAKE_PROFIT",
            feature_vec=[0.5]*12,
        )
        assert isinstance(lessons, str)
        assert len(lessons) > 0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_ranging_loss(self, mock_config, mock_db):
        """Test _derive_lessons for ranging market with loss."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        engine = LearningEngine({})
        
        lessons = engine._derive_lessons(
            strategy_name="Strat",
            won=False,
            regime="RANGING",
            exit_reason="STOP_LOSS",
            feature_vec=[0.5]*12,
        )
        assert isinstance(lessons, str)
        assert len(lessons) > 0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_streak_info_edge_cases(self, mock_config, mock_db):
        """Test _streak_info edge cases."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        engine = LearningEngine({})
        
        # Empty history
        info = engine._streak_info([])
        assert "No trade history" in info
        
        # Single trade
        info = engine._streak_info([0.05])
        assert len(info) > 0
        
        # Long losing streak
        info = engine._streak_info([-0.01, -0.02, -0.015, -0.01])
        assert "losing streak" in info


# ─── portfolio_manager.py tests ────────────────────────────────────────────────

class TestPortfolioRisk:
    """Test portfolio risk checking."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_risk_check_ml_confidence_below_threshold(self, mock_config, mock_binance_cls, mock_db):
        """Test risk check rejects ML confidence below threshold."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.SYMBOL = "BTCUSDT"
        mock_config.MAX_OPEN_POSITIONS_PER_STRATEGY = 2
        mock_config.MAX_PORTFOLIO_DRAWDOWN_PCT = 0.20
        mock_config.MIN_POSITION_PCT = 0.05
        mock_config.CONFIDENCE_THRESHOLD = 0.40
        
        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()
        
        from portfolio_manager import PortfolioManager
        from strategies.base_strategy import Signal, SignalType
        
        strategy = Mock()
        strategy.name = "LowMLConf"
        strategy.is_active = True
        
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        pm._capital["LowMLConf"] = 1000
        pm._peak_capital["LowMLConf"] = 1000
        
        signal = Signal(SignalType.BUY, confidence=0.7)
        
        # ML confidence below 0.40 threshold
        result = pm._risk_check("LowMLConf", signal, ml_confidence=0.3)
        assert result == False


class TestPortfolioPositionSizing:
    """Test position sizing."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_size_position_confidence_scaling(self, mock_config, mock_binance_cls, mock_db):
        """Test position sizing scales with confidence."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.SYMBOL = "BTCUSDT"
        mock_config.MAX_OPEN_POSITIONS_PER_STRATEGY = 2
        mock_config.MAX_PORTFOLIO_DRAWDOWN_PCT = 0.20
        mock_config.MIN_POSITION_PCT = 0.05
        mock_config.CONFIDENCE_THRESHOLD = 0.40
        
        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()
        
        from portfolio_manager import PortfolioManager
        from strategies.base_strategy import Signal, SignalType
        
        strategy = Mock()
        strategy.name = "TestStrat"
        strategy.is_active = True
        
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        # Low confidence
        signal_low = Signal(SignalType.BUY, confidence=0.45)
        qty_low, notional_low = pm._size_position(1000, 50000, signal_low, 0.45)
        
        # High confidence
        signal_high = Signal(SignalType.BUY, confidence=0.95)
        qty_high, notional_high = pm._size_position(1000, 50000, signal_high, 0.95)
        
        # High confidence should give more notional
        assert notional_high >= notional_low


class TestPortfolioMonitoring:
    """Test position monitoring and closing."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_check_sl_tp_short_stop_loss(self, mock_config, mock_binance_cls, mock_db):
        """Test _check_sl_tp for SHORT stop loss."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.SYMBOL = "BTCUSDT"
        mock_config.MAX_OPEN_POSITIONS_PER_STRATEGY = 2
        mock_config.MAX_PORTFOLIO_DRAWDOWN_PCT = 0.20
        mock_config.MIN_POSITION_PCT = 0.05
        mock_config.CONFIDENCE_THRESHOLD = 0.40
        
        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()
        
        from portfolio_manager import PortfolioManager
        
        strategy = Mock()
        strategy.name = "TestStrat"
        strategy.is_active = True
        
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        pos = {
            "side": "SHORT",
            "stop_loss": 51000,
            "take_profit": 48000,
        }
        
        hit, reason = PortfolioManager._check_sl_tp(pos, 51100)
        assert hit == True
        assert reason == "STOP_LOSS"
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_close_position_short_profit(self, mock_config, mock_binance_cls, mock_db):
        """Test closing a profitable SHORT position."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.SYMBOL = "BTCUSDT"
        mock_config.MAX_OPEN_POSITIONS_PER_STRATEGY = 2
        mock_config.MAX_PORTFOLIO_DRAWDOWN_PCT = 0.20
        mock_config.MIN_POSITION_PCT = 0.05
        mock_config.CONFIDENCE_THRESHOLD = 0.40
        
        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()
        mock_db.record_trade = Mock(return_value=1)
        mock_db.close_position = Mock()
        
        from portfolio_manager import PortfolioManager
        
        strat = Mock()
        strat.name = "CloseStrat"
        strat.is_active = True
        strat.capital = 5000
        
        mock_client = MagicMock()
        mock_client.place_market_order.return_value = {
            "fills": [{"price": "49000.0", "qty": "0.1"}]
        }
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strat])
        
        pm._capital["CloseStrat"] = 5000
        pm._peak_capital["CloseStrat"] = 5000
        
        pos = {
            "id": 1,
            "strategy_name": "CloseStrat",
            "side": "SHORT",
            "entry_price": 50000,
            "quantity": 0.1,
            "stop_loss": 51000,
            "take_profit": 48000,
            "entry_time": "2024-01-01T00:00:00Z",
            "metadata": {},
        }
        
        result = pm._close_position(pos, 49000, "TAKE_PROFIT")
        
        assert result is not None
        mock_client.place_market_order.assert_called_once()


class TestPortfolioCloseBySignal:
    """Test close_position_by_signal."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_close_by_signal_no_positions(self, mock_config, mock_binance_cls, mock_db):
        """Test close_position_by_signal with no open positions."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.SYMBOL = "BTCUSDT"
        mock_config.MAX_OPEN_POSITIONS_PER_STRATEGY = 2
        mock_config.MAX_PORTFOLIO_DRAWDOWN_PCT = 0.20
        mock_config.MIN_POSITION_PCT = 0.05
        mock_config.CONFIDENCE_THRESHOLD = 0.40
        
        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()
        
        from portfolio_manager import PortfolioManager
        
        strat = Mock()
        strat.name = "SignalStrat"
        strat.is_active = True
        
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strat])
        
        # Should not raise
        pm.close_position_by_signal(strat, 50000)


# ─── ml_adaptive strategy tests ─────────────────────────────────────────────────

class TestMLAdaptiveStrategy:
    """Test ML Adaptive Strategy methods."""
    
    @patch("strategies.ml_adaptive.config")
    def test_get_applicable_lessons_max(self, mock_config):
        """Test get_applicable_lessons respects max limit."""
        mock_config.STRATEGY_PARAMS = {
            "ML_Adaptive": {
                "min_confidence": 0.55,
                "retrain_interval": 20,
                "n_estimators": 100,
                "candle_interval": "1h",
            }
        }
        from strategies.ml_adaptive import MLAdaptiveStrategy
        
        strat = MLAdaptiveStrategy()
        strat._regime_failure_patterns = {
            "RANGING": [
                {"lesson": f"Lesson {i}", "exit_reason": "STOP_LOSS"}
                for i in range(20)
            ]
        }
        
        lessons = strat.get_applicable_lessons("RANGING")
        assert len(lessons) == 5  # max 5 lessons
    
    @patch("strategies.ml_adaptive.config")
    def test_get_regime_caution_with_recent_failures(self, mock_config):
        """Test get_regime_caution_level with 5 recent stop losses."""
        mock_config.STRATEGY_PARAMS = {
            "ML_Adaptive": {
                "min_confidence": 0.55,
                "retrain_interval": 20,
                "n_estimators": 100,
                "candle_interval": "1h",
            }
        }
        from strategies.ml_adaptive import MLAdaptiveStrategy
        
        strat = MLAdaptiveStrategy()
        # Add 5 recent STOP_LOSS failures (should trigger additional caution)
        strat._regime_failure_patterns = {
            "TRENDING_DOWN": [
                {"exit_reason": "STOP_LOSS", "lesson": f"Fail {i}"}
                for i in range(5)
            ]
        }
        
        caution = strat.get_regime_caution_level("TRENDING_DOWN")
        # Should be higher than base due to 5 recent STOP_LOSS
        assert caution > 0.0
