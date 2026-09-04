"""B1 — per-profile gateway lifecycle + status.

`/api/gateway/{start,stop,restart}` and `/api/gateway/status` accept an optional
`profile` so an operator can act on / inspect a *non-active* bot's gateway
without switching the WebUI's active profile. No `profile` -> unchanged
active-profile behaviour (covered by test_gateway_lifecycle_controls.py).
"""

from __future__ import annotations

import json
import subprocess
import sys
from urllib.parse import urlparse


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.sent_headers: list[tuple[str, str]] = []
        self.body = bytearray()
        self.wfile = self
        self.headers = {}

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.sent_headers.append((key, value))

    def end_headers(self):
        pass

    def write(self, data):
        self.body.extend(data if isinstance(data, (bytes, bytearray)) else data.encode("utf-8"))

    def get_json(self):
        return json.loads(self.body.decode("utf-8"))


def _fake_agent(tmp_path):
    agent_dir = tmp_path / "hermes-agent"
    cli_dir = agent_dir / "hermes_cli"
    cli_dir.mkdir(parents=True)
    (cli_dir / "main.py").write_text("print('fake hermes cli')\n", encoding="utf-8")
    return agent_dir


def _call_post(monkeypatch, path: str, body: dict | None = None):
    from api import routes

    monkeypatch.setattr(routes, "_check_csrf", lambda handler: True)
    monkeypatch.setattr(routes, "read_body", lambda handler: body or {})
    handler = _FakeHandler()
    routes.handle_post(handler, urlparse(path))
    return handler, handler.get_json()


def _stub_status(monkeypatch):
    from api import routes

    monkeypatch.setattr(
        routes,
        "_gateway_status_payload_impl",
        lambda: {
            "running": False,
            "configured": True,
            "platforms": [],
            "last_active": "",
            "session_count": 0,
            "health": {},
        },
    )


def _capture_run(monkeypatch):
    from api import routes

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(routes.subprocess, "run", fake_run)
    return calls


def test_explicit_profile_targets_that_profile_not_the_active_one(monkeypatch, tmp_path):
    from api import config, profiles

    monkeypatch.setattr(config, "_AGENT_DIR", _fake_agent(tmp_path))
    monkeypatch.setattr(config, "PYTHON_EXE", sys.executable)
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "lancelot")
    _stub_status(monkeypatch)
    calls = _capture_run(monkeypatch)

    handler, data = _call_post(monkeypatch, "/api/gateway/start", {"profile": "bohorth"})

    assert handler.status == 200
    assert data["ok"] is True
    assert data["profile"] == "bohorth"
    # --profile is the requested bot, NOT the active profile.
    assert calls[0][-4:] == ["--profile", "bohorth", "gateway", "start"]


def test_profile_default_omits_the_profile_flag(monkeypatch, tmp_path):
    from api import config, profiles

    monkeypatch.setattr(config, "_AGENT_DIR", _fake_agent(tmp_path))
    monkeypatch.setattr(config, "PYTHON_EXE", sys.executable)
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "lancelot")
    _stub_status(monkeypatch)
    calls = _capture_run(monkeypatch)

    handler, data = _call_post(monkeypatch, "/api/gateway/restart", {"profile": "default"})

    assert handler.status == 200
    assert calls[0][-2:] == ["gateway", "restart"]
    assert "--profile" not in calls[0]


def test_invalid_profile_is_rejected_without_spawning(monkeypatch, tmp_path):
    from api import config, routes

    monkeypatch.setattr(config, "_AGENT_DIR", _fake_agent(tmp_path))
    monkeypatch.setattr(config, "PYTHON_EXE", sys.executable)
    spawned: list = []
    monkeypatch.setattr(
        routes.subprocess,
        "run",
        lambda cmd, **kw: spawned.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    handler, data = _call_post(monkeypatch, "/api/gateway/start", {"profile": "bad/x"})

    assert handler.status == 400
    assert data["error"] == "invalid profile"
    assert spawned == []


def test_actions_on_different_profiles_do_not_contend(monkeypatch, tmp_path):
    from api import config, profiles, routes

    monkeypatch.setattr(config, "_AGENT_DIR", _fake_agent(tmp_path))
    monkeypatch.setattr(config, "PYTHON_EXE", sys.executable)
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "lancelot")
    _stub_status(monkeypatch)
    _capture_run(monkeypatch)

    # Hold bohorth's per-profile lock -> an action on bohorth must 409,
    # but an action on lancelot must still proceed.
    held = routes._gateway_action_lock_for("bohorth")
    assert held.acquire(blocking=False)
    try:
        h_busy, d_busy = _call_post(monkeypatch, "/api/gateway/stop", {"profile": "bohorth"})
        h_ok, d_ok = _call_post(monkeypatch, "/api/gateway/start", {"profile": "lancelot"})
    finally:
        held.release()

    assert h_busy.status == 409
    assert d_busy["ok"] is False
    assert h_busy is not h_ok
    assert h_ok.status == 200
    assert d_ok["ok"] is True
    assert d_ok["profile"] == "lancelot"


def test_no_profile_still_uses_the_module_level_lock(monkeypatch, tmp_path):
    """Back-compat: the no-profile path keeps sharing _GATEWAY_ACTION_LOCK so
    existing single-flight coverage (and any operator scripts) is unaffected."""
    from api import config, profiles, routes

    monkeypatch.setattr(config, "_AGENT_DIR", _fake_agent(tmp_path))
    monkeypatch.setattr(config, "PYTHON_EXE", sys.executable)
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    spawned: list = []
    monkeypatch.setattr(
        routes.subprocess,
        "run",
        lambda cmd, **kw: spawned.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    assert routes._gateway_action_lock_for(None) is routes._GATEWAY_ACTION_LOCK
    assert routes._GATEWAY_ACTION_LOCK.acquire(blocking=False)
    try:
        handler, data = _call_post(monkeypatch, "/api/gateway/restart", {})
    finally:
        routes._GATEWAY_ACTION_LOCK.release()

    assert handler.status == 409
    assert spawned == []


def test_status_accepts_profile_query_and_reports_it(monkeypatch):
    from api import routes

    _stub_status(monkeypatch)
    monkeypatch.setattr(routes, "_check_gateway_running_for_home", lambda home: True)

    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/gateway/status?profile=bohorth"))
    data = handler.get_json()

    assert data["profile"] == "bohorth"
    # per-home probe wins over the metadata-derived guess
    assert data["running"] is True
    assert data["configured"] is True


def test_status_rejects_invalid_profile_query(monkeypatch):
    from api import routes

    _stub_status(monkeypatch)
    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/gateway/status?profile=..%2Fetc"))
    data = handler.get_json()

    assert handler.status == 400
    assert data["error"] == "invalid profile"


def test_status_without_profile_is_unchanged(monkeypatch):
    from api import routes

    _stub_status(monkeypatch)
    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/gateway/status"))
    data = handler.get_json()

    assert "profile" not in data
    assert data["configured"] is True
