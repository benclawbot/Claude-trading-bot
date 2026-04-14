import json
from unittest.mock import MagicMock


def test_setup_live_client_uses_ccxt_binance(monkeypatch):
    import binance_client as bc

    monkeypatch.setattr(bc, "CCXT_AVAILABLE", True)
    monkeypatch.setattr(bc, "BINANCE_SDK_AVAILABLE", False)
    monkeypatch.setattr(bc.config, "EXCHANGE_DATA_BACKEND", "binance", raising=False)
    monkeypatch.setattr(bc.config, "PAPER_TRADING", False, raising=False)
    monkeypatch.setattr(bc.config, "BINANCE_API_KEY", "k", raising=False)
    monkeypatch.setattr(bc.config, "BINANCE_API_SECRET", "s", raising=False)
    monkeypatch.setattr(bc.config, "USE_TESTNET", True, raising=False)

    fake_exchange = MagicMock()

    class _FakeCCXT:
        @staticmethod
        def binance(params):
            assert params["apiKey"] == "k"
            assert params["secret"] == "s"
            return fake_exchange

    monkeypatch.setattr(bc, "ccxt", _FakeCCXT, raising=False)
    monkeypatch.setattr(bc.BinancePublicDataFetcher, "__init__", lambda self: None)
    monkeypatch.setattr(bc.BinancePublicDataFetcher, "get_current_price", lambda self, symbol: 50000.0)
    monkeypatch.setattr(bc.BinancePublicDataFetcher, "get_order_book_spread", lambda self, symbol: 0.0005)

    client = bc.BinanceClient(use_websocket=False)

    assert client._live_mode is True
    assert client._live_client is fake_exchange
    fake_exchange.set_sandbox_mode.assert_called_once_with(True)


def test_place_market_order_live_ccxt_normalizes_order(monkeypatch):
    import binance_client as bc

    monkeypatch.setattr(bc.BinancePublicDataFetcher, "__init__", lambda self: None)
    monkeypatch.setattr(bc.BinanceClient, "_setup_live_client", lambda self: None)
    monkeypatch.setattr(bc.config, "EXCHANGE_DATA_BACKEND", "binance", raising=False)

    client = bc.BinanceClient(use_websocket=False)
    client._live_mode = True

    fake_live = MagicMock()
    fake_live.create_order.return_value = {
        "id": "abc123",
        "status": "closed",
        "filled": 0.01,
        "cost": 500.0,
        "average": 50000.0,
    }
    client._live_client = fake_live

    monkeypatch.setattr(client, "get_current_price", lambda symbol: 50000.0)

    order = client.place_market_order("BTCUSDT", "BUY", 0.01)

    assert order is not None
    assert order["orderId"] == "abc123"
    assert order["status"] == "FILLED"
    assert float(order["executedQty"]) == 0.01
    assert float(order["cummulativeQuoteQty"]) == 500.0
    assert order["symbol"] == "BTCUSDT"
    fake_live.create_order.assert_called_once_with("BTC/USDT", "market", "buy", 0.01)


def test_paper_mode_logs_live_parity_payload(monkeypatch):
    import binance_client as bc

    monkeypatch.setattr(bc.BinancePublicDataFetcher, "__init__", lambda self: None)
    monkeypatch.setattr(bc.BinanceClient, "_setup_live_client", lambda self: None)
    monkeypatch.setattr(bc.config, "PAPER_TRADING", True, raising=False)
    monkeypatch.setattr(bc.config, "PAPER_LIVE_PARITY_CHECK", True, raising=False)
    monkeypatch.setattr(bc.config, "USE_TESTNET", True, raising=False)
    monkeypatch.setattr(bc.config, "EXCHANGE_DATA_BACKEND", "binance", raising=False)

    client = bc.BinanceClient(use_websocket=False)
    monkeypatch.setattr(client, "get_current_price", lambda symbol: 50000.0)
    monkeypatch.setattr(client._paper, "place_market_order", lambda symbol, side, quantity: {"orderId": "paper-1"})

    log_messages = []

    def _capture(msg, *args, **kwargs):
        text = msg % args if args else msg
        log_messages.append(text)

    monkeypatch.setattr(bc.logger, "info", _capture)

    order = client.place_market_order("BTCUSDT", "BUY", 0.01)

    assert order is not None
    parity_logs = [m for m in log_messages if "[paper-live-parity]" in m]
    assert parity_logs, "expected paper/live parity log entry"

    payload_json = parity_logs[-1].split("[paper-live-parity]", 1)[1].strip()
    payload = json.loads(payload_json)
    assert payload["symbol"] == "BTC/USDT"
    assert payload["side"] == "buy"
    assert payload["type"] == "market"
    assert payload["amount"] == 0.01
    assert payload["paper_ref_price"] == 50000.0
    assert payload["paper_notional"] == 500.0


def test_place_oco_order_live_binance_uses_ccxt_implicit_endpoint(monkeypatch):
    import binance_client as bc

    monkeypatch.setattr(bc.BinancePublicDataFetcher, "__init__", lambda self: None)
    monkeypatch.setattr(bc.BinanceClient, "_setup_live_client", lambda self: None)
    monkeypatch.setattr(bc.config, "EXCHANGE_DATA_BACKEND", "binance", raising=False)
    monkeypatch.setattr(bc.config, "OCO_EXECUTION_MODE", "exchange", raising=False)

    client = bc.BinanceClient(use_websocket=False)
    client._live_mode = True
    client._exchange_id = "binance"

    captured = {}

    class _FakeLive:
        def private_post_order_oco(self, params):
            captured.update(params)
            return {"orderListId": 12345, "listStatusType": "EXEC_STARTED"}

    client._live_client = _FakeLive()

    out = client.place_oco_order("BTCUSDT", "SELL", 0.01, stop_price=49000.0, limit_price=48950.0, take_profit=51000.0)

    assert out is not None
    assert out["status"] == "OPEN"
    assert out["orderId"] == "12345"
    assert captured["symbol"] == "BTCUSDT"
    assert captured["side"] == "SELL"
    assert captured["stopPrice"] == "49000.00000000"
    assert captured["price"] == "51000.00000000"


def test_place_oco_order_falls_back_to_managed_on_failure(monkeypatch):
    import binance_client as bc

    monkeypatch.setattr(bc.BinancePublicDataFetcher, "__init__", lambda self: None)
    monkeypatch.setattr(bc.BinanceClient, "_setup_live_client", lambda self: None)
    monkeypatch.setattr(bc.config, "EXCHANGE_DATA_BACKEND", "binance", raising=False)
    monkeypatch.setattr(bc.config, "OCO_EXECUTION_MODE", "exchange", raising=False)

    client = bc.BinanceClient(use_websocket=False)
    client._live_mode = True
    client._exchange_id = "binance"

    class _FakeLive:
        def private_post_order_oco(self, params):
            raise RuntimeError("endpoint down")

    client._live_client = _FakeLive()

    out = client.place_oco_order("BTCUSDT", "SELL", 0.01, stop_price=49000.0, limit_price=48950.0, take_profit=51000.0)

    assert out is not None
    assert out["status"] == "MANAGED"
    assert out["mode"] == "managed_fallback"


def test_cancel_oco_order_uses_binance_order_list_endpoint(monkeypatch):
    import binance_client as bc

    monkeypatch.setattr(bc.BinancePublicDataFetcher, "__init__", lambda self: None)
    monkeypatch.setattr(bc.BinanceClient, "_setup_live_client", lambda self: None)
    monkeypatch.setattr(bc.config, "EXCHANGE_DATA_BACKEND", "binance", raising=False)

    client = bc.BinanceClient(use_websocket=False)
    client._live_mode = True
    client._exchange_id = "binance"

    captured = {}

    class _FakeLive:
        def private_delete_order_list(self, params):
            captured.update(params)
            return {"listOrderStatus": "ALL_DONE"}

    client._live_client = _FakeLive()

    ok = client.cancel_oco_order("BTCUSDT", {"orderId": "12345"})

    assert ok is True
    assert captured["symbol"] == "BTCUSDT"
    assert captured["orderListId"] == "12345"


def test_cancel_oco_order_falls_back_to_cancel_individual_orders(monkeypatch):
    import binance_client as bc

    monkeypatch.setattr(bc.BinancePublicDataFetcher, "__init__", lambda self: None)
    monkeypatch.setattr(bc.BinanceClient, "_setup_live_client", lambda self: None)
    monkeypatch.setattr(bc.config, "EXCHANGE_DATA_BACKEND", "binance", raising=False)

    client = bc.BinanceClient(use_websocket=False)
    client._live_mode = True
    client._exchange_id = "binance"

    class _FakeLive:
        pass

    client._live_client = _FakeLive()

    cancelled = []
    monkeypatch.setattr(client, "cancel_order", lambda symbol, order_id: cancelled.append((symbol, order_id)) or True)

    ok = client.cancel_oco_order(
        "BTCUSDT",
        {"raw": {"orders": [{"orderId": "A1"}, {"orderId": "B2"}]}}
    )

    assert ok is True
    assert cancelled == [("BTCUSDT", "A1"), ("BTCUSDT", "B2")]
