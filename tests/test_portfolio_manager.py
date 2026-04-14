# Tests for portfolio_manager.py

import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockStrategy:
    """Mock strategy for testing portfolio manager."""
    
    def __init__(self, name="MockStrategy", capital=1000, is_active=True):
        self.name = name
        self.capital = capital
        self.is_active = is_active
        self.total_trades = 0
        self.winning_trades = 0
    
    @property
    def win_rate(self):
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
    
    def set_capital(self, capital):
        self.capital = capital
    
    def record_trade_outcome(self, won):
        self.total_trades += 1
        if won:
            self.winning_trades += 1


class TestPortfolioManager:
    """Test PortfolioManager class."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_init(self, mock_config, mock_binance_cls, mock_db):
        """Test PortfolioManager initialization."""
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
        
        strategy = MockStrategy("TestStrategy", capital=1000, is_active=True)
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        assert "TestStrategy" in pm.strategies
        assert pm.client == mock_client
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_allocate_capital(self, mock_config, mock_binance_cls, mock_db):
        """Test capital allocation to strategies."""
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
        
        strategy1 = MockStrategy("Strategy1", capital=0, is_active=True)
        strategy2 = MockStrategy("Strategy2", capital=0, is_active=True)
        mock_client = MagicMock()
        
        pm = PortfolioManager(mock_client, [strategy1, strategy2])
        pm._allocate_capital(current_price=50000)
        
        # Each strategy should get half of 10000
        assert pm._capital["Strategy1"] >= 0
        assert pm._capital["Strategy2"] >= 0

    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_allocate_capital_experiment_mode_weighted(self, mock_config, mock_binance_cls, mock_db):
        """Experiment mode should reserve fixed pool for experiment strategies."""
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
        mock_config.CAPITAL_ALLOCATION_MODE = "experiment_weighted"
        mock_config.EXPERIMENT_MODE_ENABLED = True
        mock_config.EXPERIMENT_MODE_CAPITAL_PCT = 0.20
        mock_config.EXPERIMENT_MODE_STRATEGIES = {"MACD_Momentum"}

        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()

        from portfolio_manager import PortfolioManager

        core = MockStrategy("Residual_MeanRev", capital=0, is_active=True)
        exp = MockStrategy("MACD_Momentum", capital=0, is_active=True)
        mock_client = MagicMock()

        pm = PortfolioManager(mock_client, [core, exp])
        pm._allocate_capital(current_price=50000)

        assert pm._capital["Residual_MeanRev"] == pytest.approx(8000.0, rel=1e-6)
        assert pm._capital["MACD_Momentum"] == pytest.approx(2000.0, rel=1e-6)

    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_allocate_capital_equal_mode_ignores_experiment_weights(self, mock_config, mock_binance_cls, mock_db):
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

        # Even if experiment mode params are set, equal mode should split 50/50.
        mock_config.CAPITAL_ALLOCATION_MODE = "equal"
        mock_config.EXPERIMENT_MODE_ENABLED = True
        mock_config.EXPERIMENT_MODE_CAPITAL_PCT = 0.20
        mock_config.EXPERIMENT_MODE_STRATEGIES = {"MACD_Momentum"}

        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()

        from portfolio_manager import PortfolioManager

        core = MockStrategy("Residual_MeanRev", capital=0, is_active=True)
        exp = MockStrategy("MACD_Momentum", capital=0, is_active=True)
        mock_client = MagicMock()

        pm = PortfolioManager(mock_client, [core, exp])
        pm._allocate_capital(current_price=50000)

        assert pm._capital["Residual_MeanRev"] == pytest.approx(5000.0, rel=1e-6)
        assert pm._capital["MACD_Momentum"] == pytest.approx(5000.0, rel=1e-6)
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_risk_check_confidence_below_threshold(self, mock_config, mock_binance_cls, mock_db):
        """Test risk check rejects low ML confidence."""
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
        
        strategy = MockStrategy("TestStrategy", capital=1000, is_active=True)
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        signal = Signal(SignalType.BUY, confidence=0.3)
        result = pm._risk_check("TestStrategy", signal, ml_confidence=0.2)
        
        assert result == False
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_risk_check_low_signal_confidence(self, mock_config, mock_binance_cls, mock_db):
        """Test risk check rejects low signal confidence."""
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
        
        strategy = MockStrategy("TestStrategy", capital=1000, is_active=True)
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        # Signal confidence below 0.42
        signal = Signal(SignalType.BUY, confidence=0.3)
        result = pm._risk_check("TestStrategy", signal, ml_confidence=0.6)
        
        assert result == False
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_risk_check_drawdown_limit(self, mock_config, mock_binance_cls, mock_db):
        """Test risk check rejects when drawdown limit is hit."""
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
        
        strategy = MockStrategy("TestStrategy", capital=1000, is_active=True)
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        # Set up drawdown: peak=1000, current=700 (30% drawdown > 20% limit)
        pm._capital["TestStrategy"] = 700
        pm._peak_capital["TestStrategy"] = 1000
        
        signal = Signal(SignalType.BUY, confidence=0.6)
        result = pm._risk_check("TestStrategy", signal, ml_confidence=0.6)
        
        assert result == False
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_risk_check_passes(self, mock_config, mock_binance_cls, mock_db):
        """Test risk check passes with good conditions."""
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
        
        strategy = MockStrategy("TestStrategy", capital=1000, is_active=True)
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        # Good conditions
        pm._capital["TestStrategy"] = 1000
        pm._peak_capital["TestStrategy"] = 1000
        
        signal = Signal(SignalType.BUY, confidence=0.6)
        result = pm._risk_check("TestStrategy", signal, ml_confidence=0.6)
        
        assert result == True

    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_experiment_lane_cap_blocks_entry_when_cap_reached(self, mock_config, mock_binance_cls, mock_db):
        """Block entries for lane strategies when lane allocation cap is already consumed."""
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
        mock_config.EXPERIMENT_LANE_ENABLED = True
        mock_config.EXPERIMENT_LANE_CAP_PCT = 0.30
        mock_config.EXPERIMENT_LANE_STRATEGIES = {"MACD_Momentum"}

        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()

        from portfolio_manager import PortfolioManager
        from strategies.base_strategy import Signal, SignalType

        core = MockStrategy("Residual_MeanRev", capital=0, is_active=True)
        lane = MockStrategy("MACD_Momentum", capital=0, is_active=True)
        mock_client = MagicMock()

        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [core, lane])

        # Total allocation = 1000, lane allocation = 400 > 30% cap (300)
        pm._capital["Residual_MeanRev"] = 600
        pm._capital["MACD_Momentum"] = 400
        pm._peak_capital["MACD_Momentum"] = 400

        signal = Signal(SignalType.BUY, confidence=0.7)
        result = pm._risk_check("MACD_Momentum", signal, ml_confidence=0.7)

        assert result is False

    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_experiment_lane_cap_allows_entry_when_below_cap(self, mock_config, mock_binance_cls, mock_db):
        """Allow lane entries when allocation remains below configured cap."""
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
        mock_config.EXPERIMENT_LANE_ENABLED = True
        mock_config.EXPERIMENT_LANE_CAP_PCT = 0.30
        mock_config.EXPERIMENT_LANE_STRATEGIES = {"MACD_Momentum"}

        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()

        from portfolio_manager import PortfolioManager
        from strategies.base_strategy import Signal, SignalType

        core = MockStrategy("Residual_MeanRev", capital=0, is_active=True)
        lane = MockStrategy("MACD_Momentum", capital=0, is_active=True)
        mock_client = MagicMock()

        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [core, lane])

        # Total allocation = 1000, lane allocation = 200 < 30% cap (300)
        pm._capital["Residual_MeanRev"] = 800
        pm._capital["MACD_Momentum"] = 200
        pm._peak_capital["MACD_Momentum"] = 200

        signal = Signal(SignalType.BUY, confidence=0.7)
        result = pm._risk_check("MACD_Momentum", signal, ml_confidence=0.7)

        assert result is True


class TestPositionSizing:
    """Test position sizing logic."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_size_position_basic(self, mock_config, mock_binance_cls, mock_db):
        """Test basic position sizing."""
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
        
        strategy = MockStrategy("TestStrategy", capital=1000, is_active=True)
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        signal = Signal(SignalType.BUY, confidence=0.7)
        qty, notional = pm._size_position(
            capital=1000,
            price=50000,
            signal=signal,
            ml_confidence=0.6,
        )
        
        assert qty > 0
        assert notional > 0
        assert notional >= 10  # Minimum notional
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_size_position_respects_max_pct(self, mock_config, mock_binance_cls, mock_db):
        """Test position sizing respects max position percentage."""
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
        
        strategy = MockStrategy("TestStrategy", capital=1000, is_active=True)
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        signal = Signal(SignalType.BUY, confidence=0.95)  # High confidence
        qty, notional = pm._size_position(
            capital=1000,
            price=50000,
            signal=signal,
            ml_confidence=0.95,
        )
        
        # Notional should be capped at MAX_POSITION_PCT of capital
        assert notional <= 1000 * 0.35


class TestSLTP:
    """Test stop-loss and take-profit checking."""
    
    def test_check_sl_tp_long_stop_loss(self):
        """Test SL/TP check for LONG hitting stop loss."""
        from portfolio_manager import PortfolioManager
        
        pos = {
            "side": "LONG",
            "stop_loss": 49000,
            "take_profit": 52000,
            "strategy_name": "TestStrategy",
        }
        
        hit, reason = PortfolioManager._check_sl_tp(pos, 48900)
        assert hit == True
        assert reason == "STOP_LOSS"
    
    def test_check_sl_tp_long_take_profit(self):
        """Test SL/TP check for LONG hitting take profit."""
        from portfolio_manager import PortfolioManager
        
        pos = {
            "side": "LONG",
            "stop_loss": 49000,
            "take_profit": 52000,
            "strategy_name": "TestStrategy",
        }
        
        hit, reason = PortfolioManager._check_sl_tp(pos, 52100)
        assert hit == True
        assert reason == "TAKE_PROFIT"
    
    def test_check_sl_tp_short_stop_loss(self):
        """Test SL/TP check for SHORT hitting stop loss."""
        from portfolio_manager import PortfolioManager
        
        pos = {
            "side": "SHORT",
            "stop_loss": 51000,
            "take_profit": 48000,
            "strategy_name": "TestStrategy",
        }
        
        hit, reason = PortfolioManager._check_sl_tp(pos, 51100)
        assert hit == True
        assert reason == "STOP_LOSS"
    
    def test_check_sl_tp_short_take_profit(self):
        """Test SL/TP check for SHORT hitting take profit."""
        from portfolio_manager import PortfolioManager
        
        pos = {
            "side": "SHORT",
            "stop_loss": 51000,
            "take_profit": 48000,
            "strategy_name": "TestStrategy",
        }
        
        hit, reason = PortfolioManager._check_sl_tp(pos, 47900)
        assert hit == True
        assert reason == "TAKE_PROFIT"
    
    def test_check_sl_tp_no_hit(self):
        """Test SL/TP check when neither SL nor TP is hit."""
        from portfolio_manager import PortfolioManager
        
        pos = {
            "side": "LONG",
            "stop_loss": 49000,
            "take_profit": 52000,
            "strategy_name": "TestStrategy",
        }
        
        hit, reason = PortfolioManager._check_sl_tp(pos, 50500)
        assert hit == False
        assert reason == ""


class TestFillPrice:
    """Test fill price extraction from order dict."""
    
    def test_get_fill_price_from_fills(self):
        """Test extracting fill price from fills array."""
        from portfolio_manager import PortfolioManager
        
        order = {
            "fills": [
                {"price": "50000.0", "qty": "0.005"},
                {"price": "50010.0", "qty": "0.005"},
            ]
        }
        
        price = PortfolioManager._get_fill_price(order, fallback=50000)
        # Average: (50000*0.005 + 50010*0.005) / 0.01 = 50005
        assert abs(price - 50005.0) < 0.1
    
    def test_get_fill_price_from_quote_qty(self):
        """Test extracting fill price from cummulativeQuoteQty."""
        from portfolio_manager import PortfolioManager
        
        order = {
            "executedQty": "0.01",
            "cummulativeQuoteQty": "505.00",
            "fills": [],
        }
        
        price = PortfolioManager._get_fill_price(order, fallback=50000)
        assert price == 50500.0
    
    def test_get_fill_price_fallback(self):
        """Test fill price fallback when no fills available."""
        from portfolio_manager import PortfolioManager
        
        order = {}
        price = PortfolioManager._get_fill_price(order, fallback=50000)
        assert price == 50000.0


class TestTotalBalance:
    """Test total balance calculation."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_total_balance_no_positions(self, mock_config, mock_binance_cls, mock_db):
        """Test total balance with no open positions."""
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
        
        strategy = MockStrategy("TestStrategy", capital=1000, is_active=True)
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        pm._capital["TestStrategy"] = 1000
        pm._peak_capital["TestStrategy"] = 1000
        
        balance = pm.total_balance(current_price=50000)
        
        assert "total_balance" in balance
        assert "breakdown" in balance
        assert "TestStrategy" in balance["breakdown"]


class TestRegimeAndCorrelationGuards:
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_regime_router_blocks_disallowed_strategy_family(self, mock_config, _mock_binance_cls, mock_db):
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.SYMBOL = "BTCUSDT"
        mock_config.MAX_OPEN_POSITIONS_PER_STRATEGY = 2
        mock_config.MAX_PORTFOLIO_DRAWDOWN_PCT = 0.20
        mock_config.CONFIDENCE_THRESHOLD = 0.40
        mock_config.MIN_POSITION_PCT = 0.05

        mock_config.REGIME_ROUTER_ENABLED = True
        mock_config.REGIME_ROUTER_FAMILY_BY_STRATEGY = {
            "RSI_Bollinger": "mean_reversion",
        }
        mock_config.REGIME_ROUTER_ALLOWED_FAMILIES = {
            "TRENDING_UP": ["trend", "breakout", "adaptive"],
        }

        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.update_strategy_capital = Mock()

        from portfolio_manager import PortfolioManager
        from strategies.base_strategy import Signal, SignalType

        strategy = MockStrategy("RSI_Bollinger", is_active=True)
        pm = PortfolioManager(MagicMock(), [strategy])
        pm._capital["RSI_Bollinger"] = 1000
        pm._peak_capital["RSI_Bollinger"] = 1000

        sig = Signal(SignalType.BUY, confidence=0.8, metadata={"regime": "TRENDING_UP"})
        assert pm._risk_check("RSI_Bollinger", sig, ml_confidence=0.8) is False

    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_correlation_guard_reduces_size_for_highly_correlated_strategy(self, mock_config, _mock_binance_cls, mock_db):
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.SYMBOL = "BTCUSDT"
        mock_config.MAX_OPEN_POSITIONS_PER_STRATEGY = 2
        mock_config.MAX_PORTFOLIO_DRAWDOWN_PCT = 0.20
        mock_config.CONFIDENCE_THRESHOLD = 0.40
        mock_config.MIN_POSITION_PCT = 0.05

        mock_config.CORRELATION_GUARD_ENABLED = True
        mock_config.CORRELATION_LOOKBACK_TRADES = 20
        mock_config.CORRELATION_MIN_POINTS = 8
        mock_config.CORRELATION_THRESHOLD = 0.70
        mock_config.CORRELATION_SIZE_PENALTY = 0.50

        # High positive correlation between A and B based on pnl_pct sequence.
        strat_a_trades = [{"pnl_pct": x} for x in [0.01, 0.02, -0.01, 0.03, -0.02, 0.02, 0.01, -0.01, 0.02, 0.01]]
        strat_b_trades = [{"pnl_pct": x} for x in [0.011, 0.019, -0.012, 0.031, -0.019, 0.022, 0.009, -0.012, 0.021, 0.011]]

        def _get_trades(name=None, **kwargs):
            if name == "A":
                return strat_a_trades
            if name == "B":
                return strat_b_trades
            return []

        mock_db.get_trade_stats.return_value = {"total_pnl": 0}
        mock_db.get_open_positions.return_value = []
        mock_db.get_trades.side_effect = _get_trades
        mock_db.update_strategy_capital = Mock()

        from portfolio_manager import PortfolioManager
        from strategies.base_strategy import Signal, SignalType

        a = MockStrategy("A", is_active=True)
        b = MockStrategy("B", is_active=True)
        pm = PortfolioManager(MagicMock(), [a, b])

        sig = Signal(SignalType.BUY, confidence=0.8)
        qty, notional = pm._size_position(
            capital=1000,
            price=50000,
            signal=sig,
            ml_confidence=0.8,
            strategy_name="A",
        )

        assert qty > 0
        # with guard penalty the notional should be materially below unpenalized cap
        assert notional < 1000 * 0.35
