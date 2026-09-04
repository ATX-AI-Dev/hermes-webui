"""Read-only access to a Hermes profile's canonical "Bot Chat" session.

Palier B / B3. The Bot Chat is the only session where hermes-agent injects the
``message_agent`` tool (``tools/bot_mode_dm.py`` on the agent side) — it is
the transport for the inter-bot mesh. WebUI's normal session projection
excludes it (``hidden=1``), so it never appears in the sidebar. This module
surfaces it on demand, read-only, for the Bots panel's "inter-bot thread"
viewer.

Schema note (verified against a real ``.178`` state.db, 2026-09-04):
``sessions`` carries ``title='Bot Chat'``, ``hidden=1``. ``messages`` carries
``role, content, tool_call_id, tool_calls (JSON string), tool_name, timestamp
(float epoch seconds)``. A ``message_agent`` call is an ``assistant`` row
whose ``tool_calls`` JSON has a function named ``message_agent``/
``bot_mode_dm``; its ack lands in the paired ``tool`` row keyed by
``tool_call_id``. ``message_agent`` itself never returns the peer's reply
(see the tool's docstring) — that arrives later as its own turn, which this
reader renders like any other assistant/user text turn.

Correction (2026-09-04, same day): **each profile has its own ``state.db``**
at ``<profile home>/state.db`` — confirmed live (``find ~/.hermes -maxdepth 3
-name state.db`` returned one file per profile). There is no single shared
database; the base ``~/.hermes/state.db`` is only the root/``default``
profile's own store. Earlier revisions of this module read only that root
file and silently missed every named profile's Bot Chat. Every lookup here
now resolves the *target profile's own* Hermes home first.

Nothing here writes to state.db, except ``continue_bot_chat()`` below.

``continue_bot_chat()`` (2026-09-04, B4; generalized to all profiles
2026-09-04) is the one exception that DOES write — it imports the Bot Chat
into WebUI's own session store via the existing CLI-session bridge
(``api.models.import_cli_session``, the same mechanism behind "click a
CLI-badged session to import it and reply normally"). This is now the
standard entry point for continuing any profile's Bot Chat from WebUI: a
WebUI turn that replies in the imported session gets ``message_agent``
injected exactly as a native turn would, confirmed live on ``.178`` with
``lancelot`` on 2026-09-04 (PLAN-B4-fusion-conversation.md). Not yet verified
per-profile: whether Telegram/cron turns land in this same ``session_id`` for
every bot, or only ones with a permanent gateway (see that plan's §3.3) — and
the agent-side session-exclusivity lock ("only one surface at a time may run
a session") has been observed once between two CLI surfaces but never
reproduced with WebUI; a collision here would currently surface as whatever
error the in-process agent call raises, not a dedicated message.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RELAY_TOOL_NAMES = {"message_agent", "bot_mode_dm"}
_CONTENT_PREVIEW_CHARS = 2000
_TOOL_PREVIEW_CHARS = 300


def _normalize_profile(profile: str | None) -> str:
    profile = str(profile or "default").strip()
    return profile or "default"


def profile_db_path(profile: str) -> Path | None:
    """Return ``<that profile's own Hermes home>/state.db`` if it exists."""
    profile = _normalize_profile(profile)
    try:
        from api.profiles import get_hermes_home_for_profile
        home = Path(get_hermes_home_for_profile(profile))
    except Exception:
        logger.debug("bot_mesh: could not resolve Hermes home for %s", profile, exc_info=True)
        return None
    db = home / "state.db"
    return db if db.exists() else None


def find_bot_chat_session(profile: str) -> dict | None:
    """Return ``{"session_id", "message_count", "last_activity_at"}`` or ``None``."""
    db_path = profile_db_path(profile)
    if db_path is None:
        return None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT id, message_count, last_activity_at FROM sessions "
                "WHERE title = 'Bot Chat' AND hidden = 1 "
                "ORDER BY last_activity_at DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
    except Exception:
        logger.debug("bot_mesh: find_bot_chat_session failed for %s", profile, exc_info=True)
        return None
    if not row:
        return None
    return {"session_id": row[0], "message_count": row[1], "last_activity_at": row[2]}


def bot_chat_exists(profile: str) -> bool:
    return find_bot_chat_session(profile) is not None


def list_bot_chat_profiles(names: list[str] | None = None) -> set[str]:
    """Every profile (from ``names``, or every known profile) with a Bot Chat.

    Opens one ``state.db`` per candidate profile — cheap read-only sqlite
    opens, but O(profile count). Callers that already have the profile list
    (e.g. ``bots_overview.build_bots_overview``) should pass ``names`` to
    avoid a redundant ``list_profiles_api()`` call.
    """
    if names is None:
        try:
            from api.profiles import list_profiles_api
            names = [str(r.get("name") or "").strip() for r in (list_profiles_api() or [])]
        except Exception:
            logger.debug("bot_mesh: list_profiles_api failed", exc_info=True)
            names = []
    return {n for n in names if n and bot_chat_exists(n)}


def _parse_tool_calls(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _relay_call_from_tool_calls(tool_calls: list[dict]) -> dict | None:
    """Pull a message_agent/bot_mode_dm call's {tool_call_id, target, message}."""
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        if fn.get("name") not in _RELAY_TOOL_NAMES:
            continue
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}
        return {
            "tool_call_id": call.get("id") or call.get("call_id"),
            "target": args.get("target"),
            "message": args.get("message"),
        }
    return None


def _truncate(text: Any, limit: int = _CONTENT_PREVIEW_CHARS) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[:limit] + "…"


def _relay_ack(ack_raw: str | None) -> tuple[bool | None, str | None]:
    if not ack_raw:
        return None, None
    try:
        ack = json.loads(ack_raw)
    except Exception:
        return None, None
    if not isinstance(ack, dict):
        return None, None
    ok = ack.get("ok") if "ok" in ack else ("error" not in ack)
    return bool(ok), ack.get("error")


def continue_bot_chat(profile: str) -> dict:
    """Import a profile's Bot Chat into WebUI's own session store, keyed by
    its REAL session_id, so replying in WebUI continues that exact
    agent-native session instead of starting a fresh WebUI-only one.

    This is the single entry point for "continuing" any bot from the Bots
    panel — see PLAN-B4-fusion-conversation.md. Works for any profile with a
    Bot Chat session; nothing here is specific to a particular bot.

    Returns ``{"ok": True, "session_id": ...}`` or ``{"ok": False, "error": ...}``.
    Never raises. This does not touch state.db directly — it delegates the
    message-shape conversion to ``api.models.get_cli_session_messages`` (the
    same reader the existing CLI-session bridge uses) and the WebUI-side write
    to ``api.models.import_cli_session`` (the same writer behind "import a
    CLI session and reply normally"). Both already accept an explicit
    ``profile`` and resolve that profile's own state.db.
    """
    profile = _normalize_profile(profile)
    session = find_bot_chat_session(profile)
    if session is None:
        return {"ok": False, "error": f"No Bot Chat session found for profile {profile!r}."}
    sid = session["session_id"]
    try:
        from api.models import get_cli_session_messages, import_cli_session
        msgs = get_cli_session_messages(sid, profile=profile)
        if not msgs:
            return {"ok": False, "error": "Bot Chat session has no readable messages."}
        import_cli_session(
            sid,
            "Bot Chat",
            msgs,
            model="unknown",
            profile=profile,
            updated_at=session.get("last_activity_at"),
        )
    except Exception as exc:
        logger.exception("bot_mesh: continue_bot_chat failed for %s", profile)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "session_id": sid}


def bot_chat_state_db_message_count(profile: str, session_id: str) -> int | None:
    """Cheap ``COUNT(*)`` of ``session_id``'s rows in the profile's live
    ``state.db`` — no content read, just the row count. Returns ``None`` if
    the profile/session can't be resolved. Used to detect, without the cost
    of a full re-import, whether a Bot Chat has grown since WebUI's own
    sidecar copy was last synced (see ``resync_bot_chat_if_stale``).
    """
    db_path = profile_db_path(profile)
    if db_path is None or not session_id:
        return None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
            ).fetchone()
        finally:
            con.close()
    except Exception:
        logger.debug(
            "bot_mesh: bot_chat_state_db_message_count failed for %s/%s",
            profile, session_id, exc_info=True,
        )
        return None
    return int(row[0]) if row else None


def resync_bot_chat_if_stale(profile: str, session_id: str, known_count: int | None) -> bool:
    """Re-import a Bot Chat's WebUI sidecar copy if the agent-native
    ``state.db`` has grown past ``known_count`` (WebUI's last-known count).

    This is what makes an open Bot Chat conversation update live: a bot's
    reply delivered by ``hermes-relay-watcher.service`` (or any other
    surface — cron, Telegram, CLI) writes straight into the agent-native
    ``state.db``, which WebUI's own session store never sees on its own.
    Called from the metadata-only ``GET /api/session`` poll that the
    frontend already runs every ~30s (plus on focus/visibility) for any
    externally-sourced session (see ``static/sessions.js``,
    ``refreshActiveSessionIfExternallyUpdated`` / ``_isExternalSession``) —
    reusing that existing poll instead of adding a second one.

    Returns ``True`` if a resync happened (caller should reload ``s`` before
    building its response), ``False`` otherwise. Never raises — a failed
    resync just leaves the sidecar at its last-known state, exactly as
    before this function existed.
    """
    if known_count is None or not is_bot_chat_session(profile, session_id):
        return False
    live_count = bot_chat_state_db_message_count(profile, session_id)
    if live_count is None or live_count <= known_count:
        return False
    result = continue_bot_chat(profile)
    return bool(result.get("ok"))


class BotChatSessionLockedError(RuntimeError):
    """A WebUI turn was refused because another surface already owns this
    Bot Chat session (cron/CLI/Telegram running an agent turn against it).

    Carries ``reason`` (agent-side machine-readable code, e.g.
    ``SESSION_NOT_OWNED``) so callers can branch on it without matching text.
    """

    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.reason = reason


def is_bot_chat_session(profile: str, session_id: str) -> bool:
    """True when ``session_id`` is the profile's canonical Bot Chat session.

    Used to scope the active-session lease below to Bot Chat turns only —
    the one place WebUI writes into a session that a cron job or another
    live surface may also be driving (see ``continue_bot_chat`` docstring).
    Ordinary WebUI-only sessions never collide with another surface, so they
    are deliberately left outside this check.
    """
    if not session_id:
        return False
    session = find_bot_chat_session(profile)
    return bool(session and session.get("session_id") == session_id)


def acquire_bot_chat_lease(profile: str, session_id: str):
    """Claim the agent-side active-session lease for a Bot Chat turn.

    Returns ``(lease, None)`` on success, or ``(None, refusal)`` where
    ``refusal`` is a human-readable message (agent-native
    ``ActiveSessionRefusal``, itself a ``str``) when another surface
    (cron/CLI/Telegram) already owns this session. WebUI previously never
    called this at all — a real collision was a silent double-writer, not a
    refusal (see PLAN-B4-fusion-conversation.md §6 point 4). Degrades to
    "no lock enforcement" (``(None, None)``) if the mechanism is unavailable
    (older agent checkout, resolution failure) rather than blocking every
    Bot Chat turn on an import error.
    """
    profile = _normalize_profile(profile)
    try:
        from api.profiles import get_hermes_home_for_profile
        from hermes_cli.active_sessions import try_acquire_active_session

        registry_home = get_hermes_home_for_profile(profile)
        lease, refusal = try_acquire_active_session(
            session_id=session_id,
            surface="webui",
            config=None,
            metadata={
                "platform": "webui",
                "profile": profile,
                # Re-entrancy (mirrors gateway/run.py): a retried WebUI turn
                # against the same session in this same process re-acquires
                # its own lease instead of being fenced out by its own leak.
                "live_session_id": str(session_id),
            },
            registry_home=registry_home,
        )
    except Exception:
        logger.debug(
            "bot_mesh: active-session lease unavailable for %s; proceeding without it",
            profile,
            exc_info=True,
        )
        return None, None
    return lease, refusal


def release_bot_chat_lease(lease) -> None:
    """Release a lease from ``acquire_bot_chat_lease``. Best-effort, never raises."""
    if lease is None:
        return
    try:
        from hermes_cli.active_sessions import release_active_session
        release_active_session(lease)
    except Exception:
        logger.debug("bot_mesh: failed to release active-session lease", exc_info=True)


def read_bot_chat_transcript(profile: str, *, limit: int = 60) -> dict:
    """Return ``{"exists", "session_id", "turns": [...]}``. Read-only, best-effort.

    Each turn is one of:
      ``{"kind": "text", "role", "content", "timestamp"}``
      ``{"kind": "relay_out", "target", "message", "ok", "error", "timestamp"}``
        — a message_agent/bot_mode_dm call this bot made, merged with its ack.
      ``{"kind": "tool", "tool_name", "content", "timestamp"}`` — any other tool call.
    Oldest first (reading order). ``limit`` bounds rows read from the DB, not
    turns returned (a relay call + its ack collapse into one turn).
    """
    session = find_bot_chat_session(profile)
    if session is None:
        return {"exists": False, "session_id": None, "turns": []}

    db_path = profile_db_path(profile)
    turns: list[dict] = []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT role, content, tool_call_id, tool_calls, tool_name, timestamp "
                "FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session["session_id"], int(limit)),
            ).fetchall()
        finally:
            con.close()
    except Exception:
        logger.debug("bot_mesh: transcript read failed for %s", profile, exc_info=True)
        return {"exists": True, "session_id": session["session_id"], "turns": []}

    rows = list(reversed(rows))  # DESC fetch -> chronological order
    pending_relay: dict[str, dict] = {}  # tool_call_id -> relay call awaiting its ack row

    for r in rows:
        role = r["role"]
        ts = r["timestamp"]
        if role == "assistant":
            relay = _relay_call_from_tool_calls(_parse_tool_calls(r["tool_calls"]))
            if relay and relay.get("tool_call_id"):
                pending_relay[relay["tool_call_id"]] = {**relay, "timestamp": ts}
                continue  # rendered once the paired tool-result row arrives
            content = (r["content"] or "").strip()
            if content:
                turns.append({"kind": "text", "role": "assistant", "content": _truncate(content), "timestamp": ts})
        elif role == "tool":
            tcid = r["tool_call_id"]
            if tcid in pending_relay or r["tool_name"] in _RELAY_TOOL_NAMES:
                relay = pending_relay.pop(tcid, {"target": None, "message": None, "timestamp": ts})
                ok, error = _relay_ack(r["content"])
                turns.append({
                    "kind": "relay_out",
                    "target": relay.get("target"),
                    "message": _truncate(relay.get("message")),
                    "ok": ok,
                    "error": error,
                    "timestamp": ts or relay.get("timestamp"),
                })
            else:
                content = (r["content"] or "").strip()
                if content:
                    turns.append({
                        "kind": "tool",
                        "tool_name": r["tool_name"],
                        "content": _truncate(content, _TOOL_PREVIEW_CHARS),
                        "timestamp": ts,
                    })
        elif role == "user":
            content = (r["content"] or "").strip()
            if content:
                turns.append({"kind": "text", "role": "user", "content": _truncate(content), "timestamp": ts})
        # system / other roles: skipped in this compact viewer

    return {"exists": True, "session_id": session["session_id"], "turns": turns}
