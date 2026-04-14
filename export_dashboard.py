"""
Generate a fully self-contained static HTML dashboard from DB data.
Run:  python export_dashboard.py
Opens: dashboard_export.html
"""

import sys, os, json
import html
sys.path.insert(0, os.path.dirname(__file__))

import database as db
import config
db.init_db()

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timezone

# ── palette ──────────────────────────────────────────────────────────────────
BG     = "#0d1117"
CARD   = "#161b22"
BORDER = "#30363d"
GREEN  = "#3fb950"
RED    = "#f85149"
YELLOW = "#d29922"
BLUE   = "#58a6ff"
PURPLE = "#bc8cff"
TEXT   = "#c9d1d9"
SUB    = "#8b949e"
PAL    = [BLUE, GREEN, RED, YELLOW, PURPLE]

LAYOUT = dict(
    plot_bgcolor=BG, paper_bgcolor=CARD, font_color=TEXT,
    xaxis=dict(gridcolor=BORDER, zeroline=False),
    yaxis=dict(gridcolor=BORDER, zeroline=False),
    legend=dict(bgcolor=CARD, bordercolor=BORDER, borderwidth=1),
    margin=dict(l=50, r=20, t=50, b=40),
)

# ── load data ─────────────────────────────────────────────────────────────────
bal_hist   = db.get_balance_history(days=90)
trades     = db.get_trades(limit=500)
positions  = db.get_open_positions()
journal    = db.get_journal_entries(limit=50)
strategies = db.get_active_strategies()
stats      = db.get_trade_stats()
latest_bal = db.get_latest_balance() or {}

total_bal  = latest_bal.get("total_balance", config.INITIAL_CAPITAL)
unreal_pnl = latest_bal.get("unrealized_pnl", 0.0)
real_pnl   = latest_bal.get("realized_pnl", 0.0)
total_pnl  = real_pnl + unreal_pnl
pct_chg    = total_pnl / config.INITIAL_CAPITAL * 100

wins      = int(stats.get("wins") or 0)
total_t   = int(stats.get("total_trades") or 0)
wr        = stats.get("win_rate", 0)

# ── fig1: equity curve + drawdown ────────────────────────────────────────────
if bal_hist:
    bdf  = pd.DataFrame(bal_hist)
    bdf["recorded_at"] = pd.to_datetime(bdf["recorded_at"])
    eq   = bdf["total_balance"].values
    peak = pd.Series(eq).cummax().values
    dd   = -(peak - eq) / (peak + 1e-8) * 100

    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(
        x=bdf["recorded_at"], y=bdf["total_balance"], name="Portfolio",
        fill="tozeroy", line=dict(color=BLUE, width=2.5),
        fillcolor="rgba(88,166,255,0.10)"))
    fig_eq.add_hline(y=config.INITIAL_CAPITAL, line_dash="dot",
                     line_color=SUB, annotation_text="Initial $10,000",
                     annotation_font_color=SUB)
    fig_eq.update_layout(**LAYOUT, title="Portfolio Equity Curve",
                         title_font_color=BLUE, height=320,
                         yaxis_tickprefix="$", yaxis_tickformat=",.0f")

    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(
        x=bdf["recorded_at"], y=dd, name="Drawdown",
        fill="tozeroy", line=dict(color=RED, width=1.5),
        fillcolor="rgba(248,81,73,0.12)"))
    fig_dd.update_layout(**LAYOUT, title="Drawdown (%)",
                         title_font_color=RED, height=180,
                         yaxis_ticksuffix="%")
else:
    fig_eq = go.Figure(); fig_eq.update_layout(**LAYOUT, height=320)
    fig_dd = go.Figure(); fig_dd.update_layout(**LAYOUT, height=180)

# ── fig2: capital allocation pie ─────────────────────────────────────────────
if strategies:
    names = [s["name"] for s in strategies]
    caps  = [max(s.get("capital", config.INITIAL_CAPITAL/5), 0) for s in strategies]
    fig_pie = go.Figure(go.Pie(
        labels=names, values=caps, hole=0.5,
        marker=dict(colors=PAL[:len(names)]),
        textfont_color=TEXT,
    ))
    fig_pie.update_layout(**LAYOUT, title="Capital Allocation",
                          title_font_color=YELLOW, height=320, showlegend=True)
else:
    fig_pie = go.Figure(); fig_pie.update_layout(**LAYOUT, height=320)

# ── fig3: strategy equity mini-charts ────────────────────────────────────────
strat_names  = [s["name"] for s in strategies] if strategies else []
strat_figs   = []
strat_rows   = []

for i, strat in enumerate(strategies):
    name  = strat["name"]
    perf  = db.get_strategy_performance_history(name, days=60)
    color = PAL[i % len(PAL)]
    s_stats = db.get_trade_stats(name)

    strat_rows.append({
        "Strategy": name,
        "Capital": f"${strat.get('capital',0):,.0f}",
        "Live P&L": f"${float(s_stats.get('total_pnl') or 0):+,.2f}",
        "Win Rate": f"{float(s_stats.get('win_rate') or 0)*100:.1f}%",
        "Trades": int(s_stats.get("total_trades") or 0),
        "BT CAGR": f"{float(strat.get('backtest_cagr') or 0)*100:.1f}%",
        "BT Win Rate": f"{float(strat.get('backtest_win_rate') or 0)*100:.1f}%",
    })

    if perf:
        pdf  = pd.DataFrame(perf)
        fig_ = go.Figure()
        fig_.add_trace(go.Scatter(
            x=pdf["date"], y=pdf["capital"], name=name,
            fill="tozeroy", line=dict(color=color, width=2),
            fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.10)"))
        fig_.update_layout(**LAYOUT, title=name, title_font_color=color,
                           height=220, showlegend=False,
                           yaxis_tickprefix="$")
        strat_figs.append((name, fig_))

# ── fig4: P&L histogram ───────────────────────────────────────────────────────
if trades:
    tdf   = pd.DataFrame(trades)
    fees  = tdf.get("fees_paid", pd.Series([0.0] * len(tdf))).astype(float)
    pnls  = tdf["pnl"].astype(float) - fees
    pos_pnls = pnls[pnls >= 0]
    neg_pnls = pnls[pnls < 0]
    fig_hist = go.Figure()
    if len(pos_pnls):
        fig_hist.add_trace(go.Histogram(
            x=pos_pnls, nbinsx=30,
            name="Wins",
            marker_color=GREEN,
            opacity=0.9,
            hovertemplate="P&L: %{x:.2f}<br>Count: %{y}<extra>Wins</extra>",
        ))
    if len(neg_pnls):
        fig_hist.add_trace(go.Histogram(
            x=neg_pnls, nbinsx=30,
            name="Losses",
            marker_color=RED,
            opacity=0.9,
            hovertemplate="P&L: %{x:.2f}<br>Count: %{y}<extra>Losses</extra>",
        ))
    fig_hist.update_layout(**LAYOUT, title="P&L Distribution",
                           title_font_color=BLUE, height=230,
                           xaxis_title="P&L ($)", yaxis_title="Trades",
                           barmode="overlay", showlegend=True)

    # Cumulative PnL
    tdf_s  = tdf.sort_values("exit_time")
    cum    = (tdf_s["pnl"].astype(float) - tdf_s.get("fees_paid", pd.Series([0.0] * len(tdf_s))).astype(float)).cumsum().values
    fig_cum = go.Figure(go.Scatter(
        x=list(range(len(cum))), y=cum,
        fill="tozeroy", line=dict(color=BLUE, width=2),
        fillcolor="rgba(88,166,255,0.10)"))
    fig_cum.update_layout(**LAYOUT, title="Cumulative Realized P&L",
                          title_font_color=BLUE, height=230,
                          yaxis_tickprefix="$", xaxis_title="Trade #")
else:
    fig_hist = go.Figure(); fig_hist.update_layout(**LAYOUT, height=230)
    fig_cum  = go.Figure(); fig_cum.update_layout(**LAYOUT, height=230)

# ── HTML helpers ─────────────────────────────────────────────────────────────

def kpi(label, value, color=TEXT, subtitle=""):
    sub_html = f"<div style='color:{SUB};font-size:11px;margin-top:2px'>{subtitle}</div>" if subtitle else ""
    return f"""
    <div style='background:{CARD};border:1px solid {BORDER};border-radius:8px;padding:14px 18px;min-width:140px'>
      <div style='color:{SUB};font-size:11px;margin-bottom:4px'>{label}</div>
      <div style='color:{color};font-size:22px;font-weight:bold'>{value}</div>
      {sub_html}
    </div>"""

def trade_row(t):
    gross = float(t["pnl"])
    fees = float(t.get("fees_paid") or 0.0)
    net_pnl = gross - fees
    notional = max(float(t["entry_price"]) * float(t["quantity"]), 1e-9)
    net_pct = (net_pnl / notional) * 100
    color = GREEN if net_pnl >= 0 else RED
    side_color = GREEN if t["side"] == "LONG" else RED
    return f"""
    <tr>
      <td>{str(t.get('exit_time',''))[:16]}</td>
      <td style='color:{BLUE}'>{t['strategy_name']}</td>
      <td style='color:{side_color}'>{t['side']}</td>
      <td>${float(t['entry_price']):,.0f}</td>
      <td>${float(t['exit_price']):,.0f}</td>
      <td style='color:{color}'>${net_pnl:+,.2f}</td>
      <td style='color:{color}'>{net_pct:+.2f}%</td>
      <td>{float(t['duration_hours']):.1f}h</td>
      <td style='color:{SUB}'>{t.get('exit_reason','')}</td>
    </tr>"""


def _lessons_html(entry):
    """Return lessons as an HTML <ul> string, or empty string if no lessons."""
    lessons = entry.get("lessons") or []
    if not lessons:
        return ""
    items = "".join(
        f"<li style='color:{TEXT};font-size:12px'>{html.escape(str(l))}</li>"
        for l in lessons
    )
    return f"<ul style='padding-left:18px;margin:0'>{items}</ul>"


def journal_card(e):
    pnl = float(e.get("pnl") or 0)
    won = pnl > 0
    bc  = GREEN if won else RED
    pnl_pct = float(e.get("pnl_pct") or 0) * 100
    badge_color = "#1a4731" if won else "#3d1a1a"
    return f"""
    <div style='border:1px solid {bc};border-radius:8px;margin-bottom:14px;overflow:hidden'>
      <div style='background:{CARD};padding:10px 16px;display:flex;gap:12px;align-items:center;border-bottom:1px solid {BORDER}'>
        <span style='color:{BLUE};font-weight:bold'>{e.get("strategy_name","")}</span>
        <span style='background:{BORDER};color:{TEXT};padding:2px 8px;border-radius:4px;font-size:11px'>{e.get("side","")}</span>
        <span style='background:{badge_color};color:{bc};padding:2px 8px;border-radius:4px;font-size:11px'>{pnl_pct:+.2f}%</span>
        <span style='color:{SUB};font-size:11px;margin-left:auto'>{str(e.get("created_at",""))[:16]}</span>
      </div>
      <div style='background:{BG};padding:14px 16px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px'>
        <div>
          <div style='color:{TEXT};font-size:12px;margin-bottom:4px'><b>Setup</b></div>
          <div style='color:{SUB};font-size:12px'>{e.get("setup_summary","")}</div>
          <div style='margin-top:6px;color:{TEXT};font-size:12px'><b>Outcome</b></div>
          <div style='color:{SUB};font-size:12px'>{e.get("outcome_analysis","")}</div>
        </div>
        <div>
          <div style='color:{YELLOW};font-size:12px;margin-bottom:4px'><b>Reflection</b></div>
          <div style='color:{TEXT};font-size:12px;font-style:italic;border-left:3px solid {BORDER};padding-left:10px'>{e.get("reflection","")}</div>
        </div>
        <div>
          <div style='color:{PURPLE};font-size:12px;margin-bottom:4px'><b>Lessons</b></div>
          {_lessons_html(e)}
        </div>
      </div>
    </div>"""

def strat_table_rows():
    rows = []
    for r in strat_rows:
        pnl_str = r["Live P&L"]
        pnl_color = GREEN if "+" in pnl_str else RED
        rows.append(f"""<tr>
          <td style='color:{BLUE};font-weight:bold'>{r['Strategy']}</td>
          <td>{r['Capital']}</td>
          <td style='color:{pnl_color}'>{r['Live P&L']}</td>
          <td>{r['Win Rate']}</td><td>{r['Trades']}</td>
          <td style='color:{GREEN}'>{r['BT CAGR']}</td>
          <td>{r['BT Win Rate']}</td>
        </tr>""")
    return "".join(rows)

# ── serialise figs to JSON ────────────────────────────────────────────────────

def fig_json(fig):
    return fig.to_json()

import plotly.io as pio

eq_json   = pio.to_json(fig_eq)
dd_json   = pio.to_json(fig_dd)
pie_json  = pio.to_json(fig_pie)
hist_json = pio.to_json(fig_hist)
cum_json  = pio.to_json(fig_cum)
sf_json   = [(n, pio.to_json(f)) for n, f in strat_figs]

# ── assemble HTML ─────────────────────────────────────────────────────────────

now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

tab_ids   = ["tab-overview","tab-strategies","tab-positions","tab-history","tab-journal"]
tab_names = ["Portfolio Overview","Strategy Performance","Open Positions","Trade History","Trade Journal"]

# Pre-build tabs HTML (avoids backslash-in-f-string)
tabs_html = ""
for i, (tid, tn) in enumerate(zip(tab_ids, tab_names)):
    active = " active" if i == 0 else ""
    tabs_html += f'<button class="tab-btn{active}" onclick="showTab(\'{tid}\')">{tn}</button>\n'

# Trade history table rows
hist_rows = "".join(trade_row(t) for t in (trades[:100] if trades else []))

# Journal cards
journal_cards = "".join(journal_card(e) for e in (journal[:30] if journal else []))

# Open positions
if positions:
    pos_rows = "".join(f"""<tr>
      <td style='color:{BLUE}'>{p['strategy_name']}</td>
      <td style='color:{"#3fb950" if p["side"]=="LONG" else "#f85149"}'>{p['side']}</td>
      <td>${float(p['entry_price']):,.2f}</td>
      <td>{float(p['quantity']):.5f}</td>
      <td>${float(p['stop_loss'] or 0):,.2f}</td>
      <td>${float(p['take_profit'] or 0):,.2f}</td>
      <td>{str(p.get('entry_time',''))[:16]}</td>
    </tr>""" for p in positions)
    pos_section = f"""
    <table class="data-table">
      <thead><tr>
        <th>Strategy</th><th>Side</th><th>Entry $</th>
        <th>Qty BTC</th><th>Stop Loss</th><th>Take Profit</th><th>Entry Time</th>
      </tr></thead>
      <tbody>{pos_rows}</tbody>
    </table>"""
else:
    pos_section = f"<div style='color:{SUB};padding:30px;text-align:center'>No open positions</div>"

# Strategy mini-charts JS
sf_divs = ""
sf_js   = ""
for idx, (name, fjson) in enumerate(sf_json):
    div_id = f"strat-chart-{idx}"
    sf_divs += f"<div id='{div_id}' style='flex:1;min-width:280px;background:{CARD};border:1px solid {BORDER};border-radius:8px;padding:8px'></div>\n"
    sf_js   += f"Plotly.newPlot('{div_id}', {fjson}.data, {fjson}.layout, {{responsive:true,displayModeBar:false}});\n"

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BTC Trading Bot Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:{BG};color:{TEXT};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px}}
  .navbar{{background:{CARD};border-bottom:1px solid {BORDER};padding:10px 20px;display:flex;justify-content:space-between;align-items:center}}
  .navbar-brand{{color:{YELLOW};font-size:1.1rem;font-weight:bold}}
  .badge-live{{color:{RED};font-size:12px}}
  .badge-testnet{{color:{YELLOW};font-size:12px}}
  .kpi-row{{display:flex;gap:10px;padding:14px 16px;flex-wrap:wrap}}
  .tabs{{display:flex;gap:2px;padding:0 12px;border-bottom:1px solid {BORDER};margin-top:4px}}
  .tab-btn{{background:none;border:none;color:{SUB};padding:10px 16px;cursor:pointer;font-size:13px;border-bottom:2px solid transparent}}
  .tab-btn:hover{{color:{TEXT}}}
  .tab-btn.active{{color:{BLUE};border-bottom:2px solid {BLUE}}}
  .tab-panel{{display:none;padding:16px}}
  .tab-panel.active{{display:block}}
  .row{{display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap}}
  .chart-card{{background:{CARD};border:1px solid {BORDER};border-radius:8px;padding:10px;flex:1;min-width:300px}}
  .section-title{{color:{BLUE};font-size:14px;font-weight:600;margin:14px 0 8px}}
  .data-table{{width:100%;border-collapse:collapse;font-size:12px}}
  .data-table th{{background:{CARD};color:{BLUE};padding:8px 12px;text-align:left;border:1px solid {BORDER};white-space:nowrap}}
  .data-table td{{padding:7px 12px;border:1px solid {BORDER};white-space:nowrap}}
  .data-table tbody tr:nth-child(even){{background:rgba(255,255,255,0.02)}}
  .data-table tbody tr:hover{{background:rgba(88,166,255,0.05)}}
  .timestamp{{color:{SUB};font-size:11px}}
  .scroll-table{{overflow-x:auto;border-radius:8px;border:1px solid {BORDER}}}
</style>
</head>
<body>

<nav class="navbar">
  <span class="navbar-brand">₿ BTC Trading Bot</span>
  <span class="badge-testnet">● TESTNET / DEMO</span>
  <span class="timestamp">Generated: {now}</span>
</nav>

<div class="kpi-row">
  {kpi("Total Balance", f"${total_bal:,.2f}", GREEN if total_bal >= config.INITIAL_CAPITAL else RED, f"Started ${config.INITIAL_CAPITAL:,.0f}")}
  {kpi("Unrealized P&L", f"${unreal_pnl:+,.2f}", GREEN if unreal_pnl >= 0 else RED, "Open positions")}
  {kpi("Realized P&L", f"${real_pnl:+,.2f}", GREEN if real_pnl >= 0 else RED, "Closed trades")}
  {kpi("Total Return", f"{pct_chg:+.2f}%", GREEN if pct_chg >= 0 else RED)}
  {kpi("Win Rate", f"{wr*100:.1f}%", GREEN if wr >= 0.5 else YELLOW, f"{wins}/{total_t} trades")}
  {kpi("Open Positions", str(len(positions)), BLUE)}
</div>

<div class="tabs">
  {tabs_html}
</div>

<!-- TAB 1: Overview -->
<div id="tab-overview" class="tab-panel active">
  <div class="row">
    <div class="chart-card" style="flex:3"><div id="chart-eq"></div></div>
    <div class="chart-card" style="flex:1"><div id="chart-pie"></div></div>
  </div>
  <div class="chart-card"><div id="chart-dd"></div></div>
</div>

<!-- TAB 2: Strategies -->
<div id="tab-strategies" class="tab-panel">
  <div class="section-title">Strategy Metrics</div>
  <div class="scroll-table">
    <table class="data-table">
      <thead><tr>
        <th>Strategy</th><th>Capital</th><th>Live P&L</th><th>Win Rate</th>
        <th>Trades</th><th>BT CAGR</th><th>BT Win Rate</th>
      </tr></thead>
      <tbody>{strat_table_rows()}</tbody>
    </table>
  </div>
  <div class="section-title">Equity Curves</div>
  <div style="display:flex;gap:12px;flex-wrap:wrap">
    {sf_divs}
  </div>
</div>

<!-- TAB 3: Open Positions -->
<div id="tab-positions" class="tab-panel">
  <div class="section-title">{len(positions)} Open Position(s)</div>
  {pos_section}
</div>

<!-- TAB 4: Trade History -->
<div id="tab-history" class="tab-panel">
  <div class="row">
    <div class="chart-card" style="flex:3"><div id="chart-cum"></div></div>
    <div class="chart-card" style="flex:2"><div id="chart-hist"></div></div>
  </div>
  <div class="section-title">Trade Log ({len(trades)} trades)</div>
  <div class="scroll-table">
    <table class="data-table">
      <thead><tr>
        <th>Exit Date</th><th>Strategy</th><th>Side</th>
        <th>Entry $</th><th>Exit $</th><th>P&L $</th><th>P&L %</th>
        <th>Duration</th><th>Exit Reason</th>
      </tr></thead>
      <tbody>{hist_rows}</tbody>
    </table>
  </div>
</div>

<!-- TAB 5: Journal -->
<div id="tab-journal" class="tab-panel">
  <div class="section-title">Trade Journal ({len(journal)} entries)</div>
  {journal_cards}
</div>

<script>
function showTab(id){{
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b=>{{
    if(b.getAttribute('onclick').includes(id)) b.classList.add('active');
  }});
}}

// Render Plotly charts
const eq   = {eq_json};
const dd   = {dd_json};
const pie  = {pie_json};
const hist = {hist_json};
const cum  = {cum_json};
const cfg  = {{responsive:true,displayModeBar:false}};

Plotly.newPlot('chart-eq',  eq.data,   eq.layout,   cfg);
Plotly.newPlot('chart-dd',  dd.data,   dd.layout,   cfg);
Plotly.newPlot('chart-pie', pie.data,  pie.layout,  cfg);
Plotly.newPlot('chart-hist',hist.data, hist.layout, cfg);
Plotly.newPlot('chart-cum', cum.data,  cum.layout,  cfg);
{sf_js}
</script>
</body>
</html>"""

out = "/home/user/btc_trading_bot/dashboard_export.html"
with open(out, "w") as f:
    f.write(html)

size = os.path.getsize(out) / 1024
print(f"Saved: {out}  ({size:.0f} KB)")


