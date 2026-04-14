import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import review_engine


def test_deterministic_experiment_id_stable_for_same_inputs():
    params = {"lookback": 24, "volume_multiplier": 1.5, "experiment_tag": "wk1-a"}
    first = review_engine.deterministic_experiment_id("Breakout", params=params)
    second = review_engine.deterministic_experiment_id("Breakout", params=params)

    assert first == second
    assert first.startswith("Breakout:wk1-a:")


def test_deterministic_experiment_id_changes_when_params_change():
    base = review_engine.deterministic_experiment_id("Breakout", params={"lookback": 24})
    changed = review_engine.deterministic_experiment_id("Breakout", params={"lookback": 48})

    assert base != changed


def test_decide_size_multiplier_ladder():
    assert review_engine.decide_size_multiplier(-2.9) == 1.0
    assert review_engine.decide_size_multiplier(-3.0) == 0.70
    assert review_engine.decide_size_multiplier(-4.2) == 0.70
    assert review_engine.decide_size_multiplier(-5.0) == 0.40
    assert review_engine.decide_size_multiplier(-8.5) == 0.40


def test_evaluate_experiment_insufficient_data():
    baseline = {
        "weekly_pnl_pct": 0.8,
        "weekly_drawdown_pct": -2.1,
        "daily_pnl_std": 0.6,
        "max_daily_loss_pct": -1.1,
        "losing_streak_max": 2,
        "profit_factor": 1.2,
        "win_rate": 0.55,
        "avg_r": 0.3,
        "trade_count": 12,
    }
    experiment = dict(baseline)
    experiment["trade_count"] = 5

    result = review_engine.evaluate_experiment(experiment, baseline)

    assert result["decision"] == "INSUFFICIENT_DATA"
    assert result["score_total"] == 0


def test_evaluate_experiment_promote_for_smoother_positive_profile():
    baseline = {
        "weekly_pnl_pct": 0.6,
        "weekly_drawdown_pct": -2.5,
        "daily_pnl_std": 1.0,
        "max_daily_loss_pct": -1.2,
        "losing_streak_max": 3,
        "profit_factor": 1.10,
        "win_rate": 0.50,
        "avg_r": 0.20,
        "trade_count": 12,
    }
    experiment = {
        "weekly_pnl_pct": 1.1,
        "weekly_drawdown_pct": -1.3,
        "daily_pnl_std": 0.7,
        "max_daily_loss_pct": -0.6,
        "losing_streak_max": 1,
        "profit_factor": 1.45,
        "win_rate": 0.57,
        "avg_r": 0.40,
        "trade_count": 14,
    }

    result = review_engine.evaluate_experiment(experiment, baseline)

    assert result["decision"] == "PROMOTE"
    assert result["score_total"] >= 75


def test_evaluate_experiment_kill_on_hard_drawdown():
    baseline = {
        "weekly_pnl_pct": 0.4,
        "weekly_drawdown_pct": -2.0,
        "daily_pnl_std": 0.9,
        "max_daily_loss_pct": -0.9,
        "losing_streak_max": 2,
        "profit_factor": 1.1,
        "win_rate": 0.52,
        "avg_r": 0.2,
        "trade_count": 11,
    }
    experiment = dict(baseline)
    experiment["weekly_drawdown_pct"] = -5.4

    result = review_engine.evaluate_experiment(experiment, baseline)

    assert result["decision"] == "KILL"
    assert "drawdown" in result["decision_reason"].lower()


def test_apply_experiment_lane_scheduler_enforces_min_active(monkeypatch):
    monkeypatch.setattr(review_engine.config, "EXPERIMENT_LANE_ENABLED", True)
    monkeypatch.setattr(review_engine.config, "EXPERIMENT_LANE_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(review_engine.config, "EXPERIMENT_LANE_STRATEGIES", {"A", "B", "C"})
    monkeypatch.setattr(review_engine.config, "EXPERIMENT_LANE_MIN_ACTIVE", 2)

    rows = [
        {"name": "A", "is_active": 1, "backtest_cagr": 0.10},
        {"name": "B", "is_active": 1, "backtest_cagr": 0.08},
        {"name": "C", "is_active": 0, "backtest_cagr": 0.12},
    ]
    updates = []

    monkeypatch.setattr(review_engine.db, "get_all_strategies", lambda: rows)
    monkeypatch.setattr(review_engine.db, "set_strategy_active", lambda name, flag: updates.append((name, flag)))

    evaluated = [
        {"strategy_name": "A", "decision": "KILL", "score_total": 10},
        {"strategy_name": "B", "decision": "KEEP_TESTING", "score_total": 65},
        {"strategy_name": "C", "decision": "PROMOTE", "score_total": 90},
    ]

    result = review_engine.apply_experiment_lane_scheduler(evaluated)

    assert result["applied"] is True
    assert result["lane_active_after"] == 2
    assert any(c["strategy"] == "A" and c["to"] is False for c in result["changes"])
    assert ("A", False) in updates


def test_apply_experiment_lane_scheduler_disabled(monkeypatch):
    monkeypatch.setattr(review_engine.config, "EXPERIMENT_LANE_ENABLED", False)
    result = review_engine.apply_experiment_lane_scheduler([])
    assert result["applied"] is False
    assert result["reason"] == "lane_disabled"


