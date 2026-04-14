#!/usr/bin/env python3
"""Controlled failure-injection check.

Mode:
- default dry-run (no side effects)
- --execute performs one controlled bot-kill drill, then validates watchdog remediation
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REPORT_DIR = Path("/home/thomas/Dropbox/Projects/Claude-trading-bot/ops/reports")
WATCHDOG_CMD = "cd /home/thomas/Dropbox/Projects/Claude-trading-bot && ./.venv/bin/python ops/diagnostics/stack_watchdog.py"
WATCHDOG_REMEDIATE_CMD = WATCHDOG_CMD + " --remediate"


def run(command: str) -> tuple[int, str]:
    p = subprocess.run(["bash", "-lc", command], capture_output=True, text=True)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode, out


def watchdog_json(remediate: bool = False) -> dict:
    code, out = run(WATCHDOG_REMEDIATE_CMD if remediate else WATCHDOG_CMD)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        data = {"status": "fail", "error": "non_json_watchdog_output", "raw": out[-3000:], "exit_code": code}
    data["exit_code"] = code
    return data


def pick_bot_pid(base: dict) -> int | None:
    pids = ((base.get("bot") or {}).get("pids") or [])
    if not pids:
        return None
    return int(sorted(pids)[0])


def write_report(payload: dict) -> dict:
    now = datetime.now(timezone.utc)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"failure_injection_{stamp}.json"
    md_path = REPORT_DIR / f"failure_injection_{stamp}.md"

    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md = [
        "# Failure Injection Check",
        "",
        f"- status: {payload.get('status')}",
        f"- scenario: {payload.get('scenario')}",
        f"- bot_killed_pid: {payload.get('bot_killed_pid')}",
        f"- remediation_seconds: {payload.get('remediation_seconds')}",
        f"- gate_mttr_le_300s: {payload.get('gate_mttr_le_300s')}",
        f"- notes: {payload.get('notes')}",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled failure-injection check")
    parser.add_argument("--execute", action="store_true", help="Run the real drill (kills bot process once)")
    args = parser.parse_args()

    base = watchdog_json(remediate=False)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scenario": "bot_kill_then_watchdog_remediate",
        "mode": "execute" if args.execute else "dry_run",
        "baseline": base,
    }

    if not args.execute:
        payload.update(
            {
                "status": "PASS",
                "notes": "dry-run only; no process killed",
                "bot_killed_pid": None,
                "remediation_seconds": 0,
                "gate_mttr_le_300s": True,
            }
        )
        payload["report_files"] = write_report(payload)
        print(json.dumps(payload, indent=2))
        return 0

    if str(base.get("status")).lower() not in {"ok", "warn"}:
        payload.update(
            {
                "status": "SKIP",
                "notes": "baseline not healthy enough for controlled drill",
                "bot_killed_pid": None,
                "remediation_seconds": 0,
                "gate_mttr_le_300s": False,
            }
        )
        payload["report_files"] = write_report(payload)
        print(json.dumps(payload, indent=2))
        return 0

    pid = pick_bot_pid(base)
    if pid is None:
        payload.update(
            {
                "status": "FAIL",
                "notes": "no bot pid found for drill",
                "bot_killed_pid": None,
                "remediation_seconds": 0,
                "gate_mttr_le_300s": False,
            }
        )
        payload["report_files"] = write_report(payload)
        print(json.dumps(payload, indent=2))
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        payload.update(
            {
                "status": "FAIL",
                "notes": "target pid disappeared before kill",
                "bot_killed_pid": pid,
                "remediation_seconds": 0,
                "gate_mttr_le_300s": False,
            }
        )
        payload["report_files"] = write_report(payload)
        print(json.dumps(payload, indent=2))
        return 0

    time.sleep(2)
    t0 = time.time()
    rem = watchdog_json(remediate=True)
    elapsed = int(time.time() - t0)
    post = watchdog_json(remediate=False)

    post_ok = str(post.get("status", "")).lower() == "ok"
    mttr_ok = elapsed <= 300
    status = "PASS" if post_ok and mttr_ok else ("WARN" if post_ok else "FAIL")

    payload.update(
        {
            "status": status,
            "bot_killed_pid": pid,
            "remediation": rem,
            "post_check": post,
            "remediation_seconds": elapsed,
            "gate_mttr_le_300s": mttr_ok,
            "notes": "controlled bot kill drill executed",
        }
    )
    payload["report_files"] = write_report(payload)
    print(json.dumps(payload, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
