"""Central configuration for the BTC Paper Trading Bot."""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Credentials (optional — only needed for live/testnet execution) ───────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
USE_TESTNET        = os.getenv("USE_TESTNET", "true").lower() == "true"

# Testnet base URLs (only used if API keys are set and USE_TESTNET=true)
TESTNET_REST_URL = "https://testnet.binance.vision/api"
TESTNET_WS_URL   = "wss://testnet.binance.vision/ws"

# ─── Trading Mode ──────────────────────────────────────────────────────────────
# PAPER_TRADING=true  → simulate orders at real Binance prices (default, safe)
# PAPER_TRADING=false → live/testnet order execution (requires API keys)
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# ─── Trading Parameters ────────────────────────────────────────────────────────
SYMBOL             = "BTCUSDT"
INITIAL_CAPITAL    = float(os.getenv("INITIAL_CAPITAL", "10000"))
MAX_STRATEGIES     = 7
CANDLE_INTERVAL    = "1h"
LOOKBACK_CANDLES   = 600   # candles kept in memory per strategy interval

# ─── Risk Management ───────────────────────────────────────────────────────────
DEFAULT_STOP_LOSS_PCT              = 0.025   # 2.5%
DEFAULT_TAKE_PROFIT_PCT            = 0.055   # 5.5%
MAX_POSITION_PCT                   = 0.35    # max 35% of strategy capital per trade
MIN_POSITION_PCT                   = 0.05    # min 5% (ensures meaningful trade size)
MAX_OPEN_POSITIONS_PER_STRATEGY    = 2
MAX_PORTFOLIO_DRAWDOWN_PCT         = 0.20    # pause new entries at 20% drawdown

# ─── Fees & Slippage ───────────────────────────────────────────────────────────
TRADING_FEE = 0.001   # 0.1% Binance spot fee
SLIPPAGE    = 0.0003  # 0.03% estimated slippage (conservative)

# ─── Backtesting ───────────────────────────────────────────────────────────────
BACKTEST_DAYS          = 500   # 500 days – needed for SMA-250 on daily strategies
MIN_CAGR_THRESHOLD     = 0.30  # Require ≥30% annualised CAGR to activate a strategy
MIN_WIN_RATE           = 0.38  # 38% minimum – momentum strategies have lower WR but high R:R
MIN_PROFIT_FACTOR      = 1.20  # Min gross profit / gross loss ratio

# ─── Learning Engine ───────────────────────────────────────────────────────────
MIN_TRADES_FOR_LEARNING = 10    # start ML tuning after N trades
MODEL_UPDATE_FREQUENCY  = 5     # retrain model every N closed trades
CONFIDENCE_THRESHOLD    = 0.40  # skip trades with ML confidence below this
KELLY_FRACTION          = 0.25  # fractional Kelly for position sizing

# Claude API for journal generation (optional — enhances reflection quality)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ─── Scheduling ────────────────────────────────────────────────────────────────
STRATEGY_CHECK_INTERVAL_SEC = 60    # check for new signals every 60s
POSITION_CHECK_INTERVAL_SEC = 20    # check SL/TP every 20s
LEARNING_UPDATE_INTERVAL_SEC = 180  # run learning update every 3 minutes

# ─── Database ──────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "trading_bot.db")

# ─── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_HOST      = "0.0.0.0"
DASHBOARD_PORT      = 8050
DASHBOARD_UPDATE_MS = 10000   # refresh every 10 seconds

# ─── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = os.path.join(os.path.dirname(__file__), "trading_bot.log")

# ─── Data Management ────────────────────────────────────────────────────────────
# Set to "true" to clear all trading data on startup and start fresh
# This is useful when you want to reset the bot and not show old backtest data
RESET_ON_STARTUP = os.getenv("RESET_ON_STARTUP", "false").lower() == "true"

# Set to "true" to include backtest data in dashboards (for debugging)
# Default is false - only live trading data is shown
SHOW_BACKTEST_DATA = os.getenv("SHOW_BACKTEST_DATA", "false").lower() == "true"

# ─── Strategy Parameters (defaults; self-learning engine may override) ──────────
STRATEGY_PARAMS = {
    "EMA5_Momentum": {
        # Source  : Quantified Strategies – best EMA period for Bitcoin (~145% CAGR)
        # Entry LONG  : close crosses above 5-day EMA
        # Entry SHORT : close crosses below 5-day EMA
        "ema_period":      5,
        "atr_sl_mult":     1.5,    # SL = 1.5 × ATR below entry
        "atr_tp_mult":     3.5,    # TP = 3.5 × ATR above entry
        "candle_interval": "1d",
    },
    "DualMA_Crossover": {
        # Source  : Quantified Strategies – 100/250 SMA crossover (~115% CAGR)
        # Entry LONG  : SMA-100 crosses above SMA-250 (golden cross)
        # Entry SHORT : SMA-100 crosses below SMA-250 (death  cross)
        # Requires BACKTEST_DAYS >= 300 for SMA-250 warm-up
        "fast_period":     100,
        "slow_period":     250,
        "atr_sl_mult":     2.0,
        "atr_tp_mult":     5.0,
        "candle_interval": "1d",
    },
    "Regime_RiskOnOff": {
        # Source  : Menthor Q – binary risk-on/risk-off model (~100-200% cumulative/yr)
        # Proxy   : EMA-200 + MACD histogram + RSI all must agree (on-chain metrics
        #           not available via Binance REST API)
        # Entry LONG  : all three conditions bullish (regime switches to RISK-ON)
        # Entry SHORT : all three conditions bearish (regime switches to RISK-OFF)
        "ema_trend":       200,
        "rsi_bull_min":    50,
        "rsi_bear_max":    50,
        "atr_sl_mult":     2.0,
        "atr_tp_mult":     4.5,
        "candle_interval": "4h",
    },
    "PriceMomentum_25": {
        # Source  : Quantified Strategies – 25-day close-to-close momentum (~115% CAGR)
        # Entry LONG  : today's close > close 25 days ago
        # Entry SHORT : today's close < close 25 days ago
        "lookback":        25,
        "atr_sl_mult":     1.5,
        "atr_tp_mult":     4.0,
        "candle_interval": "1d",
    },
    "Residual_MeanRev": {
        # Source  : Medium – BTC-neutral residual mean reversion (Sharpe ~2.3 post-2021)
        # Proxy   : rolling OLS regression on log-price; trade deviations from trend
        #           (original uses altcoin-vs-BTC beta stripping; here we strip BTC's
        #            own trend since we only trade BTCUSDT)
        # Entry LONG  : z-score of residual < -1.5 (below trend, oversold)
        # Entry SHORT : z-score of residual > +1.5 (above trend, overbought)
        "reg_window":      60,
        "zscore_window":   30,
        "entry_threshold": 1.5,
        "atr_sl_mult":     1.8,
        "atr_tp_mult":     3.5,
        "candle_interval": "4h",
    },
    "Donchian_Breakout": {
        # Source  : Quantified Strategies – Donchian breakout on BTC/USD (back to 2015)
        # INVERSE ADX: enter when ADX < threshold (market is calm / consolidating)
        # 15-day lookback offers best risk/reward per research
        # Entry LONG  : close > previous 15-day Donchian upper  AND  ADX < 25
        # Entry SHORT : close < previous 15-day Donchian lower  AND  ADX < 25
        "dc_period":       15,
        "adx_calm_max":    25,
        "atr_sl_mult":     1.5,
        "atr_tp_mult":     3.5,
        "candle_interval": "1d",
    },
    "Blended_MomentumMR": {
        # Source  : Medium – 50/50 momentum + mean-reversion portfolio (best risk-adj)
        # Momentum: 25-period close-to-close (pre-2021 dominant)
        # MR      : RSI + Bollinger Bands (post-2021 dominant)
        # Blend for regime-robust performance across all market cycles
        "momentum_period":  25,
        "rsi_oversold":     38,
        "rsi_overbought":   62,
        "bb_period":        20,
        "bb_std":           2.0,
        "atr_sl_mult":      1.8,
        "atr_tp_mult":      3.8,
        "candle_interval":  "4h",
    },
}


# ─── Configuration Validation ───────────────────────────────────────────────────
def validate_config() -> list:
    """
    Validate configuration settings.
    
    Returns:
        List of validation error messages (empty if all valid)
    """
    errors = []
    
    # Validate capital
    if INITIAL_CAPITAL < 100:
        errors.append(f"INITIAL_CAPITAL must be >= $100, got ${INITIAL_CAPITAL}")
    
    # Validate risk parameters
    if DEFAULT_STOP_LOSS_PCT <= 0 or DEFAULT_STOP_LOSS_PCT >= 1:
        errors.append(f"DEFAULT_STOP_LOSS_PCT must be between 0 and 1, got {DEFAULT_STOP_LOSS_PCT}")
    
    if DEFAULT_TAKE_PROFIT_PCT <= 0 or DEFAULT_TAKE_PROFIT_PCT >= 1:
        errors.append(f"DEFAULT_TAKE_PROFIT_PCT must be between 0 and 1, got {DEFAULT_TAKE_PROFIT_PCT}")
    
    if DEFAULT_TAKE_PROFIT_PCT <= DEFAULT_STOP_LOSS_PCT:
        errors.append(f"DEFAULT_TAKE_PROFIT_PCT ({DEFAULT_TAKE_PROFIT_PCT}) must be > DEFAULT_STOP_LOSS_PCT ({DEFAULT_STOP_LOSS_PCT})")
    
    # Validate position sizing
    if MAX_POSITION_PCT <= 0 or MAX_POSITION_PCT > 1:
        errors.append(f"MAX_POSITION_PCT must be between 0 and 1, got {MAX_POSITION_PCT}")
    
    # Validate backtest parameters
    if BACKTEST_DAYS < 100:
        errors.append(f"BACKTEST_DAYS should be >= 100 for meaningful results, got {BACKTEST_DAYS}")
    
    if MIN_CAGR_THRESHOLD < 0:
        errors.append(f"MIN_CAGR_THRESHOLD must be >= 0, got {MIN_CAGR_THRESHOLD}")
    
    # Validate ML parameters
    if MIN_TRADES_FOR_LEARNING < 5:
        errors.append(f"MIN_TRADES_FOR_LEARNING should be >= 5, got {MIN_TRADES_FOR_LEARNING}")
    
    if not 0 <= CONFIDENCE_THRESHOLD <= 1:
        errors.append(f"CONFIDENCE_THRESHOLD must be between 0 and 1, got {CONFIDENCE_THRESHOLD}")
    
    # Validate API credentials for live trading
    if not PAPER_TRADING:
        if not BINANCE_API_KEY or not BINANCE_API_SECRET:
            errors.append("BINANCE_API_KEY and BINANCE_API_SECRET required for live trading")
    
    # Validate symbol format
    if not SYMBOL.endswith(("USDT", "BUSD", "USD")):
        errors.append(f"SYMBOL should end with USDT/BUSD/USD, got {SYMBOL}")
    
    return errors


def get_config_summary() -> dict:
    """Get a summary of the current configuration."""
    return {
        "symbol": SYMBOL,
        "capital": f"${INITIAL_CAPITAL:,.2f}",
        "mode": "PAPER" if PAPER_TRADING else "LIVE",
        "stop_loss": f"{DEFAULT_STOP_LOSS_PCT*100:.1f}%",
        "take_profit": f"{DEFAULT_TAKE_PROFIT_PCT*100:.1f}%",
        "max_position": f"{MAX_POSITION_PCT*100:.0f}%",
        "backtest_days": BACKTEST_DAYS,
        "strategies": len(STRATEGY_PARAMS),
    }


# Run validation on import
_config_errors = validate_config()
if _config_errors:
    import logging
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger("config")
    for error in _config_errors:
        logger.warning(f"Config validation: {error}")
