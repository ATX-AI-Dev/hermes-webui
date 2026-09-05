"""B2 — aggregated /api/bots overview for the Bots panel."""

from __future__ import annotations

import json
import sqlite3
from urllib.parse import urlparse


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.sent_headers: list[tuple[str, str]] = []
        self.body = bytearray()
        self.wfile = self

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.sent_headers.append((key, value))

    def end_headers(self):
        pass

    def write(self, data):
        self.body.extend(data if isinstance(data, (bytes, bytearray)) else data.encode("utf-8"))

    def get_json(self):
        return json.loads(self.body.decode("utf-8"))


_PROFILE_ROWS = [
    {"name": "lancelot", "path": "/x/lancelot", "gateway_running": True, "model": "longcat-2.0:free", "skill_count": 4, "is_active": True},
    {"name": "bohorth", "path": "/x/bohorth", "gateway_running": False, "model": "longcat-2.0:free", "skill_count": 2, "is_active": False},
    {"name": "yvain", "path": "/x/yvain", "gateway_running": False, "model": None, "skill_count": 0, "is_active": False},
    {"name": "some-random-profile", "path": "/x/rnd", "gateway_running": False, "model": None, "skill_count": 1, "is_active": False},
]


def _patch(monkeypatch, *, base_home=None, rows=None, profile_homes=None):
    """profile_homes: optional {name: Path}. Each profile has its OWN state.db
    (confirmed live 2026-09-04: no shared database) — get_hermes_home_for_profile
    is what every per-profile read goes through, so tests fake it directly."""
    from api import bots_overview, profiles

    monkeypatch.setattr(profiles, "list_profiles_api", lambda: list(rows if rows is not None else _PROFILE_ROWS))
    homes = dict(profile_homes or {})
    fallback_root = base_home if base_home is not None else None

    def _fake_home(name):
        if name in homes:
            return homes[name]
        if fallback_root is not None:
            return fallback_root / "profiles" / name  # no state.db there -> stats/has_bot_chat stay absent
        raise RuntimeError("no home configured for " + str(name))

    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", _fake_home)
    if base_home is not None:
        monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: base_home)
    else:
        monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: (_ for _ in ()).throw(RuntimeError("no home")))
    bots_overview.invalidate_cache()
    return bots_overview


def test_merges_bundled_hierarchy_with_live_profiles(monkeypatch):
    bo = _patch(monkeypatch)
    payload = bo.build_bots_overview(use_cache=False)
    by_id = {b["id"]: b for b in payload["bots"]}

    assert by_id["lancelot"]["branch"] == "pro"
    assert by_id["lancelot"]["manager"] is True
    assert by_id["lancelot"]["role"].startswith("Manager Pro")
    assert by_id["lancelot"]["gateway_running"] is True
    assert by_id["yvain"]["parent"] == "perceval"
    assert by_id["bohorth"]["parent"] == "lancelot"


def test_unknown_profile_lands_in_autre(monkeypatch):
    bo = _patch(monkeypatch)
    payload = bo.build_bots_overview(use_cache=False)
    rnd = next(b for b in payload["bots"] if b["id"] == "some-random-profile")
    assert rnd["branch"] == "autre"
    assert rnd["is_known"] is False
    assert rnd["parent"] is None


def test_counts_reflect_gateways_and_sessions_from_each_profiles_own_db(monkeypatch, tmp_path):
    lancelot_home = tmp_path / "lancelot"
    bohorth_home = tmp_path / "bohorth"
    lancelot_home.mkdir()
    bohorth_home.mkdir()
    _make_profile_db(lancelot_home, [
        (None, "2026-09-04T10:00:00"),
        ("2026-09-01T00:00:00", "2026-08-30T08:00:00"),  # ended: counts for last_activity, not for `active`
    ])
    _make_profile_db(bohorth_home, [(None, "2026-09-03T09:00:00")])
    # yvain / some-random-profile: no state.db at all -> zeros, no crash.
    bo = _patch(monkeypatch, profile_homes={"lancelot": lancelot_home, "bohorth": bohorth_home})
    payload = bo.build_bots_overview(use_cache=False)

    assert payload["counts"]["total"] == len(_PROFILE_ROWS)
    assert payload["counts"]["gateways_up"] == 1  # only lancelot
    by_id = {b["id"]: b for b in payload["bots"]}
    assert by_id["lancelot"]["active_sessions"] == 1  # the ended one is excluded
    assert by_id["lancelot"]["last_activity"] == "2026-09-04T10:00:00"
    assert by_id["bohorth"]["active_sessions"] == 1
    assert by_id["yvain"]["active_sessions"] == 0
    assert payload["counts"]["active_sessions"] == 2


def test_a_profile_without_its_own_db_does_not_leak_another_profiles_sessions(monkeypatch, tmp_path):
    """Regression: an earlier revision read one shared state.db and attributed
    every profile's sessions to whichever profile happened to own that file.
    lancelot's sessions must never appear under bohorth."""
    lancelot_home = tmp_path / "lancelot"
    lancelot_home.mkdir()
    _make_profile_db(lancelot_home, [(None, "2026-09-04T10:00:00"), (None, "2026-09-04T10:05:00")])
    bo = _patch(monkeypatch, profile_homes={"lancelot": lancelot_home})
    payload = bo.build_bots_overview(use_cache=False)
    by_id = {b["id"]: b for b in payload["bots"]}
    assert by_id["lancelot"]["active_sessions"] == 2
    assert by_id["bohorth"]["active_sessions"] == 0
    assert by_id["bohorth"]["last_activity"] is None


def test_bots_are_sorted_by_branch_then_order(monkeypatch):
    # 'default' sits in the 'interne' branch, which the bundled hierarchy now
    # flags hidden — see test_hidden_branch_is_excluded_from_bots_and_counts.
    bo = _patch(monkeypatch, rows=[
        {"name": "default", "path": "/x/d"},
        {"name": "roi-arthur", "path": "/x/a"},
        {"name": "lancelot", "path": "/x/l"},
        {"name": "guenievre", "path": "/x/g"},
    ])
    payload = bo.build_bots_overview(use_cache=False)
    order = [b["id"] for b in payload["bots"]]
    assert order == ["roi-arthur", "lancelot", "guenievre"]


def test_operator_override_wins_and_broken_file_is_ignored(monkeypatch, tmp_path):
    webui = tmp_path / "webui"
    webui.mkdir()
    # 1) broken JSON -> fall back to bundled
    (webui / "bots_hierarchy.json").write_text("{ not json", encoding="utf-8")
    bo = _patch(monkeypatch, base_home=tmp_path)
    payload = bo.build_bots_overview(use_cache=False)
    assert next(b for b in payload["bots"] if b["id"] == "lancelot")["branch"] == "pro"

    # 2) valid override -> its mapping wins
    (webui / "bots_hierarchy.json").write_text(
        json.dumps({"branches": [{"id": "custom", "label": "Custom"}],
                    "profiles": {"lancelot": {"branch": "custom", "role": "Overridden", "order": 0}}}),
        encoding="utf-8",
    )
    bo.invalidate_cache()
    payload = bo.build_bots_overview(use_cache=False)
    lancelot = next(b for b in payload["bots"] if b["id"] == "lancelot")
    assert lancelot["branch"] == "custom"
    assert lancelot["role"] == "Overridden"


def test_route_returns_payload(monkeypatch):
    from api import routes
    _patch(monkeypatch)

    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/bots"))
    data = handler.get_json()

    assert "bots" in data and "branches" in data and "counts" in data
    assert data["counts"]["total"] == len(_PROFILE_ROWS)


def _make_profile_db(home_dir, session_rows):
    """session_rows: list of (ended_at, last_activity_at) — this db already
    belongs to one profile, no profile_name column needed."""
    db = sqlite3.connect(home_dir / "state.db")
    db.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, ended_at TEXT, "
        "last_activity_at TEXT, archived INTEGER DEFAULT 0)"
    )
    db.executemany(
        "INSERT INTO sessions (ended_at, last_activity_at) VALUES (?, ?)",
        session_rows,
    )
    db.commit()
    db.close()


def test_duplicate_profile_names_are_collapsed_to_one_bot(monkeypatch):
    """The production host has BOTH ~/.hermes (reported as 'default') and a
    real ~/.hermes/profiles/default directory, so list_profiles_api returns two
    rows named 'default' and the panel drew the profile twice (2026-09-05).
    Uses a visible branch so the dedupe is what's under test, not the hiding.
    """
    bo = _patch(monkeypatch, rows=[
        {"name": "lancelot", "path": "/x/base/lancelot", "gateway_running": True},
        {"name": "lancelot", "path": "/x/profiles/lancelot", "gateway_running": False},
        {"name": "bohorth", "path": "/x/bohorth"},
    ])
    payload = bo.build_bots_overview(use_cache=False)
    assert [b["id"] for b in payload["bots"]] == ["lancelot", "bohorth"]
    # first row wins (the base home), so its gateway state is the one kept
    assert payload["bots"][0]["gateway_running"] is True
    assert payload["counts"]["total"] == 2
    assert payload["counts"]["gateways_up"] == 1


def test_hidden_branch_is_excluded_from_bots_and_counts(monkeypatch, tmp_path):
    """A branch flagged "hidden" disappears from the list, from counts, and
    from the branches payload — the 'interne' branch (the plain-chat 'default'
    profile) is not a bot and has its own entry point in the rail.
    """
    webui = tmp_path / "webui"
    webui.mkdir()
    (webui / "bots_hierarchy.json").write_text(json.dumps({
        "branches": [
            {"id": "pro", "label": "Pro"},
            {"id": "interne", "label": "Interne", "hidden": True},
        ],
        "profiles": {
            "lancelot": {"branch": "pro", "role": "Manager"},
            "default": {"branch": "interne", "role": "Chat"},
        },
    }), encoding="utf-8")
    bo = _patch(monkeypatch, base_home=tmp_path, rows=[
        {"name": "lancelot", "path": "/x/l", "gateway_running": True},
        {"name": "default", "path": "/x/d", "gateway_running": True},
    ])
    payload = bo.build_bots_overview(use_cache=False)
    assert [b["id"] for b in payload["bots"]] == ["lancelot"]
    assert payload["counts"]["total"] == 1
    assert payload["counts"]["gateways_up"] == 1  # 'default' not counted
    assert [b["id"] for b in payload["branches"]] == ["pro"]
