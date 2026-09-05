"""WebUI notices when Hermes Agent was updated under it, and offers a restart.

WebUI imports the agent in-process (``run_agent``, ``hermes_cli``). On the
production host the agent auto-updates hourly while WebUI, being a fork, is
deployed by hand — so after any agent release this process keeps executing the
modules it loaded at startup, with nothing saying so. api/agent_drift.py turns
that into a banner with a one-click fix.

The restart path is upstream's (``_wait_until_restart_safe`` then
``_schedule_restart``, which re-execs via ``os.execv``). These tests monkeypatch
both: calling the real ones would replace the pytest process.
"""

from __future__ import annotations

import threading
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "static"


def _fresh_module(monkeypatch, sha):
    """Reload api.agent_drift with agent_sha() pinned, so _STARTED_WITH is `sha`."""
    import importlib
    import api.agent_drift as mod
    monkeypatch.setattr(mod, "agent_sha", lambda: sha)
    mod = importlib.reload(mod)
    monkeypatch.setattr(mod, "agent_sha", lambda: sha)
    monkeypatch.setattr(mod, "_STARTED_WITH", sha)
    return mod


def test_no_drift_when_the_agent_has_not_moved(monkeypatch):
    mod = _fresh_module(monkeypatch, "aaaa1111")
    status = mod.drift_status()
    assert status["drifted"] is False
    assert status["started_with"] == status["current"] == "aaaa1111"


def test_drift_when_the_agent_sha_changed(monkeypatch):
    mod = _fresh_module(monkeypatch, "aaaa1111")
    monkeypatch.setattr(mod, "agent_sha", lambda: "bbbb2222")
    status = mod.drift_status()
    assert status["drifted"] is True
    assert status["started_with"] == "aaaa1111"
    assert status["current"] == "bbbb2222"


def test_unreadable_sha_never_claims_drift(monkeypatch):
    """A missing agent checkout must not produce a banner that can't be acted on."""
    mod = _fresh_module(monkeypatch, "aaaa1111")
    monkeypatch.setattr(mod, "agent_sha", lambda: None)
    assert mod.drift_status()["drifted"] is False

    mod = _fresh_module(monkeypatch, None)
    monkeypatch.setattr(mod, "agent_sha", lambda: "bbbb2222")
    assert mod.drift_status()["drifted"] is False


def test_restart_drains_in_flight_work_before_re_exec(monkeypatch):
    """The order matters: draining first is what keeps a live stream from being
    killed mid-response by the execv.

    Called SYNCHRONOUSLY, never through request_restart's thread: if that
    thread outlived monkeypatch teardown it would reach the real
    _schedule_restart and os.execv the pytest process itself.
    """
    mod = _fresh_module(monkeypatch, "aaaa1111")
    calls = []

    import api.updates as updates
    monkeypatch.setattr(updates, "_wait_until_restart_safe", lambda *a, **k: calls.append("wait") or {})
    monkeypatch.setattr(updates, "_schedule_restart", lambda *a, **k: calls.append("exec"))

    mod._restart_worker()
    assert calls == ["wait", "exec"]


def test_request_restart_hands_off_to_a_background_thread(monkeypatch):
    """The handler must not block: _wait_until_restart_safe sleeps up to 300s."""
    mod = _fresh_module(monkeypatch, "aaaa1111")
    started = threading.Event()
    # Replace the worker itself — nothing in this test may reach os.execv.
    monkeypatch.setattr(mod, "_restart_worker", started.set)
    import api.updates as updates
    monkeypatch.setattr(updates, "_restart_blocker_snapshot", lambda: {"restart_blocked": False})
    try:
        result = mod.request_restart()
        assert result["ok"] is True
        assert started.wait(5), "the restart worker never ran"
    finally:
        mod._restarting.clear()


def test_restart_is_idempotent_while_one_is_pending(monkeypatch):
    """Double-clicking the button must not start two re-execs."""
    mod = _fresh_module(monkeypatch, "aaaa1111")
    mod._restarting.set()
    try:
        assert mod.request_restart() == {"ok": True, "already": True}
    finally:
        mod._restarting.clear()


def test_routes_are_two_line_dispatches():
    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text(encoding="utf-8")
    assert 'if parsed.path == "/api/agent-drift":' in routes
    assert "from api.agent_drift import handle_get_drift" in routes
    assert 'if parsed.path == "/api/agent-drift/restart":' in routes
    assert "from api.agent_drift import handle_post_restart" in routes
    # imported at module level for its side effect: capture the startup SHA
    assert "from api import agent_drift as _agent_drift" in routes


def test_frontend_banner_is_persistent_and_wired():
    js = (_STATIC / "agent_drift.js").read_text(encoding="utf-8")
    css = (_STATIC / "bots_panel.css").read_text(encoding="utf-8")
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    sw = (_STATIC / "sw.js").read_text(encoding="utf-8")

    # NOT showToast: that one auto-dismisses, which is the whole point of the banner
    assert "showToast" not in js
    assert "agent-drift-banner" in js and ".agent-drift-banner" in css
    assert "position: fixed" in css[css.index(".agent-drift-banner"):css.index(".agent-drift-banner") + 200]
    # "later" is keyed on the SHA so the next agent release brings it back
    assert "AGENT_DRIFT_DISMISS_KEY" in js
    assert "localStorage.setItem(AGENT_DRIFT_DISMISS_KEY, sha)" in js
    assert "'/api/agent-drift/restart'" in js
    assert "static/agent_drift.js" in html
    assert "'./static/agent_drift.js'" in sw


def test_i18n_keys_exist_en_and_fr():
    i18n = (_STATIC / "i18n_fork.js").read_text(encoding="utf-8")
    for key in ("agent_drift_message", "agent_drift_restart",
                "agent_drift_later", "agent_drift_restarting"):
        assert i18n.count(f"{key}:") == 2, key
