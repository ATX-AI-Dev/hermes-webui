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


# ── HTTP handlers ───────────────────────────────────────────────────────────
#
# The bodies live here, not in api/routes.py, so the fork's footprint in that
# (very large, very hot) upstream file stays a two-line dispatch per route —
# see FORK-CHANGES.md. `j`, `bad` and `_sanitize_error` are imported inside the
# functions because api.routes imports this module at dispatch time; a
# module-level import would be circular.


def handle_get_avatar(handler, parsed) -> bool:
    """GET /api/bots/avatar?profile= — serve one bot's stored picture."""
    from urllib.parse import parse_qs
    from api.helpers import j  # noqa: F401  (kept for symmetry with the writers)
    from api.routes import bad, _sanitize_error
    try:
        found = avatar_file((parse_qs(parsed.query).get("profile", [""])[0] or "").strip())
        if found is None:
            return bad(handler, "not found", 404)
        path, mime = found
        data = path.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", mime)
        handler.send_header("Content-Length", str(len(data)))
        # The URL carries an mtime stamp, so a stored avatar is immutable for a
        # given URL and safe to cache hard.
        handler.send_header("Cache-Control", "private, max-age=86400")
        handler.end_headers()
        handler.wfile.write(data)
        return True
    except Exception as exc:
        logger.exception("bot avatar read failed")
        return bad(handler, _sanitize_error(exc), status=500)


def handle_post_customization(handler, body) -> bool:
    """POST /api/bots/customization — set the display name, or drop the picture."""
    from api.helpers import j
    from api.routes import bad, _sanitize_error
    from api.bots_overview import invalidate_cache
    try:
        profile = str((body or {}).get("profile") or "").strip()
        entry = get_customization(profile)
        if "display_name" in (body or {}):
            entry = set_display_name(profile, body.get("display_name"))
        if (body or {}).get("clear_avatar"):
            entry = clear_avatar(profile)
        invalidate_cache()  # the panel polls /api/bots; don't serve a stale card
        return j(handler, {"ok": True, "profile": profile, "customization": entry})
    except ValueError as exc:
        return bad(handler, str(exc), 400)
    except Exception as exc:
        logger.exception("bot customization write failed")
        return bad(handler, _sanitize_error(exc), status=500)


def handle_post_avatar(handler) -> bool:
    """POST /api/bots/avatar — store one bot's picture (multipart).

    Reuses api.upload.parse_multipart, the same parser behind /api/upload, so
    there is one multipart implementation in the process. The size and format
    guards live in save_avatar, which sniffs the bytes rather than trusting the
    uploaded filename.
    """
    from api.helpers import j
    from api.routes import bad, _sanitize_error
    from api.bots_overview import invalidate_cache
    from api.upload import parse_multipart
    try:
        content_type = handler.headers.get("Content-Type", "")
        content_length = int(handler.headers.get("Content-Length", 0) or 0)
        if content_length > MAX_AVATAR_BYTES:
            return bad(handler, f"image too large (max {MAX_AVATAR_BYTES // 1024 // 1024}MB)", 413)
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        if "file" not in files:
            return bad(handler, "No file field in request", 400)
        entry = save_avatar(str(fields.get("profile") or "").strip(), files["file"][1])
        invalidate_cache()  # the panel polls /api/bots; don't serve a stale card
        return j(handler, {"ok": True, "customization": entry})
    except ValueError as exc:
        return bad(handler, str(exc), 400)
    except Exception as exc:
        logger.exception("bot avatar upload failed")
        return bad(handler, _sanitize_error(exc), status=500)
