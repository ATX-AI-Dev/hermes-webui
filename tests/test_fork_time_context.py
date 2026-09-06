"""Fork: the WebUI ephemeral prompt states the exact wall-clock time.

Upstream gives the model the date only and tells it to query a tool for the
hour; the free-tier models the bots run on skip that call and invent one (a bot
reported "06/09/2026 ~15:22 UTC" while the server clock read 10:22 UTC). These
tests pin the shape of the line and the fact that it reaches the prompt.
"""

from datetime import datetime, timedelta, timezone

from api.fork_time_context import webui_time_context_prompt
from api.streaming import _webui_ephemeral_system_prompt


def _paris_summer(hour, minute=22):
    return datetime(2026, 9, 6, hour, minute, tzinfo=timezone(timedelta(hours=2), "CEST"))


def test_states_both_local_and_utc():
    prompt = webui_time_context_prompt(_paris_summer(12))
    assert "Local: 2026-09-06 12:22 CEST (UTC+02:00)" in prompt
    assert "UTC: 2026-09-06 10:22Z" in prompt


def test_forbids_inventing_and_mislabelling_a_time():
    prompt = webui_time_context_prompt(_paris_summer(12))
    assert "never estimate or invent one" in prompt
    assert "never relabel a local time as UTC" in prompt


def test_prompt_is_ascii_only():
    # turn_recovery strips non-ASCII from the ephemeral prompt for some
    # providers; a localized %Z ("heure d'ete") would be mangled there.
    assert webui_time_context_prompt(_paris_summer(12)).isascii()


def test_utc_input_renders_without_a_zone_mismatch():
    prompt = webui_time_context_prompt(datetime(2026, 9, 6, 10, 22, tzinfo=timezone.utc))
    assert "Local: 2026-09-06 10:22 UTC (UTC+00:00)" in prompt
    assert "UTC: 2026-09-06 10:22Z" in prompt


def test_default_now_tracks_the_server_clock():
    now = datetime.now().astimezone()
    assert now.strftime("%Y-%m-%d %H:%M") in webui_time_context_prompt()


def test_line_reaches_the_ephemeral_system_prompt():
    prompt = _webui_ephemeral_system_prompt(None)
    assert "Current time (authoritative" in prompt
    # Upstream's own blocks are still there, unchanged.
    assert "WebUI progress guidance:" in prompt
