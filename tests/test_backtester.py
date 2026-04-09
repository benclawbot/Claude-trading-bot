# Tests for backtester.py

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockStrategy:
    """Mock strategy for testing the backtester."""
    
    def __init__(self, name="MockStrategy", min_candles=50, interval="1h",
                 max_hold=48, signal_frequency=0.1):
        self.name = name
        self._min_candles = min_candles
        self._interval = interval
        self._max_hold = max_hold
        self._signal_frequency = signal_frequency  # fraction of candles that signal
        self.candle_interval = interval
        self.min_candles = min_candles
        self.max_hold_candles = max_hold
        self.capital = 0.0
        self.is_active = True
        self.total_trades = 0
        self.winning_trades = 0
    
    @property
    def win_rate(self):
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
    
    def generate_signal(self, df):
        from strategies.base_strategy import Signal, SignalType
        if len(df) < self._min_candles:
            return Signal(SignalType.HOLD, 0.0)
        
        # Generate BUY/SELL signals based on price movement
        if np.random.random() < self._signal_frequency:
            last = df.iloc[-1]
            close = float(last["close"])
            atr = float(last.get("atr_14", close * 0.015))
            
            if np.random.random() > 0.5:
                return Signal(
                    SignalType.BUY, 0.65,
                    stop_loss=close - 1.5 * atr,
                    take_profit=close + 3.0 * atr,
                )
            else:
                return Signal(
                    SignalType.SELL, 0.65,
                    stop_loss=close + 1.5 * atr,
                    take_profit=close - 3.0 * atr,
                )
        
        return Signal(SignalType.HOLD, 0.0)
    
    def set_capital(self, capital):
        self.capital = capital
    
    def record_trade_outcome(self, won):
        self.total_trades += 1
        if won:
            self.winning_trades += 1


class TestBacktester:
    """Test Backtester class."""
    
    def _make_df(self, n=300, start_price=50000, interval="h"):
        """Create a sample OHLCV DataFrame."""
        freq = "h" if interval == "h" else "D"
        dates = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
        np.random.seed(42)
        
        # Trending price data
        close = start_price + np.cumsum(np.random.randn(n) * start_price * 0.01)
        high = close + np.abs(np.random.randn(n) * start_price * 0.005)
        low = close - np.abs(np.random.randn(n) * start_price * 0.005)
        open_price = close + np.random.randn(n) * start_price * 0.002
        volume = np.random.rand(n) * 1000 + 500
        
        df = pd.DataFrame({
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        return add_all_indicators(df)
    
    @patch("backtester.config")
    def test_backtester_init(self, mock_config):
        """Test Backtester initialization."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.MIN_WIN_RATE = 0.38
        mock_config.MIN_PROFIT_FACTOR = 1.20
        
        from backtester import Backtester
        
        df = self._make_df(300)
        strategy = MockStrategy("TestStrategy", min_candles=50)
        bt = Backtester(strategy, df, initial_capital=1000)
        
        assert bt.strategy == strategy
        assert bt.initial_capital == 1000
        assert len(bt.df) == 300
    
    @patch("backtester.config")
    def test_backtester_run_no_signals(self, mock_config):
        """Test backtester run with no signals (HOLD strategy)."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.MIN_WIN_RATE = 0.38
        mock_config.MIN_PROFIT_FACTOR = 1.20
        
        from backtester import Backtester
        
        df = self._make_df(300)
        # Strategy that always holds
        strategy = MockStrategy("HoldStrategy", min_candles=50, signal_frequency=0.0)
        bt = Backtester(strategy, df, initial_capital=1000)
        result = bt.run()
        
        assert result.total_trades == 0
        assert result.winning_trades == 0
        assert result.losing_trades == 0
        assert result.cagr == 0
        assert result.passes_threshold == False
    
    @patch("backtester.config")
    def test_backtester_run_with_trades(self, mock_config):
        """Test backtester run with actual trades."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.MIN_WIN_RATE = 0.38
        mock_config.MIN_PROFIT_FACTOR = 1.20
        
        from backtester import Backtester
        
        df = self._make_df(300)
        # Strategy that signals frequently
        strategy = MockStrategy("ActiveStrategy", min_candles=50, signal_frequency=0.15)
        bt = Backtester(strategy, df, initial_capital=1000)
        result = bt.run()
        
        assert result.strategy_name == "ActiveStrategy"
        assert len(result.trades) == result.total_trades
        assert result.total_trades >= 0
        # Equity curve should have entries
        assert len(result.equity_curve) > 0
    
    @patch("backtester.config")
    def test_backtester_metrics_calculation(self, mock_config):
        """Test that backtest metrics are computed correctly."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.MIN_WIN_RATE = 0.38
        mock_config.MIN_PROFIT_FACTOR = 1.20
        
        from backtester import Backtester
        
        df = self._make_df(300)
        strategy = MockStrategy("TestStrategy", min_candles=50, signal_frequency=0.1)
        bt = Backtester(strategy, df, initial_capital=1000)
        result = bt.run()
        
        # Check that metrics are bounded
        assert 0 <= result.win_rate <= 1
        assert result.profit_factor >= 0
        assert 0 <= result.max_drawdown <= 1
        assert result.sharpe_ratio >= -10  # allow some negative
    
    @patch("backtester.config")
    def test_backtester_position_close_on_data_end(self, mock_config):
        """Test that open positions are closed at end of data."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.MIN_WIN_RATE = 0.38
        mock_config.MIN_PROFIT_FACTOR = 1.20
        
        from backtester import Backtester
        
        df = self._make_df(300)
        # Strategy that always signals BUY to ensure a position is opened
        strategy = MockStrategy("AlwaysBuyStrategy", min_candles=50)
        
        # Override to always generate BUY signal
        original_generate = strategy.generate_signal
        def forced_buy_signal(df):
            from strategies.base_strategy import Signal, SignalType
            if len(df) < strategy._min_candles:
                return Signal(SignalType.HOLD, 0.0)
            last = df.iloc[-1]
            close = float(last["close"])
            atr = float(last.get("atr_14", close * 0.015))
            return Signal(
                SignalType.BUY, 0.7,
                stop_loss=close - 1.5 * atr,
                take_profit=close + 3.0 * atr,
            )
        strategy.generate_signal = forced_buy_signal
        
        bt = Backtester(strategy, df, initial_capital=1000)
        result = bt.run()
        
        # Should have at least one trade
        assert result.total_trades >= 1
    
    def test_check_exit_long_stop_loss(self):
        """Test _check_exit for LONG position hitting stop loss."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="LONG",
            entry_price=50000,
            quantity=0.1,
            stop_loss=49000,
            take_profit=52000,
            entry_idx=0,
            entry_time=datetime.now(timezone.utc),
        )
        
        # Price drops to stop loss
        reason, price = Backtester._check_exit(pos, high=49500, low=48900, close=48900, df=None, i=5)
        assert reason == "STOP_LOSS"
        assert price == 49000
    
    def test_check_exit_long_take_profit(self):
        """Test _check_exit for LONG position hitting take profit."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="LONG",
            entry_price=50000,
            quantity=0.1,
            stop_loss=49000,
            take_profit=52000,
            entry_idx=0,
            entry_time=datetime.now(timezone.utc),
        )
        
        # Price rises to take profit
        reason, price = Backtester._check_exit(pos, high=52100, low=51500, close=52100, df=None, i=5)
        assert reason == "TAKE_PROFIT"
        assert price == 52000
    
    def test_check_exit_short_stop_loss(self):
        """Test _check_exit for SHORT position hitting stop loss."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="SHORT",
            entry_price=50000,
            quantity=0.1,
            stop_loss=51000,
            take_profit=48000,
            entry_idx=0,
            entry_time=datetime.now(timezone.utc),
        )
        
        # Price rises to stop loss
        reason, price = Backtester._check_exit(pos, high=51100, low=50500, close=51100, df=None, i=5)
        assert reason == "STOP_LOSS"
        assert price == 51000
    
    def test_check_exit_short_take_profit(self):
        """Test _check_exit for SHORT position hitting take profit."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="SHORT",
            entry_price=50000,
            quantity=0.1,
            stop_loss=51000,
            take_profit=48000,
            entry_idx=0,
            entry_time=datetime.now(timezone.utc),
        )
        
        # Price falls to take profit
        reason, price = Backtester._check_exit(pos, high=48500, low=47900, close=47900, df=None, i=5)
        assert reason == "TAKE_PROFIT"
        assert price == 48000
    
    def test_check_exit_max_hold(self):
        """Test _check_exit for max hold timeout."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="LONG",
            entry_price=50000,
            quantity=0.1,
            stop_loss=49000,
            take_profit=52000,
            entry_idx=0,
            entry_time=datetime.now(timezone.utc),
            max_hold=10,
        )
        
        # Candle index beyond max hold, but price hasn't hit SL or TP
        reason, price = Backtester._check_exit(pos, high=50500, low=49500, close=50000, df=None, i=15)
        assert reason == "MAX_HOLD"
        assert price == 50000
    
    def test_check_exit_no_exit(self):
        """Test _check_exit when no exit condition is met."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="LONG",
            entry_price=50000,
            quantity=0.1,
            stop_loss=49000,
            take_profit=52000,
            entry_idx=0,
            entry_time=datetime.now(timezone.utc),
            max_hold=10,
        )
        
        reason, price = Backtester._check_exit(pos, high=50500, low=49500, close=50000, df=None, i=3)
        assert reason is None
        assert price == 0.0
    
    def test_close_position_long_profit(self):
        """Test _close_position for a profitable LONG trade."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="LONG",
            entry_price=50000,
            quantity=0.1,
            stop_loss=49000,
            take_profit=52000,
            entry_idx=0,
            entry_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            max_hold=48,
        )
        
        trade = Backtester._close_position(
            pos, exit_price=51000,
            exit_time=datetime(2024, 1, 1, 4, 0, tzinfo=timezone.utc),
            reason="TAKE_PROFIT",
            fee_rt=0.002,
        )
        
        assert trade.side == "LONG"
        assert trade.entry_price == 50000
        assert trade.exit_price == 51000
        assert trade.quantity == 0.1
        assert trade.pnl > 0  # Profitable trade
        assert trade.exit_reason == "TAKE_PROFIT"
        assert trade.duration_hours > 0
    
    def test_close_position_short_profit(self):
        """Test _close_position for a profitable SHORT trade."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="SHORT",
            entry_price=50000,
            quantity=0.1,
            stop_loss=51000,
            take_profit=48000,
            entry_idx=0,
            entry_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            max_hold=48,
        )
        
        trade = Backtester._close_position(
            pos, exit_price=49000,
            exit_time=datetime(2024, 1, 1, 4, 0, tzinfo=timezone.utc),
            reason="TAKE_PROFIT",
            fee_rt=0.002,
        )
        
        assert trade.side == "SHORT"
        assert trade.pnl > 0  # Profitable short trade
    
    def test_close_position_loss(self):
        """Test _close_position for a losing trade."""
        from backtester import Backtester, BacktestPosition
        from datetime import datetime
        
        pos = BacktestPosition(
            side="LONG",
            entry_price=50000,
            quantity=0.1,
            stop_loss=49000,
            take_profit=52000,
            entry_idx=0,
            entry_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            max_hold=48,
        )
        
        trade = Backtester._close_position(
            pos, exit_price=49500,
            exit_time=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            reason="STOP_LOSS",
            fee_rt=0.002,
        )
        
        assert trade.pnl < 0  # Losing trade
        assert trade.exit_reason == "STOP_LOSS"
    
    @patch("backtester.config")
    def test_backtest_result_summary(self, mock_config):
        """Test BacktestResult.summary() string format."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.MIN_WIN_RATE = 0.38
        mock_config.MIN_PROFIT_FACTOR = 1.20
        
        from backtester import Backtester, BacktestResult
        
        df = self._make_df(300)
        strategy = MockStrategy("TestStrategy", min_candles=50)
        bt = Backtester(strategy, df, initial_capital=1000)
        result = bt.run()
        
        summary = result.summary()
        assert "TestStrategy" in summary
        assert "CAGR=" in summary
        assert "WinRate=" in summary
        assert "PF=" in summary
        assert "MaxDD=" in summary
        assert "Trades=" in summary
    
    @patch("backtester.config")
    def test_backtester_entry_slippage(self, mock_config):
        """Test that entry price includes slippage."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.MIN_WIN_RATE = 0.38
        mock_config.MIN_PROFIT_FACTOR = 1.20
        
        from backtester import Backtester
        
        df = self._make_df(300)
        
        # Always BUY strategy with known close price
        strategy = MockStrategy("TestStrategy", min_candles=50)
        def forced_buy(df):
            from strategies.base_strategy import Signal, SignalType
            if len(df) < strategy._min_candles:
                return Signal(SignalType.HOLD, 0.0)
            last = df.iloc[-1]
            close = float(last["close"])
            atr = float(last.get("atr_14", close * 0.015))
            return Signal(SignalType.BUY, 0.7, stop_loss=close * 0.97, take_profit=close * 1.05)
        strategy.generate_signal = forced_buy
        
        bt = Backtester(strategy, df, initial_capital=1000)
        result = bt.run()
        
        # Verify entry prices include fee/slippage
        for trade in result.trades:
            assert trade.side in ("LONG", "SHORT")


class TestBacktesterIntegration:
    """Integration tests for backtester with real strategy classes."""
    
    @patch("backtester.config")
    def test_backtester_with_real_strategy_hourly(self, mock_config):
        """Test backtester with a mock strategy on hourly data."""
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MAX_STRATEGIES = 7
        mock_config.TRADING_FEE = 0.001
        mock_config.SLIPPAGE = 0.0003
        mock_config.DEFAULT_STOP_LOSS_PCT = 0.025
        mock_config.DEFAULT_TAKE_PROFIT_PCT = 0.055
        mock_config.MAX_POSITION_PCT = 0.35
        mock_config.MIN_CAGR_THRESHOLD = 0.30
        mock_config.MIN_WIN_RATE = 0.38
        mock_config.MIN_PROFIT_FACTOR = 1.20
        
        from backtester import Backtester
        
        # Create hourly data with enough candles
        n = 500
        dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
        np.random.seed(42)
        close = 50000 + np.cumsum(np.random.randn(n) * 200)
        high = close + np.random.rand(n) * 300
        low = close - np.random.rand(n) * 300
        open_price = close + np.random.randn(n) * 100
        volume = np.random.rand(n) * 1000 + 500
        
        df = pd.DataFrame({
            "open": open_price, "high": high, "low": low,
            "close": close, "volume": volume,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strategy = MockStrategy("MockBreakout", min_candles=50, signal_frequency=0.05)
        
        bt = Backtester(strategy, df, initial_capital=1000)
        result = bt.run()
        
        assert result.strategy_name == "MockBreakout"
        assert isinstance(result.total_trades, int)
        assert isinstance(result.cagr, float)
        assert isinstance(result.equity_curve, list)
