"""B2 — the Bots panel is wired into the frontend shell.

Grep-level guard (mirrors test_gateway_lifecycle_controls.py::
test_gateway_lifecycle_frontend_renders_valid_actions): keeps the nav entry,
panel container, switchPanel hook, loader, and i18n keys from silently
drifting apart. Not a browser test.
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "static"


def test_index_html_has_nav_and_panel():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    # one rail button + one mobile sidebar-nav button
    assert html.count('data-panel="bots"') == 2
    assert 'id="panelBots"' in html
    assert 'id="botsPanel"' in html
    assert "switchPanel('bots'" in html


def test_panels_js_registers_and_loads_bots():
    js = (_STATIC / "panels.js").read_text(encoding="utf-8")
    assert "'bots'" in js and "MAIN_VIEW_PANELS" in js
    assert "if (nextPanel === 'bots') await loadBotsPanel();" in js
    assert "async function loadBotsPanel(" in js
    # actions call the per-profile B1 endpoints, not the active-profile ones
    assert "'/api/gateway/' + act" in js
    assert "JSON.stringify({ profile: bot })" in js
    assert "api('/api/bots'" in js


def test_i18n_has_bots_keys_en_and_fr():
    i18n = (_STATIC / "i18n.js").read_text(encoding="utf-8")
    for key in ("tab_bots", "bots_panel_title", "bots_gateway_start", "bots_gateway_stop", "bots_open_thread"):
        # present at least twice (en + fr blocks)
        assert i18n.count(f"{key}:") >= 2, key


def test_style_css_has_bots_scope():
    css = (_STATIC / "style.css").read_text(encoding="utf-8")
    assert "#botsPanel" in css
    assert ".bots-row" in css
