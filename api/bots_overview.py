"""Aggregated read-only overview of every Hermes profile for the Bots panel.

Palier B / B2. One call, one payload: for each profile the WebUI can see
(``list_profiles_api``) it merges the fork-local hierarchy map
(``api/bots_hierarchy.json``, or an operator copy at
``<HERMES_HOME>/webui/bots_hierarchy.json``) with a cheap read-only scan of the
shared ``state.db`` for active-session counts and last activity.

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


def _sessions_by_profile() -> dict[str, dict]:
    """{profile_name: {active, last_activity}} from a read-only state.db scan.

    ``active`` counts non-archived, not-yet-ended sessions. Best-effort: any
    error (missing db, schema drift) yields an empty map and the panel simply
    shows zeros.
    """
    base = _base_hermes_home()
    if base is None:
        return {}
    db_path = base / "state.db"
    if not db_path.exists():
        return {}
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT COALESCE(NULLIF(profile_name, ''), 'default') AS p, "
                "       SUM(CASE WHEN ended_at IS NULL THEN 1 ELSE 0 END) AS active, "
                "       MAX(last_activity_at) AS last "
                "FROM sessions "
                "WHERE COALESCE(archived, 0) = 0 "
                "GROUP BY p"
            ).fetchall()
        finally:
            con.close()
    except Exception:
        logger.debug("bots_overview: state.db scan failed", exc_info=True)
        return {}
    for pname, active, last in rows:
        out[str(pname)] = {"active": int(active or 0), "last_activity": last}
    return out


def _branch_order(hierarchy: dict) -> dict[str, int]:
    return {b.get("id"): i for i, b in enumerate(hierarchy.get("branches") or []) if b.get("id")}


def build_bots_overview(*, use_cache: bool = True) -> dict:
    """Return ``{"bots": [...], "branches": [...], "generated_at": <epoch>}``.

    Each bot: ``id, role, description, branch, parent, manager, tag,
    permanent_gateway, gateway_running, model, skill_count, is_active,
    is_known (in the hierarchy map), active_sessions, last_activity``.
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
    sessions = _sessions_by_profile()
    branch_rank = _branch_order(hierarchy)

    bots: list[dict] = []
    for r in rows:
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        h = hmap.get(name) or {}
        sess = sessions.get(name) or {}
        bots.append(
            {
                "id": name,
                "role": h.get("role") or _profile_description(r.get("path") or "") or "",
                "description": _profile_description(r.get("path") or ""),
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
            }
        )

    bots.sort(key=lambda b: (branch_rank.get(b["branch"], 999), b["order"], b["id"]))

    payload = {
        "bots": bots,
        "branches": hierarchy.get("branches") or [],
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
