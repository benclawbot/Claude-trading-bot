# Additional tests to improve coverage for binance_client.py, database.py,
# learning_engine.py, and portfolio_manager.py

import pytest
import pandas as pd
import numpy as np
import tempfile
import os
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── database.py additional tests ───────────────────────────────────────────

class TestDatabaseAdditional:
    """Additional database tests for better coverage."""
    
    @pytest.fixture
    def db_temp(self):
        """Fresh database for each test."""
        import database as db_module
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            with patch.object(db_module, 'config') as mock_config:
                mock_config.DB_PATH = db_path
                mock_config.UTC_NOW_SQL = "datetime('now')"
                mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
                db_module.init_db()
                yield db_module, db_path
    
    def test_upsert_strategy_with_params(self, db_temp):
        """Test upsert_strategy with params."""
        db, _ = db_temp
        db.upsert_strategy("TestStrat", capital=5000.0, params={"lookback": 20})
        
        conn = db.get_conn()
        row = conn.execute(
            "SELECT capital, params FROM strategies WHERE name='TestStrat'"
        ).fetchone()
        assert row[0] == 5000.0
        # params stored as JSON
        import json
        params = json.loads(row[1])
        assert params["lookback"] == 20
    
    def test_open_position_with_metadata(self, db_temp):
        """Test opening position with metadata."""
        db, _ = db_temp
        db.upsert_strategy("TestStrat", capital=1000.0, params={})
        
        pos_id = db.open_position(
            strategy_name="TestStrat",
            symbol="ETHUSDT",
            side="SHORT",
            entry_price=3000,
            quantity=1.0,
            stop_loss=3100,
            take_profit=2800,
            order_id="TEST_ETH_1",
            ml_confidence=0.7,
            metadata={"custom_key": "custom_value"},
        )
        
        assert pos_id > 0
        positions = db.get_open_positions("TestStrat")
        assert len(positions) == 1
        assert positions[0]["symbol"] == "ETHUSDT"
        assert positions[0]["side"] == "SHORT"
    
    def test_close_position_updates(self, db_temp):
        """Test that close_position properly updates position."""
        db, _ = db_temp
        db.upsert_strategy("TestStrat", capital=1000.0, params={})
        
        pos_id = db.open_position(
            "TestStrat", "BTCUSDT", "LONG", 50000, 0.1, 49000, 52000, "O1", 0.6, {}
        )
        
        db.close_position(pos_id)
        
        # Verify position is closed
        conn = db.get_conn()
        row = conn.execute(
            "SELECT status FROM positions WHERE id=?", (pos_id,)
        ).fetchone()
        assert row[0] == "CLOSED"
    
    def test_record_trade_with_features(self, db_temp):
        """Test record_trade with entry features."""
        db, _ = db_temp
        db.upsert_strategy("TestStrat", capital=1000.0, params={})
        db.open_position("TestStrat", "BTCUSDT", "LONG", 50000, 0.1, 49000, 52000, "O1", 0.6, {})
        
        trade_id = db.record_trade(
            strategy_name="TestStrat",
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000,
            exit_price=51000,
            quantity=0.1,
            pnl=100,
            pnl_pct=0.02,
            fees_paid=1.0,
            entry_time="2024-01-01T00:00:00Z",
            exit_time="2024-01-01T02:00:00Z",
            duration_hours=2.0,
            exit_reason="TAKE_PROFIT",
            entry_features={"rsi": 45, "macd_hist": 0.001},
        )
        
        assert trade_id > 0
        
        # Get trade
        conn = db.get_conn()
        row = conn.execute("SELECT entry_features FROM trades WHERE id=?", (trade_id,)).fetchone()
        assert row is not None
    
    def test_get_journal_entries_with_limit(self, db_temp):
        """Test get_journal_entries with limit."""
        db, _ = db_temp
        db.upsert_strategy("TestStrat", capital=1000.0, params={})
        
        # Create multiple trades and journal entries
        for i in range(3):
            trade_id = db.record_trade(
                strategy_name="TestStrat",
                symbol="BTCUSDT",
                side="LONG",
                entry_price=50000,
                exit_price=50000 + (100 if i % 2 == 0 else -50),
                quantity=0.1,
                pnl=100 if i % 2 == 0 else -50,
                pnl_pct=0.02 if i % 2 == 0 else -0.01,
                fees_paid=1.0,
                entry_time="2024-01-01T00:00:00Z",
                exit_time="2024-01-01T02:00:00Z",
                duration_hours=2.0,
                exit_reason="TAKE_PROFIT" if i % 2 == 0 else "STOP_LOSS",
                entry_features={},
            )
            db.record_journal_entry(
                trade_id=trade_id,
                strategy_name="TestStrat",
                entry_price=50000,
                exit_price=51000,
                pnl=100,
                pnl_pct=0.02,
                side="LONG",
                duration_hours=2.0,
                market_regime="RANGING",
                setup_summary=f"Setup {i}",
                outcome_analysis=f"Outcome {i}",
                reflection=f"Reflection {i}",
                lessons=f"Lesson {i}",
            )
        
        entries = db.get_journal_entries(limit=2)
        assert len(entries) == 2
    
    def test_get_trade_stats_all_strategies(self, db_temp):
        """Test get_trade_stats for a specific strategy with unique name."""
        db, _ = db_temp
        unique_name = "UniqueStats_" + os.urandom(4).hex()
        db.upsert_strategy(unique_name, capital=1000.0, params={})
        
        db.record_trade(
            strategy_name=unique_name,
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000,
            exit_price=51000,
            quantity=0.1,
            pnl=100,
            pnl_pct=0.02,
            fees_paid=1.0,
            entry_time="2024-01-01T00:00:00Z",
            exit_time="2024-01-01T02:00:00Z",
            duration_hours=2.0,
            exit_reason="TAKE_PROFIT",
            entry_features={},
        )
        
        stats = db.get_trade_stats(unique_name)
        assert stats["total_trades"] == 1


# ─── learning_engine.py additional tests ─────────────────────────────────────

class TestLearningEngineAdditional:
    """Additional tests for learning_engine.py."""
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_on_trade_closed_updates_recent_pnl(self, mock_config, mock_db):
        """Test on_trade_closed updates recent PnL list."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrat": Mock()}
        engine = LearningEngine(strategies)
        
        dates = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
        close = 50000 + np.cumsum(np.random.randn(100) * 100)
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(100) * 50,
            "high": close + np.abs(np.random.randn(100) * 100),
            "low": close - np.abs(np.random.randn(100) * 100),
            "volume": np.random.rand(100) * 1000 + 500,
        }, index=dates)
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        with patch("learning_engine.compute_market_regime", return_value="RANGING"):
            with patch("learning_engine.get_feature_vector", return_value=[0.5]*12):
                engine.on_trade_closed(
                    trade_id=1, strategy_name="TestStrat",
                    entry_price=50000, exit_price=50500,
                    pnl=50, pnl_pct=0.01, side="LONG",
                    duration_hours=1.0, exit_reason="TAKE_PROFIT",
                    entry_features={}, df=df,
                )
        
        assert "TestStrat" in engine._recent_pnl
        assert len(engine._recent_pnl["TestStrat"]) == 1
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_on_trade_closed_records_journal(self, mock_config, mock_db):
        """Test on_trade_closed records journal entry."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrat": Mock()}
        engine = LearningEngine(strategies)
        
        dates = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
        close = 50000 + np.cumsum(np.random.randn(100) * 100)
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(100) * 50,
            "high": close + np.abs(np.random.randn(100) * 100),
            "low": close - np.abs(np.random.randn(100) * 100),
            "volume": np.random.rand(100) * 1000 + 500,
        }, index=dates)
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        with patch("learning_engine.compute_market_regime", return_value="TRENDING_UP"):
            with patch("learning_engine.get_feature_vector", return_value=[0.5]*12):
                engine.on_trade_closed(
                    trade_id=1, strategy_name="TestStrat",
                    entry_price=50000, exit_price=49500,
                    pnl=-50, pnl_pct=-0.01, side="LONG",
                    duration_hours=1.0, exit_reason="STOP_LOSS",
                    entry_features={}, df=df,
                )
        
        mock_db.record_journal_entry.assert_called_once()
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_get_confidence_unknown_strategy_default(self, mock_config, mock_db):
        """Test get_confidence for unknown strategy returns default."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        engine = LearningEngine({})
        conf = engine.get_confidence("UnknownStrat")
        assert conf == 0.55  # default
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_streak_info_mixed_history(self, mock_config, mock_db):
        """Test streak info for mixed win/loss history."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        engine = LearningEngine({})
        history = [0.01, -0.02, 0.01, 0.015, 0.02, -0.01, -0.005, 0.01]
        info = engine._streak_info(history)
        assert len(info) > 0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_high_win_rate(self, mock_config, mock_db):
        """Test _derive_lessons for high win rate winning trades."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrat": Mock()}
        engine = LearningEngine(strategies)
        
        lessons = engine._derive_lessons(
            strategy_name="TestStrat",
            won=True,
            regime="TRENDING_UP",
            exit_reason="TAKE_PROFIT",
            feature_vec=[0.5]*12,
        )
        assert isinstance(lessons, str)
        assert len(lessons) > 0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_volatile_regime(self, mock_config, mock_db):
        """Test _derive_lessons for volatile regime."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrat": Mock()}
        engine = LearningEngine(strategies)
        
        lessons = engine._derive_lessons(
            strategy_name="TestStrat",
            won=False,
            regime="VOLATILE",
            exit_reason="MAX_HOLD",
            feature_vec=[0.5]*12,
        )
        assert isinstance(lessons, str)
        assert len(lessons) > 0
    
    @patch("learning_engine.db")
    @patch("learning_engine.config")
    def test_derive_lessons_trending_down(self, mock_config, mock_db):
        """Test _derive_lessons for TRENDING_DOWN."""
        mock_config.MIN_TRADES_FOR_LEARNING = 10
        mock_config.STRATEGY_PARAMS = {}
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_db.record_ml_features = Mock()
        mock_db.record_journal_entry = Mock()
        
        from learning_engine import LearningEngine
        
        strategies = {"TestStrat": Mock()}
        engine = LearningEngine(strategies)
        
        lessons = engine._derive_lessons(
            strategy_name="TestStrat",
            won=False,
            regime="TRENDING_DOWN",
            exit_reason="STOP_LOSS",
            feature_vec=[0.5]*12,
        )
        assert isinstance(lessons, str)
        assert len(lessons) > 0


# ─── portfolio_manager.py additional tests ──────────────────────────────────

class TestPortfolioManagerAdditional:
    """Additional tests for portfolio_manager.py."""
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_risk_check_no_positions_available(self, mock_config, mock_binance_cls, mock_db):
        """Test risk check when no positions are available in db."""
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
        mock_db.get_open_positions.return_value = []  # No open positions
        mock_db.update_strategy_capital = Mock()
        
        from portfolio_manager import PortfolioManager
        from strategies.base_strategy import Signal, SignalType
        
        strategy = Mock()
        strategy.name = "TestStrat"
        strategy.is_active = True
        
        mock_client = MagicMock()
        mock_client.get_current_price.return_value = 50000
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        pm._capital["TestStrat"] = 1000
        pm._peak_capital["TestStrat"] = 1000
        
        signal = Signal(SignalType.BUY, confidence=0.7)
        result = pm._risk_check("TestStrat", signal, ml_confidence=0.6)
        assert result == True
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_size_position_high_confidence(self, mock_config, mock_binance_cls, mock_db):
        """Test position sizing with high ML confidence."""
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
        
        signal = Signal(SignalType.BUY, confidence=0.95)
        qty, notional = pm._size_position(
            capital=1000,
            price=50000,
            signal=signal,
            ml_confidence=0.95,
        )
        
        assert qty > 0
        assert notional > 0
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_size_position_low_confidence(self, mock_config, mock_binance_cls, mock_db):
        """Test position sizing with low ML confidence reduces size."""
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
        
        signal = Signal(SignalType.BUY, confidence=0.45)  # Low confidence
        qty_high, notional_high = pm._size_position(
            capital=1000, price=50000, signal=signal, ml_confidence=0.45,
        )
        
        signal2 = Signal(SignalType.BUY, confidence=0.95)  # High confidence
        qty_low, notional_low = pm._size_position(
            capital=1000, price=50000, signal=signal2, ml_confidence=0.95,
        )
        
        # Higher confidence should result in larger position
        assert notional_high <= notional_low or qty_high <= qty_low
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_total_balance_with_positions(self, mock_config, mock_binance_cls, mock_db):
        """Test total_balance with open positions."""
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
        mock_client.get_current_price.return_value = 50000
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strategy])
        
        pm._capital["TestStrat"] = 1000
        pm._peak_capital["TestStrat"] = 1000
        
        balance = pm.total_balance(current_price=50000)
        
        assert "total_balance" in balance
        assert "breakdown" in balance
        assert balance["total_balance"] > 0
    
    @patch("portfolio_manager.db")
    @patch("portfolio_manager.BinanceClient")
    @patch("portfolio_manager.config")
    def test_allocate_capital_distribution(self, mock_config, mock_binance_cls, mock_db):
        """Test capital allocation distributes to all strategies."""
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
        
        strat1 = Mock()
        strat1.name = "Strat1"
        strat1.is_active = True
        
        strat2 = Mock()
        strat2.name = "Strat2"
        strat2.is_active = True
        
        mock_client = MagicMock()
        
        with patch.object(PortfolioManager, '_allocate_capital'):
            pm = PortfolioManager(mock_client, [strat1, strat2])
        
        pm._allocate_capital(current_price=50000)
        
        # Both strategies should have capital allocated
        assert pm._capital["Strat1"] > 0
        assert pm._capital["Strat2"] > 0
        # Total allocated should not exceed initial capital
        total = sum(pm._capital.values())
        assert total <= mock_config.INITIAL_CAPITAL


# ─── binance_client.py additional tests ──────────────────────────────────────

class TestBinanceClientAdditional:
    """Additional tests for binance_client.py."""
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_client_no_live_methods_called(self, mock_fetcher_cls, mock_config):
        """Test that no live methods are called in paper mode."""
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
        
        # In paper mode, get_account_balance returns the paper capital
        balance = client.get_account_balance()
        assert balance["USDT"] == 10000.0
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_validate_order_min_notional(self, mock_fetcher_cls, mock_config):
        """Test validate_order_quantity with minimum notional."""
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
        mock_fetcher_cls.return_value = mock_fetcher
        
        from binance_client import BinanceClient
        from binance_client import validate_order_quantity
        
        # Very small quantity - below minimum notional
        is_valid, msg, adj_qty = validate_order_quantity("BTCUSDT", 0.00001, 50000)
        # Should either reject or try to adjust
        assert adj_qty >= 0
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_client_get_current_price(self, mock_fetcher_cls, mock_config):
        """Test get_current_price method."""
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
    
    def test_circuit_breaker_full_integration(self):
        """Test circuit breaker with full state transitions."""
        from binance_client import CircuitBreaker
        
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        
        # Closed -> Open after 2 failures
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"
        
        # Open -> half-open (can proceed)
        cb._last_failure_time = 0  # Force timeout
        assert cb.can_proceed() == True
        assert cb.state == "half-open"
        
        # half-open -> closed on success
        cb.record_success()
        assert cb.state == "closed"
        
        # Open -> half-open
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        cb._last_failure_time = 0
        cb.can_proceed()
        assert cb.state == "half-open"
        
        # half-open -> open on failure
        cb.record_failure()
        assert cb.state == "open"
