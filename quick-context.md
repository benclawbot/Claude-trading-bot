# Claude Trading Bot — Quick Context

## Status
- **Project Status:** ✅ COMPLETE — initial plan done, live on mainnet
- **Current Phase:** Live — paper trading (mainnet, real data)
- **Stack:** Python | python-binance | Dash | SQLite

## Phase Progress

| Phase | Status |
|-------|--------|
| Phase 1 — Framework | Complete |
| Phase 2 — Strategies | Complete |
| Phase 3 — Live Paper Trading | Complete |
| Strategy Tuning | Complete |

## Active Tasks
_(none — initial plan complete)_

## Bot Status (Live)
- Mode: PAPER TRADING (real Binance market data)
- WebSocket: connected to wss://stream.binance.com:9443/ws/btcusdt@ticker
- Balance: $10,000 (paper)
- Bot PID: running (check `ps aux | grep main.py`)
- Dashboard: http://localhost:8050
- Log: Projects/Claude-trading-bot/bot.log

## Enhancement Backlog
- [ ] Monitor strategies — tune ATR params based on live paper performance
- [ ] Add more strategy parameters from learning engine

## Blockers
- None

## Key References
- `code/main.py` — Entry point
- `code/strategies/` — All strategy implementations
- `code/config.py` — Thresholds and strategy params
- `ops/status-dashboard.html` — Team status dashboard

## Last Update
2026-03-26
