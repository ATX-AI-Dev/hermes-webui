"""Bots panel, iteration 2 — the card behaves like a conversation-list row.

Grep-level guard, same family as test_bots_panel_frontend_b2.py and
test_bots_avatar_preview.py: it pins the card contract Ludo asked for after
seeing the first iteration in prod (see PROMPT-bots-panel-ux-rework.md):

  * the WHOLE card opens the bot's conversation, not just a button;
  * the secondary actions (inter-bot thread, gateway) and the low-frequency
    badges (permanent gateway, session count) live in a folded "···" area;
  * the model name is gone from the card.

Not a browser test — it only guarantees the pieces don't silently drift apart.
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "static"


def _panel_js() -> str:
    """The fork's own panel file (extracted from panels.js, see FORK-CHANGES.md)."""
    return (_STATIC / "bots_panel.js").read_text(encoding="utf-8")


def _panels_js() -> str:
    """Upstream's panels.js — only the integration hooks still live there."""
    return (_STATIC / "panels.js").read_text(encoding="utf-8")


def test_card_is_a_button_that_opens_the_conversation():
    js = _panel_js()
    assert 'data-card-act="${cardAct}"' in js
    assert 'role="button" tabindex="0"' in js
    # continue for bots with a Bot Chat, open as the fallback (B4 contract)
    assert "const cardAct = bot.has_bot_chat ? 'continue' : 'open';" in js
    # the card click and the keyboard activation both go through the one helper
    assert "async function _botsOpenConversation(bot, act, srcEl)" in js
    assert "_botsOpenConversation(card.dataset.bot, card.dataset.cardAct, card)" in js
    assert "function _botsOnKeydown(" in js
    assert "panel.addEventListener('keydown', _botsOnKeydown);" in js


def test_secondary_actions_live_in_a_folded_area():
    js = _panel_js()
    assert 'data-act="details"' in js
    assert 'class="bots-details" data-details-for=' in js
    assert "function _botsToggleDetails(bot, btn)" in js
    # a click on a folded action must not also fire the card's open action:
    # _botsOnClick returns from the button branch before reaching the card one
    assert "const card = ev.target.closest('.bots-row[data-card-act]');" in js


def test_folded_state_survives_a_poll_re_render():
    js = _panel_js()
    assert "const openDetails = new Set();" in js
    assert ".bots-details:not([hidden])" in js


def test_model_name_is_not_rendered_on_the_card():
    js = _panel_js()
    css = (_STATIC / "bots_panel.css").read_text(encoding="utf-8")
    assert "bots-model" not in js
    assert "bots-model" not in css


def test_bots_sidebar_stays_visible_while_a_conversation_is_open():
    """Point 6: the list must not disappear when you open a bot's chat.

    switchPanel('chat', {keepSidebarPanel:true}) moves only the main view, so
    #panelBots stays the active sidebar panel — which also means the 15s poll
    can no longer key off _currentPanel.
    """
    host = _panels_js()   # the switchPanel hooks stay in upstream's file
    panel = _panel_js()   # the caller lives in the fork's file
    assert "let _sidebarStickyPanel = null;" in host
    assert "if (!opts.keepSidebarPanel) {" in host
    # a rail click on Chat while pinned must restore the session list, not
    # collapse the sidebar
    assert "prevPanel === nextPanel && !_sidebarStickyPanel" in host
    assert "switchPanel('chat', desktop ? { keepSidebarPanel: true } : {});" in panel
    assert "function _botsPanelVisible()" in panel
    assert "if (!_botsPanelVisible()) return;" in panel


def test_open_bot_is_highlighted_in_the_list():
    js = _panel_js()
    css = (_STATIC / "bots_panel.css").read_text(encoding="utf-8")
    assert "function _botsMarkCurrent(bot)" in js
    assert "row.classList.toggle('is-current'" in js
    assert ".bots-row.is-current" in css


def test_style_and_i18n_back_the_new_card():
    css = (_STATIC / "bots_panel.css").read_text(encoding="utf-8")
    assert ".bots-more-btn" in css
    assert ".bots-details" in css
    # Fork keys live in i18n_fork.js and only supply en + fr; t() falls back
    # to LOCALES.en for the other 13 locales (see FORK-CHANGES.md).
    i18n = (_STATIC / "i18n_fork.js").read_text(encoding="utf-8")
    assert i18n.count("bots_more:") == 2
