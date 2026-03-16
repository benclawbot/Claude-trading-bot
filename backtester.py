"""
Backtesting Engine
──────────────────
Vectorised walk-forward backtest over 500 days of hourly OHLCV data.
For each strategy it simulates every candle in order, checks for:
  1. Entry signals
  2. Stop-loss / take-profit hits on open positions
  3. Exit signals

Reports: CAGR, Win-Rate, Profit Factor, Max Drawdown, Sharpe Ratio, total trades.
Only strategies that pass MIN_CAGR_THRESHOLD are activated.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config
from strategies.base_strategy import BaseStrategy, Signal, SignalType

logger = logging.getLogger(__name__)


@dataclass
class BacktestPosition:
    side: str                          # LONG or SHORT
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    entry_idx: int
    entry_time: datetime
    confidence: float = 0.5
    max_hold: int = 48                 # per-strategy max hold (candles)


@dataclass
class BacktestTrade:
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fees: float
    entry_time: datetime
    exit_time: datetime
    duration_hours: float
    exit_reason: str


@dataclass
class BacktestResult:
    strategy_name: str
    cagr: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    total_pnl_pct: float
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    avg_hold_hours: float
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    passes_threshold: bool = False

    def summary(self) -> str:
        status = "✓ PASS" if self.passes_threshold else "✗ FAIL"
        return (
            f"[{status}] {self.strategy_name}: "
            f"CAGR={self.cagr*100:.1f}% | "
            f"WinRate={self.win_rate*100:.1f}% | "
            f"PF={self.profit_factor:.2f} | "
            f"MaxDD={self.max_drawdown*100:.1f}% | "
            f"Trades={self.total_trades}"
        )


class Backtester:
    """
    Runs a single-strategy backtest over a pre-fetched OHLCV DataFrame.
    Capital is split from config.INITIAL_CAPITAL / MAX_STRATEGIES.
    """

    def __init__(self, strategy: BaseStrategy, df: pd.DataFrame,
                 initial_capital: float = None):
        self.strategy = strategy
        self.df = df.copy().reset_index(drop=True)
        self.initial_capital = initial_capital or (
            config.INITIAL_CAPITAL / config.MAX_STRATEGIES
        )

    def run(self) -> BacktestResult:
        strat   = self.strategy
        df      = self.df
        capital = self.initial_capital
        equity  = [capital]
        trades: List[BacktestTrade] = []
        position: Optional[BacktestPosition] = None

        fee_rt = config.TRADING_FEE + config.SLIPPAGE   # round-trip half
        min_c  = strat.min_candles
        max_pos_pct = config.MAX_POSITION_PCT

        for i in range(min_c, len(df)):
            row   = df.iloc[i]
            close = float(row["close"])
            high  = float(row["high"])
            low   = float(row["low"])
            ts    = row.name if hasattr(row.name, "isoformat") else datetime.utcnow()

            # ── Manage open position ──────────────────────────────────────────
            if position is not None:
                exit_reason, exit_price = self._check_exit(
                    position, high, low, close, df, i
                )
                if exit_reason:
                    trade = self._close_position(
                        position, exit_price, ts, exit_reason, fee_rt
                    )
                    trades.append(trade)
                    capital += trade.pnl - trade.fees
                    position = None
                    equity.append(capital)
                    continue

            # ── Look for new entry (no pyramiding) ────────────────────────────
            if position is None:
                window = df.iloc[max(0, i - strat.min_candles): i + 1]
                signal: Signal = strat.generate_signal(window)

                if signal.is_actionable and signal.confidence >= 0.45:
                    qty_capital = capital * max_pos_pct * signal.confidence
                    qty_capital = min(qty_capital, capital * 0.60)   # hard cap
                    quantity    = qty_capital / close
                    if quantity * close < 10:   # min $10 order
                        continue

                    sl = signal.stop_loss  or close * (1 - config.DEFAULT_STOP_LOSS_PCT)
                    tp = signal.take_profit or close * (1 + config.DEFAULT_TAKE_PROFIT_PCT)
                    if signal.type == SignalType.SELL:
                        sl = signal.stop_loss  or close * (1 + config.DEFAULT_STOP_LOSS_PCT)
                        tp = signal.take_profit or close * (1 - config.DEFAULT_TAKE_PROFIT_PCT)

                    position = BacktestPosition(
                        side="LONG" if signal.type == SignalType.BUY else "SHORT",
                        entry_price=close * (1 + fee_rt),   # include entry slippage
                        quantity=quantity,
                        stop_loss=sl,
                        take_profit=tp,
                        entry_idx=i,
                        entry_time=ts,
                        confidence=signal.confidence,
                        max_hold=strat.max_hold_candles,
                    )

            equity.append(capital)

        # Close any leftover open position at last price
        if position is not None:
            last_close = float(df.iloc[-1]["close"])
            last_ts    = df.index[-1] if hasattr(df.index[-1], "isoformat") else datetime.utcnow()
            trade = self._close_position(position, last_close, last_ts, "END_OF_DATA", fee_rt)
            trades.append(trade)
            capital += trade.pnl - trade.fees

        equity.append(capital)
        return self._compute_metrics(trades, equity, len(df))

    # ─── Exit logic ───────────────────────────────────────────────────────────

    @staticmethod
    def _check_exit(pos: BacktestPosition, high: float, low: float,
                    close: float, df: pd.DataFrame, i: int
                    ) -> Tuple[Optional[str], float]:
        """Returns (reason, exit_price) or (None, 0)."""
        max_hold = getattr(pos, "max_hold", 48)
        if pos.side == "LONG":
            if low <= pos.stop_loss:
                return "STOP_LOSS", pos.stop_loss
            if high >= pos.take_profit:
                return "TAKE_PROFIT", pos.take_profit
            if i - pos.entry_idx >= max_hold:
                return "MAX_HOLD", close
        else:   # SHORT
            if high >= pos.stop_loss:
                return "STOP_LOSS", pos.stop_loss
            if low <= pos.take_profit:
                return "TAKE_PROFIT", pos.take_profit
            if i - pos.entry_idx >= max_hold:
                return "MAX_HOLD", close
        return None, 0.0

    @staticmethod
    def _close_position(pos: BacktestPosition, exit_price: float,
                        exit_time: datetime, reason: str,
                        fee_rt: float) -> BacktestTrade:
        if pos.side == "LONG":
            raw_pnl = (exit_price - pos.entry_price) * pos.quantity
            pnl_pct = (exit_price / pos.entry_price) - 1
        else:
            raw_pnl = (pos.entry_price - exit_price) * pos.quantity
            pnl_pct = (pos.entry_price / exit_price) - 1

        fees = pos.entry_price * pos.quantity * fee_rt  # exit fee ≈ entry fee

        duration = 0.0
        if hasattr(exit_time, "hour") and hasattr(pos.entry_time, "hour"):
            try:
                delta = (exit_time - pos.entry_time).total_seconds() / 3600
                duration = max(delta, 0.0)
            except Exception:
                pass

        return BacktestTrade(
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl=raw_pnl,
            pnl_pct=pnl_pct,
            fees=fees,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            duration_hours=duration,
            exit_reason=reason,
        )

    # ─── Metrics ─────────────────────────────────────────────────────────────

    def _compute_metrics(self, trades: List[BacktestTrade],
                         equity: List[float], n_candles: int) -> BacktestResult:
        strat_name = self.strategy.name

        if not trades:
            return BacktestResult(
                strategy_name=strat_name, cagr=0, win_rate=0, profit_factor=0,
                max_drawdown=0, sharpe_ratio=0, sortino_ratio=0, total_trades=0,
                winning_trades=0, losing_trades=0, total_pnl=0, total_pnl_pct=0,
                avg_trade_pnl=0, avg_win=0, avg_loss=0, avg_hold_hours=0,
                trades=[], equity_curve=equity, passes_threshold=False,
            )

        wins   = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        total_pnl  = sum(t.pnl - t.fees for t in trades)
        win_rate   = len(wins) / len(trades)
        gross_win  = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses)) + 1e-8
        pf         = gross_win / gross_loss

        # CAGR: approximate days from candle count (interval-aware)
        interval_h = {"1h": 1, "4h": 4, "1d": 24}.get(
            self.strategy.candle_interval, 1
        )
        days = n_candles * interval_h / 24
        years = max(days / 365, 0.001)
        final_capital = equity[-1]
        cagr = (final_capital / self.initial_capital) ** (1 / years) - 1

        # Max drawdown
        eq_arr  = np.array(equity)
        peak    = np.maximum.accumulate(eq_arr)
        dd      = (peak - eq_arr) / (peak + 1e-8)
        max_dd  = float(dd.max())

        # Sharpe / Sortino on per-trade returns
        returns = np.array([t.pnl_pct for t in trades])
        rf = 0.0
        if len(returns) > 1:
            sr = float((returns.mean() - rf) / (returns.std() + 1e-8))
            neg = returns[returns < 0]
            sortino = float((returns.mean() - rf) / (neg.std() + 1e-8)) if len(neg) > 1 else 0.0
        else:
            sr = sortino = 0.0

        passes = (
            cagr >= config.MIN_CAGR_THRESHOLD and
            win_rate >= config.MIN_WIN_RATE and
            pf >= config.MIN_PROFIT_FACTOR
        )

        return BacktestResult(
            strategy_name=strat_name,
            cagr=cagr,
            win_rate=win_rate,
            profit_factor=pf,
            max_drawdown=max_dd,
            sharpe_ratio=sr,
            sortino_ratio=sortino,
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl / self.initial_capital,
            avg_trade_pnl=np.mean([t.pnl for t in trades]),
            avg_win=np.mean([t.pnl for t in wins]) if wins else 0,
            avg_loss=np.mean([t.pnl for t in losses]) if losses else 0,
            avg_hold_hours=np.mean([t.duration_hours for t in trades]),
            trades=trades,
            equity_curve=equity,
            passes_threshold=passes,
        )


# ─── Multi-strategy runner ────────────────────────────────────────────────────

def run_all_backtests(strategies: List[BaseStrategy],
                      client) -> Dict[str, BacktestResult]:
    """
    Fetch 500 days of data for each strategy's interval and run backtests.
    Returns a dict of strategy_name -> BacktestResult.
    """
    results = {}
    logger.info(f"Running backtests for {len(strategies)} strategies over {config.BACKTEST_DAYS} days...")

    cache: Dict[str, pd.DataFrame] = {}   # avoid re-fetching same interval

    for strat in strategies:
        interval = strat.candle_interval
        if interval not in cache:
            logger.info(f"Fetching {config.BACKTEST_DAYS}-day history ({interval})...")
            df = client.get_historical_klines(
                config.SYMBOL, interval, config.BACKTEST_DAYS
            )
            if df.empty:
                logger.error(f"No data for interval {interval}. Skipping.")
                continue
            cache[interval] = df

        df = cache[interval]
        bt = Backtester(strat, df)
        result = bt.run()
        results[strat.name] = result
        logger.info(result.summary())

    return results
