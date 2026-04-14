# TradingBot Autoresearch Program (Karpathy-style)

Goal: continuously optimize BOTH
1) guardrails (risk / activation thresholds), and
2) strategy parameters

for consistency + profit %, with throughput target >= 20 trades/day,
while challenging backtest winners against recent live metrics.

## Rules
- Do not touch database schema.
- Keep all changes in either:
  - `ops/autoresearch/best_config.json` (promoted winner)
  - `ops/autoresearch/results.tsv` (experiment log)
- Promote a candidate only when composite score improves.

## Core command

```bash
python autoresearch_trading.py --cycles 80 --target-trades-per-day 20 --apply
```

## Runtime activation

```bash
export AUTORESEARCH_USE_OVERRIDES=true
python main.py
```

Optional custom winner file:

```bash
export AUTORESEARCH_OVERRIDES_FILE=/abs/path/to/best_config.json
```

## Success Criteria
- Higher consistency score than baseline
- Higher profit % than baseline OR materially improved consistency with similar profit
- Throughput at or above target (20+ trades/day preferred)
- No critical config validation issues
