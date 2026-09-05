"""Aggregated read-only overview of every Hermes profile for the Bots panel.

Palier B / B2. One call, one payload: for each profile the WebUI can see
(``list_profiles_api``) it merges the fork-local hierarchy map
(``api/bots_hierarchy.json``, or an operator copy at
``<HERMES_HOME>/webui/bots_hierarchy.json``) with a cheap read-only scan of
*that profile's own* ``state.db`` for active-session counts and last activity.

Correction (2026-09-04, same day as first deploy): each profile has its own
``state.db`` at ``<profile home>/state.db`` — confirmed live
(``find ~/.hermes -maxdepth 3 -name state.db`` returned one file per
profile). There is no single shared database. An earlier revision of this
module read only the base ``~/.hermes/state.db`` (the root/``default``
profile's own store) and silently attributed every OTHER profile's session
stats to it — every bot but ``default`` showed zero sessions. Every lookup
now resolves each profile's own Hermes home first.

Everything here is read-only. Mutations (start/stop a bot's gateway) go through
the existing ``/api/gateway/*`` endpoints with an explicit ``profile`` (B1).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BUNDLED_HIERARCHY = Path(__file__).with_name("bots_hierarchy.json")

_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_TTL = 3.0  # seconds; the panel polls, list_profiles_api has its own 4s cache


def _base_hermes_home() -> Path | None:
    try:
        from api.profiles import _resolve_base_hermes_home
        return Path(_resolve_base_hermes_home())
    except Exception:
        logger.debug("bots_overview: could not resolve base Hermes home", exc_info=True)
        return None


def _operator_hierarchy_path() -> Path | None:
    base = _base_hermes_home()
    if base is None:
        return None
    return base / "webui" / "bots_hierarchy.json"


def _load_hierarchy() -> dict:
    """Operator copy wins over the bundled file; a broken file never breaks the panel."""
    for candidate in (_operator_hierarchy_path(), _BUNDLED_HIERARCHY):
        if candidate is None or not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("bots_overview: %s is not valid JSON; ignoring", candidate)
            continue
        if isinstance(data, dict) and isinstance(data.get("profiles"), dict):
            data.setdefault("branches", [])
            return data
    return {"branches": [], "profiles": {}}


def _profile_description(profile_home: str | Path) -> str | None:
    """The ``hermes profile describe`` text, read from the profile's profile.yaml."""
    try:
        import yaml  # PyYAML is a hard WebUI dep
        meta = Path(profile_home) / "profile.yaml"
        if not meta.exists():
            return None
        data = yaml.safe_load(meta.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            desc = data.get("description")
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
    except Exception:
        logger.debug("bots_overview: profile.yaml read failed for %s", profile_home, exc_info=True)
    return None


def _sessions_for_one_profile(name: str) -> dict | None:
    """{active, last_activity} for ONE profile's own state.db, or None.

    Correction (2026-09-04): each profile has its own ``state.db`` at
    ``<profile home>/state.db`` — there is no single shared database (an
    earlier revision of this module assumed one and silently read only the
    root/``default`` profile's store for every bot). ``active`` counts
    non-archived, not-yet-ended sessions. Best-effort: any error (missing db,
    schema drift) yields ``None`` and the panel shows zeros for that bot.
    """
    try:
        from api.profiles import get_hermes_home_for_profile
        db_path = Path(get_hermes_home_for_profile(name)) / "state.db"
    except Exception:
        logger.debug("bots_overview: could not resolve Hermes home for %s", name, exc_info=True)
        return None
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT SUM(CASE WHEN ended_at IS NULL THEN 1 ELSE 0 END) AS active, "
                "       MAX(last_activity_at) AS last "
                "FROM sessions WHERE COALESCE(archived, 0) = 0"
            ).fetchone()
            preview = _last_message_preview_on_connection(con, name)
        finally:
            con.close()
    except Exception:
        logger.debug("bots_overview: state.db scan failed for %s", name, exc_info=True)
        return None
    if not row:
        return None
    return {"active": int(row[0] or 0), "last_activity": row[1], "last_message_preview": preview}


def _last_message_preview_on_connection(con: sqlite3.Connection, name: str) -> str | None:
    """Short preview of the bot's most recent Bot Chat turn, reusing the
    ``state.db`` connection ``_sessions_for_one_profile`` already opened for
    that profile rather than opening a second one just for this.
    """
    try:
        bot_chat_row = con.execute(
            "SELECT id FROM sessions WHERE title = 'Bot Chat' AND hidden = 1 "
            "ORDER BY last_activity_at DESC LIMIT 1"
        ).fetchone()
    except Exception:
        logger.debug("bots_overview: bot chat lookup failed for %s", name, exc_info=True)
        return None
    if not bot_chat_row:
        return None
    try:
        from api.bot_mesh import last_bot_chat_snippet_from_connection
        return last_bot_chat_snippet_from_connection(con, bot_chat_row[0])
    except Exception:
        logger.debug("bots_overview: snippet read failed for %s", name, exc_info=True)
        return None


def _sessions_by_profile(names: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in names:
        stats = _sessions_for_one_profile(name)
        if stats is not None:
            out[name] = stats
    return out


def _branch_order(hierarchy: dict) -> dict[str, int]:
    return {b.get("id"): i for i, b in enumerate(hierarchy.get("branches") or []) if b.get("id")}


def _hidden_branches(hierarchy: dict) -> set[str]:
    """Branch ids flagged ``"hidden": true`` — kept out of the Bots panel.

    The panel lists *bots*; a Hermes profile that is only ever a plain chat
    (the ``interne`` branch, i.e. the root ``default`` profile) has its own
    entry point in the rail and does not belong in the list, nor in its
    counts. Driven by the hierarchy file rather than a hardcoded id so the
    operator copy at ``<HERMES_HOME>/webui/bots_hierarchy.json`` can bring a
    branch back.
    """
    return {
        b["id"] for b in (hierarchy.get("branches") or [])
        if isinstance(b, dict) and b.get("id") and b.get("hidden")
    }


def _dedupe_rows_by_name(rows: list) -> list:
    """Keep the first row per profile name.

    ``list_profiles_api`` can return two rows with the same *name*: upstream
    hardcodes the base home's display name to ``'default'``
    (``api/profiles.py::_build_profile_rows_fast``) and then walks
    ``<HERMES_HOME>/profiles/*``, so a real ``profiles/default`` directory —
    which exists on the production host — yields a second ``'default'`` row
    for a different home. The panel keyed its cards on the name and rendered
    the profile twice (reported 2026-09-05). First wins, i.e. the base home.
    """
    out: list = []
    seen: set[str] = set()
    for r in rows:
        name = str((r or {}).get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(r)
    return out


def build_bots_overview(*, use_cache: bool = True) -> dict:
    """Return ``{"bots": [...], "branches": [...], "generated_at": <epoch>}``.

    Each bot: ``id, display_name, avatar_url, role, description, emoji, color,
    branch, parent, manager, tag, permanent_gateway, gateway_running, model,
    skill_count, is_active, is_known (in the hierarchy map), active_sessions,
    last_activity, last_message_preview``.
    """
    now = time.time()
    if use_cache and _CACHE["payload"] is not None and (now - _CACHE["at"]) < _CACHE_TTL:
        return _CACHE["payload"]

    try:
        from api.profiles import list_profiles_api
        rows = list_profiles_api() or []
    except Exception:
        logger.warning("bots_overview: list_profiles_api failed", exc_info=True)
        rows = []

    hierarchy = _load_hierarchy()
    hmap: dict[str, dict] = hierarchy.get("profiles") or {}
    hidden = _hidden_branches(hierarchy)

    rows = _dedupe_rows_by_name(rows)
    if hidden:
        rows = [
            r for r in rows
            if (hmap.get(str(r.get("name") or "").strip()) or {}).get("branch", "autre") not in hidden
        ]

    names = [str(r.get("name") or "").strip() for r in rows if r.get("name")]
    sessions = _sessions_by_profile(names)
    branch_rank = _branch_order(hierarchy)
    try:
        from api.bot_mesh import list_bot_chat_profiles
        bot_chat_profiles = list_bot_chat_profiles(names)
    except Exception:
        logger.debug("bots_overview: list_bot_chat_profiles failed", exc_info=True)
        bot_chat_profiles = set()

    # User-chosen name/picture wins over the org file's declared emoji/colour,
    # which in turn wins over the front-end's hash-based fallback.
    try:
        from api.bot_customization import avatar_url, load_customization
        custom = load_customization()
    except Exception:
        logger.debug("bots_overview: customization load failed", exc_info=True)
        custom, avatar_url = {}, (lambda *_a, **_k: None)

    bots: list[dict] = []
    for r in rows:
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        h = hmap.get(name) or {}
        sess = sessions.get(name) or {}
        c = custom.get(name) or {}
        bots.append(
            {
                "id": name,
                "display_name": c.get("display_name") or None,
                "avatar_url": avatar_url(name, c),
                "role": h.get("role") or _profile_description(r.get("path") or "") or "",
                "description": _profile_description(r.get("path") or ""),
                "emoji": h.get("emoji"),
                "color": h.get("color"),
                "branch": h.get("branch") or "autre",
                "parent": h.get("parent"),
                "manager": bool(h.get("manager")),
                "tag": h.get("tag"),
                "permanent_gateway": bool(h.get("permanent_gateway")),
                "is_known": name in hmap,
                "order": h.get("order", 10_000),
                "gateway_running": bool(r.get("gateway_running")),
                "model": r.get("model"),
                "provider": r.get("provider"),
                "skill_count": r.get("skill_count", r.get("enabled_skills", 0)) or 0,
                "is_active": bool(r.get("is_active")),
                "active_sessions": sess.get("active", 0),
                "last_activity": sess.get("last_activity"),
                "last_message_preview": sess.get("last_message_preview"),
                "has_bot_chat": name in bot_chat_profiles,
            }
        )

    bots.sort(key=lambda b: (branch_rank.get(b["branch"], 999), b["order"], b["id"]))

    payload = {
        "bots": bots,
        "branches": [
            b for b in (hierarchy.get("branches") or [])
            if not (isinstance(b, dict) and b.get("hidden"))
        ],
        "generated_at": now,
        "counts": {
            "total": len(bots),
            "gateways_up": sum(1 for b in bots if b["gateway_running"]),
            "active_sessions": sum(b["active_sessions"] for b in bots),
        },
    }
    _CACHE["at"] = now
    _CACHE["payload"] = payload
    return payload


def invalidate_cache() -> None:
    _CACHE["at"] = 0.0
    _CACHE["payload"] = None
