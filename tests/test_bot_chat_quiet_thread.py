"""Bot Chat threads hide the bot's plumbing and offer it in a Trace tab.

Point 7 of the Bots panel iteration-2 review. Opening a bot's conversation
imports that bot's own agent session (api/bot_mesh.py::continue_bot_chat),
which carries operational turns a human never wrote: background-process
wakeups, cronjob relays, and the tool trace.

Checked against a real transcript on the production host (roi-arthur's Bot
Chat, 2026-09-05): those arrive as ``role='user'`` rows whose content starts
with the agent's notice grammar, plus ``role='tool'`` rows. The consolidated
status tables in the same thread are ordinary assistant markdown — the bot's
own words — so they are deliberately NOT hidden.

Grep-level guard, in the family of test_bots_panel_frontend_b2.py.
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "static"


def _ui_js() -> str:
    return (_STATIC / "ui.js").read_text(encoding="utf-8")


def test_machine_notice_grammar_matches_what_the_agent_writes():
    """The regex in ui.js must accept the two real notice shapes and reject a
    human message that merely mentions one of them."""
    js = _ui_js()
    m = re.search(r"const _MACHINE_NOTICE_RE=(/.+/);", js)
    assert m, "machine-notice regex not found in ui.js"
    pattern = m.group(1)
    assert pattern.startswith("/^\\[")  # anchored, like _RELAY_INBOUND_RE
    for shape in ("IMPORTANT: Background process ", 'Cronjob "'):
        assert shape in pattern


def test_process_notice_shapes_stay_in_sync_with_the_server():
    """api/process_event_utils.py pins the wakeup grammar server-side; the
    front-end prefix must still be a prefix of it."""
    server = (Path(__file__).resolve().parents[1] / "api" / "process_event_utils.py").read_text(encoding="utf-8")
    assert r"\A\[IMPORTANT: Background process " in server


def test_thread_marks_bot_chats_and_machine_rows():
    js = _ui_js()
    assert "function isBotChatSession()" in js
    assert "S.session.title==='Bot Chat'" in js
    assert "_msgsEl.dataset.botChat='1'" in js
    assert "' machine-notice-row'" in js


def test_css_hides_only_the_plumbing():
    css = (_STATIC / "style.css").read_text(encoding="utf-8")
    block = css[css.index('.messages[data-bot-chat="1"] .machine-notice-row'):]
    block = block[:block.index("}") + 1]
    for hidden in ("machine-notice-row", "process-wakeup-row",
                   "transparent-event-controls", "transparent-event-row"):
        assert hidden in block
    # assistant prose (status tables included) must not be targeted
    assert "assistant-turn" not in block
    assert "msg-body" not in block


def test_workspace_trace_tab_mirrors_the_todos_tab():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    ws = (_STATIC / "workspace.js").read_text(encoding="utf-8")
    assert 'id="workspaceTraceTab"' in html and "switchWorkspacePanelTab('trace')" in html
    assert 'id="workspaceTracePanel"' in html
    # hidden by default, exactly like the Todos tab
    trace_btn = next(l for l in html.splitlines() if 'id="workspaceTraceTab"' in l)
    assert " hidden" in trace_btn
    assert "function _loadWorkspacePanelTrace()" in ws
    assert "function syncWorkspaceTraceTab()" in ws
    assert "tab === 'trace' ? 'trace'" in ws
    # the tab only shows for a Bot Chat that actually has trace
    assert "isBotChatSession()" in ws
    assert "_workspaceTraceEntries().length > 0" in ws
    assert _ui_js().count("syncWorkspaceTraceTab()") >= 1


def test_trace_i18n_keys_exist_en_and_fr():
    i18n = (_STATIC / "i18n.js").read_text(encoding="utf-8")
    for key in ("workspace_trace_tab", "workspace_trace_empty",
                "workspace_trace_tool", "workspace_trace_process"):
        assert i18n.count(f"{key}:") >= 2, key
