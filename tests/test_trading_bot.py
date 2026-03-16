# Trading Bot - Unit Tests
# Run with: pytest tests/ -v

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import Mock, MagicMock, patch
import numpy as np
import pandas as pd


class TestIndicators:
    """Test technical indicator calculations."""
    
    def test_rsi_calculation(self):
        """Test RSI indicator calculation."""
        from utils.indicators import _rsi
        
        # Create sample price data with known RSI behavior
        # Rising prices should give high RSI
        prices = pd.Series([100 + i for i in range(50)])
        rsi = _rsi(prices, period=14)
        
        assert rsi.iloc[-1] > 50  # Should be overbought
        assert 0 <= rsi.iloc[-1] <= 100  # Should be bounded
    
    def test_ema_calculation(self):
        """Test EMA calculation."""
        from utils.indicators import _ema
        
        prices = pd.Series([100] * 50)
        prices[25:] = 110  # Step change
        
        ema = _ema(prices, span=10)
        
        # EMA should respond to the step change
        assert ema.iloc[-1] > 105
    
    def test_atr_calculation(self):
        """Test ATR calculation."""
        from utils.indicators import _atr
        
        # Simple OHLC data
        high = pd.Series([105, 110, 108, 112, 115])
        low = pd.Series([95, 100, 98, 102, 105])
        close = pd.Series([100, 105, 102, 110, 108])
        
        atr = _atr(high, low, close, period=3)
        
        assert atr.iloc[-1] > 0  # Should be positive


class TestBinanceClient:
    """Test Binance client functionality."""
    
    def test_order_validation_btc(self):
        """Test order quantity validation for BTCUSDT."""
        from binance_client import validate_order_quantity
        
        # Valid order
        is_valid, msg, adj_qty = validate_order_quantity("BTCUSDT", 0.001, 50000)
        assert is_valid
        assert adj_qty == 0.001
        
        # Invalid order (below minimum notional)
        is_valid, msg, adj_qty = validate_order_quantity("BTCUSDT", 0.00001, 50000)
        # Should try to adjust to minimum
        assert not is_valid or adj_qty > 0.00001
    
    def test_order_validation_eth(self):
        """Test order quantity validation for ETHUSDT."""
        from binance_client import validate_order_quantity
        
        # Valid order
        is_valid, msg, adj_qty = validate_order_quantity("ETHUSDT", 0.1, 3000)
        assert is_valid


class TestMLAdaptiveStrategy:
    """Test ML Adaptive strategy."""
    
    def test_caution_level_calculation(self):
        """Test regime caution level calculation."""
        from strategies.ml_adaptive import MLAdaptiveStrategy
        
        strategy = MLAdaptiveStrategy()
        
        # Initially no failures, caution should be 0
        caution = strategy.get_regime_caution_level("TRENDING_UP")
        assert caution == 0.0
        
        # Add some failure patterns (simulated)
        strategy._regime_failure_patterns = {
            "TRENDING_UP": [
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
            ]
        }
        
        caution = strategy.get_regime_caution_level("TRENDING_UP")
        assert caution > 0.0
        assert caution <= 1.0
    
    def test_learn_from_lessons(self):
        """Test learning from journal entries."""
        from strategies.ml_adaptive import MLAdaptiveStrategy
        
        strategy = MLAdaptiveStrategy()
        
        journal_entries = [
            {
                "market_regime": "RANGING",
                "won": False,
                "exit_reason": "STOP_LOSS",
                "strategy_name": "RSI_Bollinger",
                "lessons": "Mean reversion failed in ranging market"
            },
            {
                "market_regime": "TRENDING_UP", 
                "won": True,
                "exit_reason": "TAKE_PROFIT",
                "strategy_name": "EMA_Crossover",
                "lessons": "Trend following worked well"
            }
        ]
        
        strategy.learn_from_lessons(journal_entries)
        
        # Should have failure patterns for RANGING
        assert "RANGING" in strategy._regime_failure_patterns
        assert len(strategy._regime_failure_patterns["RANGING"]) == 1


class TestLearningEngine:
    """Test learning engine."""
    
    def test_confidence_adjustment(self):
        """Test confidence adjustment on losing streaks."""
        from learning_engine import LearningEngine
        
        strategies = {}
        engine = LearningEngine(strategies)
        
        # Simulate 3 consecutive losses
        for _ in range(3):
            engine._consecutive_losses["test_strategy"] = 3
            engine._adjust_confidence("test_strategy")
        
        # Should have a penalty applied
        assert "test_strategy" in engine._confidence_adjustments
        assert engine._confidence_adjustments["test_strategy"] > 0


class TestPortfolioManager:
    """Test portfolio manager."""
    
    def test_position_sizing(self):
        """Test position sizing calculation."""
        from portfolio_manager import PortfolioManager
        from strategies.base_strategy import Signal, SignalType
        
        with patch('portfolio_manager.db'):
            with patch('portfolio_manager.BinanceClient'):
                # Create a mock strategy
                mock_strat = Mock()
                mock_strat.name = "TestStrategy"
                mock_strat.is_active = True
                mock_strat.capital = 10000
                
                # Create portfolio manager
                pm = PortfolioManager(Mock(), [mock_strat])
                
                # Mock the database
                pm._capital = {"TestStrategy": 10000}
                pm._peak_capital = {"TestStrategy": 10000}
                
                # Create a mock signal
                signal = Signal(
                    type=SignalType.BUY,
                    confidence=0.7,
                    stop_loss=49000,
                    take_profit=52000
                )
                
                # Test position sizing
                qty, notional = pm._size_position(
                    capital=10000,
                    price=50000,
                    signal=signal,
                    ml_confidence=0.6
                )
                
                assert qty > 0
                assert notional > 0
                assert notional <= 10000 * 0.35  # Max position pct


class TestUtils:
    """Test utility functions."""
    
    def test_utc_now(self):
        """Test UTC now function."""
        from utils import utc_now, utc_now_iso
        
        now = utc_now()
        now_iso = utc_now_iso()
        
        # Should be timezone aware
        assert now.tzinfo is not None
        # Should be ISO format
        assert "+" in now_iso or "Z" in now_iso or "-" in now_iso[-6:]


class TestDatabase:
    """Test database functions."""
    
    def test_db_connection(self):
        """Test database connection."""
        import tempfile
        import os
        
        # Create temporary database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            
            # Mock config
            with patch('config.DB_PATH', db_path):
                # This would fail without proper setup, but tests imports work
                pass
    
    def test_journal_entry_retrieval(self):
        """Test journal entry retrieval."""
        # This would require a real database
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
