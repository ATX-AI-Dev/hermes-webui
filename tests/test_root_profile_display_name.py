"""The root profile displays as "Assistant", not as its 'default' alias.

Point 9 of the Bots panel iteration-2 review: "default" is an internal
identifier (upstream hardcodes it as the base home's name in
``_build_profile_rows_fast``) and reads as jargon to a non-technical user. Only
the DISPLAY changes — 'default' stays the identifier in paths, API parameters
and ``_is_root_profile``.

Also guards the rail move from point 10 (Bots sits right after Chat).
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "static"


def test_root_profile_row_gets_the_display_label():
    from api import profiles

    assert profiles.root_profile_display_label() == "Assistant"
    row = profiles._with_display_name({"name": "default", "is_default": True})
    assert row["display_name"] == "Assistant"
    assert row["name"] == "default"  # identifier untouched


def test_other_profiles_display_under_their_own_name():
    from api import profiles

    assert profiles._with_display_name({"name": "lancelot", "is_default": False})["display_name"] == "lancelot"
    # a row that already carries one is left alone
    row = {"name": "default", "is_default": True, "display_name": "Kinni"}
    assert profiles._with_display_name(row)["display_name"] == "Kinni"


def test_list_profiles_api_stamps_display_name(monkeypatch):
    from api import profiles

    monkeypatch.setattr(profiles, "_list_profiles_rows", lambda: [
        {"name": "default", "is_default": True},
        {"name": "lancelot", "is_default": False},
    ])
    rows = profiles.list_profiles_api()
    assert [r["display_name"] for r in rows] == ["Assistant", "lancelot"]


def test_frontend_resolves_the_display_name_everywhere_a_profile_is_named():
    panels = (_STATIC / "panels.js").read_text(encoding="utf-8")
    boot = (_STATIC / "boot.js").read_text(encoding="utf-8")
    assert "const ROOT_PROFILE_DISPLAY_NAME = 'Assistant';" in panels
    assert "function profileDisplayName(p)" in panels
    # profile dropdown, profiles panel card, titlebar label, boot-time label
    assert panels.count("profileDisplayName(") >= 4
    assert "profileDisplayName(S.activeProfile||'default')" in boot


def test_bots_rail_button_sits_right_after_chat():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    panels_in_order = []
    for line in html.splitlines():
        if 'data-panel="' in line and "switchPanel(" in line:
            panels_in_order.append(line.split('data-panel="', 1)[1].split('"', 1)[0])
    # two rails (desktop .rail + mobile .sidebar-nav), both chat → bots → …
    assert panels_in_order[:2] == ["chat", "bots"]
    second = panels_in_order[panels_in_order.index("chat", 1):]
    assert second[:2] == ["chat", "bots"]
