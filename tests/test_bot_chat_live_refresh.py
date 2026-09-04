"""Bot Chat live refresh (04/09/2026, session following B4 deployment).

Ludo asked for inter-bot communication to feel "fluide et dynamique, comme
une conversation entre humains". Investigation found that WebUI already has
a generic live-refresh mechanism for externally-sourced sessions
(``static/sessions.js``, ``refreshActiveSessionIfExternallyUpdated`` --
30s poll + SSE + focus/visibility triggers) but it only ever compares
WebUI's own sidecar ``message_count`` against itself: nothing re-read the
agent-native ``state.db`` a Bot Chat actually lives in, so a reply delivered
by ``hermes-relay-watcher.service`` (or any other surface) into that
database was invisible to WebUI until the user manually reopened the
session.

Confirmed empirically on `.178` (disposable instance, real profile,
message inserted directly into a live Bot Chat's state.db): before this
fix, a metadata-only ``GET /api/session`` never reflected the insert; after
it, the same request returns the fresh message_count/last_message_at.

These tests cover the two new bot_mesh.py functions in isolation (mocked
state.db access -- no real Hermes profile needed).
"""

from __future__ import annotations


def test_state_db_message_count_reads_matching_session(monkeypatch, tmp_path):
    from api import bot_mesh
    import sqlite3

    db_path = tmp_path / "state.db"
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, timestamp REAL)"
    )
    con.executemany(
        "INSERT INTO messages (session_id, role, timestamp) VALUES (?,?,?)",
        [("s1", "user", 1.0), ("s1", "assistant", 2.0), ("s2", "user", 3.0)],
    )
    con.commit()
    con.close()

    monkeypatch.setattr(bot_mesh, "profile_db_path", lambda profile: db_path)

    assert bot_mesh.bot_chat_state_db_message_count("lancelot", "s1") == 2
    assert bot_mesh.bot_chat_state_db_message_count("lancelot", "s2") == 1
    assert bot_mesh.bot_chat_state_db_message_count("lancelot", "s3") == 0


def test_state_db_message_count_returns_none_without_profile(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "profile_db_path", lambda profile: None)
    assert bot_mesh.bot_chat_state_db_message_count("ghost", "s1") is None


def test_state_db_message_count_returns_none_for_empty_session_id(monkeypatch):
    from api import bot_mesh
    assert bot_mesh.bot_chat_state_db_message_count("lancelot", "") is None
    assert bot_mesh.bot_chat_state_db_message_count("lancelot", None) is None


def test_resync_skips_when_known_count_is_none(monkeypatch):
    from api import bot_mesh
    calls = []
    monkeypatch.setattr(bot_mesh, "is_bot_chat_session", lambda p, s: calls.append("is_bot_chat_session") or True)
    assert bot_mesh.resync_bot_chat_if_stale("lancelot", "s1", None) is False
    assert calls == []  # short-circuited before even checking is_bot_chat_session


def test_resync_skips_for_non_bot_chat_session(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "is_bot_chat_session", lambda p, s: False)
    monkeypatch.setattr(
        bot_mesh, "bot_chat_state_db_message_count",
        lambda p, s: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    assert bot_mesh.resync_bot_chat_if_stale("lancelot", "s1", 5) is False


def test_resync_skips_when_state_db_not_ahead(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "is_bot_chat_session", lambda p, s: True)
    monkeypatch.setattr(bot_mesh, "bot_chat_state_db_message_count", lambda p, s: 5)
    calls = []
    monkeypatch.setattr(bot_mesh, "continue_bot_chat", lambda p: calls.append(p) or {"ok": True})
    assert bot_mesh.resync_bot_chat_if_stale("lancelot", "s1", 5) is False
    assert bot_mesh.resync_bot_chat_if_stale("lancelot", "s1", 6) is False  # local count higher than db: no-op
    assert calls == []


def test_resync_reimports_when_state_db_is_ahead(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "is_bot_chat_session", lambda p, s: True)
    monkeypatch.setattr(bot_mesh, "bot_chat_state_db_message_count", lambda p, s: 9)
    calls = []
    monkeypatch.setattr(bot_mesh, "continue_bot_chat", lambda p: calls.append(p) or {"ok": True, "session_id": "s1"})
    result = bot_mesh.resync_bot_chat_if_stale("lancelot", "s1", 5)
    assert result is True
    assert calls == ["lancelot"]


def test_resync_returns_false_when_reimport_fails(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "is_bot_chat_session", lambda p, s: True)
    monkeypatch.setattr(bot_mesh, "bot_chat_state_db_message_count", lambda p, s: 9)
    monkeypatch.setattr(bot_mesh, "continue_bot_chat", lambda p: {"ok": False, "error": "boom"})
    assert bot_mesh.resync_bot_chat_if_stale("lancelot", "s1", 5) is False


def test_resync_returns_none_state_db_count_gracefully(monkeypatch):
    """profile_db_path resolution failure inside bot_chat_state_db_message_count
    (e.g. profile deleted mid-poll) must not raise up through resync."""
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "is_bot_chat_session", lambda p, s: True)
    monkeypatch.setattr(bot_mesh, "bot_chat_state_db_message_count", lambda p, s: None)
    assert bot_mesh.resync_bot_chat_if_stale("lancelot", "s1", 5) is False
