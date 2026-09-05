"""B3b — the inter-bot thread viewer is wired into the Bots panel frontend.

Grep-level guard, same style as test_bots_panel_frontend_b2.py.
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "static"


def test_panels_js_has_thread_button_and_loader():
    js = (_STATIC / "bots_panel.js").read_text(encoding="utf-8")
    assert "data-act=\"chat\"" in js
    assert "async function _botsToggleChat(" in js
    assert "api('/api/bot-chat?profile=' + encodeURIComponent(bot))" in js
    assert "async function _botsRenderChatTurns" in js or "function _botsRenderChatTurns" in js
    assert "'relay_out'" in js


def test_i18n_has_thread_keys_en_and_fr():
    """Was: one copy per locale block in i18n.js. The fork's keys now live in
    i18n_fork.js with en + fr only — t() falls back to LOCALES.en for the other
    13 locales, which is exactly what the duplicated English text did before.
    See FORK-CHANGES.md."""
    i18n = (_STATIC / "i18n_fork.js").read_text(encoding="utf-8")
    for key in ("bots_thread", "bots_thread_empty", "bots_relay_pending", "bots_relay_ok", "bots_relay_error"):
        assert i18n.count(f"{key}:") == 2, f"{key} should be defined for en and fr"


def test_style_css_has_bot_chat_scope():
    css = (_STATIC / "bots_panel.css").read_text(encoding="utf-8")
    assert ".bots-chat" in css
    assert ".bots-relay" in css
