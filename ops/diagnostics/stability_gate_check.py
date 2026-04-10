#!/usr/bin/env python3
"""Compute 24h stability gate metrics for bot watchdog runs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

WATCHDOG_JOB_ID = "6bc4ba3c68ae"
CRON_DIR = Path(f"/home/thomas/.hermes/cron/output/{WATCHDOG_JOB_ID}")
INCIDENTS_FILE = Path("/home/thomas/Dropbox/Projects/Claude-trading-bot/ops/INCIDENTS.md")


@dataclass
class Metrics:
    runs_24h: int = 0
    fail_24h: int = 0
    warn_24h: int = 0
    action_24h: int = 0
    incident_entries_24h: int = 0


def parse_run_time(text: str) -> datetime | None:
    m = re.search(r"\*\*Run Time:\*\*\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    if not m:
        return None
    # Local timezone in cron file; normalize as UTC+local offset from system
    local_dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").astimezone()
    return local_dt.astimezone(timezone.utc)


def collect_watchdog_metrics(now_utc: datetime) -> Metrics:
    out = Metrics()
    if not CRON_DIR.exists():
        return out

    cutoff = now_utc - timedelta(hours=24)
    for p in sorted(CRON_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        run_ts = parse_run_time(text)
        if not run_ts or run_ts < cutoff:
            continue

        out.runs_24h += 1
        lower = text.lower()
        if "status: fail" in lower or '"status":"fail"' in lower:
            out.fail_24h += 1
        if "status: warn" in lower or '"status":"warn"' in lower or '"startup_grace": true' in lower:
            out.warn_24h += 1

        # Count only explicit JSON action arrays from canonical watchdog output
        m_actions = re.search(r'"actions"\s*:\s*\[(.*?)\]', text, flags=re.DOTALL)
        if m_actions and m_actions.group(1).strip():
            out.action_24h += 1

    return out


def collect_incident_count(now_utc: datetime, metrics: Metrics) -> None:
    if not INCIDENTS_FILE.exists():
        return
    text = INCIDENTS_FILE.read_text(encoding="utf-8", errors="ignore")
    entries = re.findall(r"### Incident (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    cutoff = now_utc - timedelta(hours=24)
    count = 0
    for ts in entries:
        dt_local = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").astimezone()
        if dt_local.astimezone(timezone.utc) >= cutoff:
            count += 1
    metrics.incident_entries_24h = count


def main() -> int:
    now = datetime.now(timezone.utc)
    m = collect_watchdog_metrics(now)
    collect_incident_count(now, m)

    gates = {
        "G1_zero_fail_24h": m.fail_24h == 0,
        "G2_warn_rate_le_20pct": (m.warn_24h / m.runs_24h <= 0.2) if m.runs_24h else True,
        "G3_action_rate_le_20pct": (m.action_24h / m.runs_24h <= 0.2) if m.runs_24h else True,
    }
    pass_all = all(gates.values())

    payload = {
        "window": "24h",
        "watchdog_job_id": WATCHDOG_JOB_ID,
        "metrics": {
            "runs": m.runs_24h,
            "fail": m.fail_24h,
            "warn": m.warn_24h,
            "action": m.action_24h,
            "incident_entries": m.incident_entries_24h,
        },
        "gates": gates,
        "overall": "PASS" if pass_all else "FAIL",
    }
    print(json.dumps(payload, indent=2))
    return 0 if pass_all else 2


if __name__ == "__main__":
    raise SystemExit(main())
