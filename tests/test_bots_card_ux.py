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


def test_folded_areas_are_actually_hidden_by_the_hidden_attribute():
    """`hidden` only wins over the UA stylesheet — not over an author `display`.

    .bots-details / .bots-custom / .bots-chat all set `display: flex`, which
    kept the folded areas permanently open and made "···" look inert (reported
    2026-09-06). The explicit [hidden] rule is what makes the toggle work.
    """
    css = (_STATIC / "bots_panel.css").read_text(encoding="utf-8")
    rule = next((l for l in css.splitlines() if "[hidden]" in l and "display: none" in l), "")
    for cls in (".bots-details[hidden]", ".bots-custom[hidden]", ".bots-chat[hidden]"):
        assert cls in rule, f"{cls} must be in the shared [hidden] rule, got: {rule!r}"


def test_continue_does_not_mint_a_throwaway_session():
    """Opening a bot's Bot Chat must not create a blank session on the way.

    switchToProfile's `sessionInProgress` branch mints a new session, awaits its
    workspace tree, re-renders the session list and toasts "new conversation
    started" — all discarded by the loadSession() that follows. Upstream's own
    session list avoids it with `_profileSwitchOpeningExistingSession`; the Bots
    panel has to hold the same contract (reported 2026-09-06: switching from one
    bot to another took seconds and toasted a conversation the user never saw).
    """
    js = _panel_js()
    assert "async function _botsSwitchProfileForExistingSession(bot)" in js
    assert "_profileSwitchOpeningExistingSession = true;" in js
    assert "_profileSwitchOpeningExistingSession = false;" in js
    # the flag must be cleared even when the switch throws
    helper = js.split("async function _botsSwitchProfileForExistingSession(bot)")[1]
    helper = helper.split("async function _botsOpenConversation")[0]
    assert "finally" in helper, "the flag must be reset in a finally block"
    # and the 'open' fallback (no Bot Chat to load) must keep the default branch
    assert "if (typeof switchToProfile === 'function') await switchToProfile(bot);" in js


def test_continue_and_profile_switch_run_in_parallel():
    """They have no dependency on each other — api/bot_mesh.py resolves the
    profile explicitly rather than through the cookie the switch sets."""
    js = _panel_js()
    assert "const importing = api('/api/bot-chat/continue'" in js
    assert "const switching = _botsSwitchProfileForExistingSession(bot);" in js
    assert "await Promise.all([importing, switching]);" in js


def test_bot_mesh_continue_resolves_the_profile_explicitly():
    """The parallelism above is only safe while this stays true."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "api" / "bot_mesh.py").read_text(encoding="utf-8")
    body = src.split("def continue_bot_chat(profile: str) -> dict:")[1].split("\ndef ")[0]
    assert "find_bot_chat_session(profile)" in body
    assert "get_cli_session_messages(sid, profile=profile)" in body
    assert "profile=profile," in body
