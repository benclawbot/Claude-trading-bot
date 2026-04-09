# Shared pytest fixtures for trading bot tests

import sys
import os
import pytest
import pandas as pd
import numpy as np

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def reset_database_connections():
    """Reset database module-level connections between tests to ensure isolation."""
    import database as db_module
    yield
    # Close any existing connections after each test
    if hasattr(db_module, '_local') and hasattr(db_module._local, 'conn'):
        try:
            db_module._local.conn.close()
        except Exception:
            pass
        db_module._local.conn = None


@pytest.fixture
def sample_ohlcv_df():
    """Generate a sample OHLCV DataFrame with all required columns and indicators."""
    n = 300
    dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    np.random.seed(42)
    
    # Generate price data with some trends
    close = 50000 + np.cumsum(np.random.randn(n) * 100)
    high = close + np.random.rand(n) * 200
    low = close - np.random.rand(n) * 200
    open_price = close + np.random.randn(n) * 50
    volume = np.random.rand(n) * 1000 + 500
    
    df = pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)
    
    # Add all indicators
    from utils.indicators import add_all_indicators
    return add_all_indicators(df)


@pytest.fixture
def sample_ohlcv_1d():
    """Daily OHLCV DataFrame for daily-interval strategies."""
    n = 300
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    np.random.seed(42)
    
    close = 30000 + np.cumsum(np.random.randn(n) * 500)
    high = close + np.random.rand(n) * 1000
    low = close - np.random.rand(n) * 1000
    open_price = close + np.random.randn(n) * 200
    volume = np.random.rand(n) * 5000 + 2000
    
    df = pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)
    
    from utils.indicators import add_all_indicators
    return add_all_indicators(df)


@pytest.fixture
def mock_config(monkeypatch):
    """Mock the config module with test values."""
    class MockConfig:
        INITIAL_CAPITAL = 10000
        MAX_STRATEGIES = 7
        SYMBOL = "BTCUSDT"
        TRADING_FEE = 0.001
        SLIPPAGE = 0.0003
        DEFAULT_STOP_LOSS_PCT = 0.025
        DEFAULT_TAKE_PROFIT_PCT = 0.055
        MAX_POSITION_PCT = 0.35
        MIN_POSITION_PCT = 0.05
        MAX_OPEN_POSITIONS_PER_STRATEGY = 2
        MAX_PORTFOLIO_DRAWDOWN_PCT = 0.20
        BACKTEST_DAYS = 500
        MIN_CAGR_THRESHOLD = 0.30
        MIN_WIN_RATE = 0.38
        MIN_PROFIT_FACTOR = 1.20
        MIN_TRADES_FOR_LEARNING = 10
        MODEL_UPDATE_FREQUENCY = 5
        CONFIDENCE_THRESHOLD = 0.40
        KELLY_FRACTION = 0.25
        PAPER_TRADING = True
        DB_PATH = ":memory:"
        
        STRATEGY_PARAMS = {
            "EMA5_Momentum": {
                "ema_period": 3,
                "atr_sl_mult": 0.75,
                "atr_tp_mult": 1.5,
                "candle_interval": "1d",
            },
            "Breakout": {
                "lookback": 20,
                "volume_multiplier": 1.8,
                "atr_period": 14,
                "atr_sl_mult": 1.5,
                "atr_tp_mult": 2.5,
                "candle_interval": "4h",
            },
            "DualMA_Crossover": {
                "fast_period": 20,
                "slow_period": 60,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 4.5,
                "candle_interval": "4h",
            },
            "RSI_Bollinger": {
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "bb_period": 20,
                "bb_std": 2.0,
                "atr_sl_mult": 1.5,
                "atr_tp_mult": 3.0,
                "candle_interval": "4h",
            },
            "MACD_Momentum": {
                "macd_fast": 12,
                "macd_slow": 26,
                "signal_period": 9,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 4.0,
                "candle_interval": "4h",
            },
            "ML_Adaptive": {
                "min_confidence": 0.55,
                "retrain_interval": 20,
                "n_estimators": 100,
                "candle_interval": "1h",
            },
        }
    
    return MockConfig()
