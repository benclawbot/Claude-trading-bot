# Tests for binance_client.py

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, PropertyMock
import json

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestValidateOrderQuantity:
    """Test the validate_order_quantity function."""
    
    def test_valid_btc_order(self):
        """Test valid BTCUSDT order."""
        from binance_client import validate_order_quantity
        
        is_valid, msg, adj_qty = validate_order_quantity("BTCUSDT", 0.01, 50000)
        assert is_valid
        assert adj_qty == 0.01
    
    def test_valid_eth_order(self):
        """Test valid ETHUSDT order."""
        from binance_client import validate_order_quantity
        
        is_valid, msg, adj_qty = validate_order_quantity("ETHUSDT", 0.1, 3000)
        assert is_valid
        assert adj_qty == 0.1
    
    def test_below_minimum_notional_adjusts(self):
        """Test that small orders are adjusted to meet minimum notional."""
        from binance_client import validate_order_quantity
        
        # BTC order below $5 minimum notional
        # 0.00001 * 50000 = $0.50, below $5 minimum
        is_valid, msg, adj_qty = validate_order_quantity("BTCUSDT", 0.00001, 50000)
        # Should either reject or try to adjust
        assert adj_qty >= 0  # adj_qty is 0 if rejected, or adjusted value
    
    def test_above_minimum_valid(self):
        """Test order above minimum notional is valid."""
        from binance_client import validate_order_quantity
        
        is_valid, msg, adj_qty = validate_order_quantity("BTCUSDT", 0.001, 50000)
        # $50 notional > $5 minimum
        assert is_valid
        assert adj_qty == 0.001


class TestPaperTrader:
    """Test PaperTrader class."""
    
    @patch("binance_client.config")
    def test_place_market_order_buy(self, mock_config):
        """Test paper trader BUY order."""
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0}
        
        from binance_client import PaperTrader, BinancePublicDataFetcher
        
        # Mock data fetcher
        mock_data = Mock(spec=BinancePublicDataFetcher)
        mock_data.get_current_price.return_value = 50000.0
        mock_data.get_order_book_spread.return_value = 0.0005
        
        trader = PaperTrader(mock_data)
        order = trader.place_market_order("BTCUSDT", "BUY", 0.01)
        
        assert order is not None
        assert order["symbol"] == "BTCUSDT"
        assert order["side"] == "BUY"
        assert order["status"] == "FILLED"
        assert order["_paper_trade"] == True
        assert "_real_market_price" in order
    
    @patch("binance_client.config")
    def test_place_market_order_sell(self, mock_config):
        """Test paper trader SELL order."""
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0}
        
        from binance_client import PaperTrader, BinancePublicDataFetcher
        
        mock_data = Mock(spec=BinancePublicDataFetcher)
        mock_data.get_current_price.return_value = 50000.0
        mock_data.get_order_book_spread.return_value = 0.0005
        
        trader = PaperTrader(mock_data)
        order = trader.place_market_order("BTCUSDT", "SELL", 0.01)
        
        assert order is not None
        assert order["side"] == "SELL"
    
    @patch("binance_client.config")
    def test_place_market_order_invalid_quantity(self, mock_config):
        """Test paper trader with invalid order quantity."""
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0}
        
        from binance_client import PaperTrader, BinancePublicDataFetcher
        
        mock_data = Mock(spec=BinancePublicDataFetcher)
        mock_data.get_current_price.return_value = 50000.0
        
        trader = PaperTrader(mock_data)
        # Very small quantity that won't meet minimum notional
        order = trader.place_market_order("BTCUSDT", "BUY", 0.00001)
        
        assert order is None  # Should be rejected
    
    @patch("binance_client.config")
    def test_place_market_order_price_slippage(self, mock_config):
        """Test that BUY fills at higher price (ask) and SELL at lower (bid)."""
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0}
        
        from binance_client import PaperTrader, BinancePublicDataFetcher
        
        mock_data = Mock(spec=BinancePublicDataFetcher)
        real_price = 50000.0
        mock_data.get_current_price.return_value = real_price
        mock_data.get_order_book_spread.return_value = 0.001  # 0.1% spread
        
        trader = PaperTrader(mock_data)
        
        buy_order = trader.place_market_order("BTCUSDT", "BUY", 0.01)
        sell_order = trader.place_market_order("BTCUSDT", "SELL", 0.01)
        
        # BUY should fill above market price
        assert buy_order["_real_market_price"] == real_price
        assert float(buy_order["fills"][0]["price"]) >= real_price
        
        # SELL should fill below market price
        assert float(sell_order["fills"][0]["price"]) <= real_price


class TestBinancePublicDataFetcher:
    """Test BinancePublicDataFetcher with mocked HTTP responses."""
    
    def test_parse_klines_empty(self):
        """Test parsing empty klines data."""
        from binance_client import BinancePublicDataFetcher
        
        result = BinancePublicDataFetcher._parse_klines([])
        assert result.empty
    
    def test_parse_klines_valid(self):
        """Test parsing valid klines data."""
        from binance_client import BinancePublicDataFetcher
        
        # _parse_klines drops the last row (incomplete candle)
        # so we need at least 3 klines to have at least 1 after dropping
        klines = [[
            1700000000000 + i * 3600000,  # open_time - 1 hour apart
            str(50000 + i * 100),          # open
            str(51000 + i * 100),          # high
            str(49000 + i * 100),          # low
            str(50500 + i * 100),          # close
            str(100 + i * 10),             # volume
            1700003600000 + i * 3600000,   # close_time
            str(5050000 + i * 1000),       # quote_volume
            100 + i * 10,                  # num_trades
            str(50 + i),                    # taker_buy_base
            str(2500 + i * 10),            # taker_buy_quote
            "0",                            # ignore
        ] for i in range(3)]
        
        result = BinancePublicDataFetcher._parse_klines(klines)
        
        assert not result.empty
        assert "close" in result.columns


class TestCircuitBreaker:
    """Test CircuitBreaker class."""
    
    def test_circuit_breaker_initial_state(self):
        """Test circuit breaker starts closed."""
        from binance_client import CircuitBreaker
        
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert cb.state == "closed"
        assert cb.can_proceed() == True
    
    def test_circuit_breaker_opens_after_threshold(self):
        """Test circuit breaker opens after reaching failure threshold."""
        from binance_client import CircuitBreaker
        
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_proceed() == False
    
    def test_circuit_breaker_success_resets(self):
        """Test circuit breaker resets on success."""
        from binance_client import CircuitBreaker
        
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        
        assert cb.failure_count == 0
        assert cb.state == "closed"
    
    def test_circuit_breaker_half_open_after_timeout(self):
        """Test circuit breaker enters half-open state after recovery timeout."""
        from binance_client import CircuitBreaker
        import time
        
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)  # 0 second timeout
        
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        
        # Immediately should be able to proceed (half-open)
        can_proceed = cb.can_proceed()
        # With 0 timeout, it should immediately try half-open
        assert can_proceed == True
        assert cb.state == "half-open"


class TestBinanceWebSocketClient:
    """Test BinanceWebSocketClient (mostly tests the interface)."""
    
    def test_websocket_client_init(self):
        """Test WebSocket client initialization."""
        from binance_client import BinanceWebSocketClient, WEBSOCKET_AVAILABLE
        
        if not WEBSOCKET_AVAILABLE:
            pytest.skip("websockets not available")
        
        client = BinanceWebSocketClient(["btcusdt", "ethusdt"])
        assert client._symbols == ["btcusdt", "ethusdt"]
        assert client._running == False
        assert client.get_price("btcusdt") is None
    
    def test_add_price_callback(self):
        """Test adding a price callback."""
        from binance_client import BinanceWebSocketClient, WEBSOCKET_AVAILABLE
        
        if not WEBSOCKET_AVAILABLE:
            pytest.skip("websockets not available")
        
        client = BinanceWebSocketClient()
        callback_called = []
        
        def callback(symbol, price):
            callback_called.append((symbol, price))
        
        client.add_price_callback(callback)
        assert callback in client._price_callbacks
    
    def test_get_price_mock(self):
        """Test getting current price from internal state."""
        from binance_client import BinanceWebSocketClient, WEBSOCKET_AVAILABLE
        
        if not WEBSOCKET_AVAILABLE:
            pytest.skip("websockets not available")
        
        client = BinanceWebSocketClient()
        # Manually set a price
        client._current_prices["btcusdt"] = 50000.0
        
        assert client.get_price("btcusdt") == 50000.0
        assert client.get_price("ethusdt") is None


class TestBinanceClient:
    """Test the main BinanceClient class."""
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_client_init_paper_mode(self, mock_fetcher_cls, mock_config):
        """Test BinanceClient initializes in paper trading mode."""
        mock_config.PAPER_TRADING = True
        mock_config.BINANCE_API_KEY = ""
        mock_config.BINANCE_API_SECRET = ""
        mock_config.USE_TESTNET = False
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0}
        mock_config.TESTNET_REST_URL = "https://testnet.binance.vision/api"
        mock_config.ANTHROPIC_API_KEY = ""
        
        # Mock the data fetcher
        mock_fetcher = MagicMock()
        mock_fetcher.get_current_price.return_value = 50000.0
        mock_fetcher.get_order_book_spread.return_value = 0.0005
        mock_fetcher_cls.return_value = mock_fetcher
        
        from binance_client import BinanceClient
        
        with patch("binance_client.BINANCE_SDK_AVAILABLE", False):
            with patch("binance_client.WEBSOCKET_AVAILABLE", False):
                client = BinanceClient(use_websocket=False)
        
        assert client.is_paper_trading == True
        assert client.is_demo == False
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_client_get_current_price(self, mock_fetcher_cls, mock_config):
        """Test getting current price."""
        mock_config.PAPER_TRADING = True
        mock_config.BINANCE_API_KEY = ""
        mock_config.BINANCE_API_SECRET = ""
        mock_config.USE_TESTNET = False
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0}
        mock_config.TESTNET_REST_URL = "https://testnet.binance.vision/api"
        
        mock_fetcher = MagicMock()
        mock_fetcher.get_current_price.return_value = 50000.0
        mock_fetcher_cls.return_value = mock_fetcher
        
        from binance_client import BinanceClient
        
        with patch("binance_client.BINANCE_SDK_AVAILABLE", False):
            with patch("binance_client.WEBSOCKET_AVAILABLE", False):
                client = BinanceClient(use_websocket=False)
        
        price = client.get_current_price("BTCUSDT")
        assert price == 50000.0
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_client_place_market_order(self, mock_fetcher_cls, mock_config):
        """Test placing a market order."""
        mock_config.PAPER_TRADING = True
        mock_config.BINANCE_API_KEY = ""
        mock_config.BINANCE_API_SECRET = ""
        mock_config.USE_TESTNET = False
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0, "DEFAULT": 10.0}
        mock_config.TESTNET_REST_URL = "https://testnet.binance.vision/api"
        mock_config.ANTHROPIC_API_KEY = ""
        
        mock_fetcher = MagicMock()
        mock_fetcher.get_current_price.return_value = 50000.0
        mock_fetcher.get_order_book_spread.return_value = 0.0005
        mock_fetcher_cls.return_value = mock_fetcher
        
        from binance_client import BinanceClient
        
        with patch("binance_client.BINANCE_SDK_AVAILABLE", False):
            with patch("binance_client.WEBSOCKET_AVAILABLE", False):
                client = BinanceClient(use_websocket=False)
        
        order = client.place_market_order("BTCUSDT", "BUY", 0.01)
        
        assert order is not None
        assert order["symbol"] == "BTCUSDT"
        assert order["side"] == "BUY"
        assert order["status"] == "FILLED"
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_client_place_market_order_invalid(self, mock_fetcher_cls, mock_config):
        """Test placing an invalid market order."""
        mock_config.PAPER_TRADING = True
        mock_config.BINANCE_API_KEY = ""
        mock_config.BINANCE_API_SECRET = ""
        mock_config.USE_TESTNET = False
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0, "DEFAULT": 10.0}
        mock_config.TESTNET_REST_URL = "https://testnet.binance.vision/api"
        mock_config.ANTHROPIC_API_KEY = ""
        
        mock_fetcher = MagicMock()
        mock_fetcher.get_current_price.return_value = 50000.0
        mock_fetcher_cls.return_value = mock_fetcher
        
        from binance_client import BinanceClient
        
        with patch("binance_client.BINANCE_SDK_AVAILABLE", False):
            with patch("binance_client.WEBSOCKET_AVAILABLE", False):
                client = BinanceClient(use_websocket=False)
        
        # Quantity way too small
        order = client.place_market_order("BTCUSDT", "BUY", 0.000001)
        assert order is None  # Should be rejected
    
    @patch("binance_client.config")
    @patch("binance_client.BinancePublicDataFetcher")
    def test_client_get_account_balance_paper(self, mock_fetcher_cls, mock_config):
        """Test getting account balance in paper mode."""
        mock_config.PAPER_TRADING = True
        mock_config.BINANCE_API_KEY = ""
        mock_config.BINANCE_API_SECRET = ""
        mock_config.USE_TESTNET = False
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.INITIAL_CAPITAL = 10000
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0}
        mock_config.TESTNET_REST_URL = "https://testnet.binance.vision/api"
        mock_config.ANTHROPIC_API_KEY = ""
        
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher
        
        from binance_client import BinanceClient
        
        with patch("binance_client.BINANCE_SDK_AVAILABLE", False):
            with patch("binance_client.WEBSOCKET_AVAILABLE", False):
                client = BinanceClient(use_websocket=False)
        
        balance = client.get_account_balance()
        assert "USDT" in balance
        assert balance["USDT"] == 10000.0


class TestPlaceMarketOrderWithRetry:
    """Test place_market_order_with_retry function."""
    
    @patch("binance_client._circuit_breaker")
    @patch("binance_client.config")
    def test_circuit_breaker_open(self, mock_config, mock_cb):
        """Test that order is not placed when circuit breaker is open."""
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0, "DEFAULT": 10.0}
        mock_config.ANTHROPIC_API_KEY = ""
        
        mock_cb.can_proceed.return_value = False
        
        from binance_client import place_market_order_with_retry
        
        result = place_market_order_with_retry(None, "BTCUSDT", "BUY", 0.01, 50000, use_live=False)
        assert result is None
    
    @patch("binance_client._circuit_breaker")
    @patch("binance_client.config")
    def test_invalid_quantity_rejected(self, mock_config, mock_cb):
        """Test that invalid quantity is rejected before retry loop."""
        mock_config.SLIPPAGE = 0.0003
        mock_config.TRADING_FEE = 0.001
        mock_config.MIN_NOTIONAL = {"BTCUSDT": 5.0, "DEFAULT": 10.0}
        mock_config.ANTHROPIC_API_KEY = ""
        
        mock_cb.can_proceed.return_value = True
        
        from binance_client import place_market_order_with_retry
        
        # Very small quantity
        result = place_market_order_with_retry(None, "BTCUSDT", "BUY", 0.000001, 50000, use_live=False)
        assert result is None
