"""Regression coverage for the message_agent/bot_mode_dm tool-card rendering
(B4 §6 point 2 — see PLAN-B4-fusion-conversation.md).

Before this change, a message_agent tool call in the real chat view (not just
the Bots-panel "Fil inter-bots" viewer from B3b) rendered as a generic
"unknown"-kind tool card: wrench icon, raw arg dump, raw ack JSON as the
preview. This gives it the dedicated treatment: a message icon, a
"Messaged @target" header, the message body as the expanded detail lead, and
the parsed ack status ("Sent" / the error text) as the compact preview
instead of raw JSON.

Drives the real `static/ui.js` helpers under node (no server), same pattern
as test_issue4926_shell_full_command.py.
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
global._decodeToolLabelEntities = (s) => s;
global._redactToolTargetLabel = (s) => s;
eval(grab('_shortToolLabel'));
eval(grab('_toolActionKind'));
eval(grab('_toolTargetLabel'));
eval(grab('_toolDetailLeadLabel'));
eval(grab('_toolDetailLeadText'));
eval(grab('_toolDisplayName'));
eval(grab('_relayAckStatus'));
let buf = '';
process.stdin.on('data', c => { buf += c; });
process.stdin.on('end', () => {
  const payload = JSON.parse(buf || '{}');
  const tc = payload.tc || {};
  const kind = _toolActionKind(tc);
  process.stdout.write(JSON.stringify({
    kind,
    target: _toolTargetLabel(tc),
    leadLabel: _toolDetailLeadLabel(kind),
    lead: _toolDetailLeadText(kind, tc),
    displayName: _toolDisplayName(tc),
    ackStatus: _relayAckStatus(tc),
  }));
});
"""


@pytest.fixture(scope="module")
def driver_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("relay_toolcard_driver") / "driver.js"
    p.write_text(_DRIVER_SRC, encoding="utf-8")
    return str(p)


def _run(driver_path: str, tc: dict) -> dict:
    assert NODE is not None
    result = subprocess.run(
        [NODE, driver_path, str(UI_JS_PATH)],
        input=json.dumps({"tc": tc}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


@pytest.mark.parametrize("tool_name", ["message_agent", "bot_mode_dm"])
def test_relay_tool_names_classified_as_relay_kind(driver_path, tool_name):
    out = _run(driver_path, {"name": tool_name, "args": {"target": "@roi-arthur", "message": "hi"}})
    assert out["kind"] == "relay"


def test_target_label_reads_args_target(driver_path):
    out = _run(driver_path, {"name": "message_agent", "args": {"target": "@bohorth", "message": "ping"}})
    assert out["target"] == "@bohorth"


def test_detail_lead_shows_message_body_not_target(driver_path):
    out = _run(driver_path, {
        "name": "message_agent",
        "args": {"target": "@roi-arthur", "message": "Test B4 - ignore, no action needed."},
    })
    assert out["leadLabel"] == "Message"
    assert out["lead"] == "Test B4 - ignore, no action needed."


def test_display_name_is_human_readable(driver_path):
    out = _run(driver_path, {"name": "message_agent", "args": {}})
    assert out["displayName"] == "Message agent"
    out2 = _run(driver_path, {"name": "bot_mode_dm", "args": {}})
    assert out2["displayName"] == "Message agent"


def test_ack_status_parses_sent_dispatch_ack(driver_path):
    ack = json.dumps({"status": "sent", "to": "@roi-arthur", "detail": "Message dispatched. Async."})
    out = _run(driver_path, {"name": "message_agent", "args": {"target": "@roi-arthur"}, "snippet": ack})
    assert out["ackStatus"] == "Sent"


def test_ack_status_surfaces_error_text(driver_path):
    ack = json.dumps({"error": "unknown target profile"})
    out = _run(driver_path, {"name": "message_agent", "args": {"target": "@nope"}, "snippet": ack})
    assert out["ackStatus"] == "unknown target profile"


def test_ack_status_blank_when_snippet_missing_or_unparseable(driver_path):
    out = _run(driver_path, {"name": "message_agent", "args": {"target": "@x"}})
    assert out["ackStatus"] == ""
    out2 = _run(driver_path, {"name": "message_agent", "args": {"target": "@x"}, "snippet": "not json"})
    assert out2["ackStatus"] == ""


def test_unrelated_tool_still_classified_unknown(driver_path):
    out = _run(driver_path, {"name": "web_search", "args": {"query": "x"}})
    assert out["kind"] != "relay"
