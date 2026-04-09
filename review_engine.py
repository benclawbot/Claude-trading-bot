"""Automated experiment scoring + risk ladder review engine.

Runs scheduled Wed/Sun reviews, writes decisions to experiment_runs,
and records risk ladder events in risk_events.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import database as db

logger = logging.getLogger(__name__)


def current_week_id(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def decide_size_multiplier(weekly_dd_pct: float) -> float:
    """Risk ladder:
    - DD <= -5% => 0.40x
    - DD <= -3% => 0.70x
    - otherwise 1.00x
    """
    if weekly_dd_pct <= -5.0:
        return 0.40
    if weekly_dd_pct <= -3.0:
        return 0.70
    return 1.0


def _consistency_score(exp_std: float, base_std: float) -> float:
    if base_std <= 0:
        if exp_std <= 0:
            return 20
        return -15

    ratio = (exp_std - base_std) / base_std
    if ratio <= -0.15:
        return 20
    if ratio <= -0.05:
        return 12
    if ratio < 0:
        return 6
    if ratio >= 0.10:
        return -15
    return -6


def evaluate_experiment(experiment: Dict[str, float], baseline: Dict[str, float]) -> Dict[str, float | str]:
    """Score one experiment against baseline and return decision payload."""
    trade_count = int(experiment.get("trade_count", 0))
    if trade_count < 8:
        return {
            "score_consistency": 0,
            "score_drawdown": 0,
            "score_profit": 0,
            "score_quality": 0,
            "score_participation": 0,
            "score_total": 0,
            "decision": "INSUFFICIENT_DATA",
            "decision_reason": f"trade_count={trade_count} < 8 minimum",
        }

    exp_dd = float(experiment.get("weekly_drawdown_pct", 0.0))
    if exp_dd <= -5.0:
        return {
            "score_consistency": 0,
            "score_drawdown": -20,
            "score_profit": -20,
            "score_quality": -20,
            "score_participation": 0,
            "score_total": -60,
            "decision": "KILL",
            "decision_reason": f"hard drawdown breach ({exp_dd:.2f} <= -5.0)",
        }

    base_std = float(baseline.get("daily_pnl_std", 0.0))
    exp_std = float(experiment.get("daily_pnl_std", 0.0))
    consistency = _consistency_score(exp_std, base_std)

    base_dd = float(baseline.get("weekly_drawdown_pct", 0.0))
    delta_dd = exp_dd - base_dd
    drawdown = 0
    if delta_dd >= 1.0:
        drawdown -= 12
    elif delta_dd <= -1.0:
        drawdown += 12

    exp_max_daily_loss = float(experiment.get("max_daily_loss_pct", 0.0))
    base_max_daily_loss = float(baseline.get("max_daily_loss_pct", 0.0))
    delta_max_daily_loss = exp_max_daily_loss - base_max_daily_loss
    if delta_max_daily_loss >= 0.5:
        drawdown -= 8
    elif delta_max_daily_loss <= -0.5:
        drawdown += 8

    exp_pnl = float(experiment.get("weekly_pnl_pct", 0.0))
    base_pnl = float(baseline.get("weekly_pnl_pct", 0.0))
    delta_pnl = exp_pnl - base_pnl
    profit = 0
    profit += 10 if exp_pnl > 0 else -10
    profit += 10 if delta_pnl > 0 else -10

    quality = 0
    exp_pf = float(experiment.get("profit_factor", 0.0))
    quality += 8 if exp_pf >= 1.20 else -8

    exp_avg_r = float(experiment.get("avg_r", 0.0))
    base_avg_r = float(baseline.get("avg_r", 0.0))
    quality += 6 if exp_avg_r > base_avg_r else -4

    exp_streak = int(experiment.get("losing_streak_max", 0))
    base_streak = int(baseline.get("losing_streak_max", 0))
    quality += 6 if exp_streak < base_streak else -6

    participation = 0
    if 10 <= trade_count <= 20:
        participation = 10
    elif 8 <= trade_count < 10 or 20 < trade_count <= 24:
        participation = 2
    else:
        participation = -10

    score_total = 50 + consistency + drawdown + profit + quality + participation

    if score_total >= 75:
        decision = "PROMOTE"
    elif score_total >= 60:
        decision = "KEEP_TESTING"
    elif score_total >= 45:
        decision = "DEMOTE"
    else:
        decision = "KILL"

    reason = (
        f"score={score_total:.1f}; std={exp_std:.4f} vs {base_std:.4f}; "
        f"dd={exp_dd:.2f}; pnl={exp_pnl:.4f}; trades={trade_count}"
    )

    return {
        "score_consistency": float(consistency),
        "score_drawdown": float(drawdown),
        "score_profit": float(profit),
        "score_quality": float(quality),
        "score_participation": float(participation),
        "score_total": float(score_total),
        "decision": decision,
        "decision_reason": reason,
    }


def _risk_trigger_level(weekly_dd_pct: float) -> Optional[float]:
    if weekly_dd_pct <= -5.0:
        return -5.0
    if weekly_dd_pct <= -3.0:
        return -3.0
    return None


def run_auto_review(baseline_version: str = "auto", days: int = 7,
                    now: Optional[datetime] = None) -> Dict[str, object]:
    now = now or datetime.now(timezone.utc)
    week_id = current_week_id(now)

    portfolio = db.get_recent_portfolio_metrics(days=days)
    weekly_dd = float(portfolio.get("weekly_drawdown_pct", 0.0))
    size_multiplier = decide_size_multiplier(weekly_dd)

    # Persist current ladder output for the execution layer.
    db.set_metadata("risk_size_multiplier", f"{size_multiplier:.2f}")
    db.set_metadata("risk_size_multiplier_week", week_id)

    # Record ladder events only when state changes.
    ladder_key = f"risk_ladder_state:{week_id}"
    trigger_level = _risk_trigger_level(weekly_dd)
    new_state = "none" if trigger_level is None else str(trigger_level)
    prev_state = db.get_metadata(ladder_key)
    if new_state != prev_state:
        db.set_metadata(ladder_key, new_state)
        if trigger_level is not None:
            db.record_risk_event(
                week_id=week_id,
                trigger_level_pct=trigger_level,
                portfolio_dd_pct=weekly_dd,
                size_multiplier_applied=size_multiplier,
                note="Auto ladder trigger",
            )

    evaluated = []
    active = db.get_active_strategies()
    for strat in active:
        strategy_name = strat["name"]
        exp_metrics = db.get_recent_trade_metrics(strategy_name=strategy_name, days=days)
        exp_metrics["weekly_drawdown_pct"] = weekly_dd

        score = evaluate_experiment(exp_metrics, portfolio)
        payload = {
            "experiment_id": strategy_name,
            "week_id": week_id,
            "baseline_version": baseline_version,
            "weekly_pnl_pct": exp_metrics["weekly_pnl_pct"],
            "weekly_drawdown_pct": exp_metrics["weekly_drawdown_pct"],
            "daily_pnl_std": exp_metrics["daily_pnl_std"],
            "max_daily_loss_pct": exp_metrics["max_daily_loss_pct"],
            "losing_streak_max": exp_metrics["losing_streak_max"],
            "profit_factor": exp_metrics["profit_factor"],
            "win_rate": exp_metrics["win_rate"],
            "avg_r": exp_metrics["avg_r"],
            "trade_count": exp_metrics["trade_count"],
            "score_consistency": score["score_consistency"],
            "score_drawdown": score["score_drawdown"],
            "score_profit": score["score_profit"],
            "score_quality": score["score_quality"],
            "score_participation": score["score_participation"],
            "score_total": score["score_total"],
            "decision": score["decision"],
            "decision_reason": score["decision_reason"],
        }
        db.upsert_experiment_run(payload)
        evaluated.append(payload)

    return {
        "week_id": week_id,
        "portfolio_weekly_dd_pct": weekly_dd,
        "size_multiplier": size_multiplier,
        "strategies_evaluated": len(evaluated),
        "decisions": {d["experiment_id"]: d["decision"] for d in evaluated},
    }


def should_run_scheduled_review(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    # Wednesday=2, Sunday=6
    if now.weekday() not in (2, 6):
        return False

    today = now.strftime("%Y-%m-%d")
    last_run = db.get_metadata("auto_review_last_run_date")
    return last_run != today


def maybe_run_scheduled_review(now: Optional[datetime] = None) -> Dict[str, object]:
    now = now or datetime.now(timezone.utc)
    if not should_run_scheduled_review(now):
        return {"ran": False, "reason": "not_due"}

    summary = run_auto_review(now=now)
    db.set_metadata("auto_review_last_run_date", now.strftime("%Y-%m-%d"))
    logger.info(
        "[ReviewEngine] Scheduled review ran: %s | size=%.2f",
        summary["week_id"],
        summary["size_multiplier"],
    )
    return {"ran": True, **summary}
