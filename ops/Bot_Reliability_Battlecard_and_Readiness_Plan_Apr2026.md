# Bot Reliability Battlecard + System Readiness Plan

Date: 2026-04-10 20:18
Author: Hermes

## Executive Decision
Do **not** launch paid services until internal reliability gates are met.

## Reliability Gates
- 14 days zero SEV-1 incidents
- False-positive watchdog rate < 2% over 200+ checks
- MTTD < 60s, MTTR < 5m for injected failures
- Dual readiness checks (lsof + HTTP)
- CI quality: unit >=99%, critical integration tests passing
- Runbook complete with singleton/lockfile and one-command recovery

## Competitor Snapshot
- 3Commas / Cryptohopper / Coinrule / Bitsgap / Altrady: strong execution automation, weaker reliability-ops specialization
- TraderSync / TradeZella: strong journals and post-trade analytics, not runtime guardrail control plane
- Freqtrade OSS: strong free substitute for technical users; high DIY ops burden remains

## SWOT
### Strengths
- Existing drawdown/risk event logic
- Real incident data and ops experience
- Existing alerting paths

### Weaknesses
- Watchdog brittleness and startup race conditions
- Incomplete launch-grade integration testing

### Opportunities
- Reliability-first wedge largely underserved
- Build proprietary incident benchmark moat

### Threats
- Incumbent feature copy
- DIY/open-source substitution
- Trust/reputation damage from noisy alerts

## 30-Day System-First Plan
1. Reliability hardening
2. Integration and failure-injection testing
3. Observability and alert quality scoring
4. Go/No-Go audit against hard gates

## Launch Criteria
- GO only when all gates pass.
