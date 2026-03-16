# Portfolio Manager Debug Guide

## Quick Diagnostics

### Checking Capital Consistency

Run this Python command to verify capital calculations:

```python
from portfolio_manager import PortfolioManager
from binance_client import BinanceClient
from strategies import EMA5MomentumStrategy

client = BinanceClient()
price = client.get_current_price("BTCUSDT")
strat = EMA5MomentumStrategy()
pm = PortfolioManager(client, [strat])
bal = pm.total_balance(price)

# Print breakdown
for name, info in bal['breakdown'].items():
    cap = info['capital']
    free = info['free_capital']
    committed = info['committed_notional']
    unrealized = info['unrealized_pnl']

    print(f"\nStrategy: {name}")
    print(f"  Total Capital:    ${cap:,.2f}")
    print(f"  Free Capital:     ${free:,.2f}")
    print(f"  Committed:        ${committed:,.2f}")
    print(f"  Unrealized P&L:   ${unrealized:,.2f}")

    # Verify consistency
    calculated = free + committed + unrealized
    print(f"  Consistency Check: ${cap:,.2f} == ${calculated:,.2f} ?", end=" ")
    print("✓" if abs(cap - calculated) < 0.01 else "✗")
```

### Common Issues and Solutions

#### Issue: Total Capital is less than initial capital despite no trades

**Possible Causes:**
1. Positions are open with unrealized losses
2. Fees haven't been properly accounted for

**Debug:**
```sql
-- Check open positions
SELECT * FROM positions WHERE status='OPEN';

-- Check if they have losses
SELECT id, entry_price, quantity, 'LONG' as side FROM positions WHERE status='OPEN';
-- Compare entry_price to current price

-- Check realized P&L from closed trades
SELECT SUM(pnl) as total_realized_pnl FROM trades;
```

#### Issue: Total Capital shows more than expected with no winning trades

**Possible Causes:**
1. Unrealized gains on open positions
2. Incorrect price data

**Debug:**
```bash
# Verify current price
curl -s "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT" | jq '.price'

# In Python:
from binance_client import BinanceClient
client = BinanceClient()
print(client.get_current_price("BTCUSDT"))
```

#### Issue: Free Capital is negative

**Possible Causes:**
1. Multiple losing trades that exceeded the allocated capital
2. Position sizing bug allowed positions larger than capital

**Debug:**
```python
# Check all positions and their P&L impact
import database as db

for strat_name in db.get_active_strategies():
    positions = db.get_open_positions(strat_name)
    trades = db.get_trades(strat_name)

    print(f"\n{strat_name}:")
    print(f"  Open positions: {len(positions)}")
    print(f"  Total trades: {len(trades)}")

    realized_pnl = sum(t['pnl'] for t in trades)
    print(f"  Realized P&L: ${realized_pnl:,.2f}")

    # Total committed
    committed = sum(float(p['entry_price']) * float(p['quantity'])
                   for p in positions)
    print(f"  Committed notional: ${committed:,.2f}")
```

#### Issue: Dashboard shows different total than expected

**Possible Causes:**
1. Dashboard reading stale database values
2. Live price different from when data was last updated
3. Browser cache showing old values

**Solutions:**
1. Refresh the dashboard page (Ctrl+R or Cmd+R)
2. Check that current price is fetched correctly:
   ```python
   from binance_client import BinanceClient
   client = BinanceClient()
   price = client.get_current_price("BTCUSDT")
   print(f"Current price: ${price:,.2f}")
   ```
3. Check database update time:
   ```python
   import database as db
   latest_bal = db.get_latest_balance()
   print(f"Last update: {latest_bal['recorded_at']}")
   ```

## Capital Tracking Flow

### State Transitions

```
STARTUP
  ├─ Load strategies
  ├─ Call PortfolioManager.__init__()
  │  └─ _allocate_capital() with default price
  │     └─ Compute: total_cap = share + realized_pnl (unrealized=0, no positions yet)
  │     └─ Store in DB: strategy.capital = free_capital = share
  ├─ Call total_balance(current_price)
  │  └─ Read DB: free_capital = share
  │  └─ Read open positions: none
  │  └─ Compute unrealized: 0
  │  └─ Result: capital = share (correct!)
  └─ Store balance snapshot in DB

POSITION OPENS
  ├─ process_signal() called with price
  ├─ Place market order
  ├─ Update self._capital -= notional
  ├─ Store in DB: strategy.capital = self._capital (now reduced)
  └─ Open position record created in DB

PRICE MOVES (Every 60 seconds)
  ├─ total_balance(current_price) called
  ├─ Read DB: free_capital (reduced)
  ├─ Read open positions: entry_price, quantity
  ├─ Compute unrealized from: current_price - entry_price
  ├─ Result: capital = free_capital + committed + unrealized
  └─ Store balance snapshot

POSITION CLOSES
  ├─ check_open_positions() hits SL/TP
  ├─ _close_position() called
  ├─ Calculate P&L
  ├─ Record trade in DB
  ├─ Update self._capital += notional + P&L
  ├─ Store in DB: strategy.capital = self._capital (now increased by P&L)
  ├─ Close position record
  └─ Next total_balance() call:
     ├─ Read DB: free_capital (increased by P&L)
     ├─ Read open positions: fewer now
     └─ Result: reflects the P&L!
```

## Key Values to Monitor

### Dashboard Metrics

Every 60 seconds, check:
1. **Total Balance** - Should match: free_capital + unrealized_pnl + committed
2. **Free Capital** - Should be: initial - locked_in_positions
3. **Unrealized P&L** - Should match: (current_price - entry) * quantity for each position
4. **Realized P&L** - Should match: sum of all closed trade P&L

### Database Values

Key queries:
```sql
-- Current free capital per strategy
SELECT name, capital FROM strategies;

-- Open positions
SELECT strategy_name, side, entry_price, quantity, stop_loss, take_profit
FROM positions WHERE status='OPEN';

-- Recent closed trades
SELECT strategy_name, side, pnl, pnl_pct, exit_reason
FROM trades ORDER BY closed_at DESC LIMIT 10;

-- Balance history
SELECT recorded_at, total_balance, realized_pnl, unrealized_pnl
FROM balance_history ORDER BY recorded_at DESC LIMIT 5;
```

## Testing Specific Scenarios

### Test 1: Verify capital updates on trade close

```python
import database as db
from datetime import datetime

# Before closing trade
bal_before = db.get_latest_balance()
print(f"Before: {bal_before['total_balance']}")

# Close a position manually
# ... (use close_position.py or API)

# After closing trade
bal_after = db.get_latest_balance()
print(f"After: {bal_after['total_balance']}")

# Difference should equal the P&L
diff = bal_after['total_balance'] - bal_before['total_balance']
print(f"Difference (should be P&L): ${diff:,.2f}")
```

### Test 2: Verify unrealized P&L calculation

```python
import database as db
from binance_client import BinanceClient

client = BinanceClient()
price = client.get_current_price("BTCUSDT")

positions = db.get_open_positions()
total_unrealized = 0.0

for pos in positions:
    ep = float(pos['entry_price'])
    qty = float(pos['quantity'])
    side = pos['side']

    if side == 'LONG':
        unrealized = (price - ep) * qty
    else:
        unrealized = (ep - price) * qty

    print(f"{pos['strategy_name']}: ${unrealized:+.2f}")
    total_unrealized += unrealized

print(f"Total unrealized: ${total_unrealized:+.2f}")

# Compare with dashboard
latest_bal = db.get_latest_balance()
db_unrealized = latest_bal['unrealized_pnl']
print(f"Database says: ${db_unrealized:+.2f}")

if abs(total_unrealized - db_unrealized) < 0.01:
    print("✓ Unrealized P&L calculation matches!")
else:
    print(f"✗ Mismatch: ${total_unrealized - db_unrealized:+.2f}")
```

### Test 3: Verify capital consistency

```python
import database as db
from binance_client import BinanceClient

client = BinanceClient()
price = client.get_current_price("BTCUSDT")

strategies = db.get_active_strategies()

for strat in strategies:
    name = strat['name']
    free_cap = strat['capital']  # From DB

    # Calculate committed and unrealized
    positions = db.get_open_positions(name)
    committed = sum(float(p['entry_price']) * float(p['quantity'])
                   for p in positions)

    unrealized = 0.0
    for p in positions:
        ep = float(p['entry_price'])
        qty = float(p['quantity'])
        if p['side'] == 'LONG':
            unrealized += (price - ep) * qty
        else:
            unrealized += (ep - price) * qty

    # Get realized P&L
    stats = db.get_trade_stats(name)
    realized = float(stats.get('total_pnl') or 0)

    # Compute true total
    true_total = free_cap + committed + unrealized

    print(f"\n{name}:")
    print(f"  Free Capital: ${free_cap:,.2f}")
    print(f"  Committed: ${committed:,.2f}")
    print(f"  Realized P&L: ${realized:,.2f}")
    print(f"  Unrealized P&L: ${unrealized:,.2f}")
    print(f"  True Total: ${true_total:,.2f}")
    print(f"  Expected: ~${10000/7 + realized + unrealized:,.2f}")
```

## Performance Notes

- `total_balance()` is called every 60 seconds and immediately after trades
- Dashboard fetches current price on every refresh (adjustable in config)
- Balance history is recorded every 60 seconds (check `balance_history` table size)
- No cache invalidation issues - values are computed live from DB and current price

## When to Investigate Further

Contact support or check logs if:
1. Total Balance is significantly different (>$1) from expected value
2. Free Capital remains negative for more than a few minutes
3. Unrealized P&L doesn't update within 60 seconds of price movement
4. Total Capital decreases without closing trades or opening positions
5. Dashboard shows "No active strategies" but strategies are enabled in DB

