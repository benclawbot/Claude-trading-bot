import sqlite3
from datetime import datetime

# Use utils for timezone-aware datetime
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import utc_now_iso

DB_PATH = r"C:\Users\ThomasCHAFFANJON\Downloads\Claude-trading-bot-main\trading_bot.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 1. Get the open position
pos = cursor.execute("SELECT * FROM positions WHERE status='OPEN' LIMIT 1").fetchone()
if not pos:
    print("No open positions found")
    exit()

pos_id = pos["id"]
strategy = pos["strategy_name"]
side = pos["side"]
entry_price = float(pos["entry_price"])
quantity = float(pos["quantity"])
entry_time = pos["entry_time"]

# 2. Get current price (you'll need to specify this manually or fetch from API)
current_price = float(input(f"Enter current BTC price (entry was ${entry_price:,.2f}): $"))

# 3. Calculate P&L
if side == "LONG":
    pnl = (current_price - entry_price) * quantity
else:  # SHORT
    pnl = (entry_price - current_price) * quantity

pnl_pct = (pnl / (entry_price * quantity)) if (entry_price * quantity) != 0 else 0
fees = entry_price * quantity * 0.002  # Binance round-trip fee (0.1% × 2)

# 3. Record the trade
cursor.execute("""
    INSERT INTO trades
    (strategy_name, symbol, side, entry_price, exit_price, quantity, pnl, pnl_pct, fees_paid,
     entry_time, exit_time, duration_hours, exit_reason)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    strategy, "BTCUSDT", side, entry_price, current_price, quantity, pnl, pnl_pct, fees,
    entry_time, utc_now_iso(), 0, "MANUAL_CLOSE"
))

# 4. Close the position
cursor.execute("UPDATE positions SET status='CLOSED' WHERE id=?", (pos_id,))

conn.commit()
conn.close()

print(f"\n[OK] Position closed!")
print(f"  Strategy: {strategy}")
print(f"  Side: {side}")
print(f"  Entry: ${entry_price:,.2f} | Exit: ${current_price:,.2f}")
print(f"  Quantity: {quantity:.5f} BTC")
print(f"  P&L: ${pnl:+.2f} ({pnl_pct*100:+.2f}%)")
print(f"  Fees: ${fees:.2f}")
