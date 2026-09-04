"""Bot Chat active-session lease (PLAN-B4-fusion-conversation.md §6 point 4).

WebUI previously never called hermes-agent's per-session exclusivity lease
(``hermes_cli.active_sessions.try_acquire_active_session``) at all -- only
gateway/CLI surfaces did. A real collision (e.g. the cron rattrapage job or a
CLI turn already driving a profile's Bot Chat while WebUI also replies into
the imported session) was therefore a silent double-writer, never a refusal.

These tests cover the WebUI-side plumbing only: scoping the lease to Bot Chat
sessions (``is_bot_chat_session``), acquiring/releasing it
(``acquire_bot_chat_lease`` / ``release_bot_chat_lease``), and degrading to
"no lock enforcement" rather than raising when the mechanism -- or the agent
module backing it -- is unavailable. Never reproduced live: the underlying
refusal mechanism itself is agent-side and unit-tested there.
"""

from __future__ import annotations

import sys
import types


def test_is_bot_chat_session_true_for_matching_sid(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "find_bot_chat_session", lambda profile: {"session_id": "s1"})
    assert bot_mesh.is_bot_chat_session("lancelot", "s1") is True


def test_is_bot_chat_session_false_for_other_sid(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "find_bot_chat_session", lambda profile: {"session_id": "s1"})
    assert bot_mesh.is_bot_chat_session("lancelot", "some-other-webui-session") is False


def test_is_bot_chat_session_false_when_no_bot_chat_exists(monkeypatch):
    from api import bot_mesh
    monkeypatch.setattr(bot_mesh, "find_bot_chat_session", lambda profile: None)
    assert bot_mesh.is_bot_chat_session("lancelot", "s1") is False


def test_is_bot_chat_session_false_for_empty_session_id(monkeypatch):
    from api import bot_mesh
    assert bot_mesh.is_bot_chat_session("lancelot", "") is False
    assert bot_mesh.is_bot_chat_session("lancelot", None) is False


def _install_fake_active_sessions_module(monkeypatch, *, try_acquire=None, release=None):
    """Inject a fake ``hermes_cli.active_sessions`` module for import-time patching.

    The real module lives in the agent checkout, not this repo's venv --
    tests fake it at the ``sys.modules`` level the same way the lazy
    ``from hermes_cli.active_sessions import ...`` inside bot_mesh.py sees it.
    """
    hermes_cli_pkg = types.ModuleType("hermes_cli")
    active_sessions_mod = types.ModuleType("hermes_cli.active_sessions")
    active_sessions_mod.try_acquire_active_session = try_acquire or (lambda **kw: (None, None))
    active_sessions_mod.release_active_session = release or (lambda lease: None)
    hermes_cli_pkg.active_sessions = active_sessions_mod
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.active_sessions", active_sessions_mod)


def test_acquire_bot_chat_lease_success(monkeypatch):
    from api import bot_mesh, profiles

    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda p: "/home/atx/.hermes/profiles/lancelot")

    captured = {}

    def fake_try_acquire(**kwargs):
        captured.update(kwargs)
        return "LEASE-OBJ", None

    _install_fake_active_sessions_module(monkeypatch, try_acquire=fake_try_acquire)

    lease, refusal = bot_mesh.acquire_bot_chat_lease("lancelot", "s1")

    assert lease == "LEASE-OBJ"
    assert refusal is None
    assert captured["session_id"] == "s1"
    assert captured["surface"] == "webui"
    assert captured["registry_home"] == "/home/atx/.hermes/profiles/lancelot"
    assert captured["metadata"]["live_session_id"] == "s1"


def test_acquire_bot_chat_lease_refused(monkeypatch):
    from api import bot_mesh, profiles

    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda p: "/home/atx/.hermes/profiles/lancelot")

    refusal_msg = (
        "Session s1 already has a live owner (gateway:telegram, pid 123, running 2m). "
        "Only one surface at a time may run a session, because a second one would "
        "reason from a transcript that does not include the first one's work."
    )
    _install_fake_active_sessions_module(
        monkeypatch, try_acquire=lambda **kw: (None, refusal_msg),
    )

    lease, refusal = bot_mesh.acquire_bot_chat_lease("lancelot", "s1")

    assert lease is None
    assert refusal == refusal_msg


def test_acquire_bot_chat_lease_degrades_when_module_missing(monkeypatch):
    """No hermes_cli.active_sessions available (older agent, resolution error) ->
    (None, None), never an exception -- Bot Chat turns must not be blocked by
    an import failure in this best-effort mechanism."""
    from api import bot_mesh, profiles

    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda p: "/home/atx/.hermes/profiles/lancelot")
    monkeypatch.delitem(sys.modules, "hermes_cli.active_sessions", raising=False)
    monkeypatch.delitem(sys.modules, "hermes_cli", raising=False)

    lease, refusal = bot_mesh.acquire_bot_chat_lease("lancelot", "s1")

    assert lease is None
    assert refusal is None


def test_release_bot_chat_lease_calls_through(monkeypatch):
    from api import bot_mesh

    calls = []
    _install_fake_active_sessions_module(monkeypatch, release=lambda lease: calls.append(lease))

    bot_mesh.release_bot_chat_lease("LEASE-OBJ")

    assert calls == ["LEASE-OBJ"]


def test_release_bot_chat_lease_noop_for_none(monkeypatch):
    from api import bot_mesh

    calls = []
    _install_fake_active_sessions_module(monkeypatch, release=lambda lease: calls.append(lease))

    bot_mesh.release_bot_chat_lease(None)

    assert calls == []


def test_release_bot_chat_lease_swallows_errors(monkeypatch):
    from api import bot_mesh

    def boom(lease):
        raise RuntimeError("lock file vanished")

    _install_fake_active_sessions_module(monkeypatch, release=boom)

    # Must not raise.
    bot_mesh.release_bot_chat_lease("LEASE-OBJ")


def test_bot_chat_session_locked_error_carries_reason():
    from api.bot_mesh import BotChatSessionLockedError

    exc = BotChatSessionLockedError("Session s1 already has a live owner.", "SESSION_NOT_OWNED")
    assert str(exc) == "Session s1 already has a live owner."
    assert exc.reason == "SESSION_NOT_OWNED"
