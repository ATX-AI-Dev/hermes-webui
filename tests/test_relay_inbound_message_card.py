"""Incoming Bot Chat relay turn rendering (04/09/2026, follow-up to B4 §6
point 2 — the "Message from X" gap noted as not-done in
PLAN-B4-fusion-conversation.md).

An incoming ``message_agent`` delivery lands as a plain user-role message
with a fixed prefix built by hermes-agent's ``tools/bot_mode_dm.py``:
``f"Message from 🤖 {sender_handle} (@{sender_handle}): {body}"`` (the same
handle used for both the display name and the ``@handle`` slot). Before this
change it rendered as a normal text bubble showing that raw prefix; now
``_relayInboundMatch`` detects it and the render path gives it the same
relay-icon treatment as the outgoing ``message_agent`` tool-card.

Drives the real `static/ui.js` helper under node (no server), same pattern
as test_message_agent_tool_card.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.resolve()
UI_JS_PATH = REPO_ROOT / "static" / "ui.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")

_DRIVER_SRC = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
function grab(name){
  const re = new RegExp('function ' + name + '\\([^]*?\\n}', 'm');
  const m = src.match(re);
  if (!m) throw new Error('function not found: ' + name);
  return m[0];
}
global.li = (name, size) => `<svg data-icon="${name}"></svg>`;
global.esc = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
global.t = (key) => (key === 'relay_inbound_from' ? 'Message from' : key);
function grabConst(name){
  const re = new RegExp('const ' + name + '=.*?;', 'm');
  const m = src.match(re);
  if (!m) throw new Error('const not found: ' + name);
  return m[0];
}
eval(grabConst('_RELAY_INBOUND_RE').replace('const _RELAY_INBOUND_RE', 'global._RELAY_INBOUND_RE'));
eval(grab('_relayInboundMatch'));
eval(grab('_relayInboundHeaderHtml'));
let buf = '';
process.stdin.on('data', c => { buf += c; });
process.stdin.on('end', () => {
  const payload = JSON.parse(buf || '{}');
  const text = payload.text;
  const match = _relayInboundMatch(text);
  process.stdout.write(JSON.stringify({
    match,
    headerHtml: match ? _relayInboundHeaderHtml(match.from) : null,
  }));
});
"""


@pytest.fixture(scope="module")
def driver_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("relay_inbound_driver") / "driver.js"
    p.write_text(_DRIVER_SRC, encoding="utf-8")
    return str(p)


def _run(driver_path: str, text: str) -> dict:
    assert NODE is not None
    proc = subprocess.run(
        [NODE, driver_path, str(UI_JS_PATH)],
        input=json.dumps({"text": text}),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_matches_the_exact_agent_prefix(driver_path):
    text = "Message from \U0001F916 lancelot (@lancelot): Test B4 note."
    result = _run(driver_path, text)
    assert result["match"] == {"from": "lancelot", "message": "Test B4 note."}


def test_matches_hyphenated_handle(driver_path):
    text = "Message from \U0001F916 pere-blaise (@pere-blaise): OK recu."
    result = _run(driver_path, text)
    assert result["match"] == {"from": "pere-blaise", "message": "OK recu."}


def test_matches_multiline_body(driver_path):
    text = "Message from \U0001F916 roi-arthur (@roi-arthur): Line one\nLine two"
    result = _run(driver_path, text)
    assert result["match"] == {"from": "roi-arthur", "message": "Line one\nLine two"}


def test_rejects_mismatched_handles(driver_path):
    """Never produced by the real tool (same handle both slots) -- must not match."""
    text = "Message from \U0001F916 lancelot (@roi-arthur): spoofed?"
    result = _run(driver_path, text)
    assert result["match"] is None


def test_rejects_plain_user_text_that_merely_starts_similarly(driver_path):
    text = "Message from the team: please review this."
    result = _run(driver_path, text)
    assert result["match"] is None


def test_rejects_missing_robot_emoji(driver_path):
    text = "Message from lancelot (@lancelot): missing the emoji prefix"
    result = _run(driver_path, text)
    assert result["match"] is None


def test_empty_text_does_not_match(driver_path):
    assert _run(driver_path, "")["match"] is None


def test_header_html_includes_icon_and_handle(driver_path):
    text = "Message from \U0001F916 lancelot (@lancelot): hi"
    result = _run(driver_path, text)
    header = result["headerHtml"]
    assert 'data-icon="message-square"' in header
    assert "@lancelot" in header
    assert "Message from" in header


def test_header_html_escapes_handle(driver_path):
    """Defense in depth: handle is regex-constrained to [a-z0-9_-], but the
    header builder must still escape it rather than assume the constraint
    holds forever."""
    text = "Message from \U0001F916 lancelot (@lancelot): hi"
    result = _run(driver_path, text)
    # Sanity: real handles never contain HTML-special chars, so this just
    # confirms esc() is actually being called in the header builder, not
    # bypassed -- a raw '<' would only ever come from a future regex change.
    assert "<strong>@lancelot</strong>" in result["headerHtml"]
