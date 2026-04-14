#!/usr/bin/env python3
"""One-command bot reset:
- Start fresh (clear live-visible trade/position/perf state)
- Preserve learnings/settings (journal + config + strategy params)
- Set total portfolio allocation (default: 10,000)
- Optionally restart systemd user service
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


RESET_TABLES_CHILD_TO_PARENT: List[str] = [
    "trade_review_labels",
    "trades_outcome",
    "trades_execution",
    "trades_decision",
    "balance_history",
    "strategy_performance",
    "experiment_runs",
    "risk_events",
    "infra_incidents",
    "regime_performance_daily",
    "signal_quality_index",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_database(db_path: Path) -> Path:
    backup = db_path.with_name(f"{db_path.stem}.reset_preserve_learning_backup_{utc_stamp()}{db_path.suffix}")
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(backup))
    src.backup(dst)
    dst.close()
    src.close()
    return backup


def collect_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    return {
        "live_trades": conn.execute("SELECT COUNT(*) FROM trades WHERE is_backtest=0").fetchone()[0],
        "total_trades": conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
        "open_positions": conn.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0],
        "journal_entries": conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0],
        "balance_rows": conn.execute("SELECT COUNT(*) FROM balance_history").fetchone()[0],
        "active_strategies": conn.execute("SELECT COUNT(*) FROM strategies WHERE is_active=1").fetchone()[0],
    }


def set_env_initial_capital(env_path: Path, capital: float) -> None:
    lines = env_path.read_text().splitlines()
    key = "INITIAL_CAPITAL="
    new_line = f"INITIAL_CAPITAL={int(capital) if float(capital).is_integer() else capital}"

    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(key):
            lines[i] = new_line
            replaced = True
            break

    if not replaced:
        insert_at = None
        for i, line in enumerate(lines):
            if line.startswith("PAPER_TRADING="):
                insert_at = i + 1
                break
        if insert_at is None:
            lines.append(new_line)
        else:
            lines.insert(insert_at, new_line)

    env_path.write_text("\n".join(lines) + "\n")


def reset_db_state(conn: sqlite3.Connection, capital: float) -> Dict[str, float | int | str]:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN IMMEDIATE")

    # Fresh live history while preserving learnings linked to archived trades.
    conn.execute("UPDATE trades SET is_backtest=1 WHERE is_backtest=0")
    conn.execute("DELETE FROM positions")

    for table in RESET_TABLES_CHILD_TO_PARENT:
        conn.execute(f"DELETE FROM {table}")

    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO bot_metadata (key, value, updated_at)
        VALUES ('live_since', ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')
        """,
        (now_iso,),
    )

    n_active = conn.execute("SELECT COUNT(*) FROM strategies WHERE is_active=1").fetchone()[0]
    if n_active <= 0:
        conn.rollback()
        raise RuntimeError("No active strategies found; cannot allocate capital")

    share = float(capital) / float(n_active)
    conn.execute("UPDATE strategies SET capital=0 WHERE is_active=0")
    conn.execute("UPDATE strategies SET capital=? WHERE is_active=1", (share,))

    conn.commit()

    sum_active = conn.execute("SELECT ROUND(COALESCE(SUM(capital),0), 2) FROM strategies WHERE is_active=1").fetchone()[0]
    sum_all = conn.execute("SELECT ROUND(COALESCE(SUM(capital),0), 2) FROM strategies").fetchone()[0]
    live_since = conn.execute("SELECT value FROM bot_metadata WHERE key='live_since'").fetchone()[0]

    return {
        "active_strategies": n_active,
        "capital_per_active_strategy": round(share, 6),
        "sum_active_capital": float(sum_active or 0),
        "sum_all_capital": float(sum_all or 0),
        "live_since": str(live_since),
    }


def restart_service(service: str) -> str:
    subprocess.run(["systemctl", "--user", "restart", service], check=True)
    status = subprocess.run(
        ["systemctl", "--user", "--no-pager", "--plain", "status", service],
        check=True,
        capture_output=True,
        text=True,
    )
    first_lines = "\n".join(status.stdout.splitlines()[:8])
    return first_lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset bot state fresh while preserving learnings/settings")
    parser.add_argument("--capital", type=float, default=10000.0, help="Total portfolio capital allocation")
    parser.add_argument("--db", default="trading_bot.db", help="Path to sqlite DB")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--service", default="trading-bot.service", help="systemd user service name")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart service")
    parser.add_argument("--dry-run", action="store_true", help="Show current state only; no writes")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    db_path = (project_root / args.db).resolve()
    env_path = (project_root / args.env).resolve()

    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    if not env_path.exists():
        raise FileNotFoundError(f".env not found: {env_path}")
    if args.capital <= 0:
        raise ValueError("--capital must be > 0")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    before = collect_counts(conn)

    if args.dry_run:
        print(json.dumps({
            "mode": "dry-run",
            "project_root": str(project_root),
            "db": str(db_path),
            "env": str(env_path),
            "capital_target": args.capital,
            "before": before,
        }, indent=2))
        conn.close()
        return

    backup_path = backup_database(db_path)
    after_reset = reset_db_state(conn, args.capital)
    after_counts = collect_counts(conn)
    conn.close()

    set_env_initial_capital(env_path, args.capital)

    service_status_head = None
    if not args.no_restart:
        service_status_head = restart_service(args.service)

    print(json.dumps({
        "mode": "applied",
        "backup": str(backup_path),
        "capital_target": args.capital,
        "before": before,
        "after": after_counts,
        "allocation": after_reset,
        "service": {
            "name": args.service,
            "restarted": (not args.no_restart),
            "status_head": service_status_head,
        },
    }, indent=2))


if __name__ == "__main__":
    main()
