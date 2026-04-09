#!/usr/bin/env python3
"""
Watch script – notifies via Telegram when the first trade is detected.
Run via cron every 5 minutes.
"""

import json, os, sqlite3, subprocess, sys, time
from pathlib import Path

BOT_DIR   = Path(__file__).parent.resolve()
DB_PATH   = BOT_DIR / "trading_bot.db"
STATE_FILE = BOT_DIR / ".watch_state.json"

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_trade_id": 0, "last_position_id": 0, "notified": False}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state))

def send_telegram(message: str):
    """Send via openclaw CLI."""
    cmd = [
        "openclaw", "send",
        "--message", message,
        "--channel", "telegram"
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        print(f"[notify] Telegram sent: {message[:80]}")
    except Exception as e:
        print(f"[notify] Telegram failed: {e}", file=sys.stderr)

def build_message(trade, is_position=False):
    side  = trade["side"]
    strat = trade["strategy_name"]
    if is_position:
        entry = float(trade["entry_price"])
        sl    = float(trade["stop_loss"]) if trade["stop_loss"] else "N/A"
        tp    = float(trade["take_profit"]) if trade["take_profit"] else "N/A"
        conf  = float(trade["ml_confidence"]) if trade["ml_confidence"] else 0
        return (
            f"📊 **Trade Opened**\n"
            f"Strategy: `{strat}`\n"
            f"Side: **{side}**\n"
            f"Entry: ${entry:,.2f}\n"
            f"SL: ${sl:,.2f} | TP: ${tp:,.2f}\n"
            f"ML confidence: {conf:.0%}"
        )
    else:
        pnl   = float(trade["pnl"])
        pnl_pct = float(trade["pnl_pct"]) * 100
        exit_reason = trade.get("exit_reason", "unknown")
        return (
            f"✅ **Trade Closed**\n"
            f"Strategy: `{strat}`\n"
            f"Side: **{side}**\n"
            f"PnL: ${pnl:+.2f} ({pnl_pct:+.2f}%)\n"
            f"Exit reason: {exit_reason}"
        )

def check():
    if not DB_PATH.exists():
        return

    state = load_state()
    if state["notified"]:
        return  # already alerted, done

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check for new CLOSED trades
    cur.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1")
    latest_trade = cur.fetchone()

    # Check for open positions
    cur.execute("SELECT * FROM positions WHERE status='OPEN' ORDER BY id DESC LIMIT 1")
    open_pos = cur.fetchone()

    conn.close()

    messages = []

    if latest_trade and latest_trade["id"] > state["last_trade_id"]:
        state["last_trade_id"] = latest_trade["id"]
        messages.append(build_message(dict(latest_trade), is_position=False))

    if open_pos and open_pos["id"] > state["last_position_id"]:
        state["last_position_id"] = open_pos["id"]
        messages.append(build_message(dict(open_pos), is_position=True))

    if messages:
        full = "\n\n".join(messages)
        send_telegram(full)
        state["notified"] = True

    save_state(state)

if __name__ == "__main__":
    check()
