"""
Trading Bot Dashboard – Dash / Plotly
──────────────────────────────────────
Six tabs:
  1. Portfolio Overview      – equity curve, balance, unrealized P&L
  2. Strategy Performance    – per-strategy metrics and equity curves
  3. Open Positions          – live table with unrealized P&L
  4. Trade History           – filterable trade log
  5. Trade Journal           – individual entries with reflections
  6. Learning & Experiments  – lesson bias + experiment review tracking

Reads all data from the SQLite database; auto-refreshes every 15 s.
Run standalone:  python dashboard/app.py
Or imported by main.py for in-process startup.
"""

import sys
import os
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import dash
from dash import dcc, html, dash_table, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

import config
import database as db

# Shared price client for dashboard callbacks.
# Important: disable websocket here to avoid creating per-refresh websocket threads.
_price_client = None


def _get_live_price(symbol: str) -> float:
    global _price_client
    try:
        if _price_client is None:
            from binance_client import BinanceClient
            _price_client = BinanceClient(use_websocket=False)
        return _price_client.get_current_price(symbol)
    except Exception:
        return 0.0

# ─── App bootstrap ────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.CYBORG],
    title="BTC Trading Bot",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

# ─── Colour palette ───────────────────────────────────────────────────────────
COLORS = {
    "bg":       "#0d1117",
    "card":     "#161b22",
    "border":   "#30363d",
    "green":    "#3fb950",
    "red":      "#f85149",
    "yellow":   "#d29922",
    "blue":     "#58a6ff",
    "purple":   "#bc8cff",
    "text":     "#c9d1d9",
    "subtext":  "#8b949e",
}

STRATEGY_PALETTE = [
    "#58a6ff", "#3fb950", "#f85149", "#d29922", "#bc8cff"
]

# ─── Layout helpers ───────────────────────────────────────────────────────────

def _metric_card(title: str, value: str, color: str = "text",
                 subtitle: str = "") -> dbc.Card:
    return dbc.Card([
        dbc.CardBody([
            html.P(title, className="text-muted mb-1", style={"fontSize": "0.75rem"}),
            html.H4(value, style={"color": COLORS[color], "fontWeight": "bold", "margin": 0}),
            html.Small(subtitle, style={"color": COLORS["subtext"]}) if subtitle else None,
        ], style={"padding": "12px 16px"}),
    ], style={"backgroundColor": COLORS["card"], "border": f"1px solid {COLORS['border']}",
              "borderRadius": "8px"})


def _empty_fig(msg: str = "No data yet") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font={"color": COLORS["subtext"], "size": 14})
    fig.update_layout(**_dark_layout())
    return fig


def _dark_layout(title: str = "") -> dict:
    return dict(
        plot_bgcolor=COLORS["bg"],
        paper_bgcolor=COLORS["card"],
        font_color=COLORS["text"],
        title=title,
        title_font_color=COLORS["blue"],
        xaxis=dict(gridcolor=COLORS["border"], zeroline=False),
        yaxis=dict(gridcolor=COLORS["border"], zeroline=False),
        legend=dict(bgcolor=COLORS["card"], bordercolor=COLORS["border"]),
        margin=dict(l=40, r=20, t=40, b=40),
    )


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _latest_detected_regime() -> str:
    try:
        row = db.get_conn().execute(
            "SELECT regime_id FROM trades_decision ORDER BY ts_decision DESC LIMIT 1"
        ).fetchone()
        if row and row["regime_id"]:
            return str(row["regime_id"]).upper()
    except Exception:
        pass
    return "UNKNOWN"


def _robustness_from_recent_metrics(strategy_name: str, days: int = 30) -> float:
    try:
        m = db.get_recent_trade_metrics(strategy_name=strategy_name, days=days)
    except Exception:
        return 0.0

    wr = _safe_float(m.get("win_rate"), 0.0)
    pf = _safe_float(m.get("profit_factor"), 0.0)
    avg_r = _safe_float(m.get("avg_r"), 0.0)
    max_daily_loss_pct = abs(_safe_float(m.get("max_daily_loss_pct"), 0.0))
    daily_std = _safe_float(m.get("daily_pnl_std"), 0.0)

    consistency = (
        0.40 * max(0.0, min(1.0, wr))
        + 0.30 * max(0.0, min(1.0, pf / 2.5))
        + 0.30 * max(0.0, min(1.0, 1.0 - (max_daily_loss_pct / 0.06)))
    )
    stability = max(0.0, min(1.0, 1.0 - (daily_std / 0.06)))
    edge = max(0.0, min(1.0, (avg_r + 0.015) / 0.05))
    return max(0.0, min(1.0, 0.50 * consistency + 0.30 * stability + 0.20 * edge))


def _correlation_penalties(active_names):
    enabled = bool(getattr(config, "CORRELATION_GUARD_ENABLED", True))
    if not enabled:
        return {n: 1.0 for n in active_names}

    lookback = max(5, int(getattr(config, "CORRELATION_LOOKBACK_TRADES", 60)))
    min_points = max(3, int(getattr(config, "CORRELATION_MIN_POINTS", 8)))
    threshold = max(0.0, min(1.0, _safe_float(getattr(config, "CORRELATION_THRESHOLD", 0.75), 0.75)))
    penalty = max(0.05, min(1.0, _safe_float(getattr(config, "CORRELATION_SIZE_PENALTY", 0.50), 0.50)))

    series = {}
    for name in active_names:
        try:
            trades = db.get_trades(name, limit=lookback)
        except Exception:
            trades = []
        vals = [
            _safe_float(t.get("pnl_pct"), 0.0)
            for t in trades
            if isinstance(t, dict) and t.get("pnl_pct") is not None
        ]
        series[name] = vals

    out = {}
    for name in active_names:
        base = series.get(name, [])
        if len(base) < min_points:
            out[name] = 1.0
            continue

        max_abs_corr = 0.0
        for other in active_names:
            if other == name:
                continue
            o = series.get(other, [])
            n = min(len(base), len(o))
            if n < min_points:
                continue
            a = np.array(base[-n:], dtype=float)
            b = np.array(o[-n:], dtype=float)
            if np.std(a) <= 1e-10 or np.std(b) <= 1e-10:
                continue
            corr = float(np.corrcoef(a, b)[0, 1])
            if np.isfinite(corr):
                max_abs_corr = max(max_abs_corr, abs(corr))

        out[name] = penalty if max_abs_corr >= threshold else 1.0
    return out


def _render_execution_governance():
    active = db.get_active_strategies()
    names = [s.get("name") for s in active if s.get("name")]
    alloc_mode = str(getattr(config, "CAPITAL_ALLOCATION_MODE", "equal")).lower()
    target_share = (1.0 / len(names)) if names else 0.0

    regime = _latest_detected_regime()
    fam_map = getattr(config, "REGIME_ROUTER_FAMILY_BY_STRATEGY", {}) if bool(getattr(config, "REGIME_ROUTER_ENABLED", True)) else {}
    allow_map = getattr(config, "REGIME_ROUTER_ALLOWED_FAMILIES", {}) if bool(getattr(config, "REGIME_ROUTER_ENABLED", True)) else {}
    allowed_families = allow_map.get(regime, []) if isinstance(allow_map, dict) else []

    penalties = _correlation_penalties(names)

    rows = []
    for name in names:
        family = str(fam_map.get(name, "adaptive")) if isinstance(fam_map, dict) else "adaptive"
        robust = _robustness_from_recent_metrics(name)
        rows.append({
            "Strategy": name,
            "Family": family,
            "Target Share": f"{target_share*100:.1f}%",
            "Corr Multiplier": f"{penalties.get(name, 1.0):.2f}x",
            "Robustness": f"{robust:.2f}",
        })

    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in (rows[0].keys() if rows else ["Strategy", "Family", "Target Share", "Corr Multiplier", "Robustness"])],
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": COLORS["card"], "color": COLORS["blue"], "fontWeight": "bold", "border": f"1px solid {COLORS['border']}"},
        style_cell={"backgroundColor": COLORS["bg"], "color": COLORS["text"], "border": f"1px solid {COLORS['border']}", "fontSize": "13px", "padding": "8px 10px"},
        page_size=10,
    )

    return dbc.Card([
        dbc.CardBody([
            html.H5("Execution Governance", style={"color": COLORS["blue"], "marginBottom": "10px"}),
            dbc.Row([
                dbc.Col(_metric_card("Current Regime", regime, color="yellow" if regime != "UNKNOWN" else "subtext"), md=3),
                dbc.Col(_metric_card("Allocation Mode", alloc_mode, color="purple"), md=3),
                dbc.Col(_metric_card("Per-Strategy Target", f"{target_share*100:.1f}%" if names else "—", color="blue"), md=3),
                dbc.Col(_metric_card("Allowed Families", ", ".join(allowed_families) if allowed_families else "n/a", color="text"), md=3),
            ], className="g-2 mb-2"),
            table,
        ])
    ], style={"backgroundColor": COLORS["card"], "border": f"1px solid {COLORS['border']}", "borderRadius": "8px", "marginTop": "10px"})


# ─── Main layout ──────────────────────────────────────────────────────────────

app.layout = dbc.Container(fluid=True, style={"backgroundColor": COLORS["bg"],
                                               "minHeight": "100vh", "padding": "0"}, children=[

    # Auto-refresh interval
    dcc.Interval(id="interval-refresh", interval=config.DASHBOARD_UPDATE_MS, n_intervals=0),
    dcc.Store(id="store-price"),
    dcc.Store(id="store-balance"),

    # ── Header ────────────────────────────────────────────────────────────────
    dbc.Navbar(
        dbc.Container([
            html.Span("₿ BTC Trading Bot", style={
                "color": COLORS["yellow"], "fontWeight": "bold", "fontSize": "1.2rem"
            }),
            html.Span(id="header-mode", style={"color": COLORS["subtext"], "fontSize": "0.85rem"}),
            html.Span(id="header-time", style={"color": COLORS["subtext"], "fontSize": "0.8rem"}),
        ], fluid=True, style={"display": "flex", "justifyContent": "space-between",
                              "alignItems": "center"}),
        color=COLORS["card"], dark=True,
        style={"borderBottom": f"1px solid {COLORS['border']}", "padding": "8px 20px"}
    ),

    # ── Top KPI row ───────────────────────────────────────────────────────────
    dbc.Row(id="kpi-row", className="g-2 my-2 mx-2"),
    html.Div(id="macro-row", className="mx-2"),

    # ── Tabs ──────────────────────────────────────────────────────────────────
    dbc.Tabs(id="main-tabs", active_tab="tab-overview", style={"margin": "0 12px"},
             children=[
        dbc.Tab(label="Portfolio Overview",      tab_id="tab-overview"),
        dbc.Tab(label="Strategy Performance",    tab_id="tab-strategies"),
        dbc.Tab(label="Open Positions",          tab_id="tab-positions"),
        dbc.Tab(label="Trade History",           tab_id="tab-history"),
        dbc.Tab(label="Trade Journal",           tab_id="tab-journal"),
        dbc.Tab(label="Learning & Experiments",  tab_id="tab-learning-exp"),
    ]),

    html.Div(id="tab-content", style={"padding": "12px 12px 30px"}),
])

# ─── Callbacks ────────────────────────────────────────────────────────────────

@app.callback(
    Output("header-time", "children"),
    Output("header-mode", "children"),
    Input("interval-refresh", "n_intervals"),
)
def update_header(_):
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode = "● TESTNET" if config.USE_TESTNET else "● LIVE"
    color = COLORS["yellow"] if config.USE_TESTNET else COLORS["red"]
    return now, html.Span(mode, style={"color": color, "marginLeft": "12px"})


@app.callback(
    Output("kpi-row", "children"),
    Output("store-balance", "data"),
    Input("interval-refresh", "n_intervals"),
)
def update_kpis(_):
    bal  = db.get_latest_balance() or {}
    total   = bal.get("total_balance", config.INITIAL_CAPITAL)
    real    = bal.get("realized_pnl", 0.0)

    # Compute unrealized P&L LIVE from current open positions + latest price
    # (don't trust stale DB values that may be minutes old)
    try:
        current_price = _get_live_price(config.SYMBOL)
        unreal = 0.0
        for pos in db.get_open_positions():
            ep = float(pos["entry_price"])
            qty = float(pos["quantity"])
            if pos["side"] == "LONG":
                unreal += (current_price - ep) * qty
            else:
                unreal += (ep - current_price) * qty
    except Exception:
        # Fallback to DB value if live calculation fails
        unreal = bal.get("unrealized_pnl", 0.0)

    total_pnl = real + unreal
    pct_chg   = (total_pnl / config.INITIAL_CAPITAL) * 100 if config.INITIAL_CAPITAL else 0

    stats   = db.get_trade_stats(include_backtest=config.SHOW_BACKTEST_DATA)
    wins    = int(stats.get("wins") or 0)
    total_t = int(stats.get("total_trades") or 0)
    wr_str  = f"{wins}/{total_t}" if total_t > 0 else "0/0"
    wr_pct  = stats.get("win_rate", 0)

    cards = [
        dbc.Col(_metric_card("Total Balance", f"${total:,.2f}",
                             "green" if total >= config.INITIAL_CAPITAL else "red"), width=2),
        dbc.Col(_metric_card("Unrealized P&L", f"${unreal:+,.2f}",
                             "green" if unreal >= 0 else "red",
                             subtitle="Open positions"), width=2),
        dbc.Col(_metric_card("Realized P&L", f"${real:+,.2f}",
                             "green" if real >= 0 else "red",
                             subtitle="Closed trades"), width=2),
        dbc.Col(_metric_card("Total Return", f"{pct_chg:+.2f}%",
                             "green" if pct_chg >= 0 else "red",
                             subtitle=f"from ${config.INITIAL_CAPITAL:,.0f}"), width=2),
        dbc.Col(_metric_card("Win Rate", f"{wr_pct*100:.1f}%",
                             "green" if wr_pct >= 0.5 else "yellow",
                             subtitle=f"{wr_str} trades"), width=2),
        dbc.Col(_metric_card("Open Positions", str(len(db.get_open_positions())),
                             color="blue"), width=2),
    ]
    
    # Add "Live Since" card if available
    live_since = db.get_live_since()
    if live_since:
        # Extract just the date
        live_since_date = live_since.split("T")[0] if "T" in live_since else live_since
        cards.append(dbc.Col(_metric_card("Live Since", live_since_date,
                             color="purple"), width=2))
    
    return cards, bal


@app.callback(
    Output("macro-row", "children"),
    Input("interval-refresh", "n_intervals"),
)
def update_macro_row(_):
    """Fetch and display macro market snapshot (SPX, VIX, EUR/USD, BTC sentiment)."""
    try:
        from tradingview_client import tv_client
        tv = tv_client()
    except Exception:
        return []

    if not tv.get("available"):
        return []

    snap = tv.get("market_snapshot") or {}
    sent = tv.get("btc_sentiment") or {}

    def _fmt(val, fmt="%s"):
        return fmt % val if val is not None else "—"

    def _pct(val):
        if val is None:
            return "—"
        try:
            return f"{float(val):+.2f}%"
        except Exception:
            return "—"

    def _color_for_vix(vix_val):
        try:
            v = float(vix_val)
            if v > 30:
                return "red"
            elif v > 20:
                return "yellow"
            return "green"
        except Exception:
            return "text"

    def _sentiment_color(label):
        if not label:
            return "text"
        l = label.lower()
        if "bullish" in l or "strongly bullish" in l:
            return "green"
        if "bearish" in l or "strongly bearish" in l:
            return "red"
        return "yellow"

    cards = [
        dbc.Col(_metric_card(
            "SPX 500",
            _fmt(snap.get("sp500", {}).get("price"), "%.0f"),
            color="text",
            subtitle=_pct(snap.get("sp500", {}).get("change_pct")),
        ), width="auto"),
        dbc.Col(_metric_card(
            "VIX",
            _fmt(snap.get("vix", {}).get("price"), "%.1f"),
            color=_color_for_vix(snap.get("vix", {}).get("price")),
            subtitle="fear index",
        ), width="auto"),
        dbc.Col(_metric_card(
            "BTC Sentiment",
            _fmt(sent.get("label"), "%s"),
            color=_sentiment_color(sent.get("label")),
            subtitle=f"score {_fmt(sent.get('score'), '%.3f')}",
        ), width="auto"),
        dbc.Col(_metric_card(
            "EUR/USD",
            _fmt(snap.get("eurusd", {}).get("price"), "%.4f"),
            color="text",
            subtitle=_pct(snap.get("eurusd", {}).get("change_pct")),
        ), width="auto"),
    ]

    return dbc.Row(cards, className="g-2 my-1 mx-0", style={"fontSize": "0.8rem"})


@app.callback(
    Output("tab-content", "children"),
    Input("main-tabs", "active_tab"),
    Input("interval-refresh", "n_intervals"),
)
def render_tab(active_tab, _):
    if active_tab == "tab-overview":
        return _render_overview()
    elif active_tab == "tab-strategies":
        return _render_strategies()
    elif active_tab == "tab-positions":
        return _render_positions()
    elif active_tab == "tab-history":
        return _render_history()
    elif active_tab == "tab-journal":
        return _render_journal()
    elif active_tab == "tab-learning-exp":
        return _render_learning_experiments()
    return html.Div("Select a tab")


# ─── Tab renderers ────────────────────────────────────────────────────────────

def _render_overview():
    # Get balance history - filter out backtest data based on config
    history = db.get_balance_history(days=90, include_backtest=config.SHOW_BACKTEST_DATA)
    if history:
        df = pd.DataFrame(history)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["recorded_at"], y=df["total_balance"],
            name="Portfolio Balance", fill="tozeroy",
            line=dict(color=COLORS["blue"], width=2),
            fillcolor="rgba(88,166,255,0.12)",
        ))
        fig.add_hline(y=config.INITIAL_CAPITAL, line_dash="dot",
                      line_color=COLORS["subtext"], annotation_text="Initial Capital")

        # Dynamic Y-axis range: adapt to observed min/max equity values.
        y_min = float(df["total_balance"].min())
        y_max = float(df["total_balance"].max())
        span = y_max - y_min
        if span <= 0:
            # Flat line edge-case (single point or identical values)
            pad = max(abs(y_max) * 0.01, 5.0)
        else:
            pad = max(span * 0.08, abs(y_max) * 0.005, 5.0)
        fig.update_layout(**_dark_layout("Portfolio Equity Curve"), height=320)
        fig.update_yaxes(range=[y_min - pad, y_max + pad])

        # Drawdown
        eq = df["total_balance"].values
        peak = pd.Series(eq).cummax().values
        dd   = (peak - eq) / (peak + 1e-8) * 100
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=df["recorded_at"], y=-dd,
            fill="tozeroy", name="Drawdown %",
            line=dict(color=COLORS["red"], width=1),
            fillcolor="rgba(248,81,73,0.15)",
        ))
        fig_dd.update_layout(**_dark_layout("Drawdown (%)"), height=160,
                             yaxis_ticksuffix="%")
    else:
        fig    = _empty_fig("No balance history yet. Waiting for first data point.")
        fig_dd = _empty_fig("No drawdown data")

    # Strategy allocation pie
    active = db.get_active_strategies()
    if active:
        names  = [s["name"] for s in active]
        caps   = [s.get("capital", config.INITIAL_CAPITAL / config.MAX_STRATEGIES) for s in active]
        fig_pie = go.Figure(go.Pie(
            labels=names, values=caps, hole=0.5,
            marker=dict(colors=STRATEGY_PALETTE[:len(names)]),
        ))
        fig_pie.update_layout(**_dark_layout("Capital Allocation"), height=260,
                              showlegend=True)
    else:
        fig_pie = _empty_fig("No active strategies")

    return html.Div([
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig, config={"displayModeBar": False}), width=9),
            dbc.Col(dcc.Graph(figure=fig_pie, config={"displayModeBar": False}), width=3),
        ], className="g-2"),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_dd, config={"displayModeBar": False}), width=12),
        ], className="g-2 mt-1"),
        dbc.Row([
            dbc.Col(_render_execution_governance(), width=12),
        ], className="g-2 mt-1"),
    ])


def _render_strategies():
    strategies = db.get_active_strategies()
    if not strategies:
        return html.Div("No active strategies.", style={"color": COLORS["subtext"], "padding": "20px"})

    rows = []
    charts = []

    # Get current price for unrealized P&L calculation
    current_price = _get_live_price(config.SYMBOL)

    for i, strat in enumerate(strategies):
        name  = strat["name"]
        stats = db.get_trade_stats(name, include_backtest=config.SHOW_BACKTEST_DATA)
        db_capital = strat.get("capital", 0)  # Free capital from DB
        wr    = float(stats.get("win_rate") or 0)
        realized_pnl = float(stats.get("total_pnl") or 0)
        n     = int(stats.get("total_trades") or 0)
        bt_cagr = float(strat.get("backtest_cagr") or 0)
        bt_wr   = float(strat.get("backtest_win_rate") or 0)

        # Calculate committed notional and unrealized P&L for this strategy
        open_pos = db.get_open_positions(name)
        committed = 0.0
        unrealized_pnl = 0.0
        for pos in open_pos:
            ep = float(pos["entry_price"])
            qty = float(pos["quantity"])
            committed += ep * qty
            if current_price > 0:
                if pos["side"] == "LONG":
                    unrealized_pnl += (current_price - ep) * qty
                else:
                    unrealized_pnl += (ep - current_price) * qty

        # Total Capital = Initial Share + Realized P&L + Unrealized P&L
        # Free Capital = Total Capital - Committed Notional (locked in open positions)
        #
        # db_capital = initial share allocated to strategy
        initial_share = db_capital
        true_total_cap = initial_share + realized_pnl + unrealized_pnl
        free_cap = true_total_cap - committed  # After subtracting locked-in positions
        total_pnl = realized_pnl + unrealized_pnl

        rows.append({
            "Strategy": name,
            "Total Cap": f"${true_total_cap:,.2f}",
            "Free Cap": f"${free_cap:,.2f}",
            "Committed": f"${committed:,.2f}" if committed > 0 else "—",
            "Realized P&L": f"${realized_pnl:+.2f}" if realized_pnl != 0 else "$0.00",
            "Unrealized P&L": f"${unrealized_pnl:+.2f}" if unrealized_pnl != 0 else "$0.00",
            "Total P&L": f"${total_pnl:+.2f}" if total_pnl != 0 else "$0.00",
            "Closed Trades": n,
            "Win Rate": f"{wr*100:.1f}%",
            "BT CAGR": f"{bt_cagr*100:.1f}%",
        })

        # Mini equity curve per strategy
        perf = db.get_strategy_performance_history(name, days=60)
        color = STRATEGY_PALETTE[i % len(STRATEGY_PALETTE)]
        if perf:
            pdf = pd.DataFrame(perf)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pdf["date"], y=pdf["capital"],
                name=name, line=dict(color=color, width=2), fill="tozeroy",
                fillcolor=f"rgba{tuple(int(color.lstrip('#')[j:j+2], 16) for j in (0,2,4)) + (0.10,)}",
            ))
            fig.update_layout(**_dark_layout(name))
            fig.update_layout(height=200, showlegend=False, margin=dict(l=30, r=10, t=30, b=30))
        else:
            fig = _empty_fig(f"{name}: no history")
            fig.update_layout(height=200)

        charts.append(dbc.Col(dcc.Graph(figure=fig, config={"displayModeBar": False}), md=4))

    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in rows[0].keys()],
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": COLORS["card"], "color": COLORS["blue"],
                      "fontWeight": "bold", "border": f"1px solid {COLORS['border']}"},
        style_cell={"backgroundColor": COLORS["bg"], "color": COLORS["text"],
                    "border": f"1px solid {COLORS['border']}", "fontSize": "13px",
                    "padding": "8px 12px"},
        style_data_conditional=[
            # Realized P&L coloring
            {"if": {"filter_query": '{Realized P&L} contains "+"'}, "color": COLORS["green"]},
            {"if": {"filter_query": '{Realized P&L} contains "-"'}, "color": COLORS["red"]},
            # Unrealized P&L coloring
            {"if": {"filter_query": '{Unrealized P&L} contains "+"'}, "color": COLORS["green"], "fontWeight": "bold"},
            {"if": {"filter_query": '{Unrealized P&L} contains "-"'}, "color": COLORS["red"], "fontWeight": "bold"},
            # Total P&L coloring
            {"if": {"filter_query": '{Total P&L} contains "+"'}, "color": COLORS["green"]},
            {"if": {"filter_query": '{Total P&L} contains "-"'}, "color": COLORS["red"]},
        ],
    )

    return html.Div([
        html.H6("Strategy Metrics", style={"color": COLORS["blue"], "marginBottom": "10px"}),
        table,
        html.H6("Equity Curves", style={"color": COLORS["blue"], "margin": "16px 0 8px"}),
        dbc.Row(charts, className="g-2"),
    ])


def _render_positions():
    positions = db.get_open_positions()
    if not positions:
        return html.Div([
            html.P("No open positions.", style={"color": COLORS["subtext"], "padding": "20px"}),
        ])

    # Need current price for unrealized PnL
    # Try to read from DB or use last stored balance
    last_bal = db.get_latest_balance()
    try:
        bd = last_bal.get("strategy_breakdown", {}) if last_bal else {}
        # Try reading a stored price from a JSON field
        current_price = None
        for v in bd.values():
            if isinstance(v, dict) and "current_price" in v:
                current_price = v["current_price"]
                break
    except Exception:
        current_price = None

    rows = []
    for p in positions:
        ep  = float(p["entry_price"])
        qty = float(p["quantity"])
        sl  = float(p["stop_loss"] or 0)
        tp  = float(p["take_profit"] or 0)
        ml  = float(p.get("ml_confidence") or 0.5)

        unreal = "N/A"
        unreal_pct = "N/A"
        if current_price:
            if p["side"] == "LONG":
                ur = (current_price - ep) * qty
            else:
                ur = (ep - current_price) * qty
            unreal     = f"${ur:+.2f}"
            unreal_pct = f"{(ur / (ep * qty)) * 100:+.2f}%"

        cur_price_str = f"${current_price:,.2f}" if current_price else "N/A"

        rows.append({
            "ID": p["id"],
            "Strategy": p["strategy_name"],
            "Side": p["side"],
            "Entry Price": f"${ep:,.2f}",
            "Current Price": cur_price_str,
            "Qty (BTC)": f"{qty:.5f}",
            "Notional": f"${ep * qty:,.2f}",
            "Stop Loss": f"${sl:,.2f}",
            "Take Profit": f"${tp:,.2f}",
            "Unrealized P&L": unreal,
            "Unrealized %": unreal_pct,
            "ML Conf.": f"{ml:.2f}",
            "Entry Time": p.get("entry_time", "")[:16],
        })

    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in rows[0].keys()],
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": COLORS["card"], "color": COLORS["blue"],
                      "fontWeight": "bold", "border": f"1px solid {COLORS['border']}"},
        style_cell={"backgroundColor": COLORS["bg"], "color": COLORS["text"],
                    "border": f"1px solid {COLORS['border']}", "fontSize": "12px",
                    "padding": "6px 10px", "whiteSpace": "nowrap"},
        style_data_conditional=[
            {"if": {"filter_query": '{Side} = "LONG"'},  "color": COLORS["green"]},
            {"if": {"filter_query": '{Side} = "SHORT"'}, "color": COLORS["red"]},
            # Current Price: green when winning (LONG up / SHORT down), red otherwise
            {"if": {"filter_query": '{Unrealized P&L} contains "+"',
                    "column_id": "Current Price"},
             "color": COLORS["green"], "fontWeight": "bold"},
            {"if": {"filter_query": '{Unrealized P&L} contains "-"',
                    "column_id": "Current Price"},
             "color": COLORS["red"], "fontWeight": "bold"},
        ],
    )

    return html.Div([
        html.H6(f"{len(positions)} Open Position(s)",
                style={"color": COLORS["blue"], "marginBottom": "10px"}),
        table,
    ])


def _render_history():
    # Get trades - filter out backtest data based on config
    trades = db.get_trades(limit=200, include_backtest=config.SHOW_BACKTEST_DATA)
    if not trades:
        return html.Div("No closed trades yet.", style={"color": COLORS["subtext"], "padding": "20px"})

    rows = []
    net_pnls = []
    for t in trades:
        gross_pnl = float(t["pnl"])
        fees = float(t.get("fees_paid") or 0.0)
        net_pnl = gross_pnl - fees
        notional = max(float(t["entry_price"]) * float(t["quantity"]), 1e-9)
        net_pct = (net_pnl / notional) * 100
        net_pnls.append(net_pnl)

        rows.append({
            "Date": t.get("exit_time", "")[:16],
            "Strategy": t["strategy_name"],
            "Side": t["side"],
            "Entry $": f"{float(t['entry_price']):,.2f}",
            "Exit $": f"{float(t['exit_price']):,.2f}",
            "Qty": f"{float(t['quantity']):.5f}",
            "P&L $": f"{net_pnl:+.2f}",
            "P&L %": f"{net_pct:+.2f}%",
            "Fees": f"${fees:.2f}",
            "Duration": f"{float(t['duration_hours']):.1f}h",
            "Exit Reason": t.get("exit_reason", ""),
        })

    # P&L distribution histogram (net after fees, split traces for explicit colors)
    pnls = net_pnls
    pos_pnls = [p for p in pnls if p >= 0]
    neg_pnls = [p for p in pnls if p < 0]
    fig_hist = go.Figure()
    if pos_pnls:
        fig_hist.add_trace(go.Histogram(
            x=pos_pnls,
            nbinsx=30,
            name="Wins",
            marker_color=COLORS["green"],
            opacity=0.9,
            hovertemplate="P&L: %{x:.2f}<br>Count: %{y}<extra>Wins</extra>",
        ))
    if neg_pnls:
        fig_hist.add_trace(go.Histogram(
            x=neg_pnls,
            nbinsx=30,
            name="Losses",
            marker_color=COLORS["red"],
            opacity=0.9,
            hovertemplate="P&L: %{x:.2f}<br>Count: %{y}<extra>Losses</extra>",
        ))
    fig_hist.update_layout(**_dark_layout("P&L Distribution"), height=200,
                           xaxis_title="P&L ($)", yaxis_title="Count",
                           bargap=0.05, barmode="overlay", showlegend=True)

    # Cumulative PnL chart (net after fees)
    cum_pnl = []
    running = 0
    dates   = []
    for t in reversed(trades):
        running += float(t["pnl"]) - float(t.get("fees_paid") or 0.0)
        cum_pnl.append(running)
        dates.append(t.get("exit_time", ""))
    fig_cum = go.Figure(go.Scatter(
        x=dates, y=cum_pnl,
        fill="tozeroy", line=dict(color=COLORS["blue"], width=2),
        fillcolor="rgba(88,166,255,0.1)",
    ))
    fig_cum.update_layout(**_dark_layout("Cumulative Realized P&L"), height=200,
                          yaxis_tickprefix="$")

    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in rows[0].keys()],
        page_size=20,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": COLORS["card"], "color": COLORS["blue"],
                      "fontWeight": "bold", "border": f"1px solid {COLORS['border']}"},
        style_cell={"backgroundColor": COLORS["bg"], "color": COLORS["text"],
                    "border": f"1px solid {COLORS['border']}", "fontSize": "12px",
                    "padding": "5px 9px", "whiteSpace": "nowrap"},
        style_data_conditional=[
            {"if": {"filter_query": '{P&L $} contains "+"'}, "color": COLORS["green"]},
            {"if": {"filter_query": '{P&L $} contains "-"'}, "color": COLORS["red"]},
        ],
    )

    return html.Div([
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_cum, config={"displayModeBar": False}), width=7),
            dbc.Col(dcc.Graph(figure=fig_hist, config={"displayModeBar": False}), width=5),
        ], className="g-2 mb-3"),
        html.H6(f"Trade History ({len(rows)} trades)",
                style={"color": COLORS["blue"], "marginBottom": "4px"}),
        html.Small("Color basis: Net P&L after fees", style={"color": COLORS["subtext"], "display": "block", "marginBottom": "8px"}),
        table,
    ])


def _render_journal():
    # Get journal entries - filter out backtest entries based on config
    entries = db.get_journal_entries(limit=50, include_backtest=config.SHOW_BACKTEST_DATA)
    if not entries:
        return html.Div("No journal entries yet. Entries are created after each closed trade.",
                        style={"color": COLORS["subtext"], "padding": "20px"})

    cards = []
    for e in entries:
        pnl     = float(e.get("pnl") or 0)
        pnl_pct = float(e.get("pnl_pct") or 0) * 100
        won     = pnl > 0
        border_color = COLORS["green"] if won else COLORS["red"]
        badge_color  = "success" if won else "danger"
        badge_text   = f"+{pnl_pct:.2f}%" if won else f"{pnl_pct:.2f}%"

        cards.append(dbc.Card([
            dbc.CardHeader([
                html.Span(e.get("strategy_name", ""), style={"fontWeight": "bold",
                          "color": COLORS["blue"]}),
                html.Span("  "),
                dbc.Badge(e.get("side", ""), color="info", className="me-2"),
                dbc.Badge(badge_text, color=badge_color, className="me-2"),
                html.Small(e.get("created_at", "")[:16],
                           style={"color": COLORS["subtext"], "float": "right"}),
            ], style={"backgroundColor": COLORS["card"]}),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.P([html.Strong("Setup: "), e.get("setup_summary", "")],
                               style={"fontSize": "13px", "color": COLORS["text"]}),
                        html.P([html.Strong("Outcome: "), e.get("outcome_analysis", "")],
                               style={"fontSize": "13px", "color": COLORS["text"]}),
                    ], md=5),
                    dbc.Col([
                        html.P([html.Strong("Reflection: ")],
                               style={"fontSize": "13px", "color": COLORS["yellow"],
                                      "marginBottom": "2px"}),
                        html.P(e.get("reflection", ""),
                               style={"fontSize": "12px", "color": COLORS["text"],
                                      "fontStyle": "italic", "borderLeft":
                                      f"3px solid {COLORS['border']}",
                                      "paddingLeft": "10px"}),
                    ], md=4),
                    dbc.Col([
                        html.P([html.Strong("Lessons: ")],
                               style={"fontSize": "13px", "color": COLORS["purple"],
                                      "marginBottom": "2px"}),
                        html.Ul(
                            [
                                html.Li(lesson, style={"fontSize": "12px", "color": COLORS["text"]})
                                for lesson in (e.get("lessons") or [])
                            ],
                            style={"paddingLeft": "18px", "margin": "0"},
                        ),
                    ], md=3),
                ]),
            ], style={"backgroundColor": COLORS["bg"], "padding": "12px 16px"}),
        ], style={"border": f"1px solid {border_color}", "borderRadius": "6px",
                  "marginBottom": "12px"}))

    return html.Div([
        html.H6("Trade Journal", style={"color": COLORS["blue"], "marginBottom": "16px"}),
        html.Div(cards),
    ])


def _compute_lesson_bias_snapshot():
    """Rebuild lesson-bias snapshot from journal entries."""
    try:
        from strategies import ALL_STRATEGIES
        from learning_engine import LearningEngine

        strat_map = {S().name: S() for S in ALL_STRATEGIES}
        le = LearningEngine(strat_map)
        le.learn_from_all_journal_entries()
        bias = le.get_lesson_bias_snapshot()
        return bias or {}
    except Exception:
        return {}


def _fetch_experiment_runs(limit: int = 80):
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT experiment_id, week_id, baseline_version,
               weekly_pnl_pct, weekly_drawdown_pct,
               daily_pnl_std, trade_count,
               score_total, decision, decision_reason, reviewed_at
        FROM experiment_runs
        ORDER BY reviewed_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_risk_events(limit: int = 80):
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT week_id, trigger_level_pct, portfolio_dd_pct,
               size_multiplier_applied, note, triggered_at
        FROM risk_events
        ORDER BY triggered_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def _render_learning_experiments():
    bias = _compute_lesson_bias_snapshot()

    if bias:
        sorted_bias = sorted(bias.items(), key=lambda kv: kv[1], reverse=True)
        bias_rows = [
            {
                "Strategy": name,
                "Lesson Bias Penalty": f"{pen:+.3f}",
                "Effective Confidence Adj": f"{-pen:+.3f}",
                "State": "Caution" if pen > 0 else ("Boost" if pen < 0 else "Neutral"),
            }
            for name, pen in sorted_bias
        ]

        fig_bias = go.Figure(go.Bar(
            x=[r["Strategy"] for r in bias_rows],
            y=[float(r["Lesson Bias Penalty"]) for r in bias_rows],
            marker_color=[COLORS["red"] if float(r["Lesson Bias Penalty"]) > 0 else COLORS["green"]
                          for r in bias_rows],
        ))
        fig_bias.update_layout(
            **_dark_layout("Journal Lesson Bias by Strategy"),
            height=260,
            yaxis_title="Penalty applied to confidence",
            xaxis_title="Strategy",
        )

        bias_table = dash_table.DataTable(
            data=bias_rows,
            columns=[{"name": c, "id": c} for c in bias_rows[0].keys()],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": COLORS["card"], "color": COLORS["blue"],
                          "fontWeight": "bold", "border": f"1px solid {COLORS['border']}"},
            style_cell={"backgroundColor": COLORS["bg"], "color": COLORS["text"],
                        "border": f"1px solid {COLORS['border']}", "fontSize": "12px",
                        "padding": "6px 10px"},
            style_data_conditional=[
                {"if": {"filter_query": '{Lesson Bias Penalty} contains "+"'}, "color": COLORS["red"]},
                {"if": {"filter_query": '{Lesson Bias Penalty} contains "-"'}, "color": COLORS["green"]},
            ],
        )
    else:
        fig_bias = _empty_fig("No lesson-bias data yet")
        bias_table = html.Div("No journal learning data available yet.",
                              style={"color": COLORS["subtext"], "padding": "8px"})

    exp_runs = _fetch_experiment_runs(limit=120)
    risk_events = _fetch_risk_events(limit=120)
    size_mult = db.get_metadata("risk_size_multiplier") or "1.00"
    size_week = db.get_metadata("risk_size_multiplier_week") or "-"

    if exp_runs:
        exp_rows = []
        for r in exp_runs:
            exp_rows.append({
                "Reviewed": str(r.get("reviewed_at", ""))[:16],
                "Week": r.get("week_id", ""),
                "Experiment": r.get("experiment_id", ""),
                "Trades": int(r.get("trade_count", 0) or 0),
                "PnL %": f"{float(r.get('weekly_pnl_pct', 0.0))*100:+.2f}%",
                "DD %": f"{float(r.get('weekly_drawdown_pct', 0.0)):+.2f}%",
                "Score": f"{float(r.get('score_total', 0.0)):.1f}",
                "Decision": r.get("decision", ""),
                "Reason": r.get("decision_reason", ""),
            })

        exp_table = dash_table.DataTable(
            data=exp_rows,
            columns=[{"name": c, "id": c} for c in exp_rows[0].keys()],
            page_size=12,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": COLORS["card"], "color": COLORS["blue"],
                          "fontWeight": "bold", "border": f"1px solid {COLORS['border']}"},
            style_cell={"backgroundColor": COLORS["bg"], "color": COLORS["text"],
                        "border": f"1px solid {COLORS['border']}", "fontSize": "12px",
                        "padding": "6px 10px", "whiteSpace": "nowrap", "maxWidth": "360px", "overflow": "hidden", "textOverflow": "ellipsis"},
            style_data_conditional=[
                {"if": {"filter_query": '{Decision} = "PROMOTE"'}, "color": COLORS["green"], "fontWeight": "bold"},
                {"if": {"filter_query": '{Decision} = "KEEP_TESTING"'}, "color": COLORS["blue"], "fontWeight": "bold"},
                {"if": {"filter_query": '{Decision} = "DEMOTE"'}, "color": COLORS["yellow"], "fontWeight": "bold"},
                {"if": {"filter_query": '{Decision} = "KILL"'}, "color": COLORS["red"], "fontWeight": "bold"},
            ],
            tooltip_data=[
                {"Reason": {"value": row.get("Reason", ""), "type": "markdown"}}
                for row in exp_rows
            ],
            tooltip_duration=None,
        )
    else:
        exp_table = html.Div("No experiment review rows yet.", style={"color": COLORS["subtext"], "padding": "8px"})

    if risk_events:
        risk_rows = [
            {
                "Triggered": str(r.get("triggered_at", ""))[:16],
                "Week": r.get("week_id", ""),
                "Trigger %": f"{float(r.get('trigger_level_pct', 0.0)):+.2f}%",
                "Portfolio DD %": f"{float(r.get('portfolio_dd_pct', 0.0)):+.2f}%",
                "Size Multiplier": f"{float(r.get('size_multiplier_applied', 1.0)):.2f}x",
                "Note": r.get("note", ""),
            }
            for r in risk_events
        ]

        risk_table = dash_table.DataTable(
            data=risk_rows,
            columns=[{"name": c, "id": c} for c in risk_rows[0].keys()],
            page_size=8,
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": COLORS["card"], "color": COLORS["blue"],
                          "fontWeight": "bold", "border": f"1px solid {COLORS['border']}"},
            style_cell={"backgroundColor": COLORS["bg"], "color": COLORS["text"],
                        "border": f"1px solid {COLORS['border']}", "fontSize": "12px",
                        "padding": "6px 10px", "whiteSpace": "nowrap"},
        )
    else:
        risk_table = html.Div("No risk ladder trigger events yet.", style={"color": COLORS["subtext"], "padding": "8px"})

    return html.Div([
        dbc.Row([
            dbc.Col(_metric_card("Current Risk Size Multiplier", f"{size_mult}x", color="yellow",
                                 subtitle=f"week {size_week}"), width=3),
            dbc.Col(_metric_card("Strategies with Lesson Bias", f"{len(bias)}", color="purple",
                                 subtitle="from journal history"), width=3),
            dbc.Col(_metric_card("Experiment Reviews", str(len(exp_runs)), color="blue",
                                 subtitle="rows tracked"), width=3),
            dbc.Col(_metric_card("Risk Events", str(len(risk_events)), color="red",
                                 subtitle="ladder triggers"), width=3),
        ], className="g-2 mb-2"),

        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_bias, config={"displayModeBar": False}), width=6),
            dbc.Col([
                html.H6("Lesson Bias Table", style={"color": COLORS["blue"], "marginBottom": "8px"}),
                bias_table,
            ], width=6),
        ], className="g-2"),

        html.H6("Experiment Review Tracker", style={"color": COLORS["blue"], "margin": "16px 0 8px"}),
        exp_table,

        html.H6("Risk Ladder Events", style={"color": COLORS["blue"], "margin": "16px 0 8px"}),
        risk_table,
    ])


# ─── Entry point ──────────────────────────────────────────────────────────────

def run_dashboard(debug: bool = False):
    db.init_db()
    app.run(
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=debug,
    )


if __name__ == "__main__":
    run_dashboard(debug=True)






