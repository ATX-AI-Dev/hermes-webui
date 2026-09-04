"""B4 prototype — continue_bot_chat_prototype() / POST /api/bot-chat/continue.

Experimental probe (see PLAN-B4-fusion-conversation.md): imports a profile's
real Bot Chat session_id into WebUI's own session store via the existing
CLI-session bridge (api.models.import_cli_session / get_cli_session_messages),
so replying in WebUI continues that exact agent-native session. These tests
cover the plumbing only — they cannot verify the actual open question (does
message_agent stay injected after a WebUI-driven turn); that needs a live
manual test on .178.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.body = bytearray()
        self.wfile = self

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        pass

    def end_headers(self):
        pass

    def write(self, data):
        self.body.extend(data if isinstance(data, (bytes, bytearray)) else data.encode("utf-8"))

    def get_json(self):
        return json.loads(self.body.decode("utf-8"))


def _call_post(monkeypatch, path, body):
    from api import routes
    monkeypatch.setattr(routes, "_check_csrf", lambda handler: True)
    monkeypatch.setattr(routes, "read_body", lambda handler: body or {})
    handler = _FakeHandler()
    routes.handle_post(handler, urlparse(path))
    return handler, handler.get_json()


def test_no_bot_chat_session_fails_cleanly(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "find_bot_chat_session", lambda profile: None)
    result = bot_mesh.continue_bot_chat_prototype("lancelot")
    assert result["ok"] is False
    assert "lancelot" in result["error"]


def test_empty_message_list_fails_cleanly(monkeypatch):
    from api import bot_mesh, models
    monkeypatch.setattr(bot_mesh, "find_bot_chat_session", lambda profile: {"session_id": "s1", "last_activity_at": 1.0})
    monkeypatch.setattr(models, "get_cli_session_messages", lambda sid, profile=None: [])
    result = bot_mesh.continue_bot_chat_prototype("lancelot")
    assert result["ok"] is False
    assert "no readable messages" in result["error"].lower()


def test_happy_path_imports_with_profile_scoped_readers(monkeypatch):
    from api import bot_mesh, models

    calls = {}
    monkeypatch.setattr(bot_mesh, "find_bot_chat_session", lambda profile: {"session_id": "s1", "message_count": 2, "last_activity_at": 42.0})

    def fake_get_messages(sid, profile=None):
        calls["get_messages"] = (sid, profile)
        return [{"role": "assistant", "content": "hi"}]

    def fake_import(sid, title, msgs, model="unknown", profile=None, updated_at=None, **kw):
        calls["import"] = dict(sid=sid, title=title, msgs=msgs, model=model, profile=profile, updated_at=updated_at)

    monkeypatch.setattr(models, "get_cli_session_messages", fake_get_messages)
    monkeypatch.setattr(models, "import_cli_session", fake_import)

    result = bot_mesh.continue_bot_chat_prototype("lancelot")

    assert result == {"ok": True, "session_id": "s1"}
    assert calls["get_messages"] == ("s1", "lancelot")
    assert calls["import"]["sid"] == "s1"
    assert calls["import"]["title"] == "Bot Chat"
    assert calls["import"]["profile"] == "lancelot"
    assert calls["import"]["updated_at"] == 42.0


def test_import_failure_is_caught_not_raised(monkeypatch):
    from api import bot_mesh, models
    monkeypatch.setattr(bot_mesh, "find_bot_chat_session", lambda profile: {"session_id": "s1", "last_activity_at": 1.0})
    monkeypatch.setattr(models, "get_cli_session_messages", lambda sid, profile=None: [{"role": "user", "content": "x"}])

    def boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(models, "import_cli_session", boom)

    result = bot_mesh.continue_bot_chat_prototype("lancelot")
    assert result["ok"] is False
    assert "disk full" in result["error"]


def test_route_rejects_invalid_profile(monkeypatch):
    handler, data = _call_post(monkeypatch, "/api/bot-chat/continue", {"profile": "bad/x"})
    assert handler.status == 400
    assert data["error"] == "invalid profile"


def test_route_returns_result_payload_on_success(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "continue_bot_chat_prototype", lambda profile: {"ok": True, "session_id": "s1"})
    handler, data = _call_post(monkeypatch, "/api/bot-chat/continue", {"profile": "lancelot"})
    assert handler.status == 200
    assert data == {"ok": True, "session_id": "s1"}


def test_route_returns_400_on_failure_payload(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "continue_bot_chat_prototype", lambda profile: {"ok": False, "error": "nope"})
    handler, data = _call_post(monkeypatch, "/api/bot-chat/continue", {"profile": "lancelot"})
    assert handler.status == 400
    assert data == {"ok": False, "error": "nope"}
