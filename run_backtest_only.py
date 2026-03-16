"""
Standalone backtest runner – no live trading.
Run this first to see which strategies pass the 50% CAGR threshold
before committing real capital.

Usage:
    python run_backtest_only.py
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backtest")

import config
import database as db
from binance_client import BinanceClient
from backtester import run_all_backtests, BacktestResult
from strategies import ALL_STRATEGIES

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def main():
    db.init_db()
    client     = BinanceClient()
    strategies = [S() for S in ALL_STRATEGIES]

    logger.info(f"Running {config.BACKTEST_DAYS}-day backtest for {len(strategies)} strategies…")
    results = run_all_backtests(strategies, client)

    # ── Print summary table ────────────────────────────────────────────────
    print("\n" + "="*80)
    print(f"{'Strategy':<22} {'CAGR':>8} {'WinRate':>9} {'ProfFactor':>11} "
          f"{'MaxDD':>8} {'Trades':>7} {'Status':>8}")
    print("-"*80)
    for name, r in results.items():
        status = "✓ PASS" if r.passes_threshold else "✗ FAIL"
        print(
            f"{name:<22} {r.cagr*100:>7.1f}%  {r.win_rate*100:>8.1f}%  "
            f"{r.profit_factor:>10.2f}  {r.max_drawdown*100:>7.1f}%  "
            f"{r.total_trades:>6}  {status:>8}"
        )
    print("="*80)
    print(f"\nThresholds: CAGR≥{config.MIN_CAGR_THRESHOLD*100:.0f}%  "
          f"WinRate≥{config.MIN_WIN_RATE*100:.0f}%  "
          f"ProfFactor≥{config.MIN_PROFIT_FACTOR:.1f}\n")

    # ── Plot equity curves ─────────────────────────────────────────────────
    n     = len(results)
    ncols = min(n, 3)
    nrows = (n + ncols - 1) // ncols

    fig = make_subplots(
        rows=nrows, cols=ncols,
        subplot_titles=list(results.keys()),
        shared_xaxes=False,
    )

    colours = ["#58a6ff", "#3fb950", "#f85149", "#d29922", "#bc8cff"]
    for idx, (name, r) in enumerate(results.items()):
        row = idx // ncols + 1
        col = idx % ncols + 1
        colour = colours[idx % len(colours)]

        fig.add_trace(
            go.Scatter(
                y=r.equity_curve,
                name=name,
                line=dict(color=colour, width=1.5),
                fill="tozeroy",
                fillcolor=f"rgba({int(colour[1:3],16)},{int(colour[3:5],16)},{int(colour[5:7],16)},0.08)",
                showlegend=True,
            ),
            row=row, col=col,
        )

    fig.update_layout(
        title=f"500-Day Backtest – Equity Curves (start ${config.INITIAL_CAPITAL/config.MAX_STRATEGIES:,.0f} each)",
        plot_bgcolor="#0d1117",
        paper_bgcolor="#161b22",
        font_color="#c9d1d9",
        height=max(350 * nrows, 400),
    )
    fig.update_xaxes(gridcolor="#30363d")
    fig.update_yaxes(gridcolor="#30363d", tickprefix="$")

    out_file = "backtest_results.html"
    fig.write_html(out_file)
    logger.info(f"Equity curve chart saved to: {out_file}")
    print(f"\nOpen '{out_file}' in your browser to view the equity curves.\n")


if __name__ == "__main__":
    main()
