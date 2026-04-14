# INCIDENTS

### Incident | local: 2026-04-10 03:10:01 CEST | utc: 2026-04-10T01:10:01Z
- Symptom: Watchdog remediation path triggered bot start while an existing bot instance was already running.
- Remediation: Executed `mkdir -p ops && nohup ./.venv/bin/python main.py >> ops/bot.log 2>&1 &` from bot repo during watchdog run.
- Final status: resolved (gateway active, bot process running, port 8050 listening).
- Likely cause hypothesis:
  - Prior watchdog check timed out and took remediation path before full verification completed.
  - Evidence: existing PID 94033 (started 00:05) already held LISTEN on :8050, while a second PID 147174 was launched at 03:04.
- Follow-up prevention action:
  - Add singleton guard (PID/lockfile) + pre-start health check (`lsof -i :8050`) before launching a new bot instance.

### Incident | local: 2026-04-10 04:45:38 CEST | utc: 2026-04-10T02:45:38Z
- Symptom: Bot process was running but dashboard port 8050 was not listening.
- Remediation: Restarted bot once (`kill` existing main.py PID, then `nohup ./.venv/bin/python main.py >> ops/bot.log 2>&1 &`) and re-verified process + :8050 listener.
- Final status: resolved
- Likely cause hypothesis:
  - Initial check showed active bot PID(s) while `ss -ltn` had no :8050 LISTEN socket.
  - Earlier logs show prior `Address already in use`/dashboard binding contention, consistent with intermittent dashboard thread startup issues.
- Follow-up prevention action:
  - Add a post-start health gate in launcher (fail/restart if :8050 is not LISTEN within 30s) and enforce single-instance startup lock.



### Incident 2026-04-10 07:55:51 CEST
- timestamp_local: 2026-04-10T07:55:51+02:00
- timestamp_utc: 2026-04-10T05:55:52Z
- incident_key: watchdog_misdetection_gateway_bot
- detected_symptom: Watchdog first pass mis-detected gateway inactive and bot down, triggering unnecessary restart path.
- remediation_actions: Ran `hermes gateway start`; launched bot via `nohup ./.venv/bin/python main.py`; verified health; removed duplicate bot instance and kept PID bound to :8050.
- final_status: resolved
- likely_cause_hypothesis:
  - Health parser used brittle text matching (`inactive` substring) against `hermes gateway status` output that still indicates `Active: active (running)`.
  - Bot process check matched only absolute path while live process command was `./.venv/bin/python main.py`, causing false negative.
- follow_up_prevention_action:
  - Harden watchdog checks to parse `Active: active (running)` and accept both relative/absolute bot command patterns before any start action.
- check_snapshot: gateway=ok, bot_process=ok, port_8050=ok


### Incident 2026-04-10 11:52:32 CEST
- timestamp_local: 2026-04-10T11:52:32.286837+02:00
- timestamp_utc: 2026-04-10T09:52:32Z
- incident_key: bot_process_running_port_8050_not_listening
- detected_symptom: Bot process running in repo, but dashboard port 8050 was not listening.
- remediation_actions: Restarted bot once (terminated existing main.py process for repo, started `./.venv/bin/python main.py` via nohup), then re-verified process + :8050 LISTEN.
- final_status: resolved
- likely_cause_hypothesis:
  - Dashboard thread likely failed to bind on prior run; evidence: process existed while initial `ss -ltnp` check showed no :8050 listener.
  - Post-restart logs show normal dashboard startup (`Dash is running on http://0.0.0.0:8050/`) and :8050 listener present.
- follow_up_prevention_action:
  - Add launcher health gate: if bot PID exists but :8050 is absent after 30s, auto-restart and emit explicit error metric.


---

### Incident 2026-04-10 14:59:31 CEST | 2026-04-10 12:59:31 UTC
- Opened Epoch: 1775825971
- Symptom Key: gateway_status_warning_outdated_unit
- Detected Symptom: `hermes gateway status` reported warning: "Installed gateway service definition is outdated" while service remained active.
- Remediation Actions: executed `hermes gateway start` (no-op; service already running), then re-verified checks.
- Final Status: resolved
- Likely Cause Hypothesis:
  - Watchdog parser treated warning text as failure condition despite `Active: active (running)` and exit code 0.
  - Evidence: post-remediation verification showed gateway active, trading bot PID present, and :8050 listening.
- Follow-up Prevention Action:
  - Treat `Active: active (running)` + exit code 0 as healthy, and classify "outdated service definition" as WARN (advisory) unless startup actually fails.

### Incident 2026-04-10 19:08:32 CEST | 2026-04-10 17:08:34 UTC
- Opened Epoch: 1775840914
- Symptom Key: bot_process_running_port_8050_not_listening
- Detected Symptom: Bot process running in repo, but dashboard port 8050 was not listening.
- Remediation Actions: Restarted bot once (terminated repo `main.py` process(es), relaunched `./.venv/bin/python main.py` in background), then continued verification. Initial `ss -ltnp` checks remained empty, but subsequent validation confirmed listener via `lsof -iTCP:8050 -sTCP:LISTEN` and HTTP 200 from `http://127.0.0.1:8050`.
- Final Status: resolved
- Likely Cause Hypothesis:
  - Dashboard startup lagged behind core bot loops; evidence: bot log shows `[dashboard] Starting on http://localhost:8050` and later `Dash is running on http://0.0.0.0:8050/` after initial port checks.
  - `ss -ltnp` appears unreliable in this environment for detecting the bot socket, while `lsof` and HTTP probe confirmed active service.
- Follow-up Prevention Action:
  - Use dual readiness checks (`lsof` + HTTP probe) with a 60s startup window before declaring `:8050` unhealthy.

### Incident 2026-04-10 19:42:01 CEST | 2026-04-10 17:42:01 UTC
- Opened Epoch: 1775842921
- Symptom Key: bot_process_running_port_8050_not_listening
- Detected Symptom: Bot process was running in repo, but dashboard port 8050 was not listening/responding on initial verification checks.
- Remediation Actions: Restarted bot once per watchdog policy (killed existing `main.py` process, relaunched `./.venv/bin/python main.py` in background), then re-checked listener with `ss -ltnp`, `lsof -iTCP:8050 -sTCP:LISTEN`, and HTTP probe `curl http://127.0.0.1:8050`.
- Final Status: resolved
- Likely Cause Hypothesis:
  - Dashboard bind was delayed during startup/backtest phase; evidence: early logs show long-running backtest stages before socket appeared.
  - `ss -ltnp` is intermittently unreliable in this environment; evidence: `ss` stayed empty while `lsof` later confirmed `python ... TCP *:8050 (LISTEN)`.
- Follow-up Prevention Action:
  - Use dual readiness checks (`ss` + `lsof`/HTTP) with a startup grace window before declaring `:8050` unhealthy.

### Incident 2026-04-10 20:59:28 CEST | 2026-04-10 18:59:28 UTC
- Opened Epoch: 1775847568
- Symptom Key: dashboard_not_ready_after_remediation
- Detected Symptom: After running canonical watchdog remediation, bot process was present but dashboard readiness checks still failed after >60s (`lsof -iTCP:8050 -sTCP:LISTEN` empty and HTTP probe to `http://127.0.0.1:8050` returned URLError).
- Remediation Actions: Executed `./.venv/bin/python ops/diagnostics/stack_watchdog.py --remediate`; watchdog run triggered bot dedupe/restart behavior and converged to a single bot PID, then performed 60s+ post-start verification checks.
- Final Status: unresolved (gateway active, bot running, dashboard not ready)
- Likely Cause Hypothesis:
  - Bot process starts but dashboard thread is not binding to :8050 in this run window (startup path delay/failure).
  - Concurrent external watchdog/process-control activity likely interrupted remediation attempts (observed watchdog exits with code 143).
- Follow-up Prevention Action:
  - Inspect `ops/bot.log` for dashboard init/bind exceptions and enforce a hard restart-with-backoff policy when :8050 fails both lsof+HTTP after 60s.

### Incident 2026-04-10 23:05:39 CEST | 2026-04-10T21:05:39Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['bot_start', 'bot_dedupe_restart']
- gateway_healthy: True
- bot_running: True
- bot_pids: [695950, 696746]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|bot_dedupe_restart,bot_start|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-10 23:05:42 CEST | 2026-04-10T21:05:42Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [695950, 696746]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-10 23:24:00 CEST | 2026-04-10T21:24:00Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['bot_dedupe_restart']
- gateway_healthy: True
- bot_running: True
- bot_pids: [738667, 739500]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|bot_dedupe_restart|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-10 23:57:16 CEST | 2026-04-10T21:57:16Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['bot_dedupe_restart']
- gateway_healthy: True
- bot_running: True
- bot_pids: [752602, 752654]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|bot_dedupe_restart|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 00:28:45 CEST | 2026-04-10T22:28:45Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['bot_dedupe_restart']
- gateway_healthy: True
- bot_running: True
- bot_pids: [760112, 760156]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|bot_dedupe_restart|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 01:00:57 CEST | 2026-04-10T23:00:57Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['bot_dedupe_restart']
- gateway_healthy: True
- bot_running: True
- bot_pids: [766204, 766251]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|bot_dedupe_restart|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 01:33:48 CEST | 2026-04-10T23:33:48Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['bot_restart']
- gateway_healthy: True
- bot_running: True
- bot_pids: [769747, 769784]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|bot_restart|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 02:05:57 CEST | 2026-04-11T00:05:57Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['bot_dedupe_restart']
- gateway_healthy: True
- bot_running: True
- bot_pids: [773355, 773392]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|bot_dedupe_restart|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 02:11:40 CEST | 2026-04-11T00:11:40Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [773355, 773392]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 02:12:18 CEST | 2026-04-11T00:12:18Z
- status: fail
- issues: ['dashboard_not_ready']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [773392]
- dashboard: {'listening': False, 'http_ok': False, 'healthy': False}
- likely_cause: dashboard_not_ready
- signature: fail|dashboard_not_ready|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 02:36:21 CEST | 2026-04-11T00:36:21Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [784329, 784368]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 02:37:40 CEST | 2026-04-11T00:37:40Z
- status: fail
- issues: ['dashboard_not_ready']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [784368]
- dashboard: {'listening': False, 'http_ok': False, 'healthy': False}
- likely_cause: dashboard_not_ready
- signature: fail|dashboard_not_ready|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 02:38:05 CEST | 2026-04-11T00:38:05Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [837640]
- dashboard: {'listening': False, 'http_ok': False, 'healthy': False}
- likely_cause: startup_grace_window
- signature: warn|none|none|startup_grace=True
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 11:44:17 CEST | 2026-04-11T09:44:17Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [837640, 924722]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 11:47:01 CEST | 2026-04-11T09:47:01Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [976386]
- dashboard: {'listening': False, 'http_ok': False, 'healthy': False}
- likely_cause: startup_grace_window
- signature: warn|none|none|startup_grace=True
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 12:20:11 CEST | 2026-04-11T10:20:11Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [976386, 999712]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 14:53:12 CEST | 2026-04-11T12:53:12Z
- status: fail
- issues: ['bot_multiple_instances']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1177808, 1180872]
- dashboard: {'listening': False, 'http_ok': False, 'healthy': False}
- likely_cause: bot_multiple_instances
- signature: fail|bot_multiple_instances|none|startup_grace=True
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-11 14:54:21 CEST | 2026-04-11T12:54:21Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1177808]
- dashboard: {'listening': False, 'http_ok': False, 'healthy': False}
- likely_cause: startup_grace_window
- signature: warn|none|none|startup_grace=True
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 01:06:17 CEST | 2026-04-11T23:06:17Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1624441]
- dashboard: {'listening': False, 'http_ok': False, 'healthy': False}
- likely_cause: startup_grace_window
- signature: warn|none|none|startup_grace=True
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 13:01:51 CEST | 2026-04-12T11:01:51Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1681176]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 18:07:58 CEST | 2026-04-12T16:07:58Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1681176]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 18:38:22 CEST | 2026-04-12T16:38:22Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1681176]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 19:09:14 CEST | 2026-04-12T17:09:14Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1681176]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 19:39:52 CEST | 2026-04-12T17:39:52Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1681176]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 20:11:00 CEST | 2026-04-12T18:11:00Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1681176]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 20:41:56 CEST | 2026-04-12T18:41:56Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1681176]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-12 21:12:14 CEST | 2026-04-12T19:12:14Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [1681176]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.

### Incident 2026-04-13 09:20:48 CEST | 2026-04-13T07:20:48Z
- status: warn
- issues: ['none']
- actions: ['none']
- gateway_healthy: True
- bot_running: True
- bot_pids: [3252]
- dashboard: {'listening': True, 'http_ok': True, 'healthy': True}
- likely_cause: remediation_performed
- signature: warn|none|none|startup_grace=False
- follow_up_prevention_action: keep watchdog canonical script as single remediation path and avoid ad-hoc restarts.
