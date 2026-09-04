"""Bots panel avatar (emoji/color from bots_hierarchy.json) and live
last-message preview, added alongside the Discord-style vignette rework.

Reuses the same profile-db fixture shape as test_bot_mesh_b3.py: each
profile's own state.db with sessions(title, hidden, ...) and
messages(role, content, tool_call_id, tool_calls, tool_name, timestamp).
"""

from __future__ import annotations

import json
import sqlite3


def _make_profile_db(home_dir, sessions, messages):
    home_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(home_dir / "state.db")
    db.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, hidden INTEGER, "
        "message_count INTEGER, last_activity_at TEXT, ended_at TEXT, archived INTEGER DEFAULT 0)"
    )
    db.executemany(
        "INSERT INTO sessions (id, title, hidden, message_count, last_activity_at) VALUES (?, ?, ?, ?, ?)",
        sessions,
    )
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


def _patch_profile_homes(monkeypatch, homes: dict):
    from api import profiles

    def _fake_home(name):
        if name in homes:
            return homes[name]
        raise RuntimeError("no home configured for " + str(name))

    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", _fake_home)


# ── bot_mesh.last_bot_chat_snippet ──────────────────────────────────────

def test_snippet_plain_assistant_text(monkeypatch, tmp_path):
    from api import bot_mesh
    home = tmp_path / "lancelot"
    _make_profile_db(home, sessions=[("s1", "Bot Chat", 1, 1, "t1")], messages=[
        ("s1", "assistant", "Je répartis entre bohorth et pere-blaise.", None, None, None, 1.0),
    ])
    _patch_profile_homes(monkeypatch, {"lancelot": home})
    assert bot_mesh.last_bot_chat_snippet("lancelot") == "Je répartis entre bohorth et pere-blaise."


def test_snippet_relay_out_shows_target_and_message(monkeypatch, tmp_path):
    from api import bot_mesh
    home = tmp_path / "lancelot"
    _make_profile_db(home, sessions=[("s1", "Bot Chat", 1, 1, "t1")], messages=[
        ("s1", "assistant", None, "call1", _relay_call("call1", "bohorth", "alertes réseau ?"), None, 1.0),
    ])
    _patch_profile_homes(monkeypatch, {"lancelot": home})
    assert bot_mesh.last_bot_chat_snippet("lancelot") == "→ bohorth: alertes réseau ?"


def test_snippet_skips_bare_ack_and_falls_back_to_earlier_row(monkeypatch, tmp_path):
    """The newest row is often a content-less relay ack; the scan should walk
    back to the most recent row that actually has something to show."""
    from api import bot_mesh
    home = tmp_path / "lancelot"
    _make_profile_db(home, sessions=[("s1", "Bot Chat", 1, 2, "t1")], messages=[
        ("s1", "assistant", "Je délègue à bohorth.", None, None, None, 1.0),
        ("s1", "tool", json.dumps({"ok": True}), "call1", None, "message_agent", 2.0),
    ])
    _patch_profile_homes(monkeypatch, {"lancelot": home})
    assert bot_mesh.last_bot_chat_snippet("lancelot") == "✓ réponse reçue"


def test_snippet_none_when_no_bot_chat(monkeypatch, tmp_path):
    from api import bot_mesh
    home = tmp_path / "lancelot"
    _make_profile_db(home, sessions=[], messages=[])
    _patch_profile_homes(monkeypatch, {"lancelot": home})
    assert bot_mesh.last_bot_chat_snippet("lancelot") is None


def test_snippet_truncates_long_text(monkeypatch, tmp_path):
    from api import bot_mesh
    home = tmp_path / "lancelot"
    long_text = "x" * 200
    _make_profile_db(home, sessions=[("s1", "Bot Chat", 1, 1, "t1")], messages=[
        ("s1", "assistant", long_text, None, None, None, 1.0),
    ])
    _patch_profile_homes(monkeypatch, {"lancelot": home})
    snippet = bot_mesh.last_bot_chat_snippet("lancelot")
    assert len(snippet) <= bot_mesh._SNIPPET_CHARS + 1  # +1 for the trailing ellipsis char
    assert snippet.endswith("…")


# ── bots_overview: emoji/color + last_message_preview propagation ──────

def test_overview_exposes_emoji_color_and_preview(monkeypatch, tmp_path):
    from api import bots_overview, profiles

    monkeypatch.setattr(profiles, "list_profiles_api", lambda: [
        {"name": "lancelot", "path": "/x/lancelot", "gateway_running": True, "model": "m", "is_active": True},
    ])
    # No operator override -> deterministically falls back to the bundled
    # api/bots_hierarchy.json, same as test_bots_overview_b2.py's _patch().
    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: (_ for _ in ()).throw(RuntimeError("no home")))
    home = tmp_path / "lancelot"
    _make_profile_db(home, sessions=[("s1", "Bot Chat", 1, 1, "t1")], messages=[
        ("s1", "assistant", "Synthèse infra Acme prête.", None, None, None, 1.0),
    ])
    _patch_profile_homes(monkeypatch, {"lancelot": home})
    bots_overview.invalidate_cache()

    payload = bots_overview.build_bots_overview(use_cache=False)
    lancelot = next(b for b in payload["bots"] if b["id"] == "lancelot")

    # lancelot is declared in the bundled bots_hierarchy.json with an emoji/color.
    assert lancelot["emoji"]
    assert lancelot["color"]
    assert lancelot["last_message_preview"] == "Synthèse infra Acme prête."


def test_overview_preview_is_none_without_bot_chat(monkeypatch, tmp_path):
    from api import bots_overview, profiles

    monkeypatch.setattr(profiles, "list_profiles_api", lambda: [
        {"name": "bohorth", "path": "/x/bohorth", "gateway_running": False, "model": None, "is_active": False},
    ])
    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: (_ for _ in ()).throw(RuntimeError("no home")))
    home = tmp_path / "bohorth"
    _make_profile_db(home, sessions=[], messages=[])
    _patch_profile_homes(monkeypatch, {"bohorth": home})
    bots_overview.invalidate_cache()

    payload = bots_overview.build_bots_overview(use_cache=False)
    bohorth = next(b for b in payload["bots"] if b["id"] == "bohorth")
    assert bohorth["last_message_preview"] is None


def test_overview_unknown_profile_has_no_declared_avatar(monkeypatch, tmp_path):
    """A profile absent from bots_hierarchy.json gets no emoji/color from the
    backend — the front end's hash-based fallback is expected to kick in."""
    from api import bots_overview, profiles

    monkeypatch.setattr(profiles, "list_profiles_api", lambda: [
        {"name": "some-random-profile", "path": "/x/rnd", "gateway_running": False, "model": None, "is_active": False},
    ])
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda name: (_ for _ in ()).throw(RuntimeError("no home")))
    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: (_ for _ in ()).throw(RuntimeError("no home")))
    bots_overview.invalidate_cache()

    payload = bots_overview.build_bots_overview(use_cache=False)
    rnd = next(b for b in payload["bots"] if b["id"] == "some-random-profile")
    assert rnd["emoji"] is None
    assert rnd["color"] is None
