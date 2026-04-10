#!/usr/bin/env python3
"""7-day watchdog false-positive baseline.

Heuristic labels:
- alert run: status warn/fail from watchdog JSON output
- true positive: alert run with non-empty actions OR non-empty issues
- false positive candidate: alert run with no actions and no issues, or startup_grace-only warn
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

WATCHDOG_OUTPUT_DIR = Path('/home/thomas/.hermes/cron/output/6bc4ba3c68ae')


def parse_run_time(text: str):
    m = re.search(r"\*\*Run Time:\*\*\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S').astimezone()
    return dt.astimezone(timezone.utc)


def extract_json_blob(text: str):
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    blob = m.group(0)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def main() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    total_runs = 0
    alert_runs = 0
    tp = 0
    fp_candidates = 0

    samples = []

    for p in sorted(WATCHDOG_OUTPUT_DIR.glob('*.md')):
        text = p.read_text(encoding='utf-8', errors='ignore')
        ts = parse_run_time(text)
        if not ts or ts < cutoff:
            continue

        total_runs += 1
        data = extract_json_blob(text)
        if not data:
            continue

        status = str(data.get('status', '')).lower()
        issues = data.get('issues') or []
        actions = data.get('actions') or []
        startup_grace = bool(data.get('startup_grace'))

        if status not in {'warn', 'fail'}:
            continue

        alert_runs += 1
        is_tp = bool(issues) or bool(actions)
        is_fp_cand = (not issues and not actions) or (startup_grace and not issues and not actions)

        if is_tp:
            tp += 1
        if is_fp_cand:
            fp_candidates += 1

        if len(samples) < 5:
            samples.append({
                'file': p.name,
                'status': status,
                'issues': issues,
                'actions': actions,
                'startup_grace': startup_grace,
                'label': 'fp_candidate' if is_fp_cand else 'tp',
            })

    fp_rate = (fp_candidates / alert_runs) if alert_runs else 0.0
    payload = {
        'window': '7d',
        'total_runs': total_runs,
        'alert_runs': alert_runs,
        'true_positive_alerts': tp,
        'false_positive_candidates': fp_candidates,
        'false_positive_candidate_rate': round(fp_rate, 4),
        'target_rate_max': 0.02,
        'gate_pass': fp_rate <= 0.02,
        'note': 'FP is heuristic candidate label; validate manually for final KPI.',
        'samples': samples,
    }

    print(json.dumps(payload, indent=2))
    return 0 if payload['gate_pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
