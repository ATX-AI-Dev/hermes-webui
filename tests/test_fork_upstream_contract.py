"""Sentinel: every upstream hook the fork leans on still exists.

The fork (ATX-AI-Dev/hermes-webui) tracks `nesquena/hermes-webui` on `master`
and rebases its `feat/*` branches onto each upstream release. Most of that goes
through public-ish surfaces, but a handful of PRIVATE helpers and implicit
contracts carry real weight — and upstream owes them no stability. When one
disappears in a `git pull`, the fork's failure is usually SILENT: the calls
sit inside `try/except` blocks so a missing agent helper degrades gracefully
instead of crashing, which is right at runtime and terrible for noticing.

This file turns that silence into a red test. Each assertion names what the
fork does with the symbol, so whoever hits the failure can decide between
"follow upstream's rename" and "write our own". The divergence ledger with the
full context is FORK-CHANGES.md.

Nothing here tests fork behaviour — the per-feature tests do that. This only
answers "are the foundations still where we left them?".
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "static"


# ── Python: private helpers the fork imports ────────────────────────────────

@pytest.mark.parametrize(("module", "symbol", "used_by"), [
    # api/routes.py, B1 — pins the thread-local active profile so a gateway
    # action can target a NON-active bot without switching WebUI's profile.
    ("api.profiles", "_tls", "routes._active_profile_override (B1)"),
    # Validates every `profile` that reaches a filesystem path or a CLI flag.
    ("api.profiles", "_PROFILE_ID_RE", "every fork route + bot_customization._valid_profile"),
    # Where the fork's own state lives: <base home>/webui/{bots_hierarchy,bot_customization}.json
    ("api.profiles", "_resolve_base_hermes_home", "bots_overview._base_hermes_home, bot_customization._webui_dir"),
    # The row builder whose hardcoded 'default' name for the base home is why
    # bots_overview has to dedupe (see _dedupe_rows_by_name).
    ("api.profiles", "_build_profile_rows_fast", "profiles.list_profiles_api fast path"),
    ("api.profiles", "get_hermes_home_for_profile", "bots_overview per-profile state.db lookup"),
    ("api.profiles", "list_profiles_api", "bots_overview.build_bots_overview"),
    # B4: importing a bot's own agent-native session into WebUI.
    ("api.models", "get_cli_session_messages", "bot_mesh.continue_bot_chat"),
    ("api.models", "import_cli_session", "bot_mesh.continue_bot_chat"),
    # One multipart parser in the process, shared with /api/upload.
    ("api.upload", "parse_multipart", "bot_customization.handle_post_avatar"),
    ("api.helpers", "j", "every fork handler"),
    ("api.routes", "bad", "every fork handler"),
    ("api.routes", "_sanitize_error", "every fork handler"),
    # agent_drift re-execs through upstream's own restart path rather than
    # reimplementing it — losing any of these silently breaks the banner's button.
    ("api.updates", "_schedule_restart", "agent_drift._restart_worker (os.execv re-exec)"),
    ("api.updates", "_wait_until_restart_safe", "agent_drift._restart_worker (drain streams first)"),
    ("api.updates", "_restart_blocker_snapshot", "agent_drift.request_restart"),
    ("api.updates", "_detect_agent_version", "agent_drift.drift_status"),
])
def test_upstream_symbol_still_exists(module, symbol, used_by):
    import importlib
    mod = importlib.import_module(module)
    assert hasattr(mod, symbol), (
        f"{module}.{symbol} is gone upstream. The fork uses it for: {used_by}. "
        "See FORK-CHANGES.md before patching around it."
    )


def test_parse_multipart_still_returns_fields_and_files():
    """handle_post_avatar unpacks ``(fields, files)`` and reads ``files['file'][1]``."""
    import inspect
    from api.upload import parse_multipart
    params = list(inspect.signature(parse_multipart).parameters)
    assert params[:3] == ["rfile", "content_type", "content_length"], params


def test_agent_gateway_probe_is_optional_but_looked_for():
    """``hermes_cli.profiles._check_gateway_running`` backs the per-profile
    gateway status (B1). It is imported inside a try/except — absence degrades
    to the metadata guess rather than crashing — so this test SKIPS when the
    agent isn't installed instead of failing a dev machine's suite.
    """
    hermes_cli_profiles = pytest.importorskip("hermes_cli.profiles")
    assert hasattr(hermes_cli_profiles, "_check_gateway_running"), (
        "hermes_cli.profiles._check_gateway_running is gone. routes."
        "_check_gateway_running_for_home falls back to the metadata guess, so a "
        "non-active bot's gateway state can silently go stale in the Bots panel."
    )


# ── Implicit data contracts (not symbols) ───────────────────────────────────

def test_bot_chat_session_title_literal_is_used_consistently():
    """'Bot Chat' is the session title the AGENT writes; the fork looks sessions
    up by it on both sides. If the agent ever renames it, all three of these
    have to move together."""
    assert "title = 'Bot Chat'" in (_ROOT / "api" / "bot_mesh.py").read_text(encoding="utf-8")
    assert "title = 'Bot Chat'" in (_ROOT / "api" / "bots_overview.py").read_text(encoding="utf-8")
    assert "S.session.title==='Bot Chat'" in (_STATIC / "ui.js").read_text(encoding="utf-8")


def test_process_wakeup_grammar_is_shared_between_server_and_front():
    """The quiet thread recognises imported wakeups by the notice text, because
    imported rows carry no _source marker. api/process_event_utils.py is where
    that grammar is pinned server-side."""
    server = (_ROOT / "api" / "process_event_utils.py").read_text(encoding="utf-8")
    assert r"\A\[IMPORTANT: Background process " in server
    assert "_MACHINE_NOTICE_RE" in (_STATIC / "ui.js").read_text(encoding="utf-8")


# ── Front-end: the host globals the fork's own files reach for ──────────────

def test_i18n_fork_merge_targets_still_exist():
    """i18n_fork.js assigns into LOCALES after i18n.js builds it, and relies on
    t() falling back to LOCALES.en for the 13 locales it does not translate."""
    i18n = (_STATIC / "i18n.js").read_text(encoding="utf-8")
    assert "const LOCALES = {" in i18n
    assert "LOCALES.en[key]" in i18n, "t() no longer falls back to English"
    assert "let _locale = LOCALES.en;" in i18n, (
        "_locale must stay a REFERENCE into LOCALES; i18n_fork.js mutates those "
        "objects in place after i18n.js has bound it."
    )


def test_fork_assets_are_loaded_and_precached():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    sw = (_STATIC / "sw.js").read_text(encoding="utf-8")
    for asset in ("static/bots_panel.js", "static/bots_panel.css", "static/i18n_fork.js",
                  "static/agent_drift.js"):
        assert asset in html, f"{asset} is not loaded by index.html"
        assert f"'./{asset}'" in sw, f"{asset} is missing from the service worker shell cache"
    # order matters: fork CSS after upstream CSS, i18n_fork after i18n
    assert html.index("static/style.css") < html.index("static/bots_panel.css")
    assert html.index("static/i18n.js") < html.index("static/i18n_fork.js")
    assert html.index("static/bots_panel.js") < html.index("static/panels.js?")


def test_host_hooks_the_fork_panel_calls_into():
    """bots_panel.js is a separate file but still calls host functions. These
    are the ones with no `typeof` guard at the call site."""
    panels = (_STATIC / "panels.js").read_text(encoding="utf-8")
    workspace = (_STATIC / "workspace.js").read_text(encoding="utf-8")
    assert "async function switchPanel(" in panels
    assert "function switchWorkspacePanelTab(" in workspace
    assert "let _workspacePanelActiveTab" in workspace or "_workspacePanelActiveTab =" in workspace
    assert 'id="messages"' in (_STATIC / "index.html").read_text(encoding="utf-8")
