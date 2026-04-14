"""
TradingView MCP Client
─────────────────────
Lightweight wrapper around `tradingview-mcp-server` (atilaahmettaner).

Provides:
  - Real-time prices + market snapshots
  - Reddit sentiment analysis
  - Technical analysis (RSI, MACD, Bollinger, etc.)
  - Strategy backtesting

Falls back gracefully if the MCP package is not installed.

Usage:
  from tradingview_client import tv_client, get_btc_sentiment, get_market_snapshot
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from tradingview_mcp.core.services.yahoo_finance_service import (
    get_price,
    get_prices_bulk,
    get_market_snapshot as _tv_market_snapshot,
)
from tradingview_mcp.core.services.sentiment_service import (
    analyze_sentiment,
)
from tradingview_mcp.core.services.backtest_service import (
    run_backtest,
    compare_strategies,
    walk_forward_backtest,
)
from tradingview_mcp.core.utils.validators import (
    sanitize_timeframe,
    sanitize_exchange,
    get_market_type,
)

logger = logging.getLogger(__name__)

# ─── Availability check ───────────────────────────────────────────────────────

_MCP_AVAILABLE = True
try:
    from tradingview_mcp.core.services.indicators import extract_extended_indicators
except Exception as exc:  # pragma: no cover
    _MCP_AVAILABLE = False
    logger.warning(
        "tradingview-mcp-server not installed or incompatible version. "
        "Run: pip install tradingview-mcp-server. "
        "Trading data features will be disabled. Error: %s",
        exc,
    )


# ─── Cache ────────────────────────────────────────────────────────────────────

@dataclass
class _CacheEntry:
    value: any
    expires_at: float


class _Cache:
    """Simple TTL cache thread-safe for basic types."""

    def __init__(self, ttl_seconds: float = 120.0):
        self._store: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def get(self, key: str) -> any:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.time() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    def set(self, key: str, value: any, ttl: Optional[float] = None):
        with self._lock:
            self._store[key] = _CacheEntry(
                value=value,
                expires_at=time.time() + (ttl if ttl is not None else self._ttl),
            )

    def invalidate(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()


# Global caches
_price_cache = _Cache(ttl_seconds=60.0)          # prices: 1 min
_sentiment_cache = _Cache(ttl_seconds=600.0)       # sentiment: 10 min
_snapshot_cache = _Cache(ttl_seconds=300.0)        # market snapshot: 5 min
_ta_cache = _Cache(ttl_seconds=120.0)             # technical analysis: 2 min


# ─── Retry decorator ───────────────────────────────────────────────────────────

def _retry(
    fn: Callable,
    *args,
    retries: int = 2,
    delay: float = 1.0,
    on_fail: Callable[[Exception], any] = lambda e: None,
    **kwargs,
) -> any:
    """Simple retry wrapper for network calls."""
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover
            if attempt == retries:
                logger.debug("[tv] %s failed after %d attempts: %s", fn.__name__, retries, exc)
                return on_fail(exc)
            time.sleep(delay)
    return on_fail(Exception("unreachable"))  # pragma: no cover


# ─── Public API ───────────────────────────────────────────────────────────────

def is_available() -> bool:
    """Returns True if tradingview-mcp-server is installed and reachable."""
    return _MCP_AVAILABLE


def get_price(symbol: str, use_cache: bool = True) -> Optional[dict]:
    """
    Get real-time price for any Yahoo Finance symbol.
    Falls back to None on failure.
    """
    if not _MCP_AVAILABLE:
        return None

    cache_key = f"price:{symbol}"
    if use_cache:
        cached = _price_cache.get(cache_key)
        if cached is not None:
            return cached

    def _fetch():
        return _retry(get_price, symbol)

    result = _fetch()
    if result is not None and "error" not in result:
        _price_cache.set(cache_key, result)
    return result


def get_btc_sentiment(category: str = "crypto", limit: int = 20) -> Optional[dict]:
    """
    Get Reddit sentiment for BTC.
    Returns dict with sentiment_score (-1 to +1), label, post breakdown.
    """
    if not _MCP_AVAILABLE:
        return None

    cache_key = f"sentiment:BTC:{category}:{limit}"
    cached = _sentiment_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        return _retry(analyze_sentiment, symbol="BTC", category=category, limit=limit, retries=2)

    result = _fetch()
    if result is not None:
        _sentiment_cache.set(cache_key, result, ttl=600.0)
    return result


def get_market_snapshot() -> Optional[dict]:
    """
    Get snapshot of major markets: S&P500, NASDAQ, Dow, VIX, BTC, ETH, EUR/USD.
    Cached for 5 minutes — suitable for dashboard display.
    """
    if not _MCP_AVAILABLE:
        return None

    cached = _snapshot_cache.get("market_snapshot")
    if cached is not None:
        return cached

    def _fetch():
        return _retry(_tv_market_snapshot, retries=2, delay=1.5)

    result = _fetch()
    if result is not None:
        _snapshot_cache.set("market_snapshot", result, ttl=300.0)
    return result


def get_technical_analysis(
    symbol: str = "BTCUSDT",
    exchange: str = "binance",
    timeframe: str = "4h",
) -> Optional[dict]:
    """
    Get 30+ technical indicators for a symbol.
    Includes RSI, MACD, Bollinger Bands, EMA, SMA, Volume, etc.
    """
    if not _MCP_AVAILABLE:
        return None

    cache_key = f"ta:{symbol}:{exchange}:{timeframe}"
    cached = _ta_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        screener = get_market_type(exchange)
        tf = sanitize_timeframe(timeframe)
        result = extract_extended_indicators(
            symbol=symbol,
            exchange=exchange,
            screener=screener,
            interval=tf,
        )
        if result:
            _ta_cache.set(cache_key, result, ttl=120.0)
        return result
    except Exception as exc:  # pragma: no cover
        logger.debug("[tv] technical_analysis failed for %s: %s", symbol, exc)
        return None


def backtest_strategy(
    symbol: str = "BTCUSDT",
    strategy: str = "rsi",
    period: str = "1y",
    interval: str = "1d",
) -> Optional[dict]:
    """
    Run a backtest using one of 6 built-in strategies.
    Strategies: rsi | bollinger | macd | ema_cross | supertrend | donchian

    Returns dict with total_return, trades, win_rate, profit_factor, sharpe_ratio, equity_curve.
    """
    if not _MCP_AVAILABLE:
        return None

    def _fetch():
        return _retry(
            run_backtest,
            symbol=symbol,
            strategy=strategy,
            period=period,
            interval=interval,
            retries=2,
        )

    try:
        return _fetch()
    except Exception as exc:  # pragma: no cover
        logger.debug("[tv] backtest failed: %s", exc)
        return None


# ─── Pre-fetch engine ──────────────────────────────────────────────────────────

class _TVPrefetchEngine:
    """
    Background thread that pre-fetches and caches:
      - Market snapshot (every 5 min)
      - BTC sentiment  (every 10 min)

    Call .start() once from main.py startup.
    """

    def __init__(self, interval_snapshot: float = 300.0, interval_sentiment: float = 600.0):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._interval_snapshot = interval_snapshot
        self._interval_sentiment = interval_sentiment

    def start(self):
        if not _MCP_AVAILABLE:
            logger.info("[tv] MCP unavailable — pre-fetch engine not started")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="tv-prefetch")
        self._thread.start()
        logger.info("[tv] Pre-fetch engine started (snapshot=5m, sentiment=10m)")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self):
        # Do an immediate first fetch so caches are warm
        self._fetch_snapshot()
        self._fetch_sentiment()

        while not self._stop.is_set():
            # Wait with early-exit on stop signal
            for _ in range(6):  # 6 × 50s = 300s
                if self._stop.wait(timeout=50.0):
                    return
            self._fetch_snapshot()
            self._fetch_sentiment()

    def _fetch_snapshot(self):
        try:
            snap = get_market_snapshot()
            if snap:
                logger.debug("[tv] Snapshot cached: %s", list(snap.keys()))
        except Exception as exc:  # pragma: no cover
            logger.debug("[tv] snapshot pre-fetch failed: %s", exc)

    def _fetch_sentiment(self):
        try:
            sent = get_btc_sentiment()
            if sent:
                logger.debug(
                    "[tv] Sentiment cached: %s (%.3f)",
                    sent.get("sentiment_label"),
                    sent.get("sentiment_score"),
                )
        except Exception as exc:  # pragma: no cover
            logger.debug("[tv] sentiment pre-fetch failed: %s", exc)


# Singleton pre-fetch engine
tv_prefetch = _TVPrefetchEngine()


# ─── Convenience aliases ───────────────────────────────────────────────────────

def tv_client():
    """Returns a dict with current cached state for all TV data — useful for dashboards."""
    if not _MCP_AVAILABLE:
        return {"available": False}

    snapshot = _snapshot_cache.get("market_snapshot")
    sentiment = _sentiment_cache.get(f"sentiment:BTC:crypto:20")

    btc_price = get_price("BTCUSDT", use_cache=True)
    btc_price = btc_price if btc_price else {}

    return {
        "available": True,
        "btc_price": btc_price.get("price"),
        "btc_change_pct": btc_price.get("change_pct"),
        "market_snapshot": snapshot,
        "btc_sentiment": {
            "score": sentiment.get("sentiment_score") if sentiment else None,
            "label": sentiment.get("sentiment_label") if sentiment else None,
            "posts_analyzed": sentiment.get("posts_analyzed") if sentiment else None,
        },
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
