"""B3 — read-only Bot Chat transcript reader.

Schema mirrors the real .178 state.db columns verified 2026-09-04 (see
api/bot_mesh.py module docstring): sessions(title, hidden, profile_name, ...),
messages(role, content, tool_call_id, tool_calls, tool_name, timestamp).
"""

from __future__ import annotations

import json
import sqlite3
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


def _make_db(base_dir, sessions, messages):
    """sessions: list of (id, title, hidden, profile_name, message_count, last_activity_at).
    messages: list of (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp).
    """
    db = sqlite3.connect(base_dir / "state.db")
    db.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, hidden INTEGER, "
        "profile_name TEXT, message_count INTEGER, last_activity_at TEXT)"
    )
    db.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)", sessions)
    db.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, "
        "role TEXT, content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL)"
    )
    db.executemany(
        "INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        messages,
    )
    db.commit()
    db.close()


def _relay_call(tool_call_id, target, message):
    return json.dumps([
        {"id": tool_call_id, "function": {"name": "message_agent", "arguments": json.dumps({"target": target, "message": message})}}
    ])


def _patch_base_home(monkeypatch, base_dir):
    from api import profiles
    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: base_dir)


def test_no_bot_chat_session_for_profile(monkeypatch, tmp_path):
    from api import bot_mesh
    _make_db(tmp_path, sessions=[], messages=[])
    _patch_base_home(monkeypatch, tmp_path)

    assert bot_mesh.find_bot_chat_session("lancelot") is None
    result = bot_mesh.read_bot_chat_transcript("lancelot")
    assert result == {"exists": False, "session_id": None, "turns": []}


def test_ignores_non_hidden_or_wrongly_titled_sessions(monkeypatch, tmp_path):
    from api import bot_mesh
    _make_db(
        tmp_path,
        sessions=[
            ("s1", "Bot Chat", 0, "lancelot", 1, "t1"),  # not hidden -> not it
            ("s2", "Some other title", 1, "lancelot", 1, "t2"),  # wrong title -> not it
            ("s3", "Bot Chat", 1, "bohorth", 1, "t3"),  # different profile
        ],
        messages=[],
    )
    _patch_base_home(monkeypatch, tmp_path)
    assert bot_mesh.find_bot_chat_session("lancelot") is None
    assert bot_mesh.find_bot_chat_session("bohorth")["session_id"] == "s3"


def test_transcript_merges_relay_call_with_its_ack_ok(monkeypatch, tmp_path):
    from api import bot_mesh
    _make_db(
        tmp_path,
        sessions=[("s1", "Bot Chat", 1, "lancelot", 3, "t1")],
        messages=[
            ("s1", "assistant", "Je répartis vers bohorth.", None, _relay_call("call1", "bohorth", "Alertes réseau Acme ?"), None, 100.0),
            ("s1", "tool", json.dumps({"ok": True, "delivered": True}), "call1", None, "message_agent", 101.0),
            ("s1", "assistant", "Fait.", None, None, None, 102.0),
        ],
    )
    _patch_base_home(monkeypatch, tmp_path)

    result = bot_mesh.read_bot_chat_transcript("lancelot")
    assert result["exists"] is True
    assert result["session_id"] == "s1"
    kinds = [t["kind"] for t in result["turns"]]
    assert kinds == ["relay_out", "text"]
    relay = result["turns"][0]
    assert relay["target"] == "bohorth"
    assert relay["message"] == "Alertes réseau Acme ?"
    assert relay["ok"] is True
    assert relay["error"] is None
    assert result["turns"][1]["content"] == "Fait."


def test_transcript_captures_relay_error_ack(monkeypatch, tmp_path):
    from api import bot_mesh
    _make_db(
        tmp_path,
        sessions=[("s1", "Bot Chat", 1, "guenievre", 2, "t1")],
        messages=[
            ("s1", "assistant", "", None, _relay_call("call2", "guenievre", "hello"), None, 10.0),
            ("s1", "tool", json.dumps({"error": "You can't message yourself.", "reason": "unknown"}), "call2", None, "message_agent", 11.0),
        ],
    )
    _patch_base_home(monkeypatch, tmp_path)

    turns = bot_mesh.read_bot_chat_transcript("guenievre")["turns"]
    assert len(turns) == 1
    assert turns[0]["kind"] == "relay_out"
    assert turns[0]["ok"] is False
    assert turns[0]["error"] == "You can't message yourself."


def test_transcript_renders_ordinary_tool_calls_and_chronological_order(monkeypatch, tmp_path):
    from api import bot_mesh
    _make_db(
        tmp_path,
        sessions=[("s1", "Bot Chat", 1, "pere-blaise", 3, "t1")],
        messages=[
            ("s1", "user", "Message from lancelot: vérifie le disque.", None, None, None, 1.0),
            ("s1", "tool", json.dumps({"output": "OK 61%"}), "callX", None, "terminal", 2.0),
            ("s1", "assistant", "Disque OK, 61% utilisé.", None, None, None, 3.0),
        ],
    )
    _patch_base_home(monkeypatch, tmp_path)

    turns = bot_mesh.read_bot_chat_transcript("pere-blaise")["turns"]
    assert [t["kind"] for t in turns] == ["text", "tool", "text"]
    assert turns[0]["role"] == "user"
    assert turns[1]["tool_name"] == "terminal"
    assert turns[2]["content"] == "Disque OK, 61% utilisé."


def test_list_bot_chat_profiles(monkeypatch, tmp_path):
    from api import bot_mesh
    _make_db(
        tmp_path,
        sessions=[
            ("s1", "Bot Chat", 1, "lancelot", 1, "t1"),
            ("s2", "Bot Chat", 1, "bohorth", 1, "t2"),
            ("s3", "Bot Chat", 0, "yvain", 1, "t3"),  # not hidden -> excluded
        ],
        messages=[],
    )
    _patch_base_home(monkeypatch, tmp_path)
    assert bot_mesh.list_bot_chat_profiles() == {"lancelot", "bohorth"}


def test_route_validates_profile_and_returns_payload(monkeypatch, tmp_path):
    from api import routes
    _make_db(
        tmp_path,
        sessions=[("s1", "Bot Chat", 1, "lancelot", 1, "t1")],
        messages=[("s1", "assistant", "hi", None, None, None, 1.0)],
    )
    _patch_base_home(monkeypatch, tmp_path)

    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/bot-chat?profile=bad/x"))
    assert handler.status == 400

    handler2 = _FakeHandler()
    routes.handle_get(handler2, urlparse("http://example.com/api/bot-chat"))
    assert handler2.status == 400

    handler3 = _FakeHandler()
    routes.handle_get(handler3, urlparse("http://example.com/api/bot-chat?profile=lancelot"))
    data = handler3.get_json()
    assert data["exists"] is True
    assert data["session_id"] == "s1"
    assert len(data["turns"]) == 1


def test_bots_overview_flags_has_bot_chat(monkeypatch, tmp_path):
    from api import bots_overview, profiles

    monkeypatch.setattr(
        profiles,
        "list_profiles_api",
        lambda: [
            {"name": "lancelot", "path": "/x/lancelot"},
            {"name": "gauvain", "path": "/x/gauvain"},
        ],
    )
    _make_db(
        tmp_path,
        sessions=[("s1", "Bot Chat", 1, "lancelot", 1, "t1")],
        messages=[],
    )
    _patch_base_home(monkeypatch, tmp_path)
    bots_overview.invalidate_cache()

    payload = bots_overview.build_bots_overview(use_cache=False)
    by_id = {b["id"]: b for b in payload["bots"]}
    assert by_id["lancelot"]["has_bot_chat"] is True
    assert by_id["gauvain"]["has_bot_chat"] is False
