"""Detect that Hermes Agent was updated under a running WebUI, and offer a restart.

Fork-only module (ATX-AI-Dev/hermes-webui).

WebUI runs on the agent's venv and imports the agent **in-process**
(``run_agent``, ``hermes_cli``). When ``hermes update`` pulls new agent code,
the gateways are restarted but this process is not — it keeps executing the
modules it imported at startup. Behaviour then quietly diverges between the
bots (new code) and WebUI (old code), which is the kind of gap that produces a
mystifying bug report days later.

On the production host the agent auto-updates hourly while WebUI, being a fork,
is deployed by hand — so this is not a corner case, it is the normal state of
affairs after any agent release (decision of 05/09/2026, see the vault note
``infra/hermes-webui.md``). This module makes the gap visible and one click away
from being fixed.

The restart itself is upstream's: ``api.updates._schedule_restart()`` re-execs
the process with ``os.execv``, so nothing here needs root, systemd, or a new
process — the PID and the listening socket are kept. ``_wait_until_restart_safe``
drains in-flight streams first. Neither is reimplemented here.
"""

from __future__ import annotations

import logging
import subprocess
import threading

logger = logging.getLogger(__name__)


def _agent_dir():
    try:
        from api.config import _AGENT_DIR
        return _AGENT_DIR
    except Exception:
        return None


def agent_sha() -> str | None:
    """HEAD of the agent checkout, or None when it can't be read.

    The SHA, not ``_detect_agent_version()``: the version string can stay put
    across commits (it reads a VERSION file when there is one), and what
    matters here is "did the code on disk move", not "did the release number
    change".
    """
    path = _agent_dir()
    if not path:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return (out.stdout or "").strip() or None
    except Exception:
        logger.debug("agent_drift: could not read the agent SHA", exc_info=True)
        return None


# The SHA this process started on. Captured at import — api/routes.py imports
# this module at startup precisely so the capture happens then and not on the
# first HTTP hit, which could land after an update and miss the drift. os.execv
# replaces the process image, so a restart naturally re-captures.
_STARTED_WITH: str | None = agent_sha()

_restarting = threading.Event()


def drift_status() -> dict:
    """What the banner needs, in one call. Never raises."""
    current = agent_sha()
    drifted = bool(_STARTED_WITH and current and _STARTED_WITH != current)
    payload = {
        "drifted": drifted,
        "started_with": _STARTED_WITH,
        "current": current,
        "restarting": _restarting.is_set(),
    }
    try:
        from api.updates import _detect_agent_version
        payload["agent_version"] = _detect_agent_version()
    except Exception:
        payload["agent_version"] = None
    return payload


def _restart_worker() -> None:
    """Drain in-flight work, then re-exec. Runs off the request thread."""
    try:
        from api.updates import _schedule_restart, _wait_until_restart_safe
        snapshot = _wait_until_restart_safe()
        if snapshot.get("wait_timed_out"):
            logger.warning("agent_drift: restarting with work still in flight (%s)", snapshot)
        _schedule_restart(delay=1.0)
    except Exception:
        logger.exception("agent_drift: restart failed")
        _restarting.clear()


def request_restart() -> dict:
    """Start the restart and return immediately.

    ``_wait_until_restart_safe`` blocks for up to 300s, so it must not run on
    the request thread — the caller would sit on an open socket that the
    ``os.execv`` is about to kill anyway. The client polls ``drift_status`` and
    reloads once the process comes back.
    """
    if _restarting.is_set():
        return {"ok": True, "already": True}
    _restarting.set()
    threading.Thread(target=_restart_worker, name="agent-drift-restart", daemon=True).start()
    blockers = {}
    try:
        from api.updates import _restart_blocker_snapshot
        blockers = _restart_blocker_snapshot()
    except Exception:
        logger.debug("agent_drift: blocker snapshot unavailable", exc_info=True)
    return {"ok": True, "blockers": blockers}


# ── HTTP handlers ───────────────────────────────────────────────────────────
# Bodies live here, not in api/routes.py, so the fork's footprint in that
# upstream file stays a two-line dispatch — see FORK-CHANGES.md. j/bad are
# imported inside the functions because api.routes imports this module.


def handle_get_drift(handler, parsed) -> bool:
    """GET /api/agent-drift."""
    from api.helpers import j
    from api.routes import bad, _sanitize_error
    try:
        return j(handler, drift_status())
    except Exception as exc:
        logger.exception("agent drift status failed")
        return bad(handler, _sanitize_error(exc), status=500)


def handle_post_restart(handler, body) -> bool:
    """POST /api/agent-drift/restart — re-exec this WebUI process."""
    from api.helpers import j
    from api.routes import bad, _sanitize_error
    try:
        return j(handler, request_restart())
    except Exception as exc:
        logger.exception("agent drift restart failed")
        return bad(handler, _sanitize_error(exc), status=500)
