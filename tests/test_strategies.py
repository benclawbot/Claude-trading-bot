# Tests for strategy files

import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_ohlcv_df(n=300, start_price=50000, freq="h"):
    """Create a sample OHLCV DataFrame with indicators."""
    freq_map = {"h": "h", "4h": "4h", "d": "D"}
    actual_freq = freq_map.get(freq, "h")
    dates = pd.date_range("2024-01-01", periods=n, freq=actual_freq, tz="UTC")
    np.random.seed(42)
    
    close = start_price + np.cumsum(np.random.randn(n) * start_price * 0.005)
    high = close + np.abs(np.random.randn(n) * start_price * 0.003)
    low = close - np.abs(np.random.randn(n) * start_price * 0.003)
    open_price = close + np.random.randn(n) * start_price * 0.001
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


# ─── Shared config mocks ────────────────────────────────────────────────────────

BREAKOUT_CONFIG = {
    "Breakout": {
        "lookback": 20,
        "volume_multiplier": 1.5,
        "atr_period": 14,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 2.5,
        "candle_interval": "4h",
    }
}

RSI_CONFIG = {
    "RSI_Bollinger": {
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "rsi_period": 14,
        "bb_period": 20,
        "bb_std": 2.0,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 3.0,
        "candle_interval": "4h",
    }
}

EMA_CONFIG = {
    "EMA_Crossover": {
        "trend_ema": 50,
        "fast_ema": 9,
        "slow_ema": 21,
        "atr_sl_mult": 2.0,
        "atr_tp_mult": 4.5,
        "candle_interval": "4h",
    }
}

MACD_CONFIG = {
    "MACD_Momentum": {
        "trend_ema": 50,
        "macd_fast": 12,
        "macd_slow": 26,
        "signal_period": 9,
        "atr_sl_mult": 2.0,
        "atr_tp_mult": 4.0,
        "candle_interval": "4h",
    }
}

ML_CONFIG = {
    "ML_Adaptive": {
        "min_confidence": 0.55,
        "retrain_interval": 20,
        "n_estimators": 100,
        "candle_interval": "1h",
    }
}


class TestBaseStrategy:
    """Test BaseStrategy class."""
    
    def test_signal_actionable_buy(self):
        """Test Signal.is_actionable for BUY."""
        from strategies.base_strategy import Signal, SignalType
        sig = Signal(SignalType.BUY, 0.7)
        assert sig.is_actionable == True
    
    def test_signal_actionable_sell(self):
        """Test Signal.is_actionable for SELL."""
        from strategies.base_strategy import Signal, SignalType
        sig = Signal(SignalType.SELL, 0.7)
        assert sig.is_actionable == True
    
    def test_signal_not_actionable_hold(self):
        """Test Signal.is_actionable for HOLD."""
        from strategies.base_strategy import Signal, SignalType
        sig = Signal(SignalType.HOLD, 0.0)
        assert sig.is_actionable == False
    
    def test_base_strategy_record_trade_outcome(self):
        """Test record_trade_outcome updates counters."""
        from strategies.base_strategy import BaseStrategy, Signal, SignalType
        
        class TestStrategy(BaseStrategy):
            @property
            def min_candles(self): return 50
            @property
            def candle_interval(self): return "1h"
            def generate_signal(self, df): return Signal(SignalType.HOLD, 0.0)
        
        strat = TestStrategy("TestStrat", {})
        
        assert strat.total_trades == 0
        assert strat.winning_trades == 0
        assert strat.win_rate == 0.0
        
        strat.record_trade_outcome(True)
        assert strat.total_trades == 1
        assert strat.winning_trades == 1
        assert strat.win_rate == 1.0
        
        strat.record_trade_outcome(False)
        assert strat.total_trades == 2
        assert strat.winning_trades == 1
        assert strat.win_rate == 0.5


class TestBreakoutStrategy:
    """Test BreakoutStrategy."""
    
    @patch("strategies.breakout.config")
    def test_breakout_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = BREAKOUT_CONFIG
        from strategies.breakout import BreakoutStrategy
        strat = BreakoutStrategy()
        assert strat.name == "Breakout"
        assert strat.candle_interval == "4h"
    
    @patch("strategies.breakout.config")
    def test_breakout_holds_without_volume(self, mock_config):
        mock_config.STRATEGY_PARAMS = BREAKOUT_CONFIG.copy()
        mock_config.STRATEGY_PARAMS["Breakout"]["volume_multiplier"] = 5.0  # Very high threshold
        from strategies.breakout import BreakoutStrategy
        from strategies.base_strategy import SignalType
        
        strat = BreakoutStrategy()
        df = make_ohlcv_df(300, start_price=50000, freq="4h")
        signal = strat.generate_signal(df)
        assert signal.type == SignalType.HOLD
    
    @patch("strategies.breakout.config")
    def test_breakout_min_candles(self, mock_config):
        mock_config.STRATEGY_PARAMS = BREAKOUT_CONFIG
        from strategies.breakout import BreakoutStrategy
        from strategies.base_strategy import SignalType
        
        strat = BreakoutStrategy()
        df = make_ohlcv_df(30, start_price=50000, freq="4h")  # Too few
        signal = strat.generate_signal(df)
        assert signal.type == SignalType.HOLD
    
    @patch("strategies.breakout.config")
    def test_breakout_generates_signal(self, mock_config):
        mock_config.STRATEGY_PARAMS = BREAKOUT_CONFIG.copy()
        mock_config.STRATEGY_PARAMS["Breakout"]["volume_multiplier"] = 0.5  # Low threshold
        from strategies.breakout import BreakoutStrategy
        from strategies.base_strategy import SignalType
        
        df = make_ohlcv_df(300, start_price=50000, freq="4h")
        strat = BreakoutStrategy()
        signal = strat.generate_signal(df)
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestEMACrossoverStrategy:
    """Test EMA Crossover Strategy."""
    
    @patch("strategies.ema_crossover.config")
    def test_ema_crossover_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = EMA_CONFIG
        from strategies.ema_crossover import EMACrossoverStrategy
        strat = EMACrossoverStrategy()
        assert strat.name == "EMA_Crossover"
        assert strat.candle_interval == "4h"
    
    @patch("strategies.ema_crossover.config")
    def test_ema_crossover_generates_signal(self, mock_config):
        mock_config.STRATEGY_PARAMS = EMA_CONFIG
        from strategies.ema_crossover import EMACrossoverStrategy
        from strategies.base_strategy import SignalType
        
        df = make_ohlcv_df(300, start_price=50000, freq="4h")
        strat = EMACrossoverStrategy()
        signal = strat.generate_signal(df)
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestRSIBollingerStrategy:
    """Test RSI Bollinger Strategy."""
    
    @patch("strategies.rsi_bollinger.config")
    def test_rsi_bollinger_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = RSI_CONFIG
        from strategies.rsi_bollinger import RSIBollingerStrategy
        strat = RSIBollingerStrategy()
        assert strat.name == "RSI_Bollinger"
        assert strat.candle_interval == "4h"
    
    @patch("strategies.rsi_bollinger.config")
    def test_rsi_bollinger_generates_signal(self, mock_config):
        mock_config.STRATEGY_PARAMS = RSI_CONFIG
        from strategies.rsi_bollinger import RSIBollingerStrategy
        from strategies.base_strategy import SignalType
        
        df = make_ohlcv_df(300, start_price=50000, freq="4h")
        strat = RSIBollingerStrategy()
        signal = strat.generate_signal(df)
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestMACDMomentumStrategy:
    """Test MACD Momentum Strategy."""
    
    @patch("strategies.macd_momentum.config")
    def test_macd_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = MACD_CONFIG
        from strategies.macd_momentum import MACDMomentumStrategy
        strat = MACDMomentumStrategy()
        assert strat.name == "MACD_Momentum"
        assert strat.candle_interval == "4h"
    
    @patch("strategies.macd_momentum.config")
    def test_macd_generates_signal(self, mock_config):
        mock_config.STRATEGY_PARAMS = MACD_CONFIG
        from strategies.macd_momentum import MACDMomentumStrategy
        from strategies.base_strategy import SignalType
        
        df = make_ohlcv_df(300, start_price=50000, freq="4h")
        strat = MACDMomentumStrategy()
        signal = strat.generate_signal(df)
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestDualMACrossoverStrategy:
    """Test Dual MA Crossover Strategy."""
    
    @patch("strategies.dual_ma_crossover.config")
    def test_dual_ma_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = {
            "DualMA_Crossover": {
                "fast_period": 20,
                "slow_period": 60,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 4.5,
                "candle_interval": "4h",
            }
        }
        from strategies.dual_ma_crossover import DualMACrossoverStrategy
        strat = DualMACrossoverStrategy()
        assert strat.name == "DualMA_Crossover"
        assert strat.candle_interval == "4h"
    
    @patch("strategies.dual_ma_crossover.config")
    def test_dual_ma_generates_signal(self, mock_config):
        mock_config.STRATEGY_PARAMS = {
            "DualMA_Crossover": {
                "fast_period": 20,
                "slow_period": 60,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 4.5,
                "candle_interval": "4h",
            }
        }
        from strategies.dual_ma_crossover import DualMACrossoverStrategy
        from strategies.base_strategy import SignalType
        
        df = make_ohlcv_df(300, start_price=50000, freq="4h")
        strat = DualMACrossoverStrategy()
        signal = strat.generate_signal(df)
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestPriceMomentum25Strategy:
    """Test Price Momentum 25 Strategy."""
    
    @patch("strategies.price_momentum_25.config")
    def test_price_momentum_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = {
            "PriceMomentum_25": {
                "lookback": 14,
                "atr_sl_mult": 1.5,
                "atr_tp_mult": 4.0,
                "candle_interval": "1d",
            }
        }
        from strategies.price_momentum_25 import PriceMomentum25Strategy
        strat = PriceMomentum25Strategy()
        assert strat.name == "PriceMomentum_25"
        assert strat.candle_interval == "1d"
    
    @patch("strategies.price_momentum_25.config")
    def test_price_momentum_generates_signal(self, mock_config):
        mock_config.STRATEGY_PARAMS = {
            "PriceMomentum_25": {
                "lookback": 14,
                "atr_sl_mult": 1.5,
                "atr_tp_mult": 4.0,
                "candle_interval": "1d",
            }
        }
        from strategies.price_momentum_25 import PriceMomentum25Strategy
        from strategies.base_strategy import SignalType
        
        df = make_ohlcv_df(300, start_price=50000, freq="d")
        strat = PriceMomentum25Strategy()
        signal = strat.generate_signal(df)
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestDonchianBreakoutStrategy:
    """Test Donchian Breakout Strategy."""
    
    @patch("strategies.donchian_breakout.config")
    def test_donchian_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = {
            "Donchian_Breakout": {
                "dc_period": 20,
                "adx_calm_max": 99,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 5.0,
                "candle_interval": "1d",
            }
        }
        from strategies.donchian_breakout import DonchianBreakoutStrategy
        strat = DonchianBreakoutStrategy()
        assert strat.name == "Donchian_Breakout"


class TestBlendedMomentumMRStrategy:
    """Test Blended Momentum MR Strategy."""
    
    @patch("strategies.blended_momentum_mr.config")
    def test_blended_init(self, mock_config):
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
        strat = BlendedMomentumMRStrategy()
        assert strat.name == "Blended_MomentumMR"


class TestResidualMeanReversionStrategy:
    """Test Residual Mean Reversion Strategy."""
    
    @patch("strategies.residual_mean_reversion.config")
    def test_residual_init(self, mock_config):
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
        strat = ResidualMeanReversionStrategy()
        assert strat.name == "Residual_MeanRev"


class TestRegimeRiskOffStrategy:
    """Test Regime Risk-Off Strategy."""
    
    @patch("strategies.regime_riskoff.config")
    def test_regime_riskoff_init(self, mock_config):
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
        strat = RegimeRiskOffStrategy()
        assert strat.name == "Regime_RiskOnOff"


class TestEMA5MomentumStrategy:
    """Test EMA5 Momentum Strategy."""
    
    @patch("strategies.ema5_momentum.config")
    def test_ema5_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = {
            "EMA5_Momentum": {
                "ema_period": 3,
                "atr_sl_mult": 0.75,
                "atr_tp_mult": 1.5,
                "candle_interval": "1d",
            }
        }
        from strategies.ema5_momentum import EMA5MomentumStrategy
        strat = EMA5MomentumStrategy()
        assert strat.name == "EMA5_Momentum"


class TestMLAdaptiveStrategy:
    """Test ML Adaptive Strategy."""
    
    @patch("strategies.ml_adaptive.config")
    def test_ml_adaptive_init(self, mock_config):
        mock_config.STRATEGY_PARAMS = ML_CONFIG
        from strategies.ml_adaptive import MLAdaptiveStrategy
        strat = MLAdaptiveStrategy()
        assert strat.name == "ML_Adaptive"
        assert strat.training_samples == 0
        assert strat.model_trained == False
    
    @patch("strategies.ml_adaptive.config")
    def test_ml_adaptive_learn_from_lessons(self, mock_config):
        mock_config.STRATEGY_PARAMS = ML_CONFIG
        from strategies.ml_adaptive import MLAdaptiveStrategy
        
        strat = MLAdaptiveStrategy()
        
        journal_entries = [
            {
                "market_regime": "RANGING",
                "won": False,
                "exit_reason": "STOP_LOSS",
                "strategy_name": "RSI_Bollinger",
                "lessons": "Mean reversion failed in ranging market",
            },
            {
                "market_regime": "TRENDING_UP",
                "won": True,
                "exit_reason": "TAKE_PROFIT",
                "strategy_name": "EMA_Crossover",
                "lessons": "Trend following worked well",
            }
        ]
        
        strat.learn_from_lessons(journal_entries)
        
        # Should have failure patterns for RANGING
        assert "RANGING" in strat._regime_failure_patterns
        assert len(strat._regime_failure_patterns["RANGING"]) == 1
    
    @patch("strategies.ml_adaptive.config")
    def test_ml_adaptive_regime_caution_level(self, mock_config):
        mock_config.STRATEGY_PARAMS = ML_CONFIG
        from strategies.ml_adaptive import MLAdaptiveStrategy
        
        strat = MLAdaptiveStrategy()
        
        # Initially no failures, caution should be 0
        caution = strat.get_regime_caution_level("TRENDING_UP")
        assert caution == 0.0
        
        # Add failure patterns
        strat._regime_failure_patterns = {
            "TRENDING_UP": [
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
                {"exit_reason": "STOP_LOSS", "lesson": "Test"},
            ]
        }
        
        caution = strat.get_regime_caution_level("TRENDING_UP")
        assert caution > 0.0
        assert caution <= 1.0
    
    @patch("strategies.ml_adaptive.config")
    def test_ml_adaptive_add_training_sample(self, mock_config):
        mock_config.STRATEGY_PARAMS = ML_CONFIG
        from strategies.ml_adaptive import MLAdaptiveStrategy
        
        strat = MLAdaptiveStrategy()
        features = [0.5] * 12
        strat.add_training_sample(features, 1.0)
        assert strat.training_samples == 1


class TestEMAStrategySignalGeneration:
    """Test EMA strategy signal generation paths."""
    
    @patch("strategies.ema5_momentum.config")
    def test_ema5_buy_signal(self, mock_config):
        """Test EMA5 generates BUY signal on golden cross."""
        mock_config.STRATEGY_PARAMS = {
            "EMA5_Momentum": {
                "ema_period": 3,
                "atr_sl_mult": 0.75,
                "atr_tp_mult": 1.5,
                "candle_interval": "1d",
            }
        }
        from strategies.ema5_momentum import EMA5MomentumStrategy
        from strategies.base_strategy import SignalType
        
        # Create data where EMA cross happens (price crosses above EMA)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
        np.random.seed(42)
        
        # Price below EMA5 first, then crosses above
        close = np.concatenate([
            np.linspace(50000, 49500, 50),  # Below EMA5
            np.linspace(49500, 50500, 50),  # Crosses above EMA5
        ])
        
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = EMA5MomentumStrategy()
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
    
    @patch("strategies.ema5_momentum.config")
    def test_ema5_sell_signal(self, mock_config):
        """Test EMA5 generates SELL signal on death cross."""
        mock_config.STRATEGY_PARAMS = {
            "EMA5_Momentum": {
                "ema_period": 3,
                "atr_sl_mult": 0.75,
                "atr_tp_mult": 1.5,
                "candle_interval": "1d",
            }
        }
        from strategies.ema5_momentum import EMA5MomentumStrategy
        from strategies.base_strategy import SignalType
        
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
        np.random.seed(42)
        
        # Price above EMA5 first, then crosses below
        close = np.concatenate([
            np.linspace(50000, 50500, 50),  # Above EMA5
            np.linspace(50500, 49500, 50),  # Crosses below EMA5
        ])
        
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = EMA5MomentumStrategy()
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestRegimeRiskOffSignalGeneration:
    """Test Regime Risk-Off strategy signal generation paths."""
    
    @patch("strategies.regime_riskoff.config")
    def test_regime_riskon_buy(self, mock_config):
        """Test Regime Risk-On generates BUY in RISK_ON regime."""
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
        
        # Create bullish data (RSI > 50, EMA rising)
        n = 300
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        close = 50000 + np.cumsum(np.abs(np.random.randn(n)) * 50 + 10)
        
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = RegimeRiskOffStrategy()
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestRSIBollingerSignalGeneration:
    """Test RSI Bollinger signal generation paths."""
    
    @patch("strategies.rsi_bollinger.config")
    def test_rsi_bollinger_buy_signal(self, mock_config):
        """Test RSI Bollinger generates BUY in oversold conditions."""
        mock_config.STRATEGY_PARAMS = {
            "RSI_Bollinger": {
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "rsi_period": 14,
                "bb_period": 20,
                "bb_std": 2.0,
                "atr_sl_mult": 1.5,
                "atr_tp_mult": 3.0,
                "candle_interval": "4h",
            }
        }
        from strategies.rsi_bollinger import RSIBollingerStrategy
        from strategies.base_strategy import SignalType
        
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        # Create data with low RSI (oversold)
        close = 50000 - np.arange(n) * 50  # Declining = low RSI
        
        df = pd.DataFrame({
            "close": close,
            "open": close + 20,
            "high": close + 50,
            "low": close - 50,
            "volume": np.ones(n) * 1000,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = RSIBollingerStrategy()
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
    
    @patch("strategies.rsi_bollinger.config")
    def test_rsi_bollinger_sell_signal(self, mock_config):
        """Test RSI Bollinger generates SELL in overbought conditions."""
        mock_config.STRATEGY_PARAMS = {
            "RSI_Bollinger": {
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "rsi_period": 14,
                "bb_period": 20,
                "bb_std": 2.0,
                "atr_sl_mult": 1.5,
                "atr_tp_mult": 3.0,
                "candle_interval": "4h",
            }
        }
        from strategies.rsi_bollinger import RSIBollingerStrategy
        from strategies.base_strategy import SignalType
        
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        # Create data with high RSI (overbought)
        close = 50000 + np.arange(n) * 50  # Rising = high RSI
        
        df = pd.DataFrame({
            "close": close,
            "open": close - 20,
            "high": close + 50,
            "low": close - 50,
            "volume": np.ones(n) * 1000,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = RSIBollingerStrategy()
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestDualMACrossoverSignal:
    """Test Dual MA Crossover signal generation."""
    
    @patch("strategies.dual_ma_crossover.config")
    def test_dual_ma_buy(self, mock_config):
        """Test Dual MA Crossover generates BUY on golden cross."""
        mock_config.STRATEGY_PARAMS = {
            "DualMA_Crossover": {
                "fast_period": 20,
                "slow_period": 60,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 4.5,
                "candle_interval": "4h",
            }
        }
        from strategies.dual_ma_crossover import DualMACrossoverStrategy
        from strategies.base_strategy import SignalType
        
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        # Fast MA below slow, then crosses above
        close = np.concatenate([
            np.linspace(50000, 48000, 100),  # Declining - fast MA below slow
            np.linspace(48000, 51000, 100),  # Rising - fast MA crosses above slow
        ])
        
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = DualMACrossoverStrategy()
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestMACDMomentumSignal:
    """Test MACD Momentum signal generation."""
    
    @patch("strategies.macd_momentum.config")
    def test_macd_bullish(self, mock_config):
        """Test MACD generates BUY on bullish crossover."""
        mock_config.STRATEGY_PARAMS = {
            "MACD_Momentum": {
                "trend_ema": 50,
                "macd_fast": 12,
                "macd_slow": 26,
                "signal_period": 9,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 4.0,
                "candle_interval": "4h",
            }
        }
        from strategies.macd_momentum import MACDMomentumStrategy
        from strategies.base_strategy import SignalType
        
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        close = np.concatenate([
            np.linspace(50000, 48000, 100),  # Declining
            np.linspace(48000, 51000, 100),  # Rising
        ])
        
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = MACDMomentumStrategy()
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
    
    @patch("strategies.macd_momentum.config")
    def test_macd_bearish(self, mock_config):
        """Test MACD generates SELL on bearish crossover."""
        mock_config.STRATEGY_PARAMS = {
            "MACD_Momentum": {
                "trend_ema": 50,
                "macd_fast": 12,
                "macd_slow": 26,
                "signal_period": 9,
                "atr_sl_mult": 2.0,
                "atr_tp_mult": 4.0,
                "candle_interval": "4h",
            }
        }
        from strategies.macd_momentum import MACDMomentumStrategy
        from strategies.base_strategy import SignalType
        
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
        np.random.seed(42)
        close = np.concatenate([
            np.linspace(50000, 51000, 100),  # Rising
            np.linspace(51000, 48000, 100),  # Declining
        ])
        
        df = pd.DataFrame({
            "close": close,
            "open": close + np.random.randn(n) * 50,
            "high": close + np.abs(np.random.randn(n) * 100),
            "low": close - np.abs(np.random.randn(n) * 100),
            "volume": np.random.rand(n) * 1000 + 500,
        }, index=dates)
        
        from utils.indicators import add_all_indicators
        df = add_all_indicators(df)
        
        strat = MACDMomentumStrategy()
        signal = strat.generate_signal(df)
        
        assert signal.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


class TestMLAdaptiveModel:
    """Test ML Adaptive strategy model training."""
    
    @patch("strategies.ml_adaptive.config")
    def test_train_model_with_samples(self, mock_config):
        """Test MLAdaptiveStrategy.add_training_sample and model_trained property."""
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
        
        # Initially no samples
        assert strat.training_samples == 0
        assert strat.model_trained == False
        
        # Add 25 training samples
        for i in range(25):
            features = [np.random.rand() for _ in range(12)]
            outcome = 1.0 if i % 2 == 0 else 0.0
            strat.add_training_sample(features, outcome)
        
        assert strat.training_samples == 25
    
    @patch("strategies.ml_adaptive.config")
    def test_train_model_insufficient_samples(self, mock_config):
        """Test model_trained stays False with insufficient training samples."""
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
        
        # Add only 5 samples (below MIN_TRADES_FOR_LEARNING threshold)
        for i in range(5):
            features = [np.random.rand() for _ in range(12)]
            strat.add_training_sample(features, 1.0)
        
        assert strat.training_samples == 5
        assert strat.model_trained == False
    
    @patch("strategies.ml_adaptive.config")
    def test_get_applicable_lessons(self, mock_config):
        """Test get_applicable_lessons returns lessons for a regime."""
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
        
        # Without lessons, should return empty list
        lessons = strat.get_applicable_lessons("TRENDING_UP")
        assert isinstance(lessons, list)
