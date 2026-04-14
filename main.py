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

import atexit
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None

import config
import database as db
import review_engine
from binance_client import BinanceClient
from backtester import run_all_backtests
from portfolio_manager import PortfolioManager
from learning_engine import LearningEngine
from strategies import ALL_STRATEGIES
from utils.indicators import compute_market_regime

# Optional: TradingView MCP for macro sentiment + extended market data
try:
    from tradingview_client import tv_prefetch, tv_client, is_available as tv_available
    _TV_IMPORTED = True
except Exception:
    tv_prefetch = None
    tv_client = None
    _TV_IMPORTED = False

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
_lock_handle = None


def _release_singleton_lock():
    global _lock_handle
    if _lock_handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        _lock_handle.close()
    except Exception:
        pass
    _lock_handle = None


def _acquire_singleton_lock() -> bool:
    """Ensure only one bot process writes to the same DB/logs at a time."""
    global _lock_handle
    if fcntl is None:
        logger.warning("fcntl unavailable; singleton lock disabled")
        return True

    lock_path = os.path.join(os.path.dirname(__file__), "trading_bot.lock")
    _lock_handle = open(lock_path, "w")
    try:
        fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_handle.write(str(os.getpid()))
        _lock_handle.flush()
        atexit.register(_release_singleton_lock)
        return True
    except BlockingIOError:
        logger.critical("Another trading bot instance is already running (singleton lock held)")
        try:
            _lock_handle.close()
        except Exception:
            pass
        _lock_handle = None
        return False


def _handle_signal(sig, frame):
    logger.warning(f"Signal {sig} received — shutting down gracefully…")
    _shutdown.set()
    if _TV_IMPORTED and tv_prefetch is not None:
        try:
            tv_prefetch.stop()
        except Exception:
            pass

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
        self._last_fresh_price_ts: float = 0.0
        self._last_stale_warn_ts: float = 0.0

    @staticmethod
    def _strategy_family(strategy_name: str) -> str:
        mapping = getattr(config, "REGIME_ROUTER_FAMILY_BY_STRATEGY", {})
        if isinstance(mapping, dict):
            return str(mapping.get(strategy_name, "adaptive")).strip().lower()
        return "adaptive"

    @staticmethod
    def _regime_allows_strategy(strategy_name: str, regime: str) -> bool:
        enabled = bool(getattr(config, "REGIME_ROUTER_ENABLED", True))
        if not enabled:
            return True
        allowed_map = getattr(config, "REGIME_ROUTER_ALLOWED_FAMILIES", {})
        if not isinstance(allowed_map, dict):
            return True
        allowed = allowed_map.get(str(regime).upper())
        if allowed is None:
            return True
        family = TradingBot._strategy_family(strategy_name)
        allowed_set = {str(x).strip().lower() for x in allowed if str(x).strip()}
        return family in allowed_set

    @staticmethod
    def _robustness_score_from_backtest(result) -> float:
        if not result:
            return 0.0
        consistency = (
            0.35 * max(0.0, min(1.0, float(result.win_rate)))
            + 0.30 * max(0.0, min(1.0, float(result.profit_factor) / 2.5))
            + 0.35 * max(0.0, min(1.0, 1.0 - float(result.max_drawdown) / 0.35))
        )
        edge = max(0.0, min(1.0, (float(result.avg_trade_pnl) + 0.02) / 0.08))
        growth = max(0.0, min(1.0, (float(result.cagr) + 0.10) / 0.80))
        return float(max(0.0, min(1.0, 0.50 * consistency + 0.30 * edge + 0.20 * growth)))

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
        self._last_fresh_price_ts = time.time()
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

        # Activate strategies that pass thresholds (+ optional experiment mode).
        def _as_bool(value, default=False):
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
            return default

        def _as_float(value, default=0.0):
            try:
                return float(value)
            except Exception:
                return default

        def _as_name_set(value):
            if isinstance(value, str):
                return {s.strip() for s in value.split(",") if s.strip()}
            if isinstance(value, (set, list, tuple)):
                return {str(s).strip() for s in value if str(s).strip()}
            return set()

        min_robustness = float(getattr(config, "AUTORESEARCH_MIN_ROBUSTNESS", 0.55))
        pass_names = {
            name for name, r in bt_results.items()
            if r and r.passes_threshold and self._robustness_score_from_backtest(r) >= min_robustness
        }

        exp_mode_enabled = _as_bool(getattr(config, "EXPERIMENT_MODE_ENABLED", False), False)
        exp_mode_cap_pct = max(0.0, min(1.0, _as_float(getattr(config, "EXPERIMENT_MODE_CAPITAL_PCT", 0.20), 0.20)))
        exp_mode_names = _as_name_set(getattr(config, "EXPERIMENT_MODE_STRATEGIES", set()))

        exp_candidate_names = {
            s.name for s in self.strategies
            if s.name in exp_mode_names and s.name not in pass_names
        }

        experiment_pool = config.INITIAL_CAPITAL * exp_mode_cap_pct if exp_mode_enabled else 0.0
        core_pool = max(config.INITIAL_CAPITAL - experiment_pool, 0.0)
        core_share = core_pool / max(len(pass_names), 1)
        experiment_share = experiment_pool / max(len(exp_candidate_names), 1) if exp_candidate_names else 0.0

        if exp_mode_enabled:
            logger.info(
                f"Experiment mode ON | pool=${experiment_pool:,.2f} ({exp_mode_cap_pct:.0%}) | "
                f"candidates={len(exp_candidate_names)}"
            )

        active_count = 0
        for strat in self.strategies:
            result = bt_results.get(strat.name)
            robust_score = self._robustness_score_from_backtest(result)
            passes = bool(result and result.passes_threshold and robust_score >= min_robustness)
            reason = "no backtest result"
            if result:
                reason = (
                    f"CAGR={result.cagr*100:.1f}% "
                    f"WR={result.win_rate*100:.1f}% "
                    f"PF={result.profit_factor:.2f} "
                    f"ROB={robust_score:.2f}"
                )

            is_experiment = exp_mode_enabled and (strat.name in exp_candidate_names)

            if passes:
                strat.is_active = True
                active_count += 1
                symbol = "✓"
                level = "info"
            elif is_experiment and experiment_share > 0:
                strat.is_active = True
                active_count += 1
                symbol = "△"
                level = "info"
                reason = f"EXPERIMENT | {reason}"
            else:
                strat.is_active = False
                symbol = "✗"
                level = "warning"

            getattr(logger, level)(f"  {symbol} {strat.name:20s}  {reason}")

            # Preserve existing capital on restart to avoid double-counting with
            # any open positions whose notional was already deducted in a prior run.
            # Only assign a fresh share when the strategy has no capital yet (first boot).
            existing_row = db.get_strategy(strat.name)
            if strat.is_active:
                target_share = experiment_share if is_experiment and not passes else core_share
                new_capital = existing_row["capital"] if (existing_row and existing_row["capital"] > 0) else target_share
            else:
                new_capital = 0

            db.upsert_strategy(
                name=strat.name,
                capital=new_capital,
                params=strat.params,
                backtest_cagr=result.cagr if result else 0,
                backtest_win_rate=result.win_rate if result else 0,
                is_active=strat.is_active,
            )

        # If nothing passes (and no experiment candidate activated), activate all as fallback.
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

        # Start TradingView MCP pre-fetch engine (market snapshots + sentiment)
        if _TV_IMPORTED and tv_prefetch is not None:
            if getattr(config, "TV_MCP_ENABLED", False):
                tv_prefetch.start()
                tv_state = tv_client()
                if tv_state.get("available"):
                    snap = tv_state.get("market_snapshot") or {}
                    sent = tv_state.get("btc_sentiment") or {}
                    logger.info(
                        "[tv] MCP active | BTC sentiment: %s (%.3f) | "
                        "snapshot: SPX=%.0f VIX=%.1f",
                        sent.get("label", "unknown"),
                        sent.get("score") or 0.0,
                        snap.get("sp500", {}).get("price") or 0,
                        snap.get("vix", {}).get("price") or 0,
                    )
            else:
                logger.info("[tv] MCP disabled via TV_MCP_ENABLED=false")
        else:
            logger.info(
                "[tv] tradingview-mcp not installed. "
                "Run: pip install tradingview-mcp-server"
            )

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

                if self._entry_paused_for_stale_price():
                    _shutdown.wait(timeout=min(config.STRATEGY_CHECK_INTERVAL_SEC, 5))
                    continue

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
                    regime = compute_market_regime(df)
                    if not self._regime_allows_strategy(strat.name, regime):
                        logger.debug(f"[{strat.name}] regime router blocked in {regime}")
                        continue

                    signal = strat.generate_signal(df)
                    meta = signal.metadata if isinstance(signal.metadata, dict) else {}
                    signal.metadata = dict(meta)
                    signal.metadata.setdefault("regime", regime)

                    if signal.is_actionable:
                        logger.info(
                            f"[{strat.name}] SIGNAL {signal.type.value} "
                            f"conf={signal.confidence:.2f} ml={ml_conf:.2f} "
                            f"regime={regime} price=${price:,.2f}"
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
                self._update_price()
                price = self._current_price
                if price > 0 and self.portfolio:
                    self.portfolio.check_open_positions(price)
            except Exception as e:
                logger.error(f"[positions] Error: {e}", exc_info=True)
            _shutdown.wait(timeout=config.POSITION_CHECK_INTERVAL_SEC)

    # ─── Learning loop ────────────────────────────────────────────────────────

    def _learning_loop(self):
        logger.info("[learning] Loop started")
        self._last_trade_count = 0
        while not _shutdown.is_set():
            try:
                all_trades = db.get_trades(limit=1000)
                current_count = len(all_trades)

                if current_count > self._last_trade_count:
                    # Only process genuinely NEW trades — skip any that already
                    # have a journal entry (idempotency guard + restart replay)
                    new_trades = all_trades[:current_count - self._last_trade_count]
                    for trade in new_trades:
                        if db.journal_has_entry(trade["id"]):
                            logger.debug(
                                f"[learning] trade #{trade['id']} already has "
                                f"journal entry — skipping"
                            )
                            continue
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
                    self._last_trade_count = current_count

                strat_dict = {s.name: s for s in self.strategies}
                self.learning.update_performance_snapshots(strat_dict)

                # Scheduled auto-review (Wed + Sun) for experiment scoring/risk ladder.
                review_result = review_engine.maybe_run_scheduled_review()
                if review_result.get("ran"):
                    logger.info(
                        "[learning] Auto-review complete | week=%s | size=%.2f | evaluated=%s",
                        review_result.get("week_id"),
                        review_result.get("size_multiplier", 1.0),
                        review_result.get("strategies_evaluated", 0),
                    )

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

    def _price_staleness_sec(self) -> float:
        if self._last_fresh_price_ts <= 0:
            return float("inf")
        return max(0.0, time.time() - self._last_fresh_price_ts)

    def _entry_paused_for_stale_price(self) -> bool:
        staleness = self._price_staleness_sec()
        stale_limit = float(getattr(config, "STALE_PRICE_ENTRY_PAUSE_SEC", 120))
        if staleness <= stale_limit:
            return False

        now = time.time()
        warn_interval = float(getattr(config, "STALE_PRICE_WARN_INTERVAL_SEC", 60))
        if now - self._last_stale_warn_ts >= warn_interval:
            logger.warning(
                "[stale-price] Pausing NEW entries: last fresh price %.1fs ago (limit %.1fs). "
                "Open positions still monitored.",
                staleness,
                stale_limit,
            )
            self._last_stale_warn_ts = now
        return True

    def _update_price(self):
        try:
            price = self.client.get_current_price(config.SYMBOL)
            if price > 0:
                with self._price_lock:
                    self._current_price = price
                self._last_fresh_price_ts = time.time()
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
    if not _acquire_singleton_lock():
        sys.exit(2)

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

