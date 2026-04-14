#!/usr/bin/env python3
"""Weekly reliability report card.

Computes last-7d metrics and prior-7d trend from watchdog cron outputs,
extracts top causes from INCIDENTS.md, and writes JSON/Markdown reports.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

WATCHDOG_JOB_ID = "6bc4ba3c68ae"
WATCHDOG_OUTPUT_DIR = Path(f"/home/thomas/.hermes/cron/output/{WATCHDOG_JOB_ID}")
INCIDENTS_FILE = Path("/home/thomas/Dropbox/Projects/Claude-trading-bot/ops/INCIDENTS.md")
REPORT_DIR = Path("/home/thomas/Dropbox/Projects/Claude-trading-bot/ops/reports")


@dataclass
class WindowMetrics:
    runs: int = 0
    ok: int = 0
    warn: int = 0
    fail: int = 0
    action_runs: int = 0

    @property
    def fail_rate(self) -> float:
        return (self.fail / self.runs) if self.runs else 0.0

    @property
    def warn_rate(self) -> float:
        return (self.warn / self.runs) if self.runs else 0.0

    @property
    def action_rate(self) -> float:
        return (self.action_runs / self.runs) if self.runs else 0.0


def parse_run_time(text: str) -> Optional[datetime]:
    m = re.search(r"\*\*Run Time:\*\*\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").astimezone().astimezone(timezone.utc)


def parse_status(text: str) -> str:
    lower = text.lower()
    if '[silent]' in lower:
        return "ok"
    if '"status": "fail"' in lower or '"status":"fail"' in lower or "status: fail" in lower:
        return "fail"
    if '"status": "warn"' in lower or '"status":"warn"' in lower or "status: warn" in lower:
        return "warn"
    if '"status": "ok"' in lower or '"status":"ok"' in lower or "status: ok" in lower:
        return "ok"
    return "unknown"


def parse_action_run(text: str) -> bool:
    m = re.search(r'"actions"\s*:\s*\[(.*?)\]', text, flags=re.DOTALL)
    if not m:
        return False
    return bool(m.group(1).strip())


def collect_metrics(start_utc: datetime, end_utc: datetime) -> WindowMetrics:
    metrics = WindowMetrics()
    if not WATCHDOG_OUTPUT_DIR.exists():
        return metrics

    for p in WATCHDOG_OUTPUT_DIR.glob("*.md"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        ts = parse_run_time(text)
        if not ts or ts < start_utc or ts >= end_utc:
            continue

        metrics.runs += 1
        status = parse_status(text)
        if status == "ok":
            metrics.ok += 1
        elif status == "warn":
            metrics.warn += 1
        elif status == "fail":
            metrics.fail += 1

        if parse_action_run(text):
            metrics.action_runs += 1

    return metrics


def top_incident_causes(limit: int = 5) -> list[tuple[str, int]]:
    if not INCIDENTS_FILE.exists():
        return []
    text = INCIDENTS_FILE.read_text(encoding="utf-8", errors="ignore")
    causes = re.findall(r"- likely_cause:\s*(.+)", text)
    cleaned = [c.strip() for c in causes if c.strip()]
    return Counter(cleaned).most_common(limit)


def grade_status(cur: WindowMetrics, prev: WindowMetrics) -> tuple[str, list[str]]:
    reasons: list[str] = []

    fail_delta = cur.fail_rate - prev.fail_rate
    warn_delta = cur.warn_rate - prev.warn_rate
    action_delta = cur.action_rate - prev.action_rate

    if cur.fail >= 3 or cur.fail_rate > 0.05:
        reasons.append("fail_rate_exceeds_threshold")
    if cur.warn_rate > 0.20:
        reasons.append("warn_rate_exceeds_threshold")
    if cur.action_rate > 0.20:
        reasons.append("action_rate_exceeds_threshold")
    if fail_delta > 0.02:
        reasons.append("fail_rate_worsened_vs_prior_week")
    if warn_delta > 0.05:
        reasons.append("warn_rate_worsened_vs_prior_week")
    if action_delta > 0.05:
        reasons.append("action_rate_worsened_vs_prior_week")

    if any("fail" in r for r in reasons):
        return "FAIL", reasons
    if reasons:
        return "WARN", reasons
    return "PASS", reasons


def main() -> int:
    now = datetime.now(timezone.utc)
    cur_start = now - timedelta(days=7)
    prev_start = now - timedelta(days=14)

    cur = collect_metrics(cur_start, now)
    prev = collect_metrics(prev_start, cur_start)

    status, reasons = grade_status(cur, prev)
    causes = top_incident_causes(limit=5)

    payload = {
        "status": status,
        "window": {
            "current": f"{cur_start.isoformat()} -> {now.isoformat()}",
            "prior": f"{prev_start.isoformat()} -> {cur_start.isoformat()}",
        },
        "current": {
            "runs": cur.runs,
            "ok": cur.ok,
            "warn": cur.warn,
            "fail": cur.fail,
            "action_runs": cur.action_runs,
            "fail_rate": round(cur.fail_rate, 4),
            "warn_rate": round(cur.warn_rate, 4),
            "action_rate": round(cur.action_rate, 4),
        },
        "prior": {
            "runs": prev.runs,
            "ok": prev.ok,
            "warn": prev.warn,
            "fail": prev.fail,
            "action_runs": prev.action_runs,
            "fail_rate": round(prev.fail_rate, 4),
            "warn_rate": round(prev.warn_rate, 4),
            "action_rate": round(prev.action_rate, 4),
        },
        "deltas": {
            "fail_rate": round(cur.fail_rate - prev.fail_rate, 4),
            "warn_rate": round(cur.warn_rate - prev.warn_rate, 4),
            "action_rate": round(cur.action_rate - prev.action_rate, 4),
        },
        "top_incident_causes": [{"cause": c, "count": n} for c, n in causes],
        "reasons": reasons,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"weekly_reliability_report_{stamp}.json"
    md_path = REPORT_DIR / f"weekly_reliability_report_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    md = [
        "# Weekly Reliability Report Card",
        "",
        f"- status: {status}",
        f"- current runs: {cur.runs} | ok: {cur.ok} warn: {cur.warn} fail: {cur.fail} action_runs: {cur.action_runs}",
        f"- current rates: fail={cur.fail_rate:.2%}, warn={cur.warn_rate:.2%}, action={cur.action_rate:.2%}",
        f"- prior rates: fail={prev.fail_rate:.2%}, warn={prev.warn_rate:.2%}, action={prev.action_rate:.2%}",
        f"- deltas: fail={cur.fail_rate - prev.fail_rate:+.2%}, warn={cur.warn_rate - prev.warn_rate:+.2%}, action={cur.action_rate - prev.action_rate:+.2%}",
        f"- reasons: {', '.join(reasons) if reasons else 'none'}",
        "",
        "## Top incident causes",
    ]
    if causes:
        md.extend([f"- {c}: {n}" for c, n in causes])
    else:
        md.append("- none")
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    payload["report_files"] = {"json": str(json_path), "md": str(md_path)}
    print(json.dumps(payload, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
