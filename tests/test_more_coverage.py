# Additional targeted tests for coverage push

import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── binance_client.py: test public API surface ────────────────────────────────

class TestBinanceClientPublicAPI:
    """Test BinanceClient public API methods."""
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_get_account_balances(self, mock_fetcher_cls, mock_config):
        """Test get_account_balance returns multiple assets."""
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
        
        balances = client.get_account_balance()
        
        assert "USDT" in balances
        assert "BTC" in balances
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_place_market_order_returns_dict(self, mock_fetcher_cls, mock_config):
        """Test place_market_order returns a properly structured dict."""
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
        
        order = client.place_market_order("BTCUSDT", "BUY", 0.01)
        
        assert isinstance(order, dict)
        assert order["symbol"] == "BTCUSDT"
        assert order["status"] == "FILLED"
        assert "fills" in order
        assert "_paper_trade" in order
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_get_current_price_calls_data_fetcher(self, mock_fetcher_cls, mock_config):
        """Test get_current_price uses the data fetcher."""
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
        
        price = client.get_current_price("BTCUSDT")
        
        assert price == 50000.0
        mock_fetcher.get_current_price.assert_called_with("BTCUSDT")


# ─── learning_engine.py: test more of the engine ──────────────────────────────

class TestLearningEngineMore:
    """More learning engine tests."""
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_multiple_regimes(self, mock_config, mock_db):
        """Test _derive_lessons for different regime/win combinations."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        engine = LearningEngine({})
        
        # Test various combinations
        cases = [
            ("RANGING", True, "TAKE_PROFIT"),
            ("TRENDING_DOWN", False, "STOP_LOSS"),
            ("VOLATILE", False, "MAX_HOLD"),
            ("TRENDING_UP", True, "TAKE_PROFIT"),
            ("RANGING", False, "STOP_LOSS"),
        ]
        
        for regime, won, exit_reason in cases:
            lessons = engine._derive_lessons(
                strategy_name="TestStrat",
                won=won,
                regime=regime,
                exit_reason=exit_reason,
                feature_vec=[0.5]*12,
            )
            assert isinstance(lessons, str)
            assert len(lessons) > 0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_build_journal_entry_various_exits(self, mock_config, mock_db):
        """Test _build_journal_entry with different exit reasons."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        engine = LearningEngine({})
        
        for exit_reason in ["TAKE_PROFIT", "STOP_LOSS", "MAX_HOLD"]:
            journal = engine._build_journal_entry(
                trade_id=1,
                strategy_name="TestStrat",
                entry_price=50000,
                exit_price=49000,
                pnl=-100,
                pnl_pct=-0.02,
                side="LONG",
                duration_hours=4.0,
                exit_reason=exit_reason,
                regime="RANGING",
                won=False,
                feature_vec=[0.5]*12,
            )
            assert "reflection" in journal
            assert journal["market_regime"] == "RANGING"


# ─── portfolio_manager.py: more tests ─────────────────────────────────────

class TestPortfolioMore:
    """More portfolio manager tests."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_reallocate_method(self, mock_config, mock_binance_cls, mock_db):
        """Test reallocate method."""
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
        strat.name = "ReallocStrat"
        strat.is_active = True
        
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strat])
        
        # Should not raise
        pm.reallocate(current_price=50000)
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_size_position_short_signal(self, mock_config, mock_binance_cls, mock_db):
        """Test position sizing for SELL signal."""
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
        
        strat = Mock()
        strat.name = "ShortStrat"
        strat.is_active = True
        
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strat])
        
        signal = Signal(SignalType.SELL, confidence=0.7)
        qty, notional = pm._size_position(
            capital=1000,
            price=50000,
            signal=signal,
            ml_confidence=0.6,
        )
        
        assert qty > 0
        assert notional > 0
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_check_sl_tp_no_exit(self, mock_config, mock_binance_cls, mock_db):
        """Test _check_sl_tp returns None when no exit condition."""
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
        strat.name = "TestStrat"
        strat.is_active = True
        
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strat])
        
        # Price between SL and TP - no exit
        pos = {
            "side": "LONG",
            "stop_loss": 49000,
            "take_profit": 52000,
        }
        
        hit, reason = PortfolioManager._check_sl_tp(pos, 50500)
        assert hit == False
        assert reason == ""


# ─── strategy tests for uncovered strategies ──────────────────────────────────

class TestRegimeRiskOffStrategy:
    """Test Regime Risk-Off Strategy."""
    
    @patch("strategies.regime_riskoff.config")
    def test_regime_riskoff_bullish(self, mock_config):
        """Test Regime Risk-Off in bullish conditions."""
        mock_config.STRATEGY_PARAMS = {
            "Regime_RiskOnOff": {
                "ema_trend": 200,
                "rsi_bull_min": 50,
                "rsi_bear_max": 50,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 4.5,
                "candle_interval": "4h",
            }
        }
        from strategies.regime_riskoff import RegimeRiskOffStrategy
        from strategies.base_strategy import SignalType
        
        params = {
            "ema_trend": 200,
            "rsi_bull_min": 50,
            "rsi_bear_max": 50,
            "atr_sl_mult": 2.0,
            "atr_tp_mult": 4.5,
            "candle_interval": "4h",
        }
        
        n = 500
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        # Strong uptrend
        close = 50000 + np.cumsum(np.abs(np.random.randn(n) * 100) + 50)
        
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = RegimeRiskOffStrategy(params=params)
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestResidualMeanReversion:
    """Test Residual Mean Reversion Strategy."""
    
    @patch("strategies.residual_mean_reversion.config")
    def test_residual_strategy_signal(self, mock_config):
        """Test Residual Mean Reversion generates signal."""
        mock_config.STRATEGY_PARAMS = {
            "Residual_MeanRev": {
                "reg_window": 30,
                "zscore_window": 15,
                "entry_threshold": 1.2,
                "atr_sl_mult": 1.5,
                "atr_tp_mult": 3.0,
                "candle_interval": "4h",
            }
        }
        from strategies.residual_mean_reversion import ResidualMeanReversionStrategy
        from strategies.base_strategy import SignalType
        
        params = {
            "reg_window": 30,
            "zscore_window": 15,
            "entry_threshold": 1.2,
            "atr_sl_mult": 1.5,
            "atr_tp_mult": 3.0,
            "candle_interval": "4h",
        }
        
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        close = 50000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = ResidualMeanReversionStrategy(params=params)
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestBlendedMomentumMR:
    """Test Blended Momentum Mean Reversion Strategy."""
    
    @patch("strategies.blended_momentum_mr.config")
    def test_blended_signal(self, mock_config):
        """Test Blended Momentum MR generates signal."""
        mock_config.STRATEGY_PARAMS = {
            "Blended_MomentumMR": {
                "momentum_period": 20,
                "rsi_oversold": 35,
                "rsi_overbought": 65,
                "bb_period": 20,
                "bb_std": 2.0,
                "atr_sl_mult": 1.5,
                "atr_tp_mult": 3.0,
                "candle_interval": "4h",
            }
        }
        from strategies.blended_momentum_mr import BlendedMomentumMRStrategy
        from strategies.base_strategy import SignalType
        
        params = {
            "momentum_period": 20,
            "rsi_oversold": 35,
            "rsi_overbought": 65,
            "bb_period": 20,
            "bb_std": 2.0,
            "atr_sl_mult": 1.5,
            "atr_tp_mult": 3.0,
            "candle_interval": "4h",
        }
        
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        close = 50000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = BlendedMomentumMRStrategy(params=params)
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestDonchianBreakoutStrategy:
    """Test Donchian Breakout Strategy."""
    
    @patch("strategies.donchian_breakout.config")
    def test_donchian_signal(self, mock_config):
        """Test Donchian Breakout generates signal."""
        mock_config.STRATEGY_PARAMS = {
            "Donchian_Breakout": {
                "dc_period": 20,
                "adx_calm_max": 25,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 5.0,
                "candle_interval": "1d",
            }
        }
        from strategies.donchian_breakout import DonchianBreakoutStrategy
        from strategies.base_strategy import SignalType
        
        params = {
            "dc_period": 20,
            "adx_calm_max": 25,
            "atr_sl_mult": 2.0,
            "atr_tp_mult": 5.0,
            "candle_interval": "1d",
        }
        
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
        np.random.seed(42)
        close = 50000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = DonchianBreakoutStrategy(params=params)
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
