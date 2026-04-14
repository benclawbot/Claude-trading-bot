import importlib


def test_to_ccxt_symbol_converts_compact_pairs():
    bc = importlib.import_module("binance_client")
    assert bc.to_ccxt_symbol("BTCUSDT") == "BTC/USDT"
    assert bc.to_ccxt_symbol("ETHUSD") == "ETH/USD"


def test_to_ccxt_symbol_keeps_slash_pairs():
    bc = importlib.import_module("binance_client")
    assert bc.to_ccxt_symbol("BTC/USDT") == "BTC/USDT"


def test_binance_client_uses_ccxt_data_backend_when_configured(monkeypatch):
    bc = importlib.import_module("binance_client")

    monkeypatch.setattr(bc.config, "EXCHANGE_DATA_BACKEND", "ccxt", raising=False)
    monkeypatch.setattr(bc, "CCXT_AVAILABLE", True)

    created = {"ccxt": False}

    def fake_ccxt_init(self, exchange_id="binance"):
        created["ccxt"] = True
        self._exchange_id = exchange_id
        self._price_cache = {}
        self._price_cache_ts = {}

    monkeypatch.setattr(bc.CCXTPublicDataFetcher, "__init__", fake_ccxt_init)
    monkeypatch.setattr(bc.BinanceClient, "_setup_live_client", lambda self: None)

    client = bc.BinanceClient(use_websocket=False)

    assert created["ccxt"] is True
    assert isinstance(client._data, bc.CCXTPublicDataFetcher)


def test_ccxt_price_sanity_guard_reuses_recent_cache_on_large_jump(monkeypatch):
    bc = importlib.import_module("binance_client")

    monkeypatch.setattr(bc.config, "PRICE_SANITY_MAX_JUMP_PCT", 0.05, raising=False)
    monkeypatch.setattr(bc.config, "PRICE_CACHE_MAX_STALE_SEC", 900, raising=False)

    class _FakeExchange:
        def __init__(self):
            self.calls = 0

        def fetch_ticker(self, market):
            self.calls += 1
            # First is baseline; second is implausible +100% jump.
            if self.calls == 1:
                return {"last": 100.0}
            return {"last": 200.0}

    f = bc.CCXTPublicDataFetcher.__new__(bc.CCXTPublicDataFetcher)
    f._exchange_id = "binance"
    f._exchange = _FakeExchange()
    f._price_cache = {}
    f._price_cache_ts = {}

    first = f.get_current_price("BTCUSDT")
    second = f.get_current_price("BTCUSDT")

    assert first == 100.0
    # Should reject 100% jump and keep recent cached value.
    assert second == 100.0
