#!/usr/bin/env python3
"""Build/update derived moat tables from trade packet data.

Outputs JSON summary with rows upserted into:
- regime_performance_daily
- signal_quality_index
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import dataclass, asdict

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import database as db


@dataclass
class UpdateSummary:
    daily_rows_upserted: int = 0
    weekly_rows_upserted: int = 0


def _latest_outcome_cte() -> str:
    return """
    WITH latest_outcome AS (
        SELECT
            o.*,
            ROW_NUMBER() OVER (
                PARTITION BY o.trade_id
                ORDER BY o.horizon_min DESC, o.ts_horizon DESC
            ) AS rn
        FROM trades_outcome o
    )
    """


def update_regime_performance_daily(summary: UpdateSummary) -> None:
    conn = db.get_conn()
    query = _latest_outcome_cte() + """
    SELECT
        DATE(d.ts_decision) AS day,
        d.strategy_id,
        d.regime_id,
        COUNT(*) AS trades,
        AVG(CASE WHEN lo.outcome_label = 'win' THEN 1.0
                 WHEN lo.outcome_label = 'loss' THEN 0.0
                 ELSE NULL END) AS win_rate,
        SUM(COALESCE(lo.pnl_bps_net, 0.0)) AS net_pnl_bps,
        AVG(lo.mae_bps) AS avg_mae,
        AVG(lo.mfe_bps) AS avg_mfe,
        AVG(
            ABS(
                COALESCE(d.confidence_calibrated, d.confidence_raw, 0.5) -
                CASE
                    WHEN lo.outcome_label = 'win' THEN 1.0
                    WHEN lo.outcome_label = 'loss' THEN 0.0
                    ELSE 0.5
                END
            )
        ) AS calibration_error
    FROM trades_decision d
    JOIN latest_outcome lo ON lo.trade_id = d.trade_id AND lo.rn = 1
    GROUP BY DATE(d.ts_decision), d.strategy_id, d.regime_id
    """

    rows = conn.execute(query).fetchall()
    for row in rows:
        db.upsert_regime_performance_daily(
            regime_id=row["regime_id"],
            strategy_id=row["strategy_id"],
            day=row["day"],
            trades=int(row["trades"] or 0),
            win_rate=row["win_rate"],
            net_pnl_bps=row["net_pnl_bps"],
            avg_mae=row["avg_mae"],
            avg_mfe=row["avg_mfe"],
            calibration_error=row["calibration_error"],
        )
        summary.daily_rows_upserted += 1


def update_signal_quality_index(summary: UpdateSummary) -> None:
    conn = db.get_conn()
    query = _latest_outcome_cte() + """
    , latest_execution AS (
        SELECT
            e.*,
            ROW_NUMBER() OVER (
                PARTITION BY e.trade_id
                ORDER BY COALESCE(e.ts_full_fill, e.ts_first_fill, e.ts_order_sent) DESC
            ) AS rn
        FROM trades_execution e
    )
    SELECT
        STRFTIME('%Y-W%W', d.ts_decision) AS week,
        d.strategy_id,
        d.regime_id,
        AVG(CASE WHEN lo.quality_label = 'good_shift' THEN 1.0
                 WHEN lo.quality_label IN ('fakeout', 'noise', 'late') THEN 0.0
                 ELSE NULL END) AS true_shift_precision,
        AVG(CASE WHEN lo.quality_label = 'fakeout' THEN 1.0 ELSE 0.0 END) AS fakeout_rate,
        AVG(CASE
                WHEN lo.quality_label = 'good_shift' THEN 1.0
                WHEN lo.quality_label = 'late' THEN 0.25
                WHEN lo.quality_label = 'noise' THEN 0.5
                WHEN lo.quality_label = 'fakeout' THEN 0.0
                ELSE 0.5
            END) AS early_entry_score,
        AVG(CASE
                WHEN le.slippage_bps IS NULL THEN 0.0
                ELSE MIN(1.0, ABS(le.slippage_bps) / 10.0)
            END) AS execution_penalty_score
    FROM trades_decision d
    JOIN latest_outcome lo ON lo.trade_id = d.trade_id AND lo.rn = 1
    LEFT JOIN latest_execution le ON le.trade_id = d.trade_id AND le.rn = 1
    GROUP BY STRFTIME('%Y-W%W', d.ts_decision), d.strategy_id, d.regime_id
    """

    rows = conn.execute(query).fetchall()
    for row in rows:
        db.upsert_signal_quality_index(
            strategy_id=row["strategy_id"],
            regime_id=row["regime_id"],
            week=row["week"],
            true_shift_precision=row["true_shift_precision"],
            fakeout_rate=row["fakeout_rate"],
            early_entry_score=row["early_entry_score"],
            execution_penalty_score=row["execution_penalty_score"],
        )
        summary.weekly_rows_upserted += 1


def main() -> int:
    db.init_db()
    summary = UpdateSummary()
    update_regime_performance_daily(summary)
    update_signal_quality_index(summary)

    print(json.dumps({
        "status": "ok",
        "summary": asdict(summary),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
