"""Autoresearch-style optimizer for TradingBot guardrails + strategy params.

Inspired by karpathy/autoresearch experiment loop:
- proposes candidate changes
- backtests all strategies on cached market data
- keeps candidate only if objective improves (consistency + profit + cycle throughput)

Usage:
  python autoresearch_trading.py --cycles 80 --target-trades-per-day 20 --apply
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import config
import database as db
from backtester import Backtester
from binance_client import BinanceClient
from strategies import ALL_STRATEGIES


GUARDRAIL_BOUNDS: Dict[str, Tuple[float, float]] = {
    "MIN_CAGR_THRESHOLD": (0.00, 0.20),
    "MIN_WIN_RATE": (0.20, 0.65),
    "MIN_PROFIT_FACTOR": (1.00, 2.80),
    "MAX_POSITION_PCT": (0.10, 0.50),
    "DEFAULT_STOP_LOSS_PCT": (0.005, 0.060),
    "DEFAULT_TAKE_PROFIT_PCT": (0.010, 0.120),
    "BACKTEST_MIN_SIGNAL_CONFIDENCE": (0.20, 0.70),
}

OUTPUT_DIR = Path(__file__).resolve().parent / "ops" / "autoresearch"
RESULTS_TSV = OUTPUT_DIR / "results.tsv"
BEST_JSON = OUTPUT_DIR / "best_config.json"
CANDLE_INTERVAL_CHOICES = ("5m", "1h", "4h", "1d")


@dataclass
class EvalSummary:
    score: float
    consistency: float
    profit_pct: float
    trades_per_day: float
    live_challenge_score: float
    individual_score: float
    pass_count: int
    total_strategies: int
    metrics_by_strategy: Dict[str, Dict[str, float]]


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def snapshot_config() -> Dict[str, Any]:
    return {
        "guardrails": {k: float(getattr(config, k)) for k in GUARDRAIL_BOUNDS.keys()},
        "strategy_params": copy.deepcopy(config.STRATEGY_PARAMS),
    }


def apply_candidate(candidate: Dict[str, Any]) -> None:
    for k, v in candidate["guardrails"].items():
        setattr(config, k, float(v))

    # reset to baseline then apply overrides
    config.STRATEGY_PARAMS = copy.deepcopy(BASELINE["strategy_params"])
    for strat_name, params in candidate["strategy_params"].items():
        if strat_name in config.STRATEGY_PARAMS and isinstance(params, dict):
            config.STRATEGY_PARAMS[strat_name].update(params)


def build_data_cache(client: BinanceClient) -> Dict[str, Any]:
    cache: Dict[str, Any] = {}
    for strategy_cls in ALL_STRATEGIES:
        strategy = strategy_cls()
        interval = strategy.candle_interval
        if interval in cache:
            continue
        df = client.get_historical_klines(config.SYMBOL, interval, config.BACKTEST_DAYS)
        if df.empty:
            raise RuntimeError(f"No backtest data for interval: {interval}")
        cache[interval] = df
    return cache


def compute_live_challenge_score(days: int = 3, min_live_trades: int = 20) -> float:
    """Score live performance to challenge backtest-fit candidates.

    Returns value in [0, 1]. If low live sample size, returns neutral-leaning score.
    """
    try:
        live = db.get_recent_portfolio_metrics(days=days)
    except Exception:
        return 0.5

    trades = int(live.get("trade_count", 0) or 0)
    if trades <= 0:
        return 0.5

    consistency = (
        0.45 * _clip(float(live.get("win_rate", 0.0)), 0.0, 1.0)
        + 0.35 * _clip(float(live.get("profit_factor", 0.0)) / 2.5, 0.0, 1.0)
        + 0.20 * _clip(1.0 - abs(float(live.get("weekly_drawdown_pct", 0.0))) / 8.0, 0.0, 1.0)
    )
    pnl_score = _clip((float(live.get("weekly_pnl_pct", 0.0)) + 2.0) / 10.0, 0.0, 1.0)
    sample_weight = _clip(trades / max(float(min_live_trades), 1.0), 0.25, 1.0)
    return _clip((0.65 * consistency + 0.35 * pnl_score) * sample_weight, 0.0, 1.0)


def apply_trade_sample_weight(raw_score: float, total_trades: float, min_trades: float) -> float:
    """Downweight strategy score when trade sample size is too small."""
    floor = 0.25
    sample_weight = _clip(float(total_trades) / max(float(min_trades), 1.0), floor, 1.0)
    return float(raw_score * sample_weight)


def compute_walk_forward_stability(equity_curve: List[float], windows: int = 3) -> float:
    """Estimate walk-forward stability from segmented equity returns (higher is better)."""
    if not equity_curve or len(equity_curve) < max(10, windows + 2):
        return 0.5
    w = max(2, int(windows))
    n = len(equity_curve)
    segment = max(2, n // w)
    returns: List[float] = []
    for i in range(0, n, segment):
        chunk = equity_curve[i:i + segment]
        if len(chunk) < 2:
            continue
        start = float(chunk[0])
        end = float(chunk[-1])
        if start <= 0:
            continue
        returns.append((end - start) / start)
    if len(returns) < 2:
        return 0.5
    mean_ret = sum(returns) / len(returns)
    variance = sum((x - mean_ret) ** 2 for x in returns) / len(returns)
    std_ret = variance ** 0.5
    stability = _clip((mean_ret + 0.10) / 0.30, 0.0, 1.0) * _clip(1.0 - std_ret / 0.25, 0.0, 1.0)
    return float(_clip(stability, 0.0, 1.0))


def compute_robustness_score(
    cagr: float,
    win_rate: float,
    profit_factor: float,
    max_drawdown: float,
    daily_pnl_std: float,
    avg_trade_pnl: float,
    walk_forward_stability: float = 0.5,
) -> float:
    """Composite robustness score in [0,1] prioritizing consistency and risk-adjusted returns."""
    consistency = (
        0.35 * _clip(float(win_rate), 0.0, 1.0)
        + 0.30 * _clip(float(profit_factor) / 2.5, 0.0, 1.0)
        + 0.35 * _clip(1.0 - (float(max_drawdown) / 0.35), 0.0, 1.0)
    )
    stability = _clip(1.0 - (float(daily_pnl_std) / 0.08), 0.0, 1.0)
    edge = _clip((float(avg_trade_pnl) + 0.02) / 0.08, 0.0, 1.0)
    growth = _clip((float(cagr) + 0.10) / 0.80, 0.0, 1.0)
    wf = _clip(float(walk_forward_stability), 0.0, 1.0)
    return float(_clip(0.38 * consistency + 0.20 * stability + 0.18 * edge + 0.09 * growth + 0.15 * wf, 0.0, 1.0))


def apply_robustness_gate(score: float, minimum: float) -> bool:
    return float(score) >= float(minimum)


def evaluate(candidate: Dict[str, Any], data_cache: Dict[str, Any], target_trades_per_day: float, live_window_days: int) -> EvalSummary:
    apply_candidate(candidate)

    results = {}
    for strategy_cls in ALL_STRATEGIES:
        strategy = strategy_cls()
        df = data_cache[strategy.candle_interval]
        res = Backtester(strategy, df).run()
        results[strategy.name] = res

    total_trades = sum(r.total_trades for r in results.values())
    trades_per_day = total_trades / max(float(config.BACKTEST_DAYS), 1.0)

    metrics_by_strategy: Dict[str, Dict[str, float]] = {}
    active_scores: List[float] = []
    active_consistency: List[float] = []
    active_cagr: List[float] = []
    pass_count = 0

    min_robustness = float(getattr(config, "AUTORESEARCH_MIN_ROBUSTNESS", 0.55))

    for name, r in results.items():
        consistency = (
            0.45 * _clip(r.win_rate, 0.0, 1.0)
            + 0.30 * _clip(r.profit_factor / 2.5, 0.0, 1.0)
            + 0.25 * _clip(1.0 - (r.max_drawdown / 0.35), 0.0, 1.0)
        )
        profit_component = _clip((r.cagr + 0.10) / 0.80, 0.0, 1.0)
        raw_score = 0.60 * consistency + 0.40 * profit_component
        score_i = apply_trade_sample_weight(
            raw_score=raw_score,
            total_trades=r.total_trades,
            min_trades=float(getattr(config, "MIN_BACKTEST_TRADES", 12)),
        )
        avg_trade_pnl = float(getattr(r, "avg_trade_pnl", 0.0))
        daily_pnl_std = abs(avg_trade_pnl) * 1.5
        walk_forward_stability = compute_walk_forward_stability(
            equity_curve=list(getattr(r, "equity_curve", []) or []),
            windows=int(getattr(config, "AUTORESEARCH_WALK_FORWARD_WINDOWS", 3)),
        )
        robustness = compute_robustness_score(
            cagr=r.cagr,
            win_rate=r.win_rate,
            profit_factor=r.profit_factor,
            max_drawdown=r.max_drawdown,
            daily_pnl_std=daily_pnl_std,
            avg_trade_pnl=avg_trade_pnl,
            walk_forward_stability=walk_forward_stability,
        )
        robust_pass = apply_robustness_gate(robustness, min_robustness)

        metrics_by_strategy[name] = {
            "cagr": float(r.cagr),
            "win_rate": float(r.win_rate),
            "profit_factor": float(r.profit_factor),
            "max_drawdown": float(r.max_drawdown),
            "total_trades": float(r.total_trades),
            "trades_per_day": float(r.total_trades / max(float(config.BACKTEST_DAYS), 1.0)),
            "score": float(score_i),
            "consistency": float(consistency),
            "walk_forward_stability": float(walk_forward_stability),
            "robustness": float(robustness),
            "passes_threshold": 1.0 if r.passes_threshold else 0.0,
            "passes_robustness": 1.0 if robust_pass else 0.0,
            "eligible": 1.0 if (r.passes_threshold and robust_pass) else 0.0,
        }

        if r.passes_threshold and robust_pass:
            pass_count += 1
            active_scores.append(score_i)
            active_consistency.append(consistency)
            active_cagr.append(r.cagr)

    # if nothing passes, still evaluate all (with penalty)
    if not active_scores:
        active_scores = [m["score"] for m in metrics_by_strategy.values()]
        active_consistency = [m["consistency"] for m in metrics_by_strategy.values()]
        active_cagr = [m["cagr"] for m in metrics_by_strategy.values()]

    mean_score = sum(active_scores) / max(len(active_scores), 1)
    mean_consistency = sum(active_consistency) / max(len(active_consistency), 1)
    mean_cagr = sum(active_cagr) / max(len(active_cagr), 1)

    # Individual-strategy objective terms (growth + consistency at strategy level)
    robustness_vals = [float(m.get("robustness", 0.0)) for m in metrics_by_strategy.values()]
    consistency_vals = [float(m.get("consistency", 0.0)) for m in metrics_by_strategy.values()]
    cagr_vals = [float(m.get("cagr", 0.0)) for m in metrics_by_strategy.values()]

    robustness_vals.sort(reverse=True)
    cagr_vals.sort(reverse=True)
    top_k = max(1, len(robustness_vals) // 3)

    top_robustness = sum(robustness_vals[:top_k]) / max(top_k, 1)
    top_growth = sum(cagr_vals[:top_k]) / max(top_k, 1)
    median_consistency = sorted(consistency_vals)[len(consistency_vals) // 2] if consistency_vals else 0.0

    top_growth_norm = _clip((top_growth + 0.10) / 0.80, 0.0, 1.0)
    individual_score = _clip(
        0.48 * top_robustness
        + 0.32 * top_growth_norm
        + 0.20 * _clip(median_consistency, 0.0, 1.0),
        0.0,
        1.0,
    )

    norm_profit = _clip((mean_cagr + 0.10) / 0.80, 0.0, 1.0)
    throughput_ratio = _clip(trades_per_day / max(target_trades_per_day, 1.0), 0.0, 1.0)

    live_challenge_score = compute_live_challenge_score(days=live_window_days, min_live_trades=int(target_trades_per_day * 2))

    objective_mode = str(getattr(config, "AUTORESEARCH_OBJECTIVE_MODE", "individual")).lower().strip()
    if objective_mode == "individual":
        score = (
            0.62 * individual_score
            + 0.20 * throughput_ratio
            + 0.10 * (pass_count / max(len(results), 1))
            + 0.08 * live_challenge_score
        )
    else:
        score = (
            0.42 * mean_consistency
            + 0.22 * norm_profit
            + 0.14 * mean_score
            + 0.12 * throughput_ratio
            + 0.10 * live_challenge_score
        )

    if trades_per_day < target_trades_per_day:
        shortfall = (target_trades_per_day - trades_per_day) / max(target_trades_per_day, 1.0)
        score -= 0.25 * shortfall

    if pass_count == 0:
        score -= 0.08

    return EvalSummary(
        score=float(score),
        consistency=float(mean_consistency),
        profit_pct=float(mean_cagr * 100.0),
        trades_per_day=float(trades_per_day),
        live_challenge_score=float(live_challenge_score),
        individual_score=float(individual_score),
        pass_count=pass_count,
        total_strategies=len(results),
        metrics_by_strategy=metrics_by_strategy,
    )


def mutate_candidate(parent: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    child = copy.deepcopy(parent)

    # mutate 2-4 guardrails each cycle
    guardrail_keys = list(GUARDRAIL_BOUNDS.keys())
    rng.shuffle(guardrail_keys)
    for key in guardrail_keys[: rng.randint(2, 4)]:
        lo, hi = GUARDRAIL_BOUNDS[key]
        current = float(child["guardrails"][key])
        scale = rng.uniform(0.80, 1.25)
        jitter = rng.uniform(-0.03, 0.03)
        proposal = current * scale + jitter
        child["guardrails"][key] = _clip(proposal, lo, hi)

    # keep TP > SL
    child["guardrails"]["DEFAULT_TAKE_PROFIT_PCT"] = max(
        child["guardrails"]["DEFAULT_TAKE_PROFIT_PCT"],
        child["guardrails"]["DEFAULT_STOP_LOSS_PCT"] + 0.004,
    )

    # mutate strategy numeric params
    strat_names = list(child["strategy_params"].keys())
    rng.shuffle(strat_names)
    mutate_count = min(len(strat_names), rng.randint(3, 8))

    for strat_name in strat_names[:mutate_count]:
        params = child["strategy_params"].get(strat_name, {})
        numeric_keys = [
            k for k, v in params.items()
            if isinstance(v, (int, float)) and k not in {"candle_interval"}
        ]
        if not numeric_keys:
            continue

        rng.shuffle(numeric_keys)
        for key in numeric_keys[: rng.randint(1, min(3, len(numeric_keys)))]:
            value = params[key]
            if isinstance(value, bool):
                continue

            if isinstance(value, int):
                step = max(1, int(abs(value) * 0.20))
                proposal = int(value + rng.randint(-step, step))
                params[key] = max(1, proposal)
            else:
                scale = rng.uniform(0.80, 1.30)
                jitter = rng.uniform(-0.05, 0.05)
                proposal = float(value) * scale + jitter
                # generic clamps
                if "rsi" in key.lower():
                    proposal = _clip(proposal, 5.0, 95.0)
                elif "mult" in key.lower() or "threshold" in key.lower():
                    proposal = _clip(proposal, 0.05, 12.0)
                elif "lookback" in key.lower() or "period" in key.lower() or "window" in key.lower() or "ema" in key.lower():
                    proposal = _clip(proposal, 2.0, 400.0)
                else:
                    proposal = max(0.01, proposal)
                params[key] = round(float(proposal), 6)

        # occasional interval mutation to increase/decrease cycle frequency
        if "candle_interval" in params and rng.random() < 0.25:
            params["candle_interval"] = rng.choice(CANDLE_INTERVAL_CHOICES)

    return child


def append_result_row(cycle: int, summary: EvalSummary, status: str, note: str) -> None:
    RESULTS_TSV.parent.mkdir(parents=True, exist_ok=True)
    if not RESULTS_TSV.exists():
        RESULTS_TSV.write_text(
            "cycle\tscore\tconsistency\tprofit_pct\ttrades_per_day\tlive_challenge\tpass_count\tstatus\tnote\n"
        )

    with RESULTS_TSV.open("a", encoding="utf-8") as f:
        f.write(
            f"{cycle}\t{summary.score:.6f}\t{summary.consistency:.6f}\t{summary.profit_pct:.3f}"
            f"\t{summary.trades_per_day:.3f}\t{summary.live_challenge_score:.3f}"
            f"\t{summary.pass_count}/{summary.total_strategies}\t{status}\t{note}\n"
        )


def persist_best(candidate: Dict[str, Any], summary: EvalSummary) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "objective": {
            "score": summary.score,
            "individual_score": summary.individual_score,
            "consistency": summary.consistency,
            "profit_pct": summary.profit_pct,
            "trades_per_day": summary.trades_per_day,
            "live_challenge_score": summary.live_challenge_score,
            "pass_count": summary.pass_count,
            "total_strategies": summary.total_strategies,
            "objective_mode": str(getattr(config, "AUTORESEARCH_OBJECTIVE_MODE", "individual")),
            "target_trades_per_day": float(getattr(config, "AUTORESEARCH_TARGET_TRADES_PER_DAY", 20.0)),
        },
        "guardrails": candidate["guardrails"],
        "strategy_params": candidate["strategy_params"],
        "metrics_by_strategy": summary.metrics_by_strategy,
    }

    BEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    BEST_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Autoresearch optimizer for trading bot")
    p.add_argument("--cycles", type=int, default=80, help="Number of mutation cycles")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument("--target-trades-per-day", type=float, default=None, help="Throughput target")
    p.add_argument("--live-window-days", type=int, default=3, help="Live validation window in days (anti-overfit)")
    p.add_argument("--backtest-days", type=int, default=None, help="Override backtest days for this run")
    p.add_argument("--cache-retries", type=int, default=4, help="Retries for market-data cache bootstrap")
    p.add_argument("--apply", action="store_true", help="Write best candidate to ops/autoresearch/best_config.json")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)

    target_trades_per_day = (
        float(args.target_trades_per_day)
        if args.target_trades_per_day is not None
        else float(getattr(config, "AUTORESEARCH_TARGET_TRADES_PER_DAY", 20.0))
    )

    if args.backtest_days is not None and args.backtest_days >= 60:
        config.BACKTEST_DAYS = int(args.backtest_days)

    print(f"[autoresearch] target trades/day: {target_trades_per_day:.1f}")
    print(f"[autoresearch] objective mode: {str(getattr(config, 'AUTORESEARCH_OBJECTIVE_MODE', 'individual'))}")
    print(f"[autoresearch] backtest days: {int(getattr(config, 'BACKTEST_DAYS', 500))}")
    print("[autoresearch] fetching backtest data cache...")
    client = BinanceClient()

    data_cache = None
    attempts = max(1, int(args.cache_retries))
    for attempt in range(1, attempts + 1):
        try:
            data_cache = build_data_cache(client)
            break
        except Exception as exc:
            if attempt == attempts:
                raise
            wait_s = min(45, 3 * attempt)
            print(f"[autoresearch] cache bootstrap failed ({attempt}/{attempts}): {exc}; retrying in {wait_s}s")
            time.sleep(wait_s)

    if data_cache is None:
        raise RuntimeError("Failed to build market data cache")

    current = snapshot_config()
    baseline_summary = evaluate(current, data_cache, target_trades_per_day, args.live_window_days)
    best = copy.deepcopy(current)
    best_summary = baseline_summary

    append_result_row(0, baseline_summary, "keep", "baseline")
    print(
        f"[baseline] score={baseline_summary.score:.4f} "
        f"individual={baseline_summary.individual_score:.4f} "
        f"consistency={baseline_summary.consistency:.4f} "
        f"profit={baseline_summary.profit_pct:.2f}% "
        f"trades/day={baseline_summary.trades_per_day:.2f} "
        f"live={baseline_summary.live_challenge_score:.3f} "
        f"passes={baseline_summary.pass_count}/{baseline_summary.total_strategies}"
    )

    for cycle in range(1, args.cycles + 1):
        candidate = mutate_candidate(best, rng)
        summary = evaluate(candidate, data_cache, target_trades_per_day, args.live_window_days)

        improve = summary.score > best_summary.score
        meets_flow = summary.trades_per_day >= target_trades_per_day
        baseline_flow_bad = baseline_summary.trades_per_day < target_trades_per_day

        keep = improve and (meets_flow or baseline_flow_bad)

        if keep:
            best = candidate
            best_summary = summary
            append_result_row(cycle, summary, "keep", "promoted")
            print(
                f"[keep:{cycle}] score={summary.score:.4f} "
                f"individual={summary.individual_score:.4f} "
                f"profit={summary.profit_pct:.2f}% trades/day={summary.trades_per_day:.2f} "
                f"live={summary.live_challenge_score:.3f}"
            )
        else:
            append_result_row(cycle, summary, "discard", "no_improvement")

    if args.apply:
        persist_best(best, best_summary)
        print(f"[autoresearch] wrote best config: {BEST_JSON}")
        print("[autoresearch] enable with AUTORESEARCH_USE_OVERRIDES=true")

    print("[done]")
    print(
        f"best score={best_summary.score:.4f} "
        f"individual={best_summary.individual_score:.4f} "
        f"consistency={best_summary.consistency:.4f} "
        f"profit={best_summary.profit_pct:.2f}% "
        f"trades/day={best_summary.trades_per_day:.2f} "
        f"live={best_summary.live_challenge_score:.3f} "
        f"passes={best_summary.pass_count}/{best_summary.total_strategies}"
    )


BASELINE = snapshot_config()


if __name__ == "__main__":
    main()
