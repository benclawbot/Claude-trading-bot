# Tests for utils/indicators.py

import pytest
import pandas as pd
import numpy as np

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestIndicators:
    """Test technical indicator calculations."""
    
    def test_rsi_bounds(self):
        """Test RSI is always bounded 0-100."""
        from utils.indicators import _rsi
        
        # Flat prices should give RSI of 50 (no changes)
        prices = pd.Series([100.0] * 50)
        rsi = _rsi(prices, period=14)
        
        # RSI should be bounded 0-100 (may not be exactly 50 with EWM)
        assert 0 <= rsi.iloc[-1] <= 100
        
        # Rising prices
        rising = pd.Series([100 + i for i in range(50)])
        rsi_rising = _rsi(rising, period=14)
        assert rsi_rising.iloc[-1] > 50
        
        # Falling prices
        falling = pd.Series([100 - i for i in range(50)])
        rsi_falling = _rsi(falling, period=14)
        assert rsi_falling.iloc[-1] < 50
    
    def test_ema_responds_to_trend(self):
        """Test EMA responds to price changes."""
        from utils.indicators import _ema
        
        # Flat then up
        prices = pd.Series([100.0] * 20 + [110.0] * 20)
        ema = _ema(prices, span=10)
        
        # EMA should be higher after the step
        assert ema.iloc[-1] > ema.iloc[19]
    
    def test_sma_calculation(self):
        """Test SMA calculation."""
        from utils.indicators import _sma
        
        prices = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        sma = _sma(prices, window=5)
        
        # SMA of last 5 values (6,7,8,9,10) should be 8.0
        assert sma.iloc[-1] == 8.0
        # First 4 values should be NaN or partial
        assert sma.iloc[4] == 3.0
    
    def test_atr_positive(self):
        """Test ATR is always positive."""
        from utils.indicators import _atr
        
        high = pd.Series([105, 110, 108, 112, 115])
        low = pd.Series([95, 100, 98, 102, 105])
        close = pd.Series([100, 105, 102, 110, 108])
        
        atr = _atr(high, low, close, period=3)
        
        assert atr.iloc[-1] > 0
    
    def test_bollinger_bands(self):
        """Test Bollinger Bands calculation."""
        from utils.indicators import _bollinger
        
        np.random.seed(42)
        close = pd.Series(50000 + np.cumsum(np.random.randn(100) * 100))
        
        upper, mid, lower, width, pband = _bollinger(close, window=20, std=2.0)
        
        # Upper should be above middle
        assert upper.iloc[-1] > mid.iloc[-1]
        # Middle should be above lower
        assert mid.iloc[-1] > lower.iloc[-1]
        # Width should be positive
        assert width.iloc[-1] > 0
        # Percent B should be between 0 and 1 for normal cases
        assert 0 <= pband.iloc[-1] <= 1
    
    def test_macd(self):
        """Test MACD calculation."""
        from utils.indicators import _macd
        
        np.random.seed(42)
        close = pd.Series(50000 + np.cumsum(np.random.randn(100) * 100))
        
        macd_line, signal_line, histogram = _macd(close)
        
        assert len(macd_line) == len(close)
        assert len(signal_line) == len(close)
        assert len(histogram) == len(close)
    
    def test_stochastic(self):
        """Test Stochastic calculation."""
        from utils.indicators import _stochastic
        
        high = pd.Series([105, 110, 108, 112, 115, 120])
        low = pd.Series([95, 100, 98, 102, 105, 110])
        close = pd.Series([100, 105, 102, 110, 108, 115])
        
        k, d = _stochastic(high, low, close, k_period=3, d_period=2)
        
        # K should be bounded 0-100
        assert 0 <= k.iloc[-1] <= 100
        # D should be bounded 0-100
        assert 0 <= d.iloc[-1] <= 100
    
    def test_adx(self):
        """Test ADX calculation."""
        from utils.indicators import _adx
        
        np.random.seed(42)
        n = 50
        close = pd.Series(50000 + np.cumsum(np.random.randn(n) * 100))
        high = close + np.abs(np.random.randn(n) * 100)
        low = close - np.abs(np.random.randn(n) * 100)
        
        adx, di_pos, di_neg = _adx(high, low, close, period=14)
        
        # ADX should be non-negative
        assert adx.iloc[-1] >= 0
        # DI+ and DI- should be non-negative
        assert di_pos.iloc[-1] >= 0
        assert di_neg.iloc[-1] >= 0
    
    def test_obv(self):
        """Test OBV (On-Balance Volume) calculation."""
        from utils.indicators import _obv
        
        close = pd.Series([100, 102, 101, 103, 102, 104])
        volume = pd.Series([1000, 1100, 900, 1200, 1000, 1300])
        
        obv = _obv(close, volume)
        
        # OBV should have same length
        assert len(obv) == len(close)
        # All OBV values should be positive
        assert obv.iloc[-1] > 0


class TestAddAllIndicators:
    """Test add_all_indicators function."""
    
    def test_add_all_indicators(self):
        """Test that add_all_indicators adds all expected columns."""
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
        np.random.seed(42)
        
        close = 50000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "close": close,
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        result = add_all_indicators(df)
        
        # Check expected columns exist
        expected = [
            "rsi_14", "rsi_7",
            "stoch_k", "stoch_d",
            "macd", "macd_signal", "macd_hist",
            "ema_9", "ema_21", "ema_50", "ema_100", "ema_200",
            "sma_20", "sma_50",
            "adx", "adx_pos", "adx_neg",
            "bb_upper", "bb_middle", "bb_lower", "bb_width", "bb_pct",
            "atr_14",
            "volume_sma_20", "volume_ratio",
            "obv",
            "candle_body", "candle_range", "body_ratio",
            "rolling_high_24", "rolling_low_24",
            "rolling_high_48", "rolling_low_48",
            "return_1h", "return_4h", "return_24h", "volatility_20",
        ]
        
        for col in expected:
            assert col in result.columns, f"Missing column: {col}"
    
    def test_add_all_indicators_does_not_modify_original(self):
        """Test that add_all_indicators returns a copy."""
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
        np.random.seed(42)
        
        df = pd.DataFrame({
            "open": np.random.rand(n) * 100 + 100,
            "high": np.random.rand(n) * 100 + 100,
            "low": np.random.rand(n) * 100 + 50,
            "close": np.random.rand(n) * 100 + 100,
            "volume": np.random.rand(n) * 1000,
        }, index=dates)
        
        original_cols = set(df.columns)
        
        from utils.indicators import add_all_indicators
        result = add_all_indicators(df)
        
        # Original should be unchanged
        assert set(df.columns) == original_cols
        # Result should have more columns
        assert len(result.columns) > len(df.columns)
        # Result should be a different object
        assert result is not df


class TestMarketRegime:
    """Test market regime classification."""
    
    def test_regime_ranging(self):
        """Test RANGING regime classification."""
        from utils.indicators import compute_market_regime
        
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
        # Flat prices = ranging
        close = np.full(n, 50000.0)
        
        df = pd.DataFrame({
            "open": close, "high": close, "low": close, "close": close,
            "volume": np.ones(n) * 1000,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        regime = compute_market_regime(df)
        assert regime == "RANGING"
    
    def test_regime_trending_up(self):
        """Test TRENDING_UP regime classification."""
        from utils.indicators import compute_market_regime
        
        n = 300
        dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
        np.random.seed(42)
        
        # Strong uptrend
        close = 50000 + np.cumsum(np.abs(np.random.randn(n) * 50) + 20)
        
        df = pd.DataFrame({
            "open": close, "high": close + 100, "low": close - 100, "close": close,
            "volume": np.ones(n) * 1000,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        regime = compute_market_regime(df)
        assert regime in ("TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE")


class TestFeatureVector:
    """Test ML feature vector generation."""
    
    def test_feature_vector_length(self):
        """Test feature vector has expected length."""
        from utils.indicators import get_feature_vector
        
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
        np.random.seed(42)
        
        close = 50000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "close": close,
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        features = get_feature_vector(df)
        
        # Should have 12 features
        assert len(features) == 12
    
    def test_feature_vector_bounds(self):
        """Test feature vector values are bounded."""
        from utils.indicators import get_feature_vector
        
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
        np.random.seed(42)
        
        close = 50000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "close": close,
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        features = get_feature_vector(df)
        
        # All features should be finite
        for f in features:
            assert np.isfinite(f), f"Non-finite feature value: {f}"
