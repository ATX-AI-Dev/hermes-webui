"""Per-bot display name and profile picture (Bots panel, iteration 2, point 12).

The store lives beside the operator hierarchy override, under
``<HERMES_HOME>/webui/``, and is deliberately separate from
``bots_hierarchy.json``: that file describes the org and is edited by hand,
this one holds what the user picked from the UI and must survive an update of
the bundled hierarchy.
"""

from __future__ import annotations

import json

import pytest

# 1x1 PNG / GIF, enough for the byte sniffer.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
GIF = b"GIF89a\x01\x00\x01\x00\x00\xff\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x00;"


@pytest.fixture()
def store(monkeypatch, tmp_path):
    from api import bot_customization, profiles

    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: tmp_path)
    return bot_customization


def test_display_name_round_trip_and_clear(store):
    store.set_display_name("lancelot", "  Le   Manager  ")
    assert store.get_customization("lancelot")["display_name"] == "Le Manager"
    # an empty value clears the name, and an entry with nothing left is dropped
    store.set_display_name("lancelot", "   ")
    assert store.get_customization("lancelot") == {}
    assert store.load_customization() == {}


def test_display_name_is_bounded(store):
    store.set_display_name("lancelot", "x" * 500)
    assert len(store.get_customization("lancelot")["display_name"]) == store.MAX_DISPLAY_NAME_CHARS


def test_invalid_profile_is_refused(store):
    for bad_name in ("", "   ", "../../etc/passwd", "a/b", "sub dir"):
        with pytest.raises(ValueError):
            store.set_display_name(bad_name, "x")
        with pytest.raises(ValueError):
            store.save_avatar(bad_name, PNG)


def test_avatar_is_typed_by_its_bytes_not_its_name(store, tmp_path):
    entry = store.save_avatar("lancelot", PNG)
    assert entry["avatar"] == "lancelot.png"
    assert (tmp_path / "webui" / "bot_avatars" / "lancelot.png").read_bytes() == PNG
    found = store.avatar_file("lancelot")
    assert found is not None and found[1] == "image/png"

    # a second upload in another format replaces the first, leaving one file
    store.save_avatar("lancelot", GIF)
    files = sorted(p.name for p in (tmp_path / "webui" / "bot_avatars").iterdir())
    assert files == ["lancelot.gif"]


def test_non_image_and_oversized_uploads_are_refused(store):
    with pytest.raises(ValueError):
        store.save_avatar("lancelot", b"<html>not an image</html>")
    with pytest.raises(ValueError):
        store.save_avatar("lancelot", b"")
    with pytest.raises(ValueError):
        store.save_avatar("lancelot", PNG + b"\x00" * store.MAX_AVATAR_BYTES)


def test_clear_avatar_removes_the_file_and_the_entry(store, tmp_path):
    store.save_avatar("lancelot", PNG)
    store.clear_avatar("lancelot")
    assert store.avatar_file("lancelot") is None
    assert list((tmp_path / "webui" / "bot_avatars").iterdir()) == []


def test_avatar_url_carries_a_cache_busting_stamp(store):
    assert store.avatar_url("lancelot") is None
    store.save_avatar("lancelot", PNG)
    url = store.avatar_url("lancelot")
    assert url.startswith("/api/bots/avatar?profile=lancelot&v=")


def test_a_broken_store_never_breaks_the_panel(store, tmp_path):
    webui = tmp_path / "webui"
    webui.mkdir(parents=True, exist_ok=True)
    (webui / "bot_customization.json").write_text("{ not json", encoding="utf-8")
    assert store.load_customization() == {}
    assert store.get_customization("lancelot") == {}
    # a valid-JSON-but-wrong-shape store is ignored row by row
    (webui / "bot_customization.json").write_text(
        json.dumps({"lancelot": "nope", "bohorth": {"display_name": "B"}}), encoding="utf-8"
    )
    assert store.load_customization() == {"bohorth": {"display_name": "B"}}


def test_overview_exposes_the_customization(monkeypatch, tmp_path):
    from api import bots_overview, profiles

    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(profiles, "list_profiles_api", lambda: [{"name": "lancelot", "path": "/x/l"}])
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda n: tmp_path / "profiles" / n)

    from api import bot_customization
    bot_customization.set_display_name("lancelot", "Le Manager")
    bot_customization.save_avatar("lancelot", PNG)

    bots_overview.invalidate_cache()
    bot = bots_overview.build_bots_overview(use_cache=False)["bots"][0]
    assert bot["display_name"] == "Le Manager"
    assert bot["avatar_url"].startswith("/api/bots/avatar?profile=lancelot&v=")


def test_frontend_renders_name_and_picture():
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "static"
    js = (static / "panels.js").read_text(encoding="utf-8")
    css = (static / "style.css").read_text(encoding="utf-8")
    assert "if (bot.avatar_url) {" in js
    assert "function _botDisplayName(bot)" in js
    assert 'data-act="customize"' in js
    assert "'/api/bots/customization'" in js
    assert "'/api/bots/avatar'" in js
    assert ".bots-avatar--img" in css
    assert ".bots-custom" in css
