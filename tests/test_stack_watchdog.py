import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "ops" / "diagnostics" / "stack_watchdog.py"
spec = importlib.util.spec_from_file_location("stack_watchdog", MODULE_PATH)
stack_watchdog = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = stack_watchdog
spec.loader.exec_module(stack_watchdog)


def test_parse_gateway_health_active_running_is_healthy():
    out = """\nActive: active (running) since Fri\nWARNING: Installed gateway service definition is outdated\n"""
    healthy, warnings = stack_watchdog.parse_gateway_health(out, 0)
    assert healthy is True
    assert "gateway_service_definition_outdated" in warnings


def test_parse_gateway_health_nonzero_is_unhealthy():
    out = "gateway command failed"
    healthy, warnings = stack_watchdog.parse_gateway_health(out, 1)
    assert healthy is False
    assert warnings == []


def test_list_bot_pids_accepts_relative_and_absolute_cmd(monkeypatch):
    output = (
        "123 /home/thomas/Dropbox/Projects/Claude-trading-bot/.venv/bin/python /home/thomas/Dropbox/Projects/Claude-trading-bot/main.py\n"
        "456 /usr/bin/python something_else.py\n"
        "777 /usr/bin/bash -lc ./.venv/bin/python main.py\n"
        "789 ./.venv/bin/python main.py\n"
    )

    def fake_run_cmd(command, cwd=None):
        return stack_watchdog.CommandResult(0, output)

    monkeypatch.setattr(stack_watchdog, "run_cmd", fake_run_cmd)
    pids = stack_watchdog.list_bot_pids()
    assert pids == [123, 789]


def test_watchdog_warn_when_outdated_warning_but_healthy(monkeypatch):
    monkeypatch.setattr(
        stack_watchdog,
        "check_gateway",
        lambda: {
            "healthy": True,
            "warnings": ["gateway_service_definition_outdated"],
            "exit_code": 0,
            "raw": "Active: active (running)",
        },
    )
    monkeypatch.setattr(stack_watchdog, "list_bot_pids", lambda repo=stack_watchdog.BOT_REPO: [111])
    monkeypatch.setattr(stack_watchdog, "get_bot_uptime_seconds", lambda pids: 999)
    monkeypatch.setattr(
        stack_watchdog,
        "check_dashboard_ready",
        lambda: {"listening": True, "http_ok": True, "healthy": True},
    )

    result = stack_watchdog.watchdog(remediate=False)
    assert result["status"] == "warn"
    assert result["issues"] == []


def test_watchdog_uses_startup_grace_instead_of_fail(monkeypatch):
    monkeypatch.setattr(
        stack_watchdog,
        "check_gateway",
        lambda: {"healthy": True, "warnings": [], "exit_code": 0, "raw": "Active: active (running)"},
    )
    monkeypatch.setattr(stack_watchdog, "list_bot_pids", lambda repo=stack_watchdog.BOT_REPO: [111])
    monkeypatch.setattr(stack_watchdog, "get_bot_uptime_seconds", lambda pids: 30)
    monkeypatch.setattr(
        stack_watchdog,
        "check_dashboard_ready",
        lambda: {"listening": False, "http_ok": False, "healthy": False},
    )

    result = stack_watchdog.watchdog(remediate=False)
    assert result["status"] == "warn"
    assert result["startup_grace"] is True
    assert result["issues"] == []


def test_watchdog_remediates_bot_not_running(monkeypatch):
    state = {"started": False}

    monkeypatch.setattr(
        stack_watchdog,
        "check_gateway",
        lambda: {"healthy": True, "warnings": [], "exit_code": 0, "raw": "Active: active (running)"},
    )

    def fake_list_bot_pids(repo=stack_watchdog.BOT_REPO):
        return [222] if state["started"] else []

    def fake_start_bot(repo=stack_watchdog.BOT_REPO):
        state["started"] = True
        return stack_watchdog.CommandResult(0, "started")

    monkeypatch.setattr(stack_watchdog, "list_bot_pids", fake_list_bot_pids)
    monkeypatch.setattr(stack_watchdog, "start_bot", fake_start_bot)
    monkeypatch.setattr(
        stack_watchdog,
        "wait_for_dashboard",
        lambda timeout_s=60, interval_s=3: {"listening": True, "http_ok": True, "healthy": True},
    )
    monkeypatch.setattr(
        stack_watchdog,
        "check_dashboard_ready",
        lambda: {"listening": False, "http_ok": False, "healthy": False},
    )

    result = stack_watchdog.watchdog(remediate=True)
    assert result["status"] == "ok"
    assert "bot_start" in result["actions"]
    assert result["bot"]["running"] is True


def test_watchdog_detects_multiple_bot_instances(monkeypatch):
    monkeypatch.setattr(
        stack_watchdog,
        "check_gateway",
        lambda: {"healthy": True, "warnings": [], "exit_code": 0, "raw": "Active: active (running)"},
    )
    monkeypatch.setattr(stack_watchdog, "list_bot_pids", lambda repo=stack_watchdog.BOT_REPO: [101, 202])
    monkeypatch.setattr(
        stack_watchdog,
        "check_dashboard_ready",
        lambda: {"listening": True, "http_ok": True, "healthy": True},
    )

    result = stack_watchdog.watchdog(remediate=False)
    assert result["status"] == "fail"
    assert "bot_multiple_instances" in result["issues"]
