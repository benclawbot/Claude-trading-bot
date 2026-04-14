"""SQLite database layer for the trading bot.

Changes:
  - Added utc_now and utc_now_iso utility for timezone-aware datetime handling
  - Replaced deprecated datetime.utcnow() calls
  - Added is_backtest column to trades table to distinguish backtest from live trades
  - Added live_since tracking to know when real trading started
  - Added clear_old_data function to reset database
"""

import sqlite3
import json
import threading
import statistics
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

import config
from utils import utc_now, utc_now_iso

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """Return a per-thread SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS strategies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            is_active   INTEGER DEFAULT 0,
            capital     REAL DEFAULT 0,
            params      TEXT DEFAULT '{}',
            backtest_cagr REAL DEFAULT 0,
            backtest_win_rate REAL DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name   TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            side            TEXT NOT NULL,       -- LONG or SHORT
            entry_price     REAL NOT NULL,
            quantity        REAL NOT NULL,
            stop_loss       REAL,
            take_profit     REAL,
            entry_time      TEXT NOT NULL,
            order_id        TEXT,
            status          TEXT DEFAULT 'OPEN', -- OPEN, CLOSED
            ml_confidence   REAL DEFAULT 0.5,
            metadata        TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name   TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            side            TEXT NOT NULL,
            entry_price     REAL NOT NULL,
            exit_price      REAL NOT NULL,
            quantity        REAL NOT NULL,
            pnl             REAL NOT NULL,
            pnl_pct         REAL NOT NULL,
            fees_paid       REAL NOT NULL,
            entry_time      TEXT NOT NULL,
            exit_time       TEXT NOT NULL,
            duration_hours  REAL NOT NULL,
            exit_reason     TEXT,               -- TAKE_PROFIT, STOP_LOSS, SIGNAL, MANUAL
            entry_features  TEXT DEFAULT '{}',  -- JSON of indicator values at entry
            closed_at       TEXT DEFAULT (datetime('now')),
            is_backtest    INTEGER DEFAULT 0   -- 0=live trade, 1=backtest (not shown in history)
        );

        CREATE TABLE IF NOT EXISTS journal_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        INTEGER NOT NULL UNIQUE REFERENCES trades(id),
            strategy_name   TEXT NOT NULL,
            entry_price     REAL,
            exit_price      REAL,
            pnl             REAL,
            pnl_pct         REAL,
            side            TEXT,
            duration_hours  REAL,
            market_regime   TEXT,
            setup_summary   TEXT,
            outcome_analysis TEXT,
            reflection      TEXT,
            lessons         TEXT DEFAULT '[]',
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS balance_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            total_balance   REAL NOT NULL,
            realized_pnl    REAL NOT NULL,
            unrealized_pnl  REAL NOT NULL,
            strategy_breakdown TEXT DEFAULT '{}',
            recorded_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ml_features (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        INTEGER REFERENCES trades(id),
            strategy_name   TEXT NOT NULL,
            features        TEXT NOT NULL,       -- JSON array
            outcome         REAL NOT NULL,       -- 1 = win, 0 = loss
            pnl_pct         REAL NOT NULL,
            recorded_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS strategy_performance (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name   TEXT NOT NULL,
            date            TEXT NOT NULL,
            capital         REAL NOT NULL,
            daily_pnl       REAL DEFAULT 0,
            cumulative_pnl  REAL DEFAULT 0,
            win_rate        REAL DEFAULT 0,
            total_trades    INTEGER DEFAULT 0,
            open_positions  INTEGER DEFAULT 0,
            UNIQUE(strategy_name, date)
        );

        CREATE TABLE IF NOT EXISTS experiment_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id TEXT NOT NULL,
            week_id TEXT NOT NULL,
            baseline_version TEXT NOT NULL,
            weekly_pnl_pct REAL NOT NULL,
            weekly_drawdown_pct REAL NOT NULL,
            daily_pnl_std REAL NOT NULL,
            max_daily_loss_pct REAL NOT NULL,
            losing_streak_max INTEGER NOT NULL,
            profit_factor REAL NOT NULL,
            win_rate REAL NOT NULL,
            avg_r REAL NOT NULL,
            trade_count INTEGER NOT NULL,
            score_consistency REAL NOT NULL,
            score_drawdown REAL NOT NULL,
            score_profit REAL NOT NULL,
            score_quality REAL NOT NULL,
            score_participation REAL NOT NULL,
            score_total REAL NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('PROMOTE','KEEP_TESTING','DEMOTE','KILL','INSUFFICIENT_DATA')),
            decision_reason TEXT NOT NULL,
            reviewed_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(experiment_id, week_id)
        );

        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_id TEXT NOT NULL,
            trigger_level_pct REAL NOT NULL,
            portfolio_dd_pct REAL NOT NULL,
            size_multiplier_applied REAL NOT NULL,
            note TEXT DEFAULT '',
            triggered_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trades_decision (
            trade_id TEXT PRIMARY KEY,
            ts_decision TEXT NOT NULL DEFAULT (datetime('now')),
            symbol TEXT NOT NULL,
            timeframe TEXT,
            strategy_id TEXT,
            regime_id TEXT,
            side TEXT NOT NULL,
            confidence_raw REAL,
            confidence_calibrated REAL,
            expected_horizon_min INTEGER,
            expected_move_bps REAL,
            risk_budget_bps REAL,
            stop_loss_bps REAL,
            take_profit_bps REAL,
            feature_snapshot_json TEXT DEFAULT '{}',
            model_version TEXT,
            policy_version TEXT,
            decision_reason_short TEXT,
            paper_or_live TEXT DEFAULT 'live'
        );

        CREATE TABLE IF NOT EXISTS trades_execution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT NOT NULL REFERENCES trades_decision(trade_id),
            ts_order_sent TEXT DEFAULT (datetime('now')),
            ts_first_fill TEXT,
            ts_full_fill TEXT,
            exchange TEXT,
            order_type TEXT,
            order_qty REAL,
            avg_fill_price REAL,
            mid_at_send REAL,
            spread_bps_at_send REAL,
            slippage_bps REAL,
            fees_bps REAL,
            latency_ms_signal_to_send INTEGER,
            latency_ms_send_to_fill INTEGER,
            execution_quality_score REAL
        );

        CREATE TABLE IF NOT EXISTS trades_outcome (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT NOT NULL REFERENCES trades_decision(trade_id),
            horizon_min INTEGER NOT NULL,
            ts_horizon TEXT DEFAULT (datetime('now')),
            pnl_bps_gross REAL,
            pnl_bps_net REAL,
            mae_bps REAL,
            mfe_bps REAL,
            stopped_out INTEGER DEFAULT 0,
            tp_hit INTEGER DEFAULT 0,
            early_exit INTEGER DEFAULT 0,
            outcome_label TEXT,
            quality_label TEXT,
            UNIQUE(trade_id, horizon_min)
        );

        CREATE TABLE IF NOT EXISTS trade_review_labels (
            review_id TEXT PRIMARY KEY,
            trade_id TEXT NOT NULL REFERENCES trades_decision(trade_id),
            ts_review TEXT DEFAULT (datetime('now')),
            reviewer TEXT,
            should_take_again INTEGER,
            mistake_type TEXT,
            confidence_error_bucket TEXT,
            notes TEXT,
            final_label TEXT
        );

        CREATE TABLE IF NOT EXISTS infra_incidents (
            incident_id TEXT PRIMARY KEY,
            ts_start TEXT DEFAULT (datetime('now')),
            ts_end TEXT,
            severity TEXT,
            component TEXT,
            incident_signature TEXT,
            remediate_action_taken TEXT,
            trade_ids_affected_json TEXT DEFAULT '[]',
            impact_tag TEXT
        );

        CREATE TABLE IF NOT EXISTS regime_performance_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regime_id TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            day TEXT NOT NULL,
            trades INTEGER NOT NULL,
            win_rate REAL,
            net_pnl_bps REAL,
            avg_mae REAL,
            avg_mfe REAL,
            calibration_error REAL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(regime_id, strategy_id, day)
        );

        CREATE TABLE IF NOT EXISTS signal_quality_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            regime_id TEXT NOT NULL,
            week TEXT NOT NULL,
            true_shift_precision REAL,
            fakeout_rate REAL,
            early_entry_score REAL,
            execution_penalty_score REAL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(strategy_id, regime_id, week)
        );

        CREATE INDEX IF NOT EXISTS idx_experiment_runs_week_decision
            ON experiment_runs(week_id, decision);

        CREATE INDEX IF NOT EXISTS idx_risk_events_week_time
            ON risk_events(week_id, triggered_at);

        CREATE INDEX IF NOT EXISTS idx_trades_decision_ts
            ON trades_decision(ts_decision);

        CREATE INDEX IF NOT EXISTS idx_trades_execution_trade_id
            ON trades_execution(trade_id);

        CREATE INDEX IF NOT EXISTS idx_trades_outcome_trade_horizon
            ON trades_outcome(trade_id, horizon_min);

        CREATE INDEX IF NOT EXISTS idx_trade_review_labels_trade_id
            ON trade_review_labels(trade_id);

        CREATE INDEX IF NOT EXISTS idx_infra_incidents_ts_start
            ON infra_incidents(ts_start);

        CREATE INDEX IF NOT EXISTS idx_regime_performance_daily_lookup
            ON regime_performance_daily(day, strategy_id, regime_id);

        CREATE INDEX IF NOT EXISTS idx_signal_quality_index_lookup
            ON signal_quality_index(week, strategy_id, regime_id);
    """)
    conn.commit()
    
    # ─── Database migrations ──────────────────────────────────────────────────
    # Add is_backtest column if it doesn't exist (for existing databases)
    try:
        conn.execute("SELECT is_backtest FROM trades LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE trades ADD COLUMN is_backtest INTEGER DEFAULT 0")
        conn.commit()
    
    # Add live_since table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    # ── Migration: add UNIQUE on trade_id in journal_entries ──────────────────
    # Also migrate existing lessons from pipe-delimited TEXT → JSON array
    _migrate_journal_lessons(conn)


def _migrate_journal_lessons(conn: sqlite3.Connection):
    """
    1) Add UNIQUE constraint on trade_id (idempotent — skips if already present).
    2) Migrate existing lessons rows from pipe-delimited TEXT → JSON array list.
    3) Delete duplicate journal rows so each trade_id is unique.
    """
    try:
        # Step 1: enforce uniqueness by keeping the oldest row per trade_id
        # and deleting newer duplicates (created by the replay bug)
        conn.execute("""
            DELETE FROM journal_entries
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM journal_entries
                GROUP BY trade_id
            )
        """)
        conn.commit()

        # Step 2: add UNIQUE on trade_id if not already there
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_trade_id ON journal_entries(trade_id)"
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass  # already exists

        # Step 3: migrate lessons from pipe-delimited text → JSON list
        rows = conn.execute(
            "SELECT id, lessons FROM journal_entries WHERE lessons IS NOT NULL AND lessons NOT LIKE '[%'"
        ).fetchall()
        for row in rows:
            raw = row["lessons"]
            parts = [p.strip() for p in raw.split(" | ") if p.strip()]
            conn.execute(
                "UPDATE journal_entries SET lessons=? WHERE id=?",
                (json.dumps(parts, ensure_ascii=False), row["id"])
            )
        conn.commit()
    except Exception:
        conn.rollback()


def clear_old_data():
    """
    Clear all trading data to start fresh.
    Use this when you want to reset the bot and start new.
    """
    conn = get_conn()
    
    # Delete all trades (keep strategies)
    conn.execute("DELETE FROM trades")
    
    # Delete all positions
    conn.execute("DELETE FROM positions")
    
    # Delete all journal entries
    conn.execute("DELETE FROM journal_entries")
    
    # Delete all balance history
    conn.execute("DELETE FROM balance_history")
    
    # Delete all ML features
    conn.execute("DELETE FROM ml_features")
    
    # Delete all performance history
    conn.execute("DELETE FROM strategy_performance")
    
    # Update live_since to now
    conn.execute("""
        INSERT OR REPLACE INTO bot_metadata (key, value, updated_at)
        VALUES ('live_since', ?, datetime('now'))
    """, (utc_now_iso(),))
    
    conn.commit()


def get_metadata(key: str) -> Optional[str]:
    """Read a metadata value by key."""
    row = get_conn().execute(
        "SELECT value FROM bot_metadata WHERE key=?",
        (key,)
    ).fetchone()
    return row[0] if row else None


def set_metadata(key: str, value: str):
    """Upsert a metadata key/value pair."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO bot_metadata (key, value, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')
        """,
        (key, value),
    )
    conn.commit()


def get_live_since() -> Optional[str]:
    """Get the date when live trading started."""
    return get_metadata('live_since')


def set_live_since():
    """Set the live trading start date if not already set."""
    existing = get_live_since()
    if not existing:
        set_metadata('live_since', utc_now_iso())

def upsert_strategy(name: str, capital: float, params: dict,
                    backtest_cagr: float = 0.0, backtest_win_rate: float = 0.0,
                    is_active: bool = False):
    conn = get_conn()
    conn.execute("""
        INSERT INTO strategies (name, capital, params, backtest_cagr, backtest_win_rate, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            capital = excluded.capital,
            params  = excluded.params,
            backtest_cagr = excluded.backtest_cagr,
            backtest_win_rate = excluded.backtest_win_rate,
            is_active = excluded.is_active
    """, (name, capital, json.dumps(params), backtest_cagr, backtest_win_rate, int(is_active)))
    conn.commit()


def get_strategy(name: str) -> Optional[Dict]:
    row = get_conn().execute("SELECT * FROM strategies WHERE name=?", (name,)).fetchone()
    if row:
        d = dict(row)
        d["params"] = json.loads(d["params"])
        return d
    return None


def get_active_strategies() -> List[Dict]:
    rows = get_conn().execute("SELECT * FROM strategies WHERE is_active=1").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["params"] = json.loads(d["params"])
        result.append(d)
    return result


def get_all_strategies() -> List[Dict]:
    """Return all strategies persisted in the DB."""
    rows = get_conn().execute("SELECT * FROM strategies").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["params"] = json.loads(d.get("params") or "{}")
        result.append(d)
    return result


def set_strategy_active(name: str, is_active: bool):
    """Activate/deactivate a strategy in the persisted strategy registry."""
    conn = get_conn()
    conn.execute("UPDATE strategies SET is_active=? WHERE name=?", (int(bool(is_active)), name))
    conn.commit()


def update_strategy_capital(name: str, capital: float):
    conn = get_conn()
    conn.execute("UPDATE strategies SET capital=? WHERE name=?", (capital, name))
    conn.commit()


def update_strategy_params(name: str, params: dict):
    conn = get_conn()
    conn.execute("UPDATE strategies SET params=? WHERE name=?", (json.dumps(params), name))
    conn.commit()


# ─── Position helpers ─────────────────────────────────────────────────────────

def open_position(strategy_name: str, symbol: str, side: str,
                  entry_price: float, quantity: float,
                  stop_loss: float, take_profit: float,
                  order_id: str = "", ml_confidence: float = 0.5,
                  metadata: dict = None) -> int:
    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO positions
        (strategy_name, symbol, side, entry_price, quantity, stop_loss,
         take_profit, entry_time, order_id, ml_confidence, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (strategy_name, symbol, side, entry_price, quantity, stop_loss,
          take_profit, utc_now_iso(), order_id,
          ml_confidence, json.dumps(metadata or {})))
    conn.commit()
    return cursor.lastrowid


def get_open_positions(strategy_name: str = None) -> List[Dict]:
    conn = get_conn()
    if strategy_name:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status='OPEN' AND strategy_name=?",
            (strategy_name,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status='OPEN'"
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        result.append(d)
    return result


def close_position(position_id: int):
    conn = get_conn()
    conn.execute("UPDATE positions SET status='CLOSED' WHERE id=?", (position_id,))
    conn.commit()


# ─── Trade helpers ────────────────────────────────────────────────────────────

def record_trade(strategy_name: str, symbol: str, side: str,
                 entry_price: float, exit_price: float, quantity: float,
                 pnl: float, pnl_pct: float, fees_paid: float,
                 entry_time: str, exit_time: str, duration_hours: float,
                 exit_reason: str, entry_features: dict = None,
                 is_backtest: bool = False) -> int:
    """Record a trade. Set is_backtest=True for backtest trades (not shown in history)."""
    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO trades
        (strategy_name, symbol, side, entry_price, exit_price, quantity,
         pnl, pnl_pct, fees_paid, entry_time, exit_time, duration_hours,
         exit_reason, entry_features, is_backtest)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (strategy_name, symbol, side, entry_price, exit_price, quantity,
          pnl, pnl_pct, fees_paid, entry_time, exit_time, duration_hours,
          exit_reason, json.dumps(entry_features or {}), 1 if is_backtest else 0))
    conn.commit()
    return cursor.lastrowid


def record_trade_decision(symbol: str,
                          timeframe: str,
                          strategy_id: str,
                          regime_id: str,
                          side: str,
                          confidence_raw: float,
                          confidence_calibrated: float,
                          expected_horizon_min: Optional[int] = None,
                          expected_move_bps: Optional[float] = None,
                          risk_budget_bps: Optional[float] = None,
                          stop_loss_bps: Optional[float] = None,
                          take_profit_bps: Optional[float] = None,
                          feature_snapshot: Optional[Dict[str, Any]] = None,
                          model_version: Optional[str] = None,
                          policy_version: Optional[str] = None,
                          decision_reason_short: str = "",
                          paper_or_live: str = "live",
                          trade_id: Optional[str] = None) -> str:
    """Persist a decision packet and return its trade_id."""
    conn = get_conn()
    resolved_trade_id = trade_id or str(uuid4())
    conn.execute("""
        INSERT INTO trades_decision
        (trade_id, ts_decision, symbol, timeframe, strategy_id, regime_id, side,
         confidence_raw, confidence_calibrated, expected_horizon_min, expected_move_bps,
         risk_budget_bps, stop_loss_bps, take_profit_bps, feature_snapshot_json,
         model_version, policy_version, decision_reason_short, paper_or_live)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        resolved_trade_id,
        utc_now_iso(),
        symbol,
        timeframe,
        strategy_id,
        regime_id,
        side,
        confidence_raw,
        confidence_calibrated,
        expected_horizon_min,
        expected_move_bps,
        risk_budget_bps,
        stop_loss_bps,
        take_profit_bps,
        json.dumps(feature_snapshot or {}),
        model_version,
        policy_version,
        decision_reason_short,
        paper_or_live,
    ))
    conn.commit()
    return resolved_trade_id


def record_trade_execution(trade_id: str,
                           exchange: str,
                           order_type: str,
                           order_qty: float,
                           avg_fill_price: float,
                           mid_at_send: Optional[float] = None,
                           spread_bps_at_send: Optional[float] = None,
                           slippage_bps: Optional[float] = None,
                           fees_bps: Optional[float] = None,
                           latency_ms_signal_to_send: Optional[int] = None,
                           latency_ms_send_to_fill: Optional[int] = None,
                           execution_quality_score: Optional[float] = None,
                           ts_order_sent: Optional[str] = None,
                           ts_first_fill: Optional[str] = None,
                           ts_full_fill: Optional[str] = None) -> int:
    """Persist an execution packet linked to a decision trade_id."""
    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO trades_execution
        (trade_id, ts_order_sent, ts_first_fill, ts_full_fill, exchange, order_type,
         order_qty, avg_fill_price, mid_at_send, spread_bps_at_send, slippage_bps,
         fees_bps, latency_ms_signal_to_send, latency_ms_send_to_fill, execution_quality_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade_id,
        ts_order_sent or utc_now_iso(),
        ts_first_fill,
        ts_full_fill,
        exchange,
        order_type,
        order_qty,
        avg_fill_price,
        mid_at_send,
        spread_bps_at_send,
        slippage_bps,
        fees_bps,
        latency_ms_signal_to_send,
        latency_ms_send_to_fill,
        execution_quality_score,
    ))
    conn.commit()
    return cursor.lastrowid


def record_trade_outcome(trade_id: str,
                         horizon_min: int,
                         pnl_bps_gross: Optional[float] = None,
                         pnl_bps_net: Optional[float] = None,
                         mae_bps: Optional[float] = None,
                         mfe_bps: Optional[float] = None,
                         stopped_out: bool = False,
                         tp_hit: bool = False,
                         early_exit: bool = False,
                         outcome_label: Optional[str] = None,
                         quality_label: Optional[str] = None,
                         ts_horizon: Optional[str] = None) -> int:
    """Upsert an outcome packet for a decision trade_id + horizon."""
    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO trades_outcome
        (trade_id, horizon_min, ts_horizon, pnl_bps_gross, pnl_bps_net, mae_bps, mfe_bps,
         stopped_out, tp_hit, early_exit, outcome_label, quality_label)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_id, horizon_min) DO UPDATE SET
            ts_horizon=excluded.ts_horizon,
            pnl_bps_gross=excluded.pnl_bps_gross,
            pnl_bps_net=excluded.pnl_bps_net,
            mae_bps=excluded.mae_bps,
            mfe_bps=excluded.mfe_bps,
            stopped_out=excluded.stopped_out,
            tp_hit=excluded.tp_hit,
            early_exit=excluded.early_exit,
            outcome_label=excluded.outcome_label,
            quality_label=excluded.quality_label
    """, (
        trade_id,
        horizon_min,
        ts_horizon or utc_now_iso(),
        pnl_bps_gross,
        pnl_bps_net,
        mae_bps,
        mfe_bps,
        int(stopped_out),
        int(tp_hit),
        int(early_exit),
        outcome_label,
        quality_label,
    ))
    conn.commit()
    return cursor.lastrowid


def record_trade_review_label(trade_id: str,
                              reviewer: str,
                              should_take_again: Optional[bool],
                              mistake_type: str,
                              confidence_error_bucket: str,
                              notes: str,
                              final_label: str,
                              review_id: Optional[str] = None,
                              ts_review: Optional[str] = None) -> str:
    """Persist a review/label packet for a decision trade_id."""
    conn = get_conn()
    resolved_review_id = review_id or str(uuid4())
    conn.execute("""
        INSERT INTO trade_review_labels
        (review_id, trade_id, ts_review, reviewer, should_take_again, mistake_type,
         confidence_error_bucket, notes, final_label)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        resolved_review_id,
        trade_id,
        ts_review or utc_now_iso(),
        reviewer,
        None if should_take_again is None else int(should_take_again),
        mistake_type,
        confidence_error_bucket,
        notes,
        final_label,
    ))
    conn.commit()
    return resolved_review_id


def record_infra_incident(severity: str,
                          component: str,
                          incident_signature: str,
                          remediate_action_taken: str = "",
                          trade_ids_affected: Optional[List[str]] = None,
                          impact_tag: str = "none",
                          incident_id: Optional[str] = None,
                          ts_start: Optional[str] = None,
                          ts_end: Optional[str] = None) -> str:
    """Persist an infra incident packet optionally linked to one or more trade_ids."""
    conn = get_conn()
    resolved_incident_id = incident_id or str(uuid4())
    conn.execute("""
        INSERT INTO infra_incidents
        (incident_id, ts_start, ts_end, severity, component, incident_signature,
         remediate_action_taken, trade_ids_affected_json, impact_tag)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        resolved_incident_id,
        ts_start or utc_now_iso(),
        ts_end,
        severity,
        component,
        incident_signature,
        remediate_action_taken,
        json.dumps(trade_ids_affected or []),
        impact_tag,
    ))
    conn.commit()
    return resolved_incident_id


def get_trades(strategy_name: str = None, limit: int = 500, include_backtest: bool = False) -> List[Dict]:
    """
    Get trades from the database.
    
    Args:
        strategy_name: Filter by strategy (optional)
        limit: Maximum number of trades to return
        include_backtest: If False (default), exclude backtest trades
    """
    conn = get_conn()
    if strategy_name:
        if include_backtest:
            rows = conn.execute(
                "SELECT * FROM trades WHERE strategy_name=? ORDER BY closed_at DESC LIMIT ?",
                (strategy_name, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE strategy_name=? AND is_backtest=0 ORDER BY closed_at DESC LIMIT ?",
                (strategy_name, limit)
            ).fetchall()
    else:
        if include_backtest:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE is_backtest=0 ORDER BY closed_at DESC LIMIT ?", (limit,)
            ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["entry_features"] = json.loads(d.get("entry_features") or "{}")
        result.append(d)
    return result


def get_trade_stats(strategy_name: str = None, include_backtest: bool = False) -> Dict:
    """Get trade statistics. Excludes backtest trades by default."""
    conn = get_conn()
    if strategy_name:
        if include_backtest:
            where = "WHERE strategy_name=?"
            params = (strategy_name,)
        else:
            where = "WHERE strategy_name=? AND is_backtest=0"
            params = (strategy_name,)
    else:
        if include_backtest:
            where = ""
            params = ()
        else:
            where = "WHERE is_backtest=0"
            params = ()
    
    query = f"""
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl) as total_pnl,
            AVG(pnl_pct) as avg_pnl_pct,
            MAX(pnl) as best_trade,
            MIN(pnl) as worst_trade,
            AVG(duration_hours) as avg_duration_hours,
            SUM(fees_paid) as total_fees
        FROM trades {where}
    """
    row = conn.execute(query, params).fetchone()
    if row:
        d = dict(row)
        d["win_rate"] = (d["wins"] / d["total_trades"]) if d["total_trades"] > 0 else 0
        return d
    return {}


# ─── Journal helpers ──────────────────────────────────────────────────────────

def record_journal_entry(trade_id: int, strategy_name: str,
                         entry_price: float, exit_price: float,
                         pnl: float, pnl_pct: float, side: str,
                         duration_hours: float, market_regime: str,
                         setup_summary: str, outcome_analysis: str,
                         reflection: str, lessons: Any):
    """
    Idempotent: one journal entry per trade_id.
    lessons: pass a list of lesson strings (will be JSON-serialized).
             Pass an empty list to write no lessons.
    """
    conn = get_conn()
    # Normalise lessons to a JSON array string
    if isinstance(lessons, list):
        lessons_json = json.dumps(lessons, ensure_ascii=False)
    elif isinstance(lessons, str):
        # Back-compat: legacy pipe-delimited string → convert to list
        try:
            parsed = json.loads(lessons)
            if isinstance(parsed, list):
                lessons_json = lessons
            else:
                lessons_json = json.dumps([lessons])
        except Exception:
            # Treat as legacy pipe-delimited string
            parts = [p.strip() for p in lessons.split(" | ") if p.strip()]
            lessons_json = json.dumps(parts, ensure_ascii=False)
    else:
        lessons_json = "[]"

    conn.execute("""
        INSERT INTO journal_entries
        (trade_id, strategy_name, entry_price, exit_price, pnl, pnl_pct,
         side, duration_hours, market_regime, setup_summary, outcome_analysis,
         reflection, lessons)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_id) DO UPDATE SET
            entry_price    = excluded.entry_price,
            exit_price     = excluded.exit_price,
            pnl            = excluded.pnl,
            pnl_pct        = excluded.pnl_pct,
            side           = excluded.side,
            duration_hours = excluded.duration_hours,
            market_regime  = excluded.market_regime,
            setup_summary  = excluded.setup_summary,
            outcome_analysis = excluded.outcome_analysis,
            reflection     = excluded.reflection,
            lessons        = excluded.lessons,
            created_at     = excluded.created_at
    """, (trade_id, strategy_name, entry_price, exit_price, pnl, pnl_pct,
          side, duration_hours, market_regime, setup_summary, outcome_analysis,
          reflection, lessons_json))
    conn.commit()


def get_journal_entries(strategy_name: str = None, limit: int = 100, include_backtest: bool = False) -> List[Dict]:
    """Get journal entries. Excludes entries for backtest trades by default."""
    conn = get_conn()
    if strategy_name:
        if include_backtest:
            rows = conn.execute(
                "SELECT * FROM journal_entries WHERE strategy_name=? ORDER BY created_at DESC LIMIT ?",
                (strategy_name, limit)
            ).fetchall()
        else:
            # Join with trades to filter out backtest trades
            rows = conn.execute("""
                SELECT j.* FROM journal_entries j
                JOIN trades t ON j.trade_id = t.id
                WHERE j.strategy_name=? AND t.is_backtest=0
                ORDER BY j.created_at DESC LIMIT ?
            """, (strategy_name, limit)).fetchall()
    else:
        if include_backtest:
            rows = conn.execute(
                "SELECT * FROM journal_entries ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute("""
                SELECT j.* FROM journal_entries j
                JOIN trades t ON j.trade_id = t.id
                WHERE t.is_backtest=0
                ORDER BY j.created_at DESC LIMIT ?
            """, (limit,)).fetchall()
    # Parse lessons from JSON string to list (back-compat: legacy pipe-delimited)
    result = []
    for row in rows:
        d = dict(row)
        raw = d.get("lessons") or "[]"
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                d["lessons"] = parsed
            else:
                d["lessons"] = [str(parsed)]
        except Exception:
            parts = [p.strip() for p in raw.split(" | ") if p.strip()]
            d["lessons"] = parts
        result.append(d)
    return result


def journal_has_entry(trade_id: int) -> bool:
    """Return True if a journal entry already exists for this trade_id."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM journal_entries WHERE trade_id=? LIMIT 1", (trade_id,)
    ).fetchone()
    return row is not None


# ─── Balance helpers ──────────────────────────────────────────────────────────

def record_balance(total_balance: float, realized_pnl: float,
                   unrealized_pnl: float, strategy_breakdown: dict = None):
    conn = get_conn()
    conn.execute("""
        INSERT INTO balance_history (total_balance, realized_pnl, unrealized_pnl, strategy_breakdown)
        VALUES (?, ?, ?, ?)
    """, (total_balance, realized_pnl, unrealized_pnl,
          json.dumps(strategy_breakdown or {})))
    conn.commit()


def get_balance_history(days: int = 30, include_backtest: bool = False) -> List[Dict]:
    """
    Get balance history for equity curve.
    
    Args:
        days: Number of days to look back
        include_backtest: If False (default), only return data from when live trading started
    """
    conn = get_conn()
    
    # Get live_since date if we should filter
    live_since = None if include_backtest else get_live_since()
    
    if live_since:
        # Filter to only include data from live trading start
        rows = conn.execute("""
            SELECT * FROM balance_history
            WHERE recorded_at >= ?
            ORDER BY recorded_at ASC
        """, (live_since,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM balance_history
            WHERE recorded_at >= datetime('now', ? || ' days')
            ORDER BY recorded_at ASC
        """, (f"-{days}",)).fetchall()
    
    result = []
    for row in rows:
        d = dict(row)
        d["strategy_breakdown"] = json.loads(d.get("strategy_breakdown") or "{}")
        result.append(d)
    return result


def get_latest_balance() -> Optional[Dict]:
    row = get_conn().execute(
        "SELECT * FROM balance_history ORDER BY recorded_at DESC LIMIT 1"
    ).fetchone()
    if row:
        d = dict(row)
        d["strategy_breakdown"] = json.loads(d.get("strategy_breakdown") or "{}")
        return d
    return None


# ─── ML Feature helpers ───────────────────────────────────────────────────────

def record_ml_features(trade_id: int, strategy_name: str,
                       features: List[float], outcome: float, pnl_pct: float):
    conn = get_conn()
    conn.execute("""
        INSERT INTO ml_features (trade_id, strategy_name, features, outcome, pnl_pct)
        VALUES (?, ?, ?, ?, ?)
    """, (trade_id, strategy_name, json.dumps(features), outcome, pnl_pct))
    conn.commit()


def get_ml_features(strategy_name: str, limit: int = 500) -> List[Dict]:
    rows = get_conn().execute("""
        SELECT * FROM ml_features WHERE strategy_name=?
        ORDER BY recorded_at DESC LIMIT ?
    """, (strategy_name, limit)).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["features"] = json.loads(d["features"])
        result.append(d)
    return result


# ─── Strategy performance snapshot ───────────────────────────────────────────

def upsert_strategy_performance(strategy_name: str, capital: float,
                                 daily_pnl: float, cumulative_pnl: float,
                                 win_rate: float, total_trades: int,
                                 open_positions: int):
    conn = get_conn()
    today = utc_now().strftime("%Y-%m-%d")
    conn.execute("""
        INSERT INTO strategy_performance
        (strategy_name, date, capital, daily_pnl, cumulative_pnl, win_rate,
         total_trades, open_positions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(strategy_name, date) DO UPDATE SET
            capital = excluded.capital,
            daily_pnl = excluded.daily_pnl,
            cumulative_pnl = excluded.cumulative_pnl,
            win_rate = excluded.win_rate,
            total_trades = excluded.total_trades,
            open_positions = excluded.open_positions
    """, (strategy_name, today, capital, daily_pnl, cumulative_pnl,
          win_rate, total_trades, open_positions))
    conn.commit()


def get_strategy_performance_history(strategy_name: str, days: int = 90) -> List[Dict]:
    rows = get_conn().execute("""
        SELECT * FROM strategy_performance
        WHERE strategy_name=?
          AND date >= date('now', ? || ' days')
        ORDER BY date ASC
    """, (strategy_name, f"-{days}")).fetchall()
    return [dict(row) for row in rows]


# ─── Automated review helpers ────────────────────────────────────────────────

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    dt: Optional[datetime] = None
    try:
        # Handles offsets and trailing Z
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except Exception:
                continue

    if dt is None:
        return None

    # Normalize to timezone-aware UTC to avoid naive/aware compare errors
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_recent_trade_metrics(strategy_name: Optional[str] = None, days: int = 7) -> Dict[str, float]:
    """Compute recent metrics used by the auto review engine."""
    conn = get_conn()
    if strategy_name:
        rows = conn.execute(
            """
            SELECT pnl, pnl_pct, exit_time
            FROM trades
            WHERE is_backtest=0 AND strategy_name=?
            ORDER BY exit_time ASC
            """,
            (strategy_name,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT pnl, pnl_pct, exit_time
            FROM trades
            WHERE is_backtest=0
            ORDER BY exit_time ASC
            """
        ).fetchall()

    cutoff = utc_now() - timedelta(days=days)
    filtered = []
    for row in rows:
        ts = _parse_dt(row["exit_time"])
        if ts and ts >= cutoff:
            filtered.append(dict(row))

    if not filtered:
        return {
            "weekly_pnl_pct": 0.0,
            "daily_pnl_std": 0.0,
            "max_daily_loss_pct": 0.0,
            "losing_streak_max": 0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "avg_r": 0.0,
            "trade_count": 0,
        }

    pnl_pcts = [float(r["pnl_pct"]) for r in filtered]
    wins = [x for x in pnl_pcts if x > 0]
    losses = [x for x in pnl_pcts if x <= 0]

    # Daily smoothness from per-day aggregated pnl_pct
    by_day: Dict[str, float] = {}
    for r in filtered:
        dt = _parse_dt(r["exit_time"])
        if not dt:
            continue
        day = dt.strftime("%Y-%m-%d")
        by_day[day] = by_day.get(day, 0.0) + float(r["pnl_pct"])

    daily_values = list(by_day.values()) or [0.0]
    daily_std = statistics.pstdev(daily_values) if len(daily_values) > 1 else 0.0

    # Losing streak max (by chronological exits)
    streak = 0
    max_streak = 0
    for p in pnl_pcts:
        if p <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    return {
        "weekly_pnl_pct": float(sum(pnl_pcts)),
        "daily_pnl_std": float(daily_std),
        "max_daily_loss_pct": float(min(pnl_pcts)),
        "losing_streak_max": int(max_streak),
        "profit_factor": float(profit_factor),
        "win_rate": float(len(wins) / len(filtered)),
        "avg_r": float(sum(pnl_pcts) / len(filtered)),
        "trade_count": int(len(filtered)),
    }


def get_portfolio_weekly_drawdown_pct(days: int = 7) -> float:
    """Return max drawdown % (negative) from balance_history over last N days."""
    rows = get_conn().execute(
        "SELECT total_balance, recorded_at FROM balance_history ORDER BY recorded_at ASC"
    ).fetchall()

    cutoff = utc_now() - timedelta(days=days)
    balances: List[float] = []
    for row in rows:
        ts = _parse_dt(row["recorded_at"])
        if ts and ts >= cutoff:
            balances.append(float(row["total_balance"]))

    if not balances:
        return 0.0

    peak = balances[0]
    max_dd = 0.0
    for b in balances:
        if b > peak:
            peak = b
        dd = ((b - peak) / peak) * 100 if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return float(max_dd)


def get_recent_portfolio_metrics(days: int = 7) -> Dict[str, float]:
    """Portfolio-level metrics for baseline comparison."""
    metrics = get_recent_trade_metrics(strategy_name=None, days=days)
    metrics["weekly_drawdown_pct"] = get_portfolio_weekly_drawdown_pct(days=days)
    return metrics


def record_risk_event(week_id: str, trigger_level_pct: float,
                      portfolio_dd_pct: float, size_multiplier_applied: float,
                      note: str = ""):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO risk_events
        (week_id, trigger_level_pct, portfolio_dd_pct, size_multiplier_applied, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (week_id, trigger_level_pct, portfolio_dd_pct, size_multiplier_applied, note),
    )
    conn.commit()


def upsert_experiment_run(payload: Dict[str, Any]):
    """Insert/update an experiment review row keyed by (experiment_id, week_id)."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO experiment_runs (
            experiment_id, week_id, baseline_version,
            weekly_pnl_pct, weekly_drawdown_pct, daily_pnl_std,
            max_daily_loss_pct, losing_streak_max,
            profit_factor, win_rate, avg_r, trade_count,
            score_consistency, score_drawdown, score_profit,
            score_quality, score_participation, score_total,
            decision, decision_reason, reviewed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(experiment_id, week_id) DO UPDATE SET
            baseline_version=excluded.baseline_version,
            weekly_pnl_pct=excluded.weekly_pnl_pct,
            weekly_drawdown_pct=excluded.weekly_drawdown_pct,
            daily_pnl_std=excluded.daily_pnl_std,
            max_daily_loss_pct=excluded.max_daily_loss_pct,
            losing_streak_max=excluded.losing_streak_max,
            profit_factor=excluded.profit_factor,
            win_rate=excluded.win_rate,
            avg_r=excluded.avg_r,
            trade_count=excluded.trade_count,
            score_consistency=excluded.score_consistency,
            score_drawdown=excluded.score_drawdown,
            score_profit=excluded.score_profit,
            score_quality=excluded.score_quality,
            score_participation=excluded.score_participation,
            score_total=excluded.score_total,
            decision=excluded.decision,
            decision_reason=excluded.decision_reason,
            reviewed_at=datetime('now')
        """,
        (
            payload["experiment_id"], payload["week_id"], payload["baseline_version"],
            payload["weekly_pnl_pct"], payload["weekly_drawdown_pct"], payload["daily_pnl_std"],
            payload["max_daily_loss_pct"], payload["losing_streak_max"],
            payload["profit_factor"], payload["win_rate"], payload["avg_r"], payload["trade_count"],
            payload["score_consistency"], payload["score_drawdown"], payload["score_profit"],
            payload["score_quality"], payload["score_participation"], payload["score_total"],
            payload["decision"], payload["decision_reason"],
        ),
    )
    conn.commit()


def upsert_regime_performance_daily(regime_id: str,
                                    strategy_id: str,
                                    day: str,
                                    trades: int,
                                    win_rate: Optional[float],
                                    net_pnl_bps: Optional[float],
                                    avg_mae: Optional[float],
                                    avg_mfe: Optional[float],
                                    calibration_error: Optional[float]):
    """Upsert daily regime-level performance aggregates."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO regime_performance_daily (
            regime_id, strategy_id, day, trades,
            win_rate, net_pnl_bps, avg_mae, avg_mfe, calibration_error, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(regime_id, strategy_id, day) DO UPDATE SET
            trades=excluded.trades,
            win_rate=excluded.win_rate,
            net_pnl_bps=excluded.net_pnl_bps,
            avg_mae=excluded.avg_mae,
            avg_mfe=excluded.avg_mfe,
            calibration_error=excluded.calibration_error,
            updated_at=datetime('now')
        """,
        (regime_id, strategy_id, day, trades, win_rate, net_pnl_bps, avg_mae, avg_mfe, calibration_error),
    )
    conn.commit()


def upsert_signal_quality_index(strategy_id: str,
                                regime_id: str,
                                week: str,
                                true_shift_precision: Optional[float],
                                fakeout_rate: Optional[float],
                                early_entry_score: Optional[float],
                                execution_penalty_score: Optional[float]):
    """Upsert weekly signal quality index aggregates."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO signal_quality_index (
            strategy_id, regime_id, week,
            true_shift_precision, fakeout_rate, early_entry_score,
            execution_penalty_score, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(strategy_id, regime_id, week) DO UPDATE SET
            true_shift_precision=excluded.true_shift_precision,
            fakeout_rate=excluded.fakeout_rate,
            early_entry_score=excluded.early_entry_score,
            execution_penalty_score=excluded.execution_penalty_score,
            updated_at=datetime('now')
        """,
        (
            strategy_id,
            regime_id,
            week,
            true_shift_precision,
            fakeout_rate,
            early_entry_score,
            execution_penalty_score,
        ),
    )
    conn.commit()


def get_latest_signal_quality_index(strategy_id: str, regime_id: str) -> Optional[Dict[str, Any]]:
    """Return latest weekly SQI row for a strategy+regime."""
    row = get_conn().execute(
        """
        SELECT * FROM signal_quality_index
        WHERE strategy_id=? AND regime_id=?
        ORDER BY week DESC
        LIMIT 1
        """,
        (strategy_id, regime_id),
    ).fetchone()
    return dict(row) if row else None





