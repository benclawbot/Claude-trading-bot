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

import numpy as np

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

        # Warning suppression state to avoid log spam from persistent guard conditions.
        # key -> last warning timestamp (epoch seconds)
        self._warning_last_emit: Dict[str, float] = {}

    # ─── Capital allocation ───────────────────────────────────────────────────

    def _allocate_capital(self, current_price: float = 0.0):
        """
        Split initial capital equally among active strategies.
        Includes realized P&L from closed trades and unrealized P&L from open positions.
        """
        active = [s for s in self.strategies.values() if s.is_active]
        if not active:
            return

        # Optional experiment-mode weighted allocation:
        # reserve a fixed capital pool for experiment strategies.
        # Default behavior is equal allocation across active strategies.
        raw_alloc_mode = getattr(config, "CAPITAL_ALLOCATION_MODE", "equal")
        alloc_mode = raw_alloc_mode.lower() if isinstance(raw_alloc_mode, str) else "equal"

        exp_enabled = (
            alloc_mode == "experiment_weighted"
            and self._as_bool(getattr(config, "EXPERIMENT_MODE_ENABLED", False), False)
        )
        exp_cap_pct = max(0.0, min(1.0, self._as_float(getattr(config, "EXPERIMENT_MODE_CAPITAL_PCT", 0.20), 0.20)))

        raw_exp_names = getattr(config, "EXPERIMENT_MODE_STRATEGIES", set())
        if isinstance(raw_exp_names, str):
            exp_names = {s.strip() for s in raw_exp_names.split(",") if s.strip()}
        elif isinstance(raw_exp_names, (set, list, tuple)):
            exp_names = {str(s).strip() for s in raw_exp_names if str(s).strip()}
        else:
            exp_names = set()

        exp_active = [s for s in active if s.name in exp_names] if exp_enabled else []
        core_active = [s for s in active if s.name not in exp_names] if exp_enabled else active

        if exp_enabled and exp_active and core_active:
            experiment_pool = config.INITIAL_CAPITAL * exp_cap_pct
            core_pool = max(config.INITIAL_CAPITAL - experiment_pool, 0.0)
            core_share = core_pool / len(core_active)
            exp_share = experiment_pool / len(exp_active)
        else:
            # Fallback to equal weighting when experiment mode is off or only one side exists.
            core_share = config.INITIAL_CAPITAL / len(active)
            exp_share = core_share

        for strat in active:
            share = exp_share if (exp_enabled and strat.name in exp_names and exp_active and core_active) else core_share
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

            decision_ts = utc_now_iso()
            side = "BUY" if signal.type == SignalType.BUY else "SELL"

            # ── Position sizing ───────────────────────────────────────────────
            quantity, notional = self._size_position(
                capital, current_price, signal, ml_confidence, strategy_name=strat_name
            )
            if quantity <= 0:
                return False

            raw_meta = signal.metadata if isinstance(signal.metadata, dict) else {}
            decision_meta = dict(raw_meta)
            default_stop = current_price * (
                (1 - config.DEFAULT_STOP_LOSS_PCT) if side == "BUY"
                else (1 + config.DEFAULT_STOP_LOSS_PCT)
            )
            default_tp = current_price * (
                (1 + config.DEFAULT_TAKE_PROFIT_PCT) if side == "BUY"
                else (1 - config.DEFAULT_TAKE_PROFIT_PCT)
            )
            planned_stop = float(signal.stop_loss or default_stop)
            planned_tp = float(signal.take_profit or default_tp)
            risk_budget_bps = abs((current_price - planned_stop) / current_price) * 10000 if current_price > 0 else None
            stop_loss_bps = (abs((current_price - planned_stop) / current_price) * 10000) if current_price > 0 else None
            take_profit_bps = (abs((planned_tp - current_price) / current_price) * 10000) if current_price > 0 else None

            decision_trade_id = db.record_trade_decision(
                symbol=config.SYMBOL,
                timeframe=str(decision_meta.get("timeframe") or "unknown"),
                strategy_id=strat_name,
                regime_id=str(decision_meta.get("regime") or "unknown"),
                side="long" if side == "BUY" else "short",
                confidence_raw=float(signal.confidence),
                confidence_calibrated=float(ml_confidence),
                expected_horizon_min=self._to_int(decision_meta.get("expected_horizon_min")),
                expected_move_bps=self._to_float(decision_meta.get("expected_move_bps")),
                risk_budget_bps=risk_budget_bps,
                stop_loss_bps=stop_loss_bps,
                take_profit_bps=take_profit_bps,
                feature_snapshot=decision_meta,
                model_version=str(decision_meta.get("model_version") or "unknown"),
                policy_version=str(decision_meta.get("policy_version") or "default"),
                decision_reason_short=str(decision_meta.get("reason") or signal.type.value),
                paper_or_live="live" if getattr(config, "LIVE_TRADING", True) else "paper",
            )

            # ── Place order ───────────────────────────────────────────────────
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

            slippage_bps = None
            if current_price > 0:
                slippage_bps = ((fill_price - current_price) / current_price) * 10000
            decision_latency_ms = self._latency_ms(decision_ts, utc_now_iso())
            exec_score = None
            if slippage_bps is not None:
                exec_score = max(0.0, 100.0 - min(abs(slippage_bps) * 8.0, 100.0))

            db.record_trade_execution(
                trade_id=decision_trade_id,
                exchange="binance",
                order_type="MARKET",
                order_qty=quantity,
                avg_fill_price=fill_price,
                mid_at_send=current_price,
                spread_bps_at_send=self._to_float(decision_meta.get("spread_bps")),
                slippage_bps=slippage_bps,
                fees_bps=float(getattr(config, "TRADING_FEE", 0.0)) * 10000,
                latency_ms_signal_to_send=decision_latency_ms,
                latency_ms_send_to_fill=None,
                execution_quality_score=exec_score,
                ts_order_sent=utc_now_iso(),
                ts_first_fill=utc_now_iso(),
                ts_full_fill=utc_now_iso(),
            )

            metadata = dict(decision_meta)
            metadata["decision_trade_id"] = decision_trade_id

            if not self.client.is_paper_trading and side == "BUY":
                try:
                    oco = self.client.place_oco_order(
                        config.SYMBOL,
                        "SELL",
                        quantity,
                        stop_price=float(sl),
                        limit_price=float(sl),
                        take_profit=float(tp),
                    )
                    if oco:
                        metadata["oco_order"] = oco
                except Exception as e:
                    logger.warning(f"{strat_name}: failed to attach OCO protection: {e}")

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
                metadata=metadata,
            )

            # Deduct reserved capital (notional value)
            self._capital[strat_name] -= notional
            db.update_strategy_capital(strat_name, self._capital[strat_name])

            # Notify via Telegram
            self._send_telegram(
                f"📊 **Trade Opened**\n"
                f"Strategy: `{strat_name}`\n"
                f"Side: **{side}**\n"
                f"Entry: ${fill_price:,.2f}\n"
                f"SL: ${sl:,.2f} | TP: ${tp:,.2f}\n"
                f"ML confidence: {ml_confidence:.0%}"
            )

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

    @staticmethod
    def _check_sl_tp(pos: dict, price: float) -> tuple:
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

    @staticmethod
    def _extract_oco_order(meta: dict):
        if not isinstance(meta, dict):
            return None
        oco = meta.get("oco_order")
        return oco if isinstance(oco, dict) else None

    def _close_position(self, pos: dict, current_price: float, reason: str):
        strat_name = pos["strategy_name"]
        side  = pos["side"]
        qty   = float(pos["quantity"])
        entry = float(pos["entry_price"])

        entry_features = pos.get("metadata", {})
        # Reconciliation: on manual/signal exits, cancel any attached exchange OCO first.
        if reason in {"SIGNAL_EXIT", "MANUAL"}:
            oco_order = self._extract_oco_order(entry_features)
            if oco_order:
                try:
                    cancelled = bool(self.client.cancel_oco_order(config.SYMBOL, oco_order))
                    logger.info(f"[{strat_name}] OCO reconcile before {reason}: cancelled={cancelled}")
                except Exception as e:
                    logger.warning(f"[{strat_name}] OCO reconcile failed: {e}")

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

        decision_trade_id = str(entry_features.get("decision_trade_id", "")).strip() if isinstance(entry_features, dict) else ""
        if decision_trade_id:
            pnl_bps_gross = (pnl_pct * 10000) if pnl_pct is not None else None
            notional = entry * qty
            pnl_bps_net = (net_pnl / notional) * 10000 if notional > 0 else None
            outcome_label = "win" if net_pnl > 0 else ("loss" if net_pnl < 0 else "flat")
            quality_label = "good_shift" if reason == "TAKE_PROFIT" else ("fakeout" if reason == "STOP_LOSS" else "noise")
            db.record_trade_outcome(
                trade_id=decision_trade_id,
                horizon_min=max(1, int(round(dur_hours * 60))),
                pnl_bps_gross=pnl_bps_gross,
                pnl_bps_net=pnl_bps_net,
                mae_bps=self._to_float(entry_features.get("mae_bps")),
                mfe_bps=self._to_float(entry_features.get("mfe_bps")),
                stopped_out=(reason == "STOP_LOSS"),
                tp_hit=(reason == "TAKE_PROFIT"),
                early_exit=(reason in {"SIGNAL_EXIT", "MANUAL"}),
                outcome_label=outcome_label,
                quality_label=quality_label,
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

        self._send_telegram(
            f"✅ **Trade Closed**\n"
            f"Strategy: `{strat_name}`\n"
            f"Side: **{side}**\n"
            f"Exit: ${exit_price:,.2f}\n"
            f"PnL: ${net_pnl:+.2f} ({pnl_pct*100:+.2f}%)\n"
            f"Reason: {reason}"
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
        drawdown_key = f"drawdown:{strat_name}"
        drawdown = ((peak - cap) / peak) if peak > 0 else 0.0
        if peak > 0 and drawdown > config.MAX_PORTFOLIO_DRAWDOWN_PCT:
            self._warn_throttled(
                drawdown_key,
                (
                    f"{strat_name}: drawdown limit hit ({drawdown:.2%} > "
                    f"{config.MAX_PORTFOLIO_DRAWDOWN_PCT:.2%}) – pausing new entries"
                ),
                cooldown_seconds=1800,
            )
            return False
        else:
            self._clear_warning_throttle(drawdown_key)

        # Regime router guard
        if not self._regime_router_allows_entry(strat_name, signal):
            return False

        # Experiment lane allocation cap guard
        if not self._experiment_lane_allows_entry(strat_name):
            return False

        # Signal confidence
        if signal.confidence < 0.42:
            return False

        return True

    # ─── Experiment-lane allocation guard ─────────────────────────────────────

    @staticmethod
    def _as_bool(value, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default

    @staticmethod
    def _as_float(value, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _to_float(value) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _to_int(value) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _latency_ms(start_iso: str, end_iso: str) -> Optional[int]:
        try:
            start_dt = datetime.fromisoformat(start_iso)
            end_dt = datetime.fromisoformat(end_iso)
            return max(0, int((end_dt - start_dt).total_seconds() * 1000))
        except Exception:
            return None

    def _warn_throttled(self, key: str, message: str, cooldown_seconds: int = 1800) -> None:
        """Emit a warning at most once per cooldown window for a given key."""
        now_ts = utc_now().timestamp()
        last_ts = self._warning_last_emit.get(key)
        if last_ts is None or (now_ts - last_ts) >= cooldown_seconds:
            logger.warning(message)
            self._warning_last_emit[key] = now_ts

    def _clear_warning_throttle(self, key: str) -> None:
        self._warning_last_emit.pop(key, None)

    def _experiment_lane_allows_entry(self, strat_name: str) -> bool:
        enabled = self._as_bool(getattr(config, "EXPERIMENT_LANE_ENABLED", True), True)
        if not enabled:
            return True

        raw_strategies = getattr(config, "EXPERIMENT_LANE_STRATEGIES", set())
        if isinstance(raw_strategies, str):
            lane_strategies = {s.strip() for s in raw_strategies.split(",") if s.strip()}
        elif isinstance(raw_strategies, (set, list, tuple)):
            lane_strategies = {str(s).strip() for s in raw_strategies if str(s).strip()}
        else:
            lane_strategies = set()

        if strat_name not in lane_strategies:
            return True

        cap_pct = self._as_float(getattr(config, "EXPERIMENT_LANE_CAP_PCT", 0.30), 0.30)
        cap_pct = max(0.0, min(1.0, cap_pct))

        # If cap is explicitly zero, fully block experiment-lane entries.
        if cap_pct == 0.0:
            self._warn_throttled(
                f"experiment_cap_zero:{strat_name}",
                f"{strat_name}: experiment lane cap is 0%, blocking new entries",
                cooldown_seconds=1800,
            )
            return False

        total_alloc = 0.0
        lane_alloc = 0.0
        for name, strat in self.strategies.items():
            if not strat.is_active:
                continue

            free_cap = float(self._capital.get(name, 0.0))
            committed = 0.0
            for pos in db.get_open_positions(name):
                committed += float(pos["entry_price"]) * float(pos["quantity"])

            alloc = free_cap + committed
            total_alloc += alloc
            if name in lane_strategies:
                lane_alloc += alloc

        if total_alloc <= 0:
            return True

        lane_cap_abs = total_alloc * cap_pct
        if lane_alloc >= lane_cap_abs:
            self._warn_throttled(
                f"experiment_cap_reached:{strat_name}",
                (
                    f"{strat_name}: experiment lane allocation cap reached "
                    f"(${lane_alloc:,.2f}/${lane_cap_abs:,.2f}, {cap_pct:.0%})"
                ),
                cooldown_seconds=1800,
            )
            return False

        self._clear_warning_throttle(f"experiment_cap_zero:{strat_name}")
        self._clear_warning_throttle(f"experiment_cap_reached:{strat_name}")

        return True

    def _regime_router_allows_entry(self, strat_name: str, signal: Signal) -> bool:
        enabled = self._as_bool(getattr(config, "REGIME_ROUTER_ENABLED", True), True)
        if not enabled:
            return True

        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        regime = str(metadata.get("regime") or "").strip().upper()
        if not regime:
            return True

        family_map = getattr(config, "REGIME_ROUTER_FAMILY_BY_STRATEGY", {})
        allowed_map = getattr(config, "REGIME_ROUTER_ALLOWED_FAMILIES", {})

        if not isinstance(family_map, dict) or not isinstance(allowed_map, dict):
            return True

        family = str(family_map.get(strat_name, "adaptive")).strip().lower()
        allowed = allowed_map.get(regime)
        if allowed is None:
            return True

        allowed_set = {str(x).strip().lower() for x in allowed if str(x).strip()}
        if family not in allowed_set:
            self._warn_throttled(
                f"regime_router:{strat_name}:{regime}",
                f"{strat_name}: blocked by regime router (regime={regime}, family={family})",
                cooldown_seconds=900,
            )
            return False

        self._clear_warning_throttle(f"regime_router:{strat_name}:{regime}")
        return True

    def _correlation_position_multiplier(self, strategy_name: str) -> float:
        enabled = self._as_bool(getattr(config, "CORRELATION_GUARD_ENABLED", True), True)
        if not enabled:
            return 1.0

        lookback = max(5, self._to_int(getattr(config, "CORRELATION_LOOKBACK_TRADES", 60)) or 60)
        min_points = max(3, self._to_int(getattr(config, "CORRELATION_MIN_POINTS", 8)) or 8)
        threshold = max(0.0, min(1.0, self._as_float(getattr(config, "CORRELATION_THRESHOLD", 0.75), 0.75)))
        penalty = max(0.05, min(1.0, self._as_float(getattr(config, "CORRELATION_SIZE_PENALTY", 0.50), 0.50)))

        try:
            base = db.get_trades(strategy_name, limit=lookback)
        except Exception:
            return 1.0
        if not isinstance(base, list):
            return 1.0
        base_series = [float(t.get("pnl_pct", 0.0) or 0.0) for t in base if isinstance(t, dict) and t.get("pnl_pct") is not None]
        if len(base_series) < min_points:
            return 1.0

        max_abs_corr = 0.0
        for other_name, other in self.strategies.items():
            if other_name == strategy_name or not other.is_active:
                continue

            try:
                other_trades = db.get_trades(other_name, limit=lookback)
            except Exception:
                continue
            if not isinstance(other_trades, list):
                continue
            other_series = [float(t.get("pnl_pct", 0.0) or 0.0) for t in other_trades if isinstance(t, dict) and t.get("pnl_pct") is not None]
            n = min(len(base_series), len(other_series))
            if n < min_points:
                continue

            a = np.array(base_series[-n:], dtype=float)
            b = np.array(other_series[-n:], dtype=float)
            if np.std(a) <= 1e-10 or np.std(b) <= 1e-10:
                continue

            corr = float(np.corrcoef(a, b)[0, 1])
            if np.isfinite(corr):
                max_abs_corr = max(max_abs_corr, abs(corr))

        if max_abs_corr >= threshold:
            return float(penalty)
        return 1.0

    # ─── Position sizing ──────────────────────────────────────────────────────

    def _size_position(self, capital: float, price: float,
                       signal: Signal, ml_confidence: float,
                       strategy_name: str = ""
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

        # Global risk ladder multiplier from review_engine (defaults to 1.0).
        try:
            risk_multiplier = float(db.get_metadata("risk_size_multiplier") or "1.0")
        except Exception:
            risk_multiplier = 1.0

        lane_multiplier = self._lane_position_multiplier(strategy_name)
        corr_multiplier = self._correlation_position_multiplier(strategy_name)

        notional = capital * base_pct * conf_scale * ml_scale * risk_multiplier * lane_multiplier * corr_multiplier
        notional = min(notional, capital * config.MAX_POSITION_PCT * risk_multiplier * lane_multiplier * corr_multiplier)
        notional = max(notional, 10.0)     # at least $10

        quantity = notional / price
        return round(quantity, 5), notional

    @staticmethod
    def _lane_position_multiplier(strategy_name: str) -> float:
        """Return per-lane position size multiplier for this strategy."""
        lane = {s.strip() for s in getattr(config, "EXPERIMENT_LANE_STRATEGIES", set()) if s and s.strip()}
        if getattr(config, "EXPERIMENT_LANE_ENABLED", False) and strategy_name in lane:
            return float(getattr(config, "EXPERIMENT_LANE_POSITION_MULTIPLIER", 0.75))
        return float(getattr(config, "CORE_LANE_POSITION_MULTIPLIER", 1.0))

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

        # Total balance = sum of all strategy totals (which includes free capital + committed + unrealized)
        # No need to add open positions notional again - it's already included in breakdown
        total_bal = sum(
            breakdown[s]["capital"] 
            for s in breakdown
        )

        return {
            "total_balance": round(total_bal, 2),
            "free_capital": round(sum(b["free_capital"] for b in breakdown.values()), 2),
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

    @staticmethod
    def _send_telegram(message: str):
        """Send a Telegram notification via openclaw CLI."""
        import subprocess, sys
        try:
            subprocess.run(
                ["openclaw", "send", "--message", message, "--channel", "telegram"],
                capture_output=True, text=True, timeout=20,
            )
        except Exception:
            pass  # non-blocking — don't disrupt trading









