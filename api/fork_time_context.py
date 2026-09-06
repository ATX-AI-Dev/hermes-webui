"""Wall-clock context for WebUI turns — fork-only (ATX-AI-Dev/hermes-webui).

Upstream's ``agent/system_prompt.py`` injects the **date only**, on purpose: the
line is byte-stable for the whole day so the cached system prefix survives, and
it tells the model to "query tools for exact time". Weaker models (the free
OpenRouter tier the bots run on) never make that tool call — they invent an hour
instead, and then present it as fact ("Heures d'envoi (UTC) : 06/09/2026
~15:22"), which is how a bot ends up reporting a time three hours off.

So the fork states the time instead of hoping for a tool call. The line is
appended to the WebUI ephemeral system prompt, which the agent injects at
API-call time and never persists to history.

Known cost: minute precision means the system block changes between turns more
than a minute apart, so the prompt prefix cache is dropped for those turns.
Deliberate trade-off — a wrong hour asserted with confidence is worse than a
cache miss. See FORK-CHANGES.md ("Heure exacte dans le prompt WebUI").
"""

from __future__ import annotations

from datetime import datetime, timezone


def _zone_label(now: datetime) -> str:
    """``CEST (UTC+02:00)`` — abbreviation plus offset, both from the local
    clock.

    ``%Z`` is a short ASCII abbreviation on the server (Linux: ``CEST``) but a
    long localized name on a Windows dev box ("Paris, Madrid (heure d'ete)").
    Only the short ASCII form is kept: the offset carries the meaning, and the
    prompt stays ASCII (``turn_recovery`` strips non-ASCII from the ephemeral
    prompt for some providers, which would mangle a localized name)."""
    abbrev = now.strftime("%Z")
    if not (abbrev.isascii() and abbrev.isalpha() and len(abbrev) <= 5):
        abbrev = ""
    offset = now.strftime("%z")  # '+0200' -> 'UTC+02:00'
    pretty_offset = f"UTC{offset[:3]}:{offset[3:]}" if offset else ""
    bits = [bit for bit in (abbrev, pretty_offset and f"({pretty_offset})") if bit]
    return " ".join(bits)


def webui_time_context_prompt(now: datetime | None = None) -> str:
    """Return the authoritative wall-clock block for the ephemeral prompt.

    ``now`` is injectable for tests; by default the server's local time is used
    (the same clock the agent runs on — WebUI and the agent share the host).
    """
    local = now if now is not None else datetime.now().astimezone()
    utc = local.astimezone(timezone.utc)
    zone = _zone_label(local)
    # Numeric format on purpose: %A/%B are locale-dependent (and non-ASCII under
    # a French locale), while the ISO-like shape reads the same everywhere.
    local_line = local.strftime('%Y-%m-%d %H:%M') + (f" {zone}" if zone else "")
    return "\n".join([
        "Current time (authoritative - supplied by the server clock at request time):",
        f"- Local: {local_line}",
        f"- UTC: {utc.strftime('%Y-%m-%d %H:%M')}Z",
        "- Use these values whenever you state, compute, or compare a time; never estimate or "
        "invent one, and never relabel a local time as UTC.",
        "- Say which zone you are using. They are accurate to the minute as of the start of this "
        "turn; a long turn may have moved on, so re-read the clock with a tool before claiming a "
        "later time.",
    ])
