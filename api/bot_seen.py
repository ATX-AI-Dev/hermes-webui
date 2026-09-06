"""Jusqu'où Ludo a lu la conversation de chaque bot.

POURQUOI CÔTÉ SERVEUR ET PAS DANS LE NAVIGATEUR
-----------------------------------------------
Le panneau Bots affiche déjà l'aperçu du dernier message de chaque bot, mais
rien ne dit *si ce message est nouveau*. Sans repère, il faut ouvrir les dix-huit
conversations pour savoir laquelle a bougé.

Le repère aurait pu vivre dans ``localStorage``. Il vit ici parce que WebUI est
la porte d'entrée **depuis n'importe où** (téléphone, poste de dev, navigateur
d'emprunt) : un badge stocké dans le navigateur ferait réapparaître comme non
lus, sur le téléphone, des messages déjà lus sur le poste. Un compteur qui ment
selon l'appareil ne serait pas consulté longtemps.

    <HERMES_HOME>/webui/bot_seen.json   {"<profil>": {"count": n, "at": "<iso>"}}

Même emplacement et mêmes règles que ``bot_customization.json`` : écriture
atomique, lecture qui n'échoue jamais (store absent ou cassé ⇒ ``{}``).

L'UNITÉ DE MESURE
-----------------
``count`` est le nombre de lignes de la Bot Chat du bot dans son ``state.db``
agent-natif — le même compteur que ``bot_mesh.resync_bot_chat_if_stale`` utilise
déjà pour décider d'un ré-import. On compte donc des messages réels, pas des
notifications, et le compteur reste juste même quand un message arrive par une
autre surface (relais, cron, gateway).

DÉMARRAGE SILENCIEUX
--------------------
Un bot jamais ouvert n'a pas d'entrée. On ne veut PAS afficher d'un coup
dix-huit badges portant l'historique complet : au premier passage, la ligne de
base est posée au compte courant et le bot démarre à zéro non lu. C'est
``baseline_unseen_profiles`` qui le fait, appelé par la construction de l'aperçu.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _store_path() -> Path | None:
    """``<base Hermes home>/webui/bot_seen.json``, ou None si le home est illisible."""
    try:
        from api.profiles import _resolve_base_hermes_home
        return Path(_resolve_base_hermes_home()) / "webui" / "bot_seen.json"
    except Exception:
        logger.debug("bot_seen: could not resolve base Hermes home", exc_info=True)
        return None


def load_seen() -> dict:
    """Store entier. Ne lève jamais : un store cassé vaut un store vide."""
    path = _store_path()
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("bot_seen: unreadable store, treating as empty", exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _write_seen(data: dict) -> None:
    """Remplacement atomique : un crash en cours d'écriture ne laisse pas un
    store tronqué qui ferait repartir tous les compteurs de zéro."""
    path = _store_path()
    if path is None:
        raise RuntimeError("no Hermes home to write bot_seen to")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".bot_seen.", suffix=".json")
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


def _valid_profile(profile: str) -> str:
    from api.profiles import _PROFILE_ID_RE
    name = str(profile or "").strip()
    if not name or not _PROFILE_ID_RE.fullmatch(name):
        raise ValueError("invalid profile")
    return name


def seen_count(profile: str) -> int | None:
    """Compte lu pour ce bot, ou None s'il n'a jamais été vu."""
    entry = load_seen().get(str(profile or "").strip())
    if not isinstance(entry, dict):
        return None
    value = entry.get("count")
    return int(value) if isinstance(value, (int, float)) else None


def mark_seen(profile: str, count) -> dict:
    """Enregistre que ce bot est lu jusqu'à ``count`` lignes.

    Le compteur ne recule jamais : deux onglets ouverts sur le même bot, ou un
    marquage qui arrive après un autre plus récent, ne doivent pas ressusciter
    des non-lus déjà consommés.
    """
    name = _valid_profile(profile)
    try:
        value = max(0, int(count))
    except (TypeError, ValueError):
        raise ValueError("count must be an integer")
    data = load_seen()
    previous = data.get(name)
    if isinstance(previous, dict) and isinstance(previous.get("count"), (int, float)):
        value = max(value, int(previous["count"]))
    entry = {"count": value, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    data[name] = entry
    _write_seen(data)
    return entry


def baseline_unseen_profiles(counts_by_profile: dict) -> dict:
    """Pose la ligne de base des bots encore inconnus du store, et renvoie la
    table complète ``{profil: compte lu}``.

    Appelé par ``bots_overview.build_bots_overview``. Écrire pendant un GET n'est
    pas élégant, mais l'alternative l'est moins : sans ligne de base, la
    première ouverture du panneau afficherait dix-huit badges portant tout
    l'historique, et le badge serait mort-né. Une seule écriture par bot, la
    première fois qu'on le voit.
    """
    data = load_seen()
    added = False
    for name, count in (counts_by_profile or {}).items():
        if count is None:
            continue
        entry = data.get(name)
        if isinstance(entry, dict) and isinstance(entry.get("count"), (int, float)):
            continue
        data[name] = {
            "count": int(count),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "baseline": True,
        }
        added = True
    if added:
        try:
            _write_seen(data)
        except Exception:
            # Pas de ligne de base persistée : on renvoie quand même les valeurs
            # calculées, le panneau reste juste pour ce passage.
            logger.debug("bot_seen: could not persist baseline", exc_info=True)
    return {
        name: int(entry["count"])
        for name, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("count"), (int, float))
    }


def unread_for(total_count, seen) -> int:
    """Non-lus d'un bot : jamais négatif, jamais faux quand on ne sait pas.

    Un ``total_count`` inconnu (pas de Bot Chat, base illisible) vaut zéro non
    lu — un badge inventé serait pire que pas de badge.
    """
    if total_count is None:
        return 0
    try:
        total = int(total_count)
    except (TypeError, ValueError):
        return 0
    if seen is None:
        return 0
    try:
        return max(0, total - int(seen))
    except (TypeError, ValueError):
        return 0


def handle_post_seen(handler, body) -> bool:
    """POST /api/bots/seen — ``{"profile": "...", "count": n}``.

    Corps déporté hors de ``api/routes.py`` (deux lignes d'aiguillage là-bas) et
    imports de ``j``/``bad`` faits dans la fonction : ``api.routes`` importe ce
    module au moment de l'aiguillage, un import au niveau module serait
    circulaire. Même patron que ``bot_customization`` et ``bots_overview``.
    """
    from api.helpers import j
    from api.routes import bad, _sanitize_error
    if not isinstance(body, dict):
        return bad(handler, "Request body must be a JSON object")
    try:
        entry = mark_seen(body.get("profile"), body.get("count"))
    except ValueError as exc:
        return bad(handler, str(exc))
    except Exception as exc:
        logger.exception("bot seen write failed")
        return bad(handler, _sanitize_error(exc), status=500)
    try:
        from api import bots_overview
        bots_overview.invalidate_cache()
    except Exception:
        logger.debug("bot_seen: could not invalidate the overview cache", exc_info=True)
    return j(handler, {"ok": True, "profile": str(body.get("profile")), **entry})
