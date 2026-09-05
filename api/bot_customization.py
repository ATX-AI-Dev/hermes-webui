"""Per-bot display name and profile picture, chosen by the user.

Iteration 2 of the Bots panel. ``bots_hierarchy.json`` describes the *org* —
which branch a bot belongs to, who its manager is, what its role is, plus a
declared emoji/colour — and is a fork-local file an operator edits by hand,
with a copy at ``<HERMES_HOME>/webui/bots_hierarchy.json`` overriding the
bundled one. What the user picks for themselves is a different thing with a
different lifecycle: it is written from the UI, one bot at a time, and it must
survive an update of the bundled hierarchy. Hence a separate store, next to the
operator hierarchy override:

    <HERMES_HOME>/webui/bot_customization.json   {"<profile>": {...}}
    <HERMES_HOME>/webui/bot_avatars/<profile>.<ext>

Read paths never raise: a missing or broken store yields ``{}`` and the panel
falls back to the hierarchy's emoji/colour, the same tolerance
``bots_overview._load_hierarchy`` already applies to a broken hierarchy file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_DISPLAY_NAME_CHARS = 64

# Extension per accepted image type. The type is decided by sniffing the
# bytes, never by trusting the uploaded filename: these files are served back
# to the browser, so the extension must describe what is actually there.
_IMAGE_SNIFFERS: tuple[tuple[str, "callable"], ...] = (
    ("png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    ("jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
    ("gif", lambda b: b.startswith(b"GIF87a") or b.startswith(b"GIF89a")),
    ("webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
)
_MIME_BY_EXT = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def _webui_dir() -> Path | None:
    """``<base Hermes home>/webui``, or None when the home can't be resolved."""
    try:
        from api.profiles import _resolve_base_hermes_home
        return Path(_resolve_base_hermes_home()) / "webui"
    except Exception:
        logger.debug("bot_customization: could not resolve base Hermes home", exc_info=True)
        return None


def _store_path() -> Path | None:
    base = _webui_dir()
    return None if base is None else base / "bot_customization.json"


def _avatar_dir() -> Path | None:
    base = _webui_dir()
    return None if base is None else base / "bot_avatars"


def _valid_profile(profile: str) -> str:
    """Return the profile name, or raise ValueError.

    Reuses upstream's profile id pattern, which is also what the routes use to
    validate ``profile`` before it reaches any filesystem path — an avatar file
    is named after the profile, so nothing but a validated id may get there.
    """
    from api.profiles import _PROFILE_ID_RE
    name = str(profile or "").strip()
    if not name or not _PROFILE_ID_RE.fullmatch(name):
        raise ValueError("invalid profile")
    return name


def _clean_display_name(value) -> str:
    name = " ".join(str(value or "").split())  # collapses whitespace, drops control chars
    return name[:MAX_DISPLAY_NAME_CHARS]


def load_customization() -> dict:
    """The whole store, or ``{}``. Never raises."""
    path = _store_path()
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("bot_customization: %s is not valid JSON; ignoring", path)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)}


def _write_store(data: dict) -> None:
    """Atomic replace, so a crash mid-write can't leave a truncated store."""
    path = _store_path()
    if path is None:
        raise RuntimeError("no Hermes home to write bot customization to")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".bot_customization.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_customization(profile: str) -> dict:
    return load_customization().get(str(profile or "").strip()) or {}


def set_display_name(profile: str, display_name) -> dict:
    """Set (or, with an empty value, clear) one bot's display name."""
    name = _valid_profile(profile)
    data = load_customization()
    entry = dict(data.get(name) or {})
    cleaned = _clean_display_name(display_name)
    if cleaned:
        entry["display_name"] = cleaned
    else:
        entry.pop("display_name", None)
    return _store_entry(data, name, entry)


def _store_entry(data: dict, name: str, entry: dict) -> dict:
    if entry:
        data[name] = entry
    else:
        data.pop(name, None)
    _write_store(data)
    return entry


def save_avatar(profile: str, file_bytes: bytes) -> dict:
    """Store one bot's profile picture and return its customization entry.

    The image type comes from sniffing ``file_bytes``; an upload that isn't one
    of the accepted formats is rejected rather than stored under a filename
    that would lie about its content.
    """
    name = _valid_profile(profile)
    if not file_bytes:
        raise ValueError("empty file")
    if len(file_bytes) > MAX_AVATAR_BYTES:
        raise ValueError(f"image too large (max {MAX_AVATAR_BYTES // 1024 // 1024}MB)")
    ext = next((e for e, sniff in _IMAGE_SNIFFERS if sniff(file_bytes)), None)
    if ext is None:
        raise ValueError("unsupported image format (PNG, JPEG, GIF or WebP)")

    directory = _avatar_dir()
    if directory is None:
        raise RuntimeError("no Hermes home to write bot avatars to")
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{name}.{ext}"
    (directory / filename).write_bytes(file_bytes)
    # One avatar per bot: drop any file left over from a previous format.
    for stale in directory.glob(f"{name}.*"):
        if stale.name != filename:
            try:
                stale.unlink()
            except OSError:
                logger.debug("bot_customization: could not remove %s", stale, exc_info=True)

    data = load_customization()
    entry = dict(data.get(name) or {})
    entry["avatar"] = filename
    return _store_entry(data, name, entry)


def clear_avatar(profile: str) -> dict:
    name = _valid_profile(profile)
    directory = _avatar_dir()
    if directory is not None:
        for stale in directory.glob(f"{name}.*"):
            try:
                stale.unlink()
            except OSError:
                logger.debug("bot_customization: could not remove %s", stale, exc_info=True)
    data = load_customization()
    entry = dict(data.get(name) or {})
    entry.pop("avatar", None)
    return _store_entry(data, name, entry)


def avatar_file(profile: str) -> tuple[Path, str] | None:
    """``(path, mime)`` for one bot's stored avatar, or None. Never raises."""
    try:
        name = _valid_profile(profile)
    except Exception:
        return None
    entry = get_customization(name)
    filename = entry.get("avatar")
    directory = _avatar_dir()
    if not filename or directory is None:
        return None
    # The stored name is always "<validated profile>.<known ext>"; rebuild it
    # instead of trusting the stored string as a path component.
    ext = str(filename).rsplit(".", 1)[-1].lower()
    if ext not in _MIME_BY_EXT:
        return None
    path = directory / f"{name}.{ext}"
    if not path.exists():
        return None
    return path, _MIME_BY_EXT[ext]


def avatar_url(profile: str, entry: dict | None = None) -> str | None:
    """Browser URL for one bot's avatar, with a cache-busting stamp, or None."""
    entry = entry if entry is not None else get_customization(profile)
    if not entry.get("avatar"):
        return None
    found = avatar_file(profile)
    if found is None:
        return None
    try:
        stamp = int(found[0].stat().st_mtime)
    except OSError:
        stamp = 0
    from urllib.parse import quote
    return f"/api/bots/avatar?profile={quote(str(profile))}&v={stamp}"
