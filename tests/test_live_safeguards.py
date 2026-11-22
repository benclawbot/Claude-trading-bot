"""Fail-closed live order routing: do not repeat an ambiguous real fill."""
from unittest.mock import Mock, patch
import binance_client


def test_failed_live_order_is_not_automatically_retried():
    exchange = Mock()
    exchange.create_order.side_effect = TimeoutError("exchange acknowledgement lost")
    with patch.object(binance_client, "validate_order_quantity", return_value=(True, "", 0.001)):
        result = binance_client.place_market_order_with_retry(
            exchange, "BTCUSDT", "BUY", 0.001, 50_000, use_live=True
        )
    assert result is None
    assert exchange.create_order.call_count == 1


def test_mainnet_requires_separate_opt_in():
    client = binance_client.BinanceClient.__new__(binance_client.BinanceClient)
    client._live_client = None
    client._live_mode = False
    with patch.object(binance_client, "BINANCE_SDK_AVAILABLE", True), \
         patch.object(binance_client.config, "BINANCE_API_KEY", "dummy"), \
         patch.object(binance_client.config, "BINANCE_API_SECRET", "dummy"), \
         patch.object(binance_client.config, "PAPER_TRADING", False), \
         patch.object(binance_client.config, "USE_TESTNET", False), \
         patch.object(binance_client.config, "ALLOW_MAINNET_TRADING", False), \
         patch.object(binance_client, "Client") as sdk:
        client._setup_live_client()
    sdk.assert_not_called()
    assert not client._live_mode
