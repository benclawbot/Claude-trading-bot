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

# ─── Experiment lane controls ────────────────────────────────────────────────
# Cap total allocation for high-frequency experiment strategies to protect
# consistency while still collecting enough data.
EXPERIMENT_LANE_ENABLED = os.getenv("EXPERIMENT_LANE_ENABLED", "true").lower() == "true"
EXPERIMENT_LANE_CAP_PCT = float(os.getenv("EXPERIMENT_LANE_CAP_PCT", "0.30"))
EXPERIMENT_LANE_STRATEGIES = {
    s.strip() for s in os.getenv(
        "EXPERIMENT_LANE_STRATEGIES",
        "MACD_Momentum,EMA_Crossover,RSI_Bollinger,Breakout"
    ).split(",") if s.strip()
}

# Experiment mode: allow selected strategies to run in low-capital data-collection
# mode even when they fail the normal backtest pass thresholds.
EXPERIMENT_MODE_ENABLED = os.getenv("EXPERIMENT_MODE_ENABLED", "false").lower() == "true"
EXPERIMENT_MODE_CAPITAL_PCT = float(os.getenv("EXPERIMENT_MODE_CAPITAL_PCT", "0.20"))
EXPERIMENT_MODE_STRATEGIES = {
    s.strip() for s in os.getenv(
        "EXPERIMENT_MODE_STRATEGIES",
        "MACD_Momentum,EMA_Crossover"
    ).split(",") if s.strip()
}

# ─── Fees & Slippage ───────────────────────────────────────────────────────────
TRADING_FEE = 0.001   # 0.1% Binance spot fee
SLIPPAGE    = 0.0003  # 0.03% estimated slippage (conservative)

# ─── Backtesting ───────────────────────────────────────────────────────────────
BACKTEST_DAYS          = 500   # 500 days – needed for SMA-250 on daily strategies
MIN_CAGR_THRESHOLD     = 0.05  # Require ≥5% annualised CAGR to activate a strategy
MIN_WIN_RATE           = 0.32  # 32% minimum – allow lower WR strategies with high R:R
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
        # Source  : Quantified Strategies – short-window EMA momentum on Bitcoin
        # Entry LONG  : close crosses above 3-EMA on daily candles
        # Entry SHORT : close crosses below 3-EMA
        "ema_period":      3,
        "atr_sl_mult":     0.75,
        "atr_tp_mult":     1.5,
        "candle_interval": "1d",
    },
    "DualMA_Crossover": {
        # Source  : Quantified Strategies – dual MA crossover on Bitcoin
        # Entry LONG  : EMA-20 crosses above EMA-60 (signals on 4h)
        # Entry SHORT : EMA-20 crosses below EMA-60
        "fast_period":     20,
        "slow_period":     60,
        "atr_sl_mult":     2.0,
        "atr_tp_mult":     4.5,
        "candle_interval": "4h",
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
        # Source  : Quantified Strategies – close-to-close momentum on Bitcoin
        # Entry LONG  : today's close > close N days ago (positive momentum)
        # Entry SHORT : today's close < close N days ago (negative momentum)
        "lookback":        14,
        "atr_sl_mult":     1.5,
        "atr_tp_mult":     4.0,
        "candle_interval": "1d",
    },
    "Residual_MeanRev": {
        # Source  : Medium – BTC-neutral residual mean reversion (Sharpe ~2.3 post-2021)
        # Proxy   : rolling OLS regression on log-price; trade deviations from trend
        #           (original uses altcoin-vs-BTC beta stripping; here we strip BTC's
        #            own trend since we only trade BTCUSDT)
        # Entry LONG  : z-score of residual < -1.2 (below trend, oversold)
        # Entry SHORT : z-score of residual > +1.2 (above trend, overbought)
        "reg_window":      30,
        "zscore_window":   15,
        "entry_threshold": 1.2,
        "atr_sl_mult":     1.5,
        "atr_tp_mult":     3.0,
        "candle_interval": "4h",
    },
    "Donchian_Breakout": {
        # Source  : Quantified Strategies – Donchian breakout on BTC/USD (back to 2015)
        # Entry LONG  : close > previous 20-day Donchian upper (no ADX filter)
        # Entry SHORT : close < previous 20-day Donchian lower (no ADX filter)
        "dc_period":       20,
        "adx_calm_max":    99,     # effectively disabled
        "atr_sl_mult":     2.0,
        "atr_tp_mult":     5.0,
        "candle_interval": "1d",
    },
    "RSI_Bollinger": {
        # Source  : Quantified Strategies – RSI + Bollinger Bands mean reversion
        # Entry LONG  : RSI < oversold AND close <= BB lower band
        # Entry SHORT : RSI > overbought AND close >= BB upper band
        # Works best in: ranging / low-ADX markets
        "rsi_period":     14,
        "rsi_oversold":   35,
        "rsi_overbought": 65,
        "bb_period":      20,
        "bb_std":         2.0,
        "atr_sl_mult":    1.5,
        "atr_tp_mult":    3.0,
        "candle_interval": "4h",
    },
    "Breakout": {
        # Source  : Quantified Strategies – Volume-confirmed breakout
        # Entry LONG  : Close breaks 24-candle high with volume spike
        # Entry SHORT : Close breaks 24-candle low with volume spike
        # Works best in: volatile markets with elevated volume
        "lookback":            24,
        "volume_multiplier":   1.5,
        "atr_period":          14,
        "atr_sl_mult":         1.5,
        "atr_tp_mult":         2.5,
        "candle_interval":     "4h",
    },
    "MACD_Momentum": {
        # Source  : Quantified Strategies – MACD momentum with trend filter
        # Entry LONG  : MACD crosses above signal AND price > EMA200
        # Entry SHORT : MACD crosses below signal AND price < EMA200
        # Works best in: trending markets (ADX > 25)
        "trend_ema":       200,
        "atr_sl_mult":     1.5,
        "atr_tp_mult":     3.0,
        "candle_interval": "1h",
    },
    "EMA_Crossover": {
        # Source  : Quantified Strategies – EMA9/21 crossover + EMA50 trend filter
        # Entry LONG  : EMA9 crosses above EMA21 AND close > EMA50
        # Entry SHORT : EMA9 crosses below EMA21 AND close < EMA50
        # Works best in: moderate trends on 1H/4H
        "trend_ema":       50,
        "atr_sl_mult":     2.0,
        "atr_tp_mult":     4.0,
        "candle_interval": "1h",
    },
    "Blended_MomentumMR": {
        # Source  : Medium – 50/50 momentum + mean-reversion portfolio (best risk-adj)
        # Momentum: 25-period close-to-close (pre-2021 dominant)
        # MR      : RSI + Bollinger Bands (post-2021 dominant)
        # Blend for regime-robust performance across all market cycles
        "momentum_period":  20,
        "rsi_oversold":     35,
        "rsi_overbought":   65,
        "bb_period":        20,
        "bb_std":           2.0,
        "atr_sl_mult":      1.5,
        "atr_tp_mult":      3.0,
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
