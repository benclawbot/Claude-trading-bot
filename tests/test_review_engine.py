import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import review_engine


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
