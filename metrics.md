# Trading Bot Metrics

> Test results as of 2026-03-25

---

## Test Coverage

| Type | Count | Coverage | Target | Status |
|------|-------|----------|--------|--------|
| Unit tests | 198 | — | 80% | PARTIAL |
| Integration tests | 0 | 0% | 80% | MISSING |
| E2E tests | 5 | — | All critical flows | PARTIAL |
| **Total** | **203** | **~97% pass rate** | **80%** | **PARTIAL** |

**Test Results:** 198 passed, 5 failed (97.5% pass rate)

**Failing Tests (real bugs to fix):**
- `test_dashboard_has_layout` — dashboard.app missing `layout` attribute
- `test_export_dashboard_imports` — wrong path `/home/user/btc_trading_bot/`
- `test_train_model_with_samples` — mock type error in ML test
- `test_train_model_insufficient_samples` — `MLAdaptiveStrategy` missing `_train_model` method
- `test_predict_outcome_no_model` — `MLAdaptiveStrategy` missing `_predict_outcome` method

---

## Active Strategies

| Strategy | CAGR | WR | PF | Status |
|----------|------|----|----|--------|
| Regime_RiskOnOff | 7.1% | 41.3% | 1.50 | ACTIVE |
| Residual_MeanRev | 5.1% | 39.3% | 1.25 | ACTIVE |
| Donchian_Breakout | 8.3% | 35.7% | 2.00 | ACTIVE |
| RSI_Bollinger | -0.3% | 33.7% | 1.07 | INACTIVE |
| Breakout | -0.5% | 0.0% | 0.00 | INACTIVE |
| MACD_Momentum | -4.8% | 36.0% | 1.00 | INACTIVE |
| EMA_Crossover | -2.5% | 37.7% | 1.07 | INACTIVE |

---

## Phase Progress

| Phase | Start | End | Duration | Status |
|-------|-------|-----|----------|--------|
| Phase 1: Bot Framework | 2026-03-25 | 2026-03-25 | ~1h | Complete |
| Phase 2: Strategies + Backtesting | 2026-03-25 | 2026-03-25 | ~1h | Complete |
| Phase 3: Live Paper Trading | 2026-03-25 | ONGOING | — | IN PROGRESS |
| Phase 4: Strategy Tuning | BACKLOG | — | — | PENDING |
| Phase 5: Real Trading | BACKLOG | — | — | PENDING |

---

## Deliverable Quality

| Deliverable | Agent | Quality Gate | Status | Issues |
|-------------|-------|--------------|--------|--------|
| Bot framework | Priya | Connects to Binance, paper mode works | PASS | None |
| 11 strategies wired | Orbit | Backtest validates, 3+ activate | PASS | 8 strategies fail CAGR threshold |
| Telegram alerts | Orbit | Fires on trade open/close | PASS | None |
| Dashboard | Jonas | Loads at localhost:8050 | PASS | None |
| Test suite | Quinn | 198/203 tests pass | PARTIAL | 5 failing tests |
