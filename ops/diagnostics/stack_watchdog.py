#!/usr/bin/env python3
"""Operational watchdog for Hermes gateway + trading bot stack.

Goals:
- Robust health checks (no brittle substring parsing)
- Dual dashboard readiness checks (LISTEN socket + HTTP probe)
- Optional remediation with startup grace window
- Singleton start lock to avoid duplicate bot launch
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


BOT_REPO = Path("/home/thomas/Dropbox/Projects/Claude-trading-bot")
BOT_CMD = "./.venv/bin/python main.py"
LOCK_FILE = BOT_REPO / ".bot_start.lock"
STALE_LOCK_SECONDS = 300
STARTUP_GRACE_SECONDS = 180
DASHBOARD_PORT = 8050
DASHBOARD_URL = "http://127.0.0.1:8050"
INCIDENTS_FILE = BOT_REPO / "ops" / "INCIDENTS.md"


@dataclass
class CommandResult:
    exit_code: int
    output: str


def run_cmd(command: str, cwd: Optional[Path] = None) -> CommandResult:
    proc = subprocess.run(
        ["bash", "-lc", command],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return CommandResult(exit_code=proc.returncode, output=out.strip())


def parse_gateway_health(status_output: str, exit_code: int) -> Tuple[bool, List[str]]:
    warnings: List[str] = []
    healthy = False

    if exit_code == 0 and (
        "Active: active (running)" in status_output
        or "User gateway service is running" in status_output
    ):
        healthy = True

    if "outdated" in status_output.lower():
        warnings.append("gateway_service_definition_outdated")

    return healthy, warnings


def check_gateway() -> Dict[str, object]:
    result = run_cmd("hermes gateway status")
    healthy, warnings = parse_gateway_health(result.output, result.exit_code)
    return {
        "healthy": healthy,
        "warnings": warnings,
        "exit_code": result.exit_code,
        "raw": result.output,
    }


def list_bot_pids(repo: Path = BOT_REPO) -> List[int]:
    result = run_cmd("ps -eo pid=,args=")
    pids: List[int] = []
    repo_s = str(repo)

    for line in result.output.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s+(.*)$", line)
        if not m:
            continue
        pid = int(m.group(1))
        args = m.group(2)

        # Ignore shell wrappers that merely contain the text "main.py"
        if "bash -lc" in args or "sh -lc" in args:
            continue

        try:
            tokens = shlex.split(args)
        except ValueError:
            continue
        if not tokens:
            continue

        exe = tokens[0]
        if "python" not in Path(exe).name.lower():
            continue

        main_tokens = [t for t in tokens[1:] if t == "main.py" or t.endswith("/main.py")]
        if not main_tokens:
            continue

        if repo_s in args or exe.startswith("./.venv/bin/python"):
            pids.append(pid)

    return sorted(set(pids))


def get_pid_uptime_seconds(pid: int) -> Optional[int]:
    result = run_cmd(f"ps -p {pid} -o etimes=")
    if result.exit_code != 0:
        return None
    try:
        return int(result.output.strip())
    except (TypeError, ValueError):
        return None


def get_bot_uptime_seconds(pids: List[int]) -> Optional[int]:
    uptimes = [u for u in (get_pid_uptime_seconds(pid) for pid in pids) if u is not None]
    if not uptimes:
        return None
    return min(uptimes)


def check_port_listening(port: int = DASHBOARD_PORT) -> bool:
    cmd = f"lsof -nP -iTCP:{port} -sTCP:LISTEN"
    result = run_cmd(cmd)
    return result.exit_code == 0 and bool(result.output.strip())


def check_http_ready(url: str = DASHBOARD_URL, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 500
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, ConnectionResetError):
        return False


def check_dashboard_ready() -> Dict[str, bool]:
    listening = check_port_listening(DASHBOARD_PORT)
    http_ok = check_http_ready(DASHBOARD_URL)
    return {
        "listening": listening,
        "http_ok": http_ok,
        "healthy": listening and http_ok,
    }


def acquire_lock(lock_path: Path = LOCK_FILE) -> bool:
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            lock_path.unlink(missing_ok=True)
        else:
            return False

    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode("utf-8"))
    os.close(fd)
    return True


def release_lock(lock_path: Path = LOCK_FILE) -> None:
    lock_path.unlink(missing_ok=True)


def start_bot(repo: Path = BOT_REPO) -> CommandResult:
    if not acquire_lock():
        return CommandResult(1, f"start_lock_busy:{LOCK_FILE}")
    try:
        ops_dir = repo / "ops"
        ops_dir.mkdir(parents=True, exist_ok=True)
        log_path = ops_dir / "bot.log"
        with open(log_path, "a", encoding="utf-8") as logf:
            proc = subprocess.Popen(
                ["./.venv/bin/python", "main.py"],
                cwd=str(repo),
                stdout=logf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        return CommandResult(0, f"started_pid:{proc.pid}")
    except Exception as e:
        return CommandResult(1, f"start_failed:{e}")
    finally:
        release_lock()


def kill_bot_processes(pids: List[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue


def wait_for_dashboard(timeout_s: int = STARTUP_GRACE_SECONDS, interval_s: int = 3) -> Dict[str, bool]:
    deadline = time.time() + timeout_s
    last = check_dashboard_ready()
    while time.time() < deadline:
        last = check_dashboard_ready()
        if last["healthy"]:
            return last
        time.sleep(interval_s)
    return last


def _build_incident_block(result: Dict[str, object]) -> str:
    now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    status = result.get("status", "unknown")
    issues = result.get("issues") or []
    actions = result.get("actions") or []

    if status == "warn" and result.get("startup_grace"):
        cause = "startup_grace_window"
    elif issues:
        cause = ", ".join(str(x) for x in issues)
    else:
        cause = "remediation_performed"

    block = [
        f"### Incident {now_local} | {now_utc}",
        f"- status: {status}",
        f"- issues: {issues if issues else ['none']}",
        f"- actions: {actions if actions else ['none']}",
        f"- gateway_healthy: {result.get('gateway', {}).get('healthy')}",
        f"- bot_running: {result.get('bot', {}).get('running')}",
        f"- bot_pids: {result.get('bot', {}).get('pids')}",
        f"- dashboard: {result.get('dashboard')}",
        f"- likely_cause: {cause}",
        "- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.",
        "",
    ]
    return "\n".join(block)


def write_incident_if_needed(result: Dict[str, object]) -> bool:
    status = result.get("status")
    actions = result.get("actions") or []
    needs_incident = status in {"warn", "fail"} or bool(actions)
    if not needs_incident:
        return False

    INCIDENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if INCIDENTS_FILE.exists():
        current = INCIDENTS_FILE.read_text(encoding="utf-8")
    else:
        current = "# INCIDENTS\n\n"

    if not current.strip():
        current = "# INCIDENTS\n\n"

    block = _build_incident_block(result)
    INCIDENTS_FILE.write_text(current.rstrip() + "\n\n" + block, encoding="utf-8")
    return True


def watchdog(remediate: bool = False) -> Dict[str, object]:
    actions: List[str] = []

    gateway = check_gateway()
    bot_pids = list_bot_pids(BOT_REPO)
    bot_running = len(bot_pids) > 0
    bot_uptime_s = get_bot_uptime_seconds(bot_pids)
    dashboard = check_dashboard_ready()

    issues: List[str] = []
    startup_grace = False
    if not gateway["healthy"]:
        issues.append("gateway_unhealthy")
    if not bot_running:
        issues.append("bot_not_running")
    if len(bot_pids) > 1:
        issues.append("bot_multiple_instances")
    if bot_running and not dashboard["healthy"]:
        if bot_uptime_s is not None and bot_uptime_s < STARTUP_GRACE_SECONDS:
            startup_grace = True
        else:
            issues.append("dashboard_not_ready")

    if remediate:
        if not gateway["healthy"]:
            run_cmd("hermes gateway start")
            actions.append("gateway_start")
            gateway = check_gateway()

        if not bot_running:
            start_bot(BOT_REPO)
            actions.append("bot_start")
            dashboard = wait_for_dashboard(interval_s=3)
            bot_pids = list_bot_pids(BOT_REPO)
            bot_running = len(bot_pids) > 0

        if len(bot_pids) > 1:
            kill_bot_processes(bot_pids)
            actions.append("bot_dedupe_restart")
            start_bot(BOT_REPO)
            dashboard = wait_for_dashboard(interval_s=3)
            bot_pids = list_bot_pids(BOT_REPO)
            bot_running = len(bot_pids) > 0

        if bot_running and not dashboard["healthy"]:
            kill_bot_processes(bot_pids)
            actions.append("bot_restart")
            start_bot(BOT_REPO)
            dashboard = wait_for_dashboard(interval_s=3)
            bot_pids = list_bot_pids(BOT_REPO)
            bot_running = len(bot_pids) > 0

        # recompute issues after remediation
        bot_uptime_s = get_bot_uptime_seconds(bot_pids)
        startup_grace = False
        issues = []
        if not gateway["healthy"]:
            issues.append("gateway_unhealthy")
        if not bot_running:
            issues.append("bot_not_running")
        if len(bot_pids) > 1:
            issues.append("bot_multiple_instances")
        if bot_running and not dashboard["healthy"]:
            if bot_uptime_s is not None and bot_uptime_s < STARTUP_GRACE_SECONDS:
                startup_grace = True
            else:
                issues.append("dashboard_not_ready")

    status = "ok" if not issues else "fail"
    if status == "ok" and (gateway.get("warnings") or startup_grace):
        status = "warn"

    return {
        "status": status,
        "issues": issues,
        "actions": actions,
        "gateway": gateway,
        "bot": {
            "running": bot_running,
            "pids": bot_pids,
            "uptime_seconds": bot_uptime_s,
        },
        "dashboard": dashboard,
        "startup_grace": startup_grace,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stack watchdog")
    parser.add_argument("--remediate", action="store_true", help="attempt automatic remediation")
    args = parser.parse_args()

    result = watchdog(remediate=args.remediate)
    incident_written = write_incident_if_needed(result)
    if incident_written:
        result["incident_logged"] = str(INCIDENTS_FILE)
    print(json.dumps(result, indent=2))
    if result["status"] == "fail":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
