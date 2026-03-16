"""
Portfolio Manager
──────────────────
Coordinates capital allocation, order execution, position tracking,
and stop-loss / take-profit enforcement across all active strategies.

Each strategy receives an equal share of total capital.
If a strategy's drawdown exceeds MAX_PORTFOLIO_DRAWDOWN_PCT its allocation
is frozen (no new entries) until it recovers.

Changes:
  - Replaced deprecated datetime.utcnow() with utils.utc_now()
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config
import database as db
from binance_client import BinanceClient
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from utils import utc_now, utc_now_iso

logger = logging.getLogger(__name__)


class PortfolioManager:

    def __init__(self, client: BinanceClient,
                 strategies: List[BaseStrategy]):
        self.client      = client
        self.strategies  = {s.name: s for s in strategies}
        self._lock       = threading.Lock()

        # In-memory capital state (persisted to DB periodically)
        self._capital: Dict[str, float] = {}
        self._peak_capital: Dict[str, float] = {}

        self._allocate_capital()

    # ─── Capital allocation ───────────────────────────────────────────────────

    def _allocate_capital(self, current_price: float = 0.0):
        """
        Split initial capital equally among active strategies.
        Includes realized P&L from closed trades and unrealized P&L from open positions.
        """
        active  = [s for s in self.strategies.values() if s.is_active]
        n       = max(len(active), 1)
        share   = config.INITIAL_CAPITAL / n
        for strat in active:
            # Reconstruct true capital from first principles:
            #   total_cap = initial share + realized P&L + unrealized P&L
            #   free_cap  = total_cap - notional locked in open positions
            stats     = db.get_trade_stats(strat.name)
            realized  = float(stats.get("total_pnl") or 0)

            # Compute unrealized P&L from current open positions
            open_pos  = db.get_open_positions(strat.name)
            committed = 0.0
            unrealized = 0.0
            for p in open_pos:
                ep = float(p["entry_price"])
                qty = float(p["quantity"])
                committed += ep * qty
                if current_price > 0:
                    if p["side"] == "LONG":
                        unrealized += (current_price - ep) * qty
                    else:
                        unrealized += (ep - current_price) * qty

            # Total capital includes both realized and unrealized gains
            total_cap = share + realized + unrealized
            free_cap = max(total_cap - committed, 0)

            self._capital[strat.name]      = free_cap
            self._peak_capital[strat.name] = total_cap   # peak tracks total, not free
            strat.set_capital(free_cap)

            # Keep DB in sync so dashboards and future restarts see the right value.
            # Store TOTAL allocated capital (not free), so dashboard shows consistent values
            # across all strategies and user isn't confused by lower numbers when positions open.
            db.update_strategy_capital(strat.name, total_cap)
            logger.info(
                f"  {strat.name}: ${free_cap:,.2f} free  "
                f"(${total_cap:,.2f} total, ${committed:,.2f} committed)"
            )

    def reallocate(self, current_price: float = 0.0):
        """Re-balance capital from strategies that are inactive or over-limit."""
        self._allocate_capital(current_price)

    # ─── Main entry-point called by the bot loop ──────────────────────────────

    def process_signal(self, strategy: BaseStrategy,
                       signal: Signal,
                       current_price: float,
                       ml_confidence: float = 0.5) -> bool:
        """
        Evaluate a signal from a strategy and execute if conditions are met.
        Returns True if an order was placed.
        """
        if not strategy.is_active:
            return False
        if not signal.is_actionable:
            return False

        with self._lock:
            strat_name = strategy.name

            # ── Risk checks ───────────────────────────────────────────────────
            if not self._risk_check(strat_name, signal, ml_confidence):
                return False

            open_positions = db.get_open_positions(strat_name)
            if len(open_positions) >= config.MAX_OPEN_POSITIONS_PER_STRATEGY:
                logger.debug(f"{strat_name}: max open positions reached")
                return False

            capital = self._capital.get(strat_name, 0.0)
            if capital < 50:
                logger.warning(f"{strat_name}: insufficient capital (${capital:.2f})")
                return False

            # ── Position sizing ───────────────────────────────────────────────
            quantity, notional = self._size_position(
                capital, current_price, signal, ml_confidence
            )
            if quantity <= 0:
                return False

            # ── Place order ───────────────────────────────────────────────────
            side = "BUY" if signal.type == SignalType.BUY else "SELL"
            order = self.client.place_market_order(config.SYMBOL, side, quantity)
            if order is None:
                logger.error(f"{strat_name}: order placement failed")
                return False

            # Actual fill price (slippage included in demo mode)
            fill_price = self._get_fill_price(order, current_price)

            sl  = signal.stop_loss  or fill_price * (
                (1 - config.DEFAULT_STOP_LOSS_PCT) if side == "BUY"
                else (1 + config.DEFAULT_STOP_LOSS_PCT)
            )
            tp  = signal.take_profit or fill_price * (
                (1 + config.DEFAULT_TAKE_PROFIT_PCT) if side == "BUY"
                else (1 - config.DEFAULT_TAKE_PROFIT_PCT)
            )

            pos_id = db.open_position(
                strategy_name=strat_name,
                symbol=config.SYMBOL,
                side="LONG" if side == "BUY" else "SHORT",
                entry_price=fill_price,
                quantity=quantity,
                stop_loss=sl,
                take_profit=tp,
                order_id=str(order.get("orderId", "")),
                ml_confidence=ml_confidence,
                metadata=signal.metadata or {},
            )

            # Deduct reserved capital (notional value)
            self._capital[strat_name] -= notional
            db.update_strategy_capital(strat_name, self._capital[strat_name])

            logger.info(
                f"[{strat_name}] OPEN {side} {quantity:.5f} BTC @ ${fill_price:,.2f} "
                f"| SL=${sl:,.2f} TP=${tp:,.2f} | notional=${notional:,.2f}"
            )
            return True

    # ─── Position monitoring ──────────────────────────────────────────────────

    def check_open_positions(self, current_price: float):
        """
        Check all open positions against current price.
        Close any that have hit SL or TP.
        """
        positions = db.get_open_positions()
        for pos in positions:
            hit, reason = self._check_sl_tp(pos, current_price)
            if hit:
                self._close_position(pos, current_price, reason)

    def _check_sl_tp(self, pos: dict, price: float) -> tuple:
        """Returns (True, reason) if position should be closed."""
        if pos["side"] == "LONG":
            if price <= pos["stop_loss"]:
                return True, "STOP_LOSS"
            if price >= pos["take_profit"]:
                return True, "TAKE_PROFIT"
        else:  # SHORT
            if price >= pos["stop_loss"]:
                return True, "STOP_LOSS"
            if price <= pos["take_profit"]:
                return True, "TAKE_PROFIT"
        return False, ""

    def close_position_by_signal(self, strategy: BaseStrategy,
                                 current_price: float):
        """Force-close open positions for a strategy on a reversal signal."""
        positions = db.get_open_positions(strategy.name)
        for pos in positions:
            self._close_position(pos, current_price, "SIGNAL_EXIT")

    def _close_position(self, pos: dict, current_price: float, reason: str):
        strat_name = pos["strategy_name"]
        side  = pos["side"]
        qty   = float(pos["quantity"])
        entry = float(pos["entry_price"])

        # Place exit order
        exit_side = "SELL" if side == "LONG" else "BUY"
        order = self.client.place_market_order(config.SYMBOL, exit_side, qty)
        if order is None:
            logger.error(f"Could not close position {pos['id']} for {strat_name}")
            return

        exit_price = self._get_fill_price(order, current_price)

        # PnL calculation
        fee_cost = entry * qty * (config.TRADING_FEE + config.SLIPPAGE) * 2
        if side == "LONG":
            raw_pnl = (exit_price - entry) * qty
        else:
            raw_pnl = (entry - exit_price) * qty

        net_pnl  = raw_pnl - fee_cost
        pnl_pct  = raw_pnl / (entry * qty) if entry * qty > 0 else 0

        entry_dt = pos.get("entry_time", utc_now_iso())
        exit_dt  = utc_now_iso()
        try:
            dur_hours = (
                datetime.fromisoformat(exit_dt) - datetime.fromisoformat(entry_dt)
            ).total_seconds() / 3600
        except Exception:
            dur_hours = 0.0

        entry_features = pos.get("metadata", {})
        trade_id = db.record_trade(
            strategy_name=strat_name,
            symbol=config.SYMBOL,
            side=side,
            entry_price=entry,
            exit_price=exit_price,
            quantity=qty,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            fees_paid=fee_cost,
            entry_time=entry_dt,
            exit_time=exit_dt,
            duration_hours=dur_hours,
            exit_reason=reason,
            entry_features=entry_features,
        )

        db.close_position(pos["id"])

        # Return notional + pnl to strategy capital
        recovered = entry * qty + net_pnl
        with self._lock:
            self._capital[strat_name] = self._capital.get(strat_name, 0) + recovered
            cap = self._capital[strat_name]
            db.update_strategy_capital(strat_name, cap)
            # Update peak for drawdown tracking
            if cap > self._peak_capital.get(strat_name, cap):
                self._peak_capital[strat_name] = cap
            strat = self.strategies.get(strat_name)
            if strat:
                strat.set_capital(cap)
                strat.record_trade_outcome(net_pnl > 0)

        logger.info(
            f"[{strat_name}] CLOSE {side} {qty:.5f} BTC @ ${exit_price:,.2f} "
            f"| PnL ${net_pnl:+.2f} ({pnl_pct*100:+.2f}%) | {reason}"
        )

        return trade_id, net_pnl, pnl_pct, dur_hours, entry_features

    # ─── Risk checks ──────────────────────────────────────────────────────────

    def _risk_check(self, strat_name: str, signal: Signal,
                    ml_confidence: float) -> bool:
        # ML confidence filter
        if ml_confidence < config.CONFIDENCE_THRESHOLD:
            logger.debug(f"{strat_name}: ML confidence {ml_confidence:.2f} below threshold")
            return False

        # Drawdown guard
        cap  = self._capital.get(strat_name, 0)
        peak = self._peak_capital.get(strat_name, cap)
        if peak > 0 and (peak - cap) / peak > config.MAX_PORTFOLIO_DRAWDOWN_PCT:
            logger.warning(f"{strat_name}: drawdown limit hit – pausing new entries")
            return False

        # Signal confidence
        if signal.confidence < 0.42:
            return False

        return True

    # ─── Position sizing ──────────────────────────────────────────────────────

    def _size_position(self, capital: float, price: float,
                       signal: Signal, ml_confidence: float
                       ) -> tuple:
        """
        Kelly-adjusted position sizing.
        Returns (quantity_btc, notional_usd).
        """
        # Base notional as fraction of capital
        base_pct = config.MAX_POSITION_PCT * 0.6   # conservative default
        # Scale by signal confidence (0.45–0.95 maps to 0.5–1.2×)
        conf_scale = 0.5 + signal.confidence
        # Scale by ML confidence
        ml_scale   = 0.8 + ml_confidence * 0.4
        notional   = capital * base_pct * conf_scale * ml_scale
        notional   = min(notional, capital * config.MAX_POSITION_PCT)
        notional   = max(notional, 10.0)     # at least $10

        quantity = notional / price
        return round(quantity, 5), notional

    # ─── Account state ────────────────────────────────────────────────────────

    def total_balance(self, current_price: float) -> dict:
        """Return a dict with total balance, realized and unrealized PnL."""
        realized_sum = 0.0
        unrealized   = 0.0
        breakdown    = {}

        for strat_name, strat in self.strategies.items():
            if not strat.is_active:
                continue
            cap = self._capital.get(strat_name, 0.0)
            stats = db.get_trade_stats(strat_name)
            realized = float(stats.get("total_pnl") or 0)
            realized_sum += realized

            # Unrealized from open positions
            open_pos = db.get_open_positions(strat_name)
            unreal = 0.0
            committed_notional = 0.0
            for p in open_pos:
                ep  = float(p["entry_price"])
                qty = float(p["quantity"])
                committed_notional += ep * qty  # notional locked in position
                if p["side"] == "LONG":
                    unreal += (current_price - ep) * qty
                else:
                    unreal += (ep - current_price) * qty
            unrealized += unreal

            # Total allocated = free capital + committed notional
            total_allocated = cap + committed_notional
            # True total capital includes realized + unrealized P&L
            true_total = total_allocated + unreal

            breakdown[strat_name] = {
                "capital": true_total,  # total allocated including P&L (realized + unrealized)
                "free_capital": cap,  # available for new trades
                "realized_pnl": realized,
                "unrealized_pnl": unreal,
                "open_positions": len(open_pos),
                "committed_notional": committed_notional,
                "current_price": current_price,
            }

        total_free  = sum(self._capital.get(s, 0) for s in self.strategies if self.strategies[s].is_active)
        total_bal   = total_free + unrealized + sum(
            float(p["entry_price"]) * float(p["quantity"])
            for p in db.get_open_positions()
        )

        return {
            "total_balance": round(total_bal, 2),
            "free_capital": round(total_free, 2),
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(realized_sum, 2),
            "breakdown": breakdown,
        }

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _get_fill_price(order: dict, fallback: float) -> float:
        """Extract average fill price from a Binance order response."""
        try:
            fills = order.get("fills", [])
            if fills:
                total_qty   = sum(float(f["qty"]) for f in fills)
                total_quote = sum(float(f["price"]) * float(f["qty"]) for f in fills)
                return total_quote / (total_qty + 1e-8)
            # Fallback: cummulativeQuoteQty / executedQty
            exec_qty   = float(order.get("executedQty", 0))
            quote_qty  = float(order.get("cummulativeQuoteQty", 0))
            if exec_qty > 0:
                return quote_qty / exec_qty
        except Exception:
            pass
        return fallback
