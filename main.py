"""
BTC Paper Trading Bot — Main Orchestrator
─────────────────────────────────────────
Market data: REAL Binance public API (no keys required)
Execution:   Paper trading at live prices by default

Startup sequence:
  1. Verify Binance API connectivity (public endpoints)
  2. Fetch 90 days of real OHLCV data for backtesting
  3. Backtest all 5 strategies on real historical data
  4. Activate strategies that pass WR + PF thresholds
  5. Launch trading loops:
       - Trading loop: signal generation every 60s
       - Position loop: SL/TP monitoring every 20s
       - Learning loop: journal + param tuning every 3min
       - Balance loop: equity snapshots every 5min
  6. Start Dash dashboard on port 8050

Changes:
  - Added log rotation to prevent unbounded log growth
"""

import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List

import config
import database as db
from binance_client import BinanceClient
from backtester import run_all_backtests
from portfolio_manager import PortfolioManager
from learning_engine import LearningEngine
from strategies import ALL_STRATEGIES

# ─── Logging setup ────────────────────────────────────────────────────────────
# Console handler with colors (if available)
try:
    import colorlog
    console_handler = colorlog.StreamHandler()
    console_handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)-8s]%(reset)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan", "INFO": "green",
            "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold_red",
        },
    ))
except ImportError:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"))

# File handler with rotation (max 5MB per file, keep 3 backup files)
log_dir = os.path.dirname(config.LOG_FILE)
if log_dir and not os.path.exists(log_dir):
    os.makedirs(log_dir, exist_ok=True)

file_handler = logging.handlers.RotatingFileHandler(
    config.LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
root_logger.handlers = [console_handler, file_handler]

logger = logging.getLogger("main")

# ─── Shutdown flag ────────────────────────────────────────────────────────────
_shutdown = threading.Event()

def _handle_signal(sig, frame):
    logger.warning(f"Signal {sig} received — shutting down gracefully…")
    _shutdown.set()

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


class TradingBot:

    def __init__(self):
        db.init_db()
        logger.info("Database initialised")
        self.client     = BinanceClient()
        self.strategies = [S() for S in ALL_STRATEGIES]
        self.portfolio:  PortfolioManager = None
        self.learning:   LearningEngine   = None
        self._strat_dfs: Dict[str, object] = {}
        self._current_price: float = 0.0
        self._price_lock = threading.Lock()

    # ─── Startup ──────────────────────────────────────────────────────────────

    def startup(self):
        logger.info("=" * 65)
        logger.info("   BTC PAPER TRADING BOT  —  Starting up")
        logger.info(f"   Mode      : {'PAPER TRADING (real Binance data)' if self.client.is_paper_trading else 'LIVE TRADING ⚠️'}")
        logger.info(f"   Capital   : ${config.INITIAL_CAPITAL:,.2f}")
        logger.info(f"   Symbol    : {config.SYMBOL}")
        logger.info(f"   Backtest  : {config.BACKTEST_DAYS} days of real OHLCV data")
        logger.info("=" * 65)

        # Fetch live price
        self._current_price = self.client.get_current_price(config.SYMBOL)
        stats = self.client.get_24hr_stats(config.SYMBOL)
        change_pct = float(stats.get("priceChangePercent", 0))
        logger.info(
            f"Live BTC price: ${self._current_price:,.2f} "
            f"({change_pct:+.2f}% 24h | vol: {float(stats.get('volume', 0)):,.0f} BTC)"
        )

        # Warm up candle cache
        logger.info("\nLoading candle data…")
        self._refresh_candles()

        # Backtest on real data
        logger.info(f"\nRunning backtests on {config.BACKTEST_DAYS} days of real Binance data…")
        bt_results = run_all_backtests(self.strategies, self.client)

        # Activate strategies that pass thresholds
        active_count = 0
        for strat in self.strategies:
            result = bt_results.get(strat.name)
            passes = False
            reason = "no backtest result"

            if result:
                passes = result.passes_threshold   # CAGR ≥ threshold AND WR ≥ min AND PF ≥ min
                reason = (
                    f"CAGR={result.cagr*100:.1f}% "
                    f"WR={result.win_rate*100:.1f}% "
                    f"PF={result.profit_factor:.2f}"
                )

            share = config.INITIAL_CAPITAL / max(
                len([r for r in bt_results.values() if r and r.passes_threshold]), 1
            )

            if passes:
                strat.is_active = True
                active_count += 1
                symbol = "✓"
                level = "info"
            else:
                strat.is_active = False
                share = 0
                symbol = "✗"
                level = "warning"

            getattr(logger, level)(f"  {symbol} {strat.name:20s}  {reason}")
            # Preserve existing capital on restart to avoid double-counting with
            # any open positions whose notional was already deducted in a prior run.
            # Only assign a fresh share when the strategy has no capital yet (first boot).
            existing_row = db.get_strategy(strat.name)
            if passes:
                new_capital = existing_row["capital"] if (existing_row and existing_row["capital"] > 0) else share
            else:
                new_capital = 0
            db.upsert_strategy(
                name=strat.name,
                capital=new_capital,
                params=strat.params,
                backtest_cagr=result.cagr if result else 0,
                backtest_win_rate=result.win_rate if result else 0,
                is_active=passes,
            )

        # If nothing passes, activate everything with reduced size
        if active_count == 0:
            logger.warning(
                "No strategy passed backtest thresholds. "
                "Activating ALL with reduced position sizing."
            )
            share = config.INITIAL_CAPITAL / len(self.strategies)
            for strat in self.strategies:
                strat.is_active = True
                result = bt_results.get(strat.name)
                existing_row = db.get_strategy(strat.name)
                new_capital = existing_row["capital"] if (existing_row and existing_row["capital"] > 0) else share
                db.upsert_strategy(
                    name=strat.name, capital=new_capital, params=strat.params,
                    backtest_cagr=result.cagr if result else 0,
                    backtest_win_rate=result.win_rate if result else 0,
                    is_active=True,
                )
            active_count = len(self.strategies)

        logger.info(f"\n{active_count}/{len(self.strategies)} strategies active\n")

        # Init portfolio + learning
        self.portfolio = PortfolioManager(self.client, self.strategies)
        strat_dict = {s.name: s for s in self.strategies}
        self.learning = LearningEngine(strat_dict)

        # Load journal entries and restore learned patterns from previous runs
        self.learning.learn_from_all_journal_entries()

        # Initial balance snapshot
        bal = self.portfolio.total_balance(self._current_price)
        db.record_balance(
            total_balance=bal["total_balance"],
            realized_pnl=bal["realized_pnl"],
            unrealized_pnl=bal["unrealized_pnl"],
            strategy_breakdown=bal.get("breakdown", {}),
        )

        logger.info("Startup complete. Entering trading loops.\n")

    # ─── Main run ─────────────────────────────────────────────────────────────

    def run(self):
        self.startup()

        threads = [
            threading.Thread(target=self._trading_loop,    daemon=True, name="trading"),
            threading.Thread(target=self._position_loop,   daemon=True, name="positions"),
            threading.Thread(target=self._learning_loop,   daemon=True, name="learning"),
            threading.Thread(target=self._balance_loop,    daemon=True, name="balance"),
            threading.Thread(target=self._dashboard_thread, daemon=True, name="dashboard"),
        ]
        for t in threads:
            t.start()
            logger.info(f"Thread started: {t.name}")

        logger.info(f"\n🚀 Bot running. Dashboard: http://localhost:{config.DASHBOARD_PORT}\n")

        while not _shutdown.is_set():
            _shutdown.wait(timeout=5)

        logger.info("Shutdown complete.")

    # ─── Trading loop ─────────────────────────────────────────────────────────

    def _trading_loop(self):
        logger.info("[trading] Loop started")
        while not _shutdown.is_set():
            try:
                self._update_price()
                self._refresh_candles()
                price = self._current_price

                for strat in self.strategies:
                    if not strat.is_active:
                        continue
                    interval = strat.candle_interval
                    df = self._strat_dfs.get(interval)
                    if df is None or len(df) < strat.min_candles:
                        logger.debug(
                            f"[{strat.name}] Insufficient data "
                            f"({len(df) if df is not None else 0}/{strat.min_candles} candles)"
                        )
                        continue

                    ml_conf = self.learning.get_confidence(strat.name, df)
                    signal = strat.generate_signal(df)

                    if signal.is_actionable:
                        logger.info(
                            f"[{strat.name}] SIGNAL {signal.type.value} "
                            f"conf={signal.confidence:.2f} ml={ml_conf:.2f} "
                            f"price=${price:,.2f}"
                        )
                        placed = self.portfolio.process_signal(strat, signal, price, ml_confidence=ml_conf)
                        if placed:
                            logger.info(f"[{strat.name}] ✓ Paper trade opened")
                    else:
                        logger.debug(f"[{strat.name}] HOLD")

            except Exception as e:
                logger.error(f"[trading] Error: {e}", exc_info=True)

            _shutdown.wait(timeout=config.STRATEGY_CHECK_INTERVAL_SEC)

    # ─── Position monitoring loop (SL/TP) ─────────────────────────────────────

    def _position_loop(self):
        logger.info("[positions] Loop started")
        while not _shutdown.is_set():
            try:
                price = self._current_price
                if price > 0 and self.portfolio:
                    self.portfolio.check_open_positions(price)
            except Exception as e:
                logger.error(f"[positions] Error: {e}", exc_info=True)
            _shutdown.wait(timeout=config.POSITION_CHECK_INTERVAL_SEC)

    # ─── Learning loop ────────────────────────────────────────────────────────

    def _learning_loop(self):
        logger.info("[learning] Loop started")
        _last_trade_count = 0
        while not _shutdown.is_set():
            try:
                all_trades = db.get_trades(limit=1000)
                current_count = len(all_trades)

                if current_count > _last_trade_count:
                    new_trades = all_trades[:current_count - _last_trade_count]
                    for trade in new_trades:
                        interval  = self._get_strat_interval(trade["strategy_name"])
                        df_latest = self._strat_dfs.get(interval)
                        self.learning.on_trade_closed(
                            trade_id=trade["id"],
                            strategy_name=trade["strategy_name"],
                            entry_price=float(trade["entry_price"]),
                            exit_price=float(trade["exit_price"]),
                            pnl=float(trade["pnl"]),
                            pnl_pct=float(trade["pnl_pct"]),
                            side=trade["side"],
                            duration_hours=float(trade["duration_hours"]),
                            exit_reason=trade.get("exit_reason", ""),
                            entry_features=trade.get("entry_features", {}),
                            df=df_latest,
                        )
                    _last_trade_count = current_count

                strat_dict = {s.name: s for s in self.strategies}
                self.learning.update_performance_snapshots(strat_dict)

            except Exception as e:
                logger.error(f"[learning] Error: {e}", exc_info=True)
            _shutdown.wait(timeout=config.LEARNING_UPDATE_INTERVAL_SEC)

    # ─── Balance snapshot loop ────────────────────────────────────────────────

    def _balance_loop(self):
        logger.info("[balance] Loop started")
        while not _shutdown.is_set():
            try:
                price = self._current_price
                if price > 0 and self.portfolio:
                    bal = self.portfolio.total_balance(price)
                    db.record_balance(
                        total_balance=bal["total_balance"],
                        realized_pnl=bal["realized_pnl"],
                        unrealized_pnl=bal["unrealized_pnl"],
                        strategy_breakdown=bal.get("breakdown", {}),
                    )
                    logger.info(
                        f"[balance] ${bal['total_balance']:,.2f} | "
                        f"Realized: ${bal['realized_pnl']:+,.2f} | "
                        f"Unrealized: ${bal['unrealized_pnl']:+,.2f}"
                    )
            except Exception as e:
                logger.error(f"[balance] Error: {e}", exc_info=True)
            _shutdown.wait(timeout=60)  # Update balance every 60 seconds (not every 5 min)

    # ─── Dashboard ────────────────────────────────────────────────────────────

    def _dashboard_thread(self):
        logger.info(f"[dashboard] Starting on http://localhost:{config.DASHBOARD_PORT}")
        try:
            from dashboard.app import run_dashboard
            run_dashboard(debug=False)
        except Exception as e:
            logger.error(f"[dashboard] Failed: {e}", exc_info=True)

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _update_price(self):
        try:
            price = self.client.get_current_price(config.SYMBOL)
            if price > 0:
                with self._price_lock:
                    self._current_price = price
        except Exception as e:
            logger.warning(f"Price update failed: {e}")

    def _refresh_candles(self):
        """Refresh OHLCV data for each unique strategy interval."""
        intervals = set(s.candle_interval for s in self.strategies if s.is_active)
        for interval in intervals:
            try:
                df = self.client.get_latest_candles(
                    config.SYMBOL, interval, limit=config.LOOKBACK_CANDLES
                )
                if df is not None and not df.empty:
                    self._strat_dfs[interval] = df
                    logger.debug(f"Refreshed {interval} candles: {len(df)} rows")
            except Exception as e:
                logger.error(f"[candles] Error refreshing {interval}: {e}")

    def _get_strat_interval(self, name: str) -> str:
        for s in self.strategies:
            if s.name == name:
                return s.candle_interval
        return "1h"


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        example = os.path.join(os.path.dirname(__file__), ".env.example")
        if os.path.exists(example):
            import shutil
            shutil.copy(example, env_path)
            logger.info("Created .env from .env.example")

    # ─── Handle data reset if configured ───────────────────────────────────────
    if config.RESET_ON_STARTUP:
        logger.warning("RESET_ON_STARTUP is enabled - clearing all trading data!")
        db.clear_old_data()
        logger.info("All trading data cleared. Starting fresh.")
    else:
        # Set live_since if not already set
        db.set_live_since()
        live_since = db.get_live_since()
        if live_since:
            logger.info(f"Live trading since: {live_since}")

    try:
        bot = TradingBot()
        bot.run()
    except ConnectionError as e:
        logger.critical(f"Cannot connect to Binance: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
