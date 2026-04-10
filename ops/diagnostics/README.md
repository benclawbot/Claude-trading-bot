Diagnostic scripts (manual, non-CI)

Purpose:
- Keep one-off/manual integrity scripts out of automated pytest unit discovery.
- Reduce test-suite noise and avoid accidental network/live-client execution in CI.

Run from repo root:
- .venv/bin/python ops/diagnostics/portfolio_integrity_check.py
- .venv/bin/python ops/diagnostics/portfolio_integrity_autofix.py
- .venv/bin/python ops/diagnostics/stack_watchdog.py
- .venv/bin/python ops/diagnostics/stack_watchdog.py --remediate

Notes:
- stack_watchdog.py uses robust gateway health parsing and treats "service definition outdated" as WARN, not FAIL, when service is active.
- Dashboard health requires BOTH socket listener (lsof) and HTTP readiness probe.
