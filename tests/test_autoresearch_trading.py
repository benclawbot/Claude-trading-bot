def test_trade_sample_weight_penalizes_small_samples():
    import autoresearch_trading as ar

    weighted = ar.apply_trade_sample_weight(raw_score=1.0, total_trades=2, min_trades=20)

    assert 0.0 < weighted < 1.0
    assert weighted < 0.5


def test_trade_sample_weight_no_penalty_when_sample_sufficient():
    import autoresearch_trading as ar

    weighted = ar.apply_trade_sample_weight(raw_score=0.73, total_trades=30, min_trades=20)

    assert weighted == 0.73


def test_compute_robustness_score_penalizes_drawdown_and_instability():
    import autoresearch_trading as ar

    robust = ar.compute_robustness_score(
        cagr=0.22,
        win_rate=0.58,
        profit_factor=1.65,
        max_drawdown=0.09,
        daily_pnl_std=0.010,
        avg_trade_pnl=0.007,
    )
    fragile = ar.compute_robustness_score(
        cagr=0.22,
        win_rate=0.58,
        profit_factor=1.65,
        max_drawdown=0.31,
        daily_pnl_std=0.060,
        avg_trade_pnl=0.002,
    )

    assert 0.0 <= robust <= 1.0
    assert 0.0 <= fragile <= 1.0
    assert robust > fragile


def test_apply_robustness_gate_requires_minimum_score():
    import autoresearch_trading as ar

    assert ar.apply_robustness_gate(0.71, 0.60) is True
    assert ar.apply_robustness_gate(0.59, 0.60) is False


def test_compute_walk_forward_stability_prefers_smoother_equity():
    import autoresearch_trading as ar

    smooth = [1000, 1015, 1030, 1045, 1060, 1075, 1090, 1105, 1120, 1135, 1150, 1165]
    choppy = [1000, 1100, 900, 1150, 850, 1200, 800, 1250, 780, 1280, 760, 1300]

    smooth_score = ar.compute_walk_forward_stability(smooth, windows=3)
    choppy_score = ar.compute_walk_forward_stability(choppy, windows=3)

    assert 0.0 <= smooth_score <= 1.0
    assert 0.0 <= choppy_score <= 1.0
    assert smooth_score > choppy_score
