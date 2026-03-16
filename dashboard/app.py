"""
Trading Bot Dashboard – Dash / Plotly
──────────────────────────────────────
Five tabs:
  1. Portfolio Overview  – equity curve, balance, unrealized P&L
  2. Strategy Performance – per-strategy metrics and equity curves
  3. Open Positions       – live table with unrealized P&L
  4. Trade History        – filterable trade log
  5. Trade Journal        – individual entries with reflections

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

import config
import database as db

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

    # ── Tabs ──────────────────────────────────────────────────────────────────
    dbc.Tabs(id="main-tabs", active_tab="tab-overview", style={"margin": "0 12px"},
             children=[
        dbc.Tab(label="Portfolio Overview",    tab_id="tab-overview"),
        dbc.Tab(label="Strategy Performance",  tab_id="tab-strategies"),
        dbc.Tab(label="Open Positions",        tab_id="tab-positions"),
        dbc.Tab(label="Trade History",         tab_id="tab-history"),
        dbc.Tab(label="Trade Journal",         tab_id="tab-journal"),
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
        from binance_client import BinanceClient
        client = BinanceClient()
        current_price = client.get_current_price(config.SYMBOL)
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
        fig.update_layout(**_dark_layout("Portfolio Equity Curve"), height=320)

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
    ])


def _render_strategies():
    strategies = db.get_active_strategies()
    if not strategies:
        return html.Div("No active strategies.", style={"color": COLORS["subtext"], "padding": "20px"})

    rows = []
    charts = []

    # Get current price for unrealized P&L calculation
    try:
        from binance_client import BinanceClient
        client = BinanceClient()
        current_price = client.get_current_price(config.SYMBOL)
    except Exception:
        current_price = 0.0

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
    for t in trades:
        pnl     = float(t["pnl"])
        pnl_pct = float(t["pnl_pct"]) * 100
        rows.append({
            "Date": t.get("exit_time", "")[:16],
            "Strategy": t["strategy_name"],
            "Side": t["side"],
            "Entry $": f"{float(t['entry_price']):,.2f}",
            "Exit $": f"{float(t['exit_price']):,.2f}",
            "Qty": f"{float(t['quantity']):.5f}",
            "P&L $": f"{pnl:+.2f}",
            "P&L %": f"{pnl_pct:+.2f}%",
            "Fees": f"${float(t['fees_paid']):.2f}",
            "Duration": f"{float(t['duration_hours']):.1f}h",
            "Exit Reason": t.get("exit_reason", ""),
        })

    # P&L distribution histogram
    pnls = [float(t["pnl"]) for t in trades]
    fig_hist = go.Figure(go.Histogram(
        x=pnls, nbinsx=30,
        marker_color=[COLORS["green"] if p >= 0 else COLORS["red"] for p in pnls],
        opacity=0.8,
    ))
    fig_hist.update_layout(**_dark_layout("P&L Distribution"), height=200,
                           xaxis_title="P&L ($)", yaxis_title="Count",
                           bargap=0.05)

    # Cumulative PnL chart
    cum_pnl = []
    running = 0
    dates   = []
    for t in reversed(trades):
        running += float(t["pnl"])
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
                style={"color": COLORS["blue"], "marginBottom": "8px"}),
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
                        html.P(e.get("lessons", ""),
                               style={"fontSize": "12px", "color": COLORS["text"]}),
                    ], md=3),
                ]),
            ], style={"backgroundColor": COLORS["bg"], "padding": "12px 16px"}),
        ], style={"border": f"1px solid {border_color}", "borderRadius": "6px",
                  "marginBottom": "12px"}))

    return html.Div([
        html.H6("Trade Journal", style={"color": COLORS["blue"], "marginBottom": "16px"}),
        html.Div(cards),
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
