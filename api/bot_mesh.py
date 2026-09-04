"""Read-only access to a Hermes profile's canonical "Bot Chat" session.

Palier B / B3. The Bot Chat is the only session where hermes-agent injects the
``message_agent`` tool (``tools/bot_mode_dm.py`` on the agent side) — it is
the transport for the inter-bot mesh. WebUI's normal session projection
excludes it (``hidden=1``), so it never appears in the sidebar. This module
surfaces it on demand, read-only, for the Bots panel's "inter-bot thread"
viewer.

Schema note (verified against a real ``.178`` state.db, 2026-09-04):
``sessions`` carries ``title='Bot Chat'``, ``hidden=1``, ``profile_name``.
``messages`` carries ``role, content, tool_call_id, tool_calls (JSON string),
tool_name, timestamp (float epoch seconds)``. A ``message_agent`` call is an
``assistant`` row whose ``tool_calls`` JSON has a function named
``message_agent``/``bot_mode_dm``; its ack lands in the paired ``tool`` row
keyed by ``tool_call_id``. ``message_agent`` itself never returns the peer's
reply (see the tool's docstring) — that arrives later as its own turn, which
this reader renders like any other assistant/user text turn.

Nothing here writes to state.db. Driving a Bot Chat turn from WebUI (actually
sending a message_agent call from the UI) is a separate, not-yet-built
capability gated on a live check — see PLAN-palier-B.md section 3.
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


def _base_hermes_home() -> Path | None:
    try:
        from api.profiles import _resolve_base_hermes_home
        return Path(_resolve_base_hermes_home())
    except Exception:
        logger.debug("bot_mesh: could not resolve base Hermes home", exc_info=True)
        return None


def _state_db_path() -> Path | None:
    base = _base_hermes_home()
    if base is None:
        return None
    db = base / "state.db"
    return db if db.exists() else None


def _normalize_profile(profile: str | None) -> str:
    profile = str(profile or "default").strip()
    return profile or "default"


def find_bot_chat_session(profile: str) -> dict | None:
    """Return ``{"session_id", "message_count", "last_activity_at"}`` or ``None``."""
    db_path = _state_db_path()
    if db_path is None:
        return None
    profile = _normalize_profile(profile)
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT id, message_count, last_activity_at FROM sessions "
                "WHERE title = 'Bot Chat' AND hidden = 1 "
                "AND COALESCE(NULLIF(profile_name, ''), 'default') = ? "
                "ORDER BY last_activity_at DESC LIMIT 1",
                (profile,),
            ).fetchone()
        finally:
            con.close()
    except Exception:
        logger.debug("bot_mesh: find_bot_chat_session failed for %s", profile, exc_info=True)
        return None
    if not row:
        return None
    return {"session_id": row[0], "message_count": row[1], "last_activity_at": row[2]}


def list_bot_chat_profiles() -> set[str]:
    """Every profile that currently has a (hidden) Bot Chat session.

    Cheap existence check the Bots panel uses to decide whether to show the
    "inter-bot thread" button for a given bot, without one query per bot.
    """
    db_path = _state_db_path()
    if db_path is None:
        return set()
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT DISTINCT COALESCE(NULLIF(profile_name, ''), 'default') "
                "FROM sessions WHERE title = 'Bot Chat' AND hidden = 1"
            ).fetchall()
        finally:
            con.close()
    except Exception:
        logger.debug("bot_mesh: list_bot_chat_profiles failed", exc_info=True)
        return set()
    return {str(r[0]) for r in rows}


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

    db_path = _state_db_path()
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
