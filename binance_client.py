"""
Binance Market Data Client + Paper Trader
──────────────────────────────────────────
Market data always comes from the REAL Binance public REST API.
No API keys required for data — Binance's public endpoints are used:
  - GET /api/v3/klines       → candlestick history
  - GET /api/v3/ticker/price → real-time price
  - GET /api/v3/depth        → order book (for realistic slippage)

Order execution is simulated locally (paper trading) using the live
price at the moment of signal. This is a true paper trading system:
  - Real prices, real indicators, real signals
  - Simulated fills at market price ± realistic slippage
  - Optional: live Binance Testnet execution if keys are provided

Changes:
  - Added retry logic for order placement (exponential backoff)
  - Added input validation (minimum quantity checks)
  - Added circuit breaker for API failures
  - Added WebSocket support for real-time price updates
"""

import logging
import threading
import time
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable

import pandas as pd
import requests

try:
    import websockets
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceOrderException
    BINANCE_SDK_AVAILABLE = True
except ImportError:
    BINANCE_SDK_AVAILABLE = False

import config
from utils.indicators import add_all_indicators

logger = logging.getLogger(__name__)

BINANCE_PUBLIC_BASE = "https://api.binance.com"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5

# Order retry configuration
ORDER_MAX_RETRIES = 3
ORDER_RETRY_BACKOFF = 1.0  # seconds

# Minimum order quantities for common symbols
MIN_NOTIONAL = {
    "BTCUSDT": 5.0,    # $5 minimum
    "ETHUSDT": 5.0,
    "BNBUSDT": 10.0,
    "DEFAULT": 10.0,
}


class CircuitBreaker:
    """Simple circuit breaker to prevent hammering failing API endpoints."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning("Circuit breaker OPEN - too many failures")

    def record_success(self):
        self.failure_count = 0
        self.state = "closed"

    def can_proceed(self) -> bool:
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                logger.info("Circuit breaker half-open - attempting request")
                return True
            return False
        return True


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker()


class BinanceWebSocketClient:
    """
    WebSocket client for real-time price updates.
    
    Uses Binance's WebSocket streams for low-latency price data.
    Falls back to REST polling if WebSocket is unavailable.
    """
    
    WS_BASE = "wss://stream.binance.com:9443/ws"
    RECONNECT_DELAY = 5  # seconds
    
    def __init__(self, symbols: List[str] = None):
        self._symbols = symbols or ["btcusdt"]
        self._price_callbacks: List[Callable[[str, float], None]] = []
        self._running = False
        self._thread = None
        self._current_prices: Dict[str, float] = {}
        self._lock = threading.Lock()
        
        if not WEBSOCKET_AVAILABLE:
            logger.warning("WebSockets not available - using REST polling")
    
    def start(self):
        """Start the WebSocket connection in a background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="websocket")
        self._thread.start()
        logger.info("WebSocket client started")
    
    def stop(self):
        """Stop the WebSocket connection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("WebSocket client stopped")
    
    def add_price_callback(self, callback: Callable[[str, float], None]):
        """Register a callback for price updates (symbol, price)."""
        self._price_callbacks.append(callback)
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Get the current price for a symbol."""
        with self._lock:
            return self._current_prices.get(symbol.lower())
    
    def _run(self):
        """Main WebSocket loop."""
        while self._running:
            try:
                streams = "/".join([f"{s}@ticker" for s in self._symbols])
                ws_url = f"{self.WS_BASE}/{streams}"
                
                import asyncio
                asyncio.run(self._connect(ws_url))
                
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if self._running:
                    time.sleep(self.RECONNECT_DELAY)
    
    async def _connect(self, ws_url: str):
        """Connect to WebSocket and process messages."""
        if not WEBSOCKET_AVAILABLE:
            return
            
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info(f"WebSocket connected to {ws_url}")
                
                async for message in ws:
                    if not self._running:
                        break
                    
                    try:
                        data = json.loads(message)
                        self._process_ticker(data)
                    except Exception as e:
                        logger.debug(f"WebSocket message error: {e}")
                        
        except Exception as e:
            logger.warning(f"WebSocket connection lost: {e}")
    
    def _process_ticker(self, data: dict):
        """Process a ticker update message."""
        if "s" not in data:  # Symbol
            return
        
        symbol = data["s"].lower()
        price = float(data["c"])  # Close price (last price)
        
        with self._lock:
            self._current_prices[symbol] = price
        
        # Notify callbacks
        for callback in self._price_callbacks:
            try:
                callback(symbol, price)
            except Exception as e:
                logger.error(f"Price callback error: {e}")


class BinancePublicDataFetcher:
    """
    Fetches OHLCV and price data from Binance's public REST API.
    No API keys required. Always returns REAL market data.
    """

    def __init__(self, base_url: str = BINANCE_PUBLIC_BASE):
        self._base = base_url
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "BTC-PaperTrading-Bot/2.0",
        })
        self._price_cache: Dict[str, float] = {}
        self._check_connectivity()

    def _check_connectivity(self):
        try:
            r = self._session.get(f"{self._base}/api/v3/ping", timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            # Also verify server time sync
            t = self._session.get(f"{self._base}/api/v3/time", timeout=REQUEST_TIMEOUT).json()
            server_dt = datetime.fromtimestamp(t["serverTime"] / 1000, tz=timezone.utc)
            logger.info(f"✓ Binance public API connected. Server time: {server_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        except Exception as e:
            raise ConnectionError(f"Cannot reach Binance API at {self._base}: {e}") from e

    def _get(self, endpoint: str, params: dict = None):
        url = f"{self._base}{endpoint}"
        for attempt in range(MAX_RETRIES):
            try:
                r = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on {endpoint} (attempt {attempt+1}/{MAX_RETRIES})")
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP {r.status_code} on {endpoint}: {e}")
                if r.status_code == 429:  # rate limited
                    time.sleep(5)
                break
            except Exception as e:
                logger.warning(f"Request error (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {endpoint} after {MAX_RETRIES} attempts")

    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        """Fetch most recent N candles — real OHLCV from Binance."""
        data = self._get("/api/v3/klines", params={
            "symbol": symbol, "interval": interval, "limit": min(limit, 1000)
        })
        return self._parse_klines(data)

    def get_klines_since(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        """Fetch historical klines going back `days` days, paginating as needed."""
        start_ms = int((time.time() - days * 86400) * 1000)
        all_klines = []
        while True:
            data = self._get("/api/v3/klines", params={
                "symbol": symbol, "interval": interval,
                "startTime": start_ms, "limit": 1000,
            })
            if not data:
                break
            all_klines.extend(data)
            if len(data) < 1000:
                break
            start_ms = data[-1][0] + 1
            time.sleep(0.15)  # gentle rate limiting
        logger.info(f"Fetched {len(all_klines)} {interval} candles for {symbol} ({days}d history)")
        return self._parse_klines(all_klines)

    def get_current_price(self, symbol: str) -> float:
        """Real-time price from Binance ticker."""
        try:
            data = self._get("/api/v3/ticker/price", params={"symbol": symbol})
            price = float(data["price"])
            self._price_cache[symbol] = price
            return price
        except Exception as e:
            logger.error(f"Price fetch failed for {symbol}: {e}")
            if symbol in self._price_cache:
                logger.warning(f"Returning cached price: ${self._price_cache[symbol]:,.2f}")
                return self._price_cache[symbol]
            raise

    def get_order_book_spread(self, symbol: str) -> float:
        """Current bid-ask spread as fraction of mid price (for slippage estimation)."""
        try:
            data = self._get("/api/v3/depth", params={"symbol": symbol, "limit": 5})
            best_bid = float(data["bids"][0][0])
            best_ask = float(data["asks"][0][0])
            mid = (best_bid + best_ask) / 2
            return (best_ask - best_bid) / mid
        except Exception:
            return 0.0005  # default 0.05% spread

    def get_24hr_stats(self, symbol: str) -> dict:
        """24h price change stats — used for dashboard."""
        try:
            return self._get("/api/v3/ticker/24hr", params={"symbol": symbol})
        except Exception:
            return {}

    @staticmethod
    def _parse_klines(klines: list) -> pd.DataFrame:
        if not klines:
            return pd.DataFrame()
        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ]
        df = pd.DataFrame(klines, columns=cols)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("open_time")[["open", "high", "low", "close", "volume"]]
        df = df.sort_index()
        # Drop incomplete last candle (still forming)
        df = df.iloc[:-1]
        df = add_all_indicators(df)
        return df


class PaperTrader:
    """
    Simulates order execution at REAL Binance prices.

    This is NOT a mock or demo — it uses the live Binance price feed.
    Fills are executed at current market price ± realistic spread/slippage.
    All paper trades are logged clearly as PAPER in logs and dashboard.
    """

    def __init__(self, data_client: BinancePublicDataFetcher):
        self._data = data_client
        self._order_counter = 0

    def place_market_order(self, symbol: str, side: str,
                           quantity: float) -> Optional[dict]:
        """
        Simulate market order at current real price.
        BUY filled at ask (real_price + spread/2 + slippage)
        SELL filled at bid (real_price - spread/2 - slippage)
        
        Includes order validation to ensure minimum notional requirements.
        """
        try:
            real_price = self._data.get_current_price(symbol)
            
            # Validate order quantity
            is_valid, error_msg, adjusted_qty = validate_order_quantity(symbol, quantity, real_price)
            if not is_valid:
                logger.error(f"Paper order validation failed: {error_msg}")
                return None
            
            if adjusted_qty > 0 and adjusted_qty != quantity:
                logger.info(f"Paper order adjusted quantity from {quantity:.6f} to {adjusted_qty:.6f}")
                quantity = adjusted_qty
            
            spread_pct = self._data.get_order_book_spread(symbol)

            if side == "BUY":
                fill_price = real_price * (1 + spread_pct / 2 + config.SLIPPAGE)
            else:
                fill_price = real_price * (1 - spread_pct / 2 - config.SLIPPAGE)

            notional = quantity * fill_price
            fee = notional * config.TRADING_FEE

            self._order_counter += 1
            order_id = f"PAPER_{self._order_counter}_{int(time.time() * 1000)}"

            order = {
                "orderId": order_id,
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "status": "FILLED",
                "origQty": f"{quantity:.6f}",
                "executedQty": f"{quantity:.6f}",
                "cummulativeQuoteQty": f"{notional:.4f}",
                "fills": [{
                    "price": f"{fill_price:.4f}",
                    "qty": f"{quantity:.6f}",
                    "commission": f"{fee:.6f}",
                    "commissionAsset": "USDT",
                }],
                "transactTime": int(time.time() * 1000),
                "_paper_trade": True,
                "_real_market_price": real_price,
                "_spread_pct": spread_pct,
            }

            logger.info(
                f"📋 [PAPER TRADE] {side} {quantity:.6f} {symbol} "
                f"@ ${fill_price:,.2f} "
                f"(live market=${real_price:,.2f}, spread={spread_pct*100:.3f}%, fee=${fee:.2f})"
            )
            return order

        except Exception as e:
            logger.error(f"Paper order failed: {e}")
            return None


def validate_order_quantity(symbol: str, quantity: float, price: float) -> tuple[bool, str, float]:
    """
    Validate that an order meets minimum requirements.
    
    Returns:
        (is_valid, error_message, adjusted_quantity)
    """
    min_notional = MIN_NOTIONAL.get(symbol, MIN_NOTIONAL["DEFAULT"])
    notional = quantity * price
    
    if notional < min_notional:
        # Try to adjust quantity to meet minimum
        adjusted_qty = min_notional / price
        if adjusted_qty < 0.00001:  # Below Binance minimum
            return False, f"Notional ${notional:.2f} below minimum ${min_notional:.2f}", 0.0
        return True, "", adjusted_qty
    
    return True, "", quantity


def place_market_order_with_retry(client, symbol: str, side: str, 
                                   quantity: float, price: float,
                                   use_live: bool = False) -> Optional[Dict]:
    """
    Place a market order with retry logic and circuit breaker.
    
    Args:
        client: Binance client instance (live or None)
        symbol: Trading symbol (e.g., "BTCUSDT")
        side: "BUY" or "SELL"
        quantity: Order quantity
        price: Current market price for validation
        use_live: Whether to attempt live execution
        
    Returns:
        Order dict on success, None on failure
    """
    # Check circuit breaker
    if not _circuit_breaker.can_proceed():
        logger.error("Circuit breaker open - skipping order")
        return None
    
    # Validate order
    is_valid, error_msg, adjusted_qty = validate_order_quantity(symbol, quantity, price)
    if not is_valid:
        logger.error(f"Order validation failed: {error_msg}")
        return None
    
    if adjusted_qty > 0 and adjusted_qty != quantity:
        logger.info(f"Adjusted quantity from {quantity:.6f} to {adjusted_qty:.6f} to meet minimum")
        quantity = adjusted_qty
    
    # Retry loop
    last_error = None
    for attempt in range(ORDER_MAX_RETRIES):
        try:
            if use_live and client:
                order = client.create_order(
                    symbol=symbol, side=side, type="MARKET",
                    quantity=f"{quantity:.5f}",
                )
                logger.info(f"[LIVE] {side} {quantity:.5f} {symbol} order filled")
                _circuit_breaker.record_success()
                return order
            else:
                # Paper trading fallback
                return None  # Will be handled by PaperTrader
                
        except Exception as e:
            last_error = e
            _circuit_breaker.record_failure()
            logger.warning(f"Order attempt {attempt + 1}/{ORDER_MAX_RETRIES} failed: {e}")
            
            if attempt < ORDER_MAX_RETRIES - 1:
                sleep_time = ORDER_RETRY_BACKOFF * (2 ** attempt)  # Exponential backoff
                logger.info(f"Retrying in {sleep_time:.1f}s...")
                time.sleep(sleep_time)
    
    logger.error(f"Order failed after {ORDER_MAX_RETRIES} attempts: {last_error}")
    return None


class BinanceClient:
    """
    Unified client for the trading bot.

    Data   → ALWAYS real Binance public API (no keys needed)
    Orders → Paper trading by default (PaperTrader with real prices)
           → Live Testnet/Mainnet if BINANCE_API_KEY is configured
    """

    def __init__(self, use_websocket: bool = True):
        self._data = BinancePublicDataFetcher()
        self._paper = PaperTrader(self._data)
        self._live_client = None
        self._live_mode = False
        self._setup_live_client()
        
        # Optional WebSocket for real-time prices
        self._ws_client = None
        if use_websocket and WEBSOCKET_AVAILABLE:
            try:
                self._ws_client = BinanceWebSocketClient(["btcusdt"])
                self._ws_client.start()
                logger.info("WebSocket enabled for real-time prices")
            except Exception as e:
                logger.warning(f"WebSocket init failed: {e} - using REST polling")

        if self._live_mode:
            env = "TESTNET" if config.USE_TESTNET else "LIVE MAINNET ⚠️"
            logger.info(f"Execution mode: {env}")
        else:
            logger.info("Execution mode: PAPER TRADING (real Binance market data)")

    def _setup_live_client(self):
        """Connect to Binance for live order execution if keys are provided."""
        if not BINANCE_SDK_AVAILABLE:
            return
        if not config.BINANCE_API_KEY or not config.BINANCE_API_SECRET:
            return
        # Don't activate live trading unless explicitly set to PAPER_TRADING=false
        if getattr(config, "PAPER_TRADING", True):
            logger.info("PAPER_TRADING=true — skipping live execution setup")
            return
        try:
            self._live_client = Client(
                api_key=config.BINANCE_API_KEY,
                api_secret=config.BINANCE_API_SECRET,
                testnet=config.USE_TESTNET,
            )
            if config.USE_TESTNET:
                self._live_client.API_URL = config.TESTNET_REST_URL
            self._live_client.ping()
            self._live_mode = True
        except Exception as e:
            logger.warning(f"Live client setup failed: {e} — using paper trading")

    # ─── Market data (always real) ─────────────────────────────────────────────

    def get_historical_klines(self, symbol: str, interval: str,
                              days: int) -> pd.DataFrame:
        """Real historical OHLCV for backtesting."""
        return self._data.get_klines_since(symbol, interval, days)

    def get_latest_candles(self, symbol: str, interval: str,
                           limit: int = 600) -> pd.DataFrame:
        """Real-time candles for live signal generation."""
        return self._data.get_klines(symbol, interval, limit=limit)

    def get_current_price(self, symbol: str) -> float:
        """Real-time market price."""
        return self._data.get_current_price(symbol)

    def get_24hr_stats(self, symbol: str) -> dict:
        """24h ticker stats for dashboard."""
        return self._data.get_24hr_stats(symbol)

    def get_account_balance(self) -> Dict[str, float]:
        if self._live_mode and self._live_client:
            try:
                account = self._live_client.get_account()
                return {
                    b["asset"]: float(b["free"])
                    for b in account["balances"]
                    if float(b["free"]) > 0 or b["asset"] in ("USDT", "BTC")
                }
            except Exception as e:
                logger.error(f"Balance fetch failed: {e}")
        return {"USDT": config.INITIAL_CAPITAL, "BTC": 0.0}

    def get_open_orders(self, symbol: str) -> List[Dict]:
        if self._live_mode and self._live_client:
            try:
                return self._live_client.get_open_orders(symbol=symbol)
            except Exception as e:
                logger.error(f"Open orders fetch failed: {e}")
        return []

    # ─── Order execution ───────────────────────────────────────────────────────

    def place_market_order(self, symbol: str, side: str,
                           quantity: float) -> Optional[Dict]:
        """Place a market order with validation and retry logic."""
        # Validate order first
        current_price = self._data.get_current_price(symbol)
        is_valid, error_msg, adjusted_qty = validate_order_quantity(symbol, quantity, current_price)
        if not is_valid:
            logger.error(f"Order validation failed: {error_msg}")
            return None
        
        if adjusted_qty > 0 and adjusted_qty != quantity:
            logger.info(f"Adjusted quantity from {quantity:.6f} to {adjusted_qty:.6f}")
            quantity = adjusted_qty
        
        if self._live_mode and self._live_client:
            # Try live order with retry logic
            result = place_market_order_with_retry(
                self._live_client, symbol, side, quantity, current_price, use_live=True
            )
            if result is not None:
                return result
            logger.warning("Live order failed, falling back to paper trading")
        
        # Paper trading fallback
        return self._paper.place_market_order(symbol, side, quantity)

    def place_oco_order(self, symbol: str, side: str, quantity: float,
                        stop_price: float, limit_price: float,
                        take_profit: float) -> Optional[Dict]:
        if self._live_mode and self._live_client:
            try:
                return self._live_client.create_oco_order(
                    symbol=symbol, side=side,
                    quantity=f"{quantity:.5f}",
                    price=f"{take_profit:.2f}",
                    stopPrice=f"{stop_price:.2f}",
                    stopLimitPrice=f"{limit_price:.2f}",
                    stopLimitTimeInForce="GTC",
                )
            except Exception as e:
                logger.error(f"OCO order error: {e}")
        # Paper: SL/TP is enforced internally by the position monitoring loop
        return {"orderId": "PAPER_SL_TP_INTERNAL", "status": "MANAGED"}

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        if self._live_mode and self._live_client:
            try:
                self._live_client.cancel_order(symbol=symbol, orderId=order_id)
                return True
            except Exception as e:
                logger.error(f"Cancel order error: {e}")
                return False
        return True  # Paper: nothing to cancel

    @property
    def is_paper_trading(self) -> bool:
        return not self._live_mode

    @property
    def is_demo(self) -> bool:
        """Legacy compat — we no longer have fake demo data, always real."""
        return False

    def get_websocket_price(self, symbol: str = "btcusdt") -> Optional[float]:
        """Get price from WebSocket (faster than REST). Returns None if not available."""
        if self._ws_client:
            return self._ws_client.get_price(symbol)
        return None

    def stop(self):
        """Stop WebSocket connection on shutdown."""
        if self._ws_client:
            self._ws_client.stop()
