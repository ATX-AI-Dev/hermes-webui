"""Les canaux inter-bots autorisés — et qui ne les respecte pas.

CE QUE CE MODULE FAIT, ET SURTOUT CE QU'IL NE FAIT PAS
------------------------------------------------------
Ludo a spécifié le 03/09/2026 quels bots ont le droit de se parler
(``infra/hermes-communication-paths.md`` dans le vault) : 26 arêtes entre bots,
dont 4 seules passerelles vers la branche Perso, et aucun lien direct
Lancelot ↔ Guenièvre — la coordination Pro/Perso passe par le Pilote.

**Ce module détecte ; il n'empêche rien.** L'application, elle, vit ailleurs :
dans un patch local de l'agent (``~/.hermes/local-patches/kingdom-channels.patch``,
rejoué après chaque ``hermes update``), posé le 06/09/2026 après que la mesure
ci-dessous a tranché. Les deux lisent **la même carte**, ce fichier-ci.

Chronologie, parce qu'elle explique la forme du code : l'amont
(``tools/bot_mode_dm.py``) valide la cible contre le roster COMPLET
(``resolved = _resolve_local_name(raw_target, roster)``) et présente au modèle
tous les autres bots comme des « teammates ». Ludo a d'abord demandé de mesurer
(option A) plutôt que de verrouiller à l'aveugle : une allowlist posée sans
observation aurait pu casser des chaînes qui marchent — la remontée du changelog
`Venec → Lancelot → Roi Arthur`, ou les contacts directs de Merlin autorisés
depuis le 05/09. **La mesure a donné 8 échanges hors spec sur 133 relais**, tous
sur un seul axe (des bots écrivant directement au Pilote), et Ludo a décidé de
faire respecter la hiérarchie.

Ce module reste **strictement en lecture** : l'audit ne bloque rien, n'écrit rien
et ne lance aucun processus (test ``test_audit_is_read_only``). C'est ce qui
permet de continuer à mesurer — y compris ce que l'application laisse encore
passer, puisqu'elle est fail-open sur les couples inconnus.

LECTURE BIDIRECTIONNELLE
------------------------
Une arête déclarée d'un côté vaut des deux. La carte se vérifie elle-même au
chargement : si un seul côté cite l'autre, c'est une faute de frappe, et la
tolérance silencieuse ferait passer un canal interdit pour autorisé.

COÛT
----
``audit_relays`` scanne les Bot Chats — c'est cher comparé au reste du panneau,
qui ne lit que les huit dernières lignes par bot. D'où une route séparée,
déclenchée à la demande, et non un compteur recalculé à chaque poll de 15 s.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_BUNDLED = Path(__file__).with_name("bots_hierarchy.json")


def _load_raw() -> dict:
    """Carte des canaux, copie opérateur prioritaire, comme la hiérarchie.

    Ne lève jamais : sans carte lisible, ``is_allowed`` renvoie ``None``
    (« on ne sait pas ») partout, et l'audit ne signale rien plutôt que de
    signaler à tort.
    """
    from api.bots_overview import _operator_hierarchy_path
    for path in (_operator_hierarchy_path(), _BUNDLED):
        if path is None or not Path(path).exists():
            continue
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            logger.debug("bot_channels: unreadable map at %s", path, exc_info=True)
            continue
        channels = data.get("channels")
        if isinstance(channels, dict) and isinstance(channels.get("allowed"), dict):
            return channels
    return {}


def load_channels() -> dict:
    """``{"allowed": {bot: [pairs]}, "wildcard_senders": {bot: raison}}``, normalisé."""
    raw = _load_raw()
    allowed_raw = raw.get("allowed") or {}
    allowed: dict[str, set] = {}
    for name, peers in allowed_raw.items():
        if isinstance(peers, list):
            allowed[str(name)] = {str(p) for p in peers}
    wildcards = raw.get("wildcard_senders") or {}
    return {
        "allowed": allowed,
        "wildcard_senders": {str(k): str(v) for k, v in wildcards.items()} if isinstance(wildcards, dict) else {},
    }


def map_inconsistencies(channels: dict | None = None) -> list[str]:
    """Arêtes déclarées d'un seul côté. Une carte saine renvoie une liste vide.

    Exposé (et testé) plutôt que caché dans un ``assert`` : c'est le seul garde-fou
    contre une carte à moitié éditée, dont la lecture bidirectionnelle ferait
    passer un canal pour autorisé alors qu'il ne l'est que dans un sens.
    """
    ch = channels or load_channels()
    allowed = ch["allowed"]
    problems = []
    for a, peers in allowed.items():
        for b in peers:
            if b not in allowed:
                problems.append(f"{a} cite {b}, qui n'est pas dans la carte")
            elif a not in allowed[b]:
                problems.append(f"arête {a}–{b} déclarée uniquement du côté de {a}")
    return sorted(set(problems))


def is_allowed(sender: str, target: str, channels: dict | None = None):
    """``True`` autorisé, ``False`` hors spec, ``None`` si on ne peut pas trancher.

    ``None`` couvre les cas où juger serait malhonnête : carte absente, ou un des
    deux bots hors carte (profil créé après la spec, cible sur une machine pair).
    Un badge « hors spec » sur un bot simplement inconnu ferait perdre confiance
    dans tous les autres.
    """
    ch = channels or load_channels()
    allowed = ch["allowed"]
    a, b = str(sender or "").strip(), str(target or "").strip()
    if not allowed or not a or not b:
        return None
    if a == b:
        return None  # un bot ne se parle pas à lui-même ; l'agent le refuse déjà
    if a in ch["wildcard_senders"]:
        return True
    if a not in allowed or b not in allowed:
        return None
    return b in allowed[a] or a in allowed.get(b, set())


def classify_relay(sender: str, target: str, channels: dict | None = None) -> dict:
    """Verdict prêt à sérialiser pour une carte de relais du fil Bot Chat."""
    verdict = is_allowed(sender, target, channels)
    return {"channel_ok": verdict, "channel_target": str(target or "").strip() or None}


# ── Audit : qui a parlé à qui, en dehors de la spec ─────────────────────────

def _relay_targets_for_profile(profile: str, since_epoch: float | None) -> list[dict]:
    """``[{target, timestamp}]`` des appels message_agent d'un bot. Best-effort."""
    from api.bot_mesh import (
        _parse_tool_calls, _relay_call_from_tool_calls, find_bot_chat_session, profile_db_path,
    )
    session = find_bot_chat_session(profile)
    if session is None:
        return []
    db_path = profile_db_path(profile)
    if db_path is None:
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT tool_calls, timestamp FROM messages "
                "WHERE session_id = ? AND role = 'assistant' AND tool_calls IS NOT NULL "
                "ORDER BY id DESC LIMIT 2000",
                (session["session_id"],),
            ).fetchall()
        finally:
            con.close()
    except Exception:
        logger.debug("bot_channels: relay scan failed for %s", profile, exc_info=True)
        return []

    out = []
    for tool_calls_raw, ts in rows:
        if since_epoch is not None and isinstance(ts, (int, float)) and ts < since_epoch:
            continue
        relay = _relay_call_from_tool_calls(_parse_tool_calls(tool_calls_raw))
        target = (relay or {}).get("target")
        if target:
            out.append({"target": str(target).lstrip("@"), "timestamp": ts})
    return out


def audit_relays(profiles: list[str], *, days: int = 7) -> dict:
    """Combien d'échanges hors spec, par bot, sur la fenêtre demandée.

    Renvoie ``{"days", "since", "checked", "violations": [...],
    "by_profile": {p: {"total", "out_of_spec", "unknown"}}, "map_problems": [...]}``.
    Lecture seule de bout en bout : aucun envoi n'est modifié ni empêché.
    """
    channels = load_channels()
    since = time.time() - days * 86400 if days else None
    by_profile: dict[str, dict] = {}
    violations: list[dict] = []

    for profile in profiles:
        calls = _relay_targets_for_profile(profile, since)
        stats = {"total": 0, "out_of_spec": 0, "unknown": 0}
        for call in calls:
            stats["total"] += 1
            verdict = is_allowed(profile, call["target"], channels)
            if verdict is False:
                stats["out_of_spec"] += 1
                violations.append({
                    "sender": profile,
                    "target": call["target"],
                    "timestamp": call["timestamp"],
                })
            elif verdict is None:
                stats["unknown"] += 1
        if stats["total"]:
            by_profile[profile] = stats

    violations.sort(key=lambda v: (v["timestamp"] or 0), reverse=True)
    return {
        "days": days,
        "since": since,
        "checked": len(profiles),
        "violations": violations[:200],
        "violation_count": len(violations),
        "by_profile": by_profile,
        "map_problems": map_inconsistencies(channels),
    }


def handle_get_audit(handler, parsed) -> bool:
    """GET /api/bot-channels/audit?days=7 — audit à la demande.

    Corps hors de ``api/routes.py`` (aiguillage de deux lignes là-bas), imports
    de ``j``/``bad`` dans la fonction pour la même raison de circularité que les
    autres modules du fork.
    """
    from urllib.parse import parse_qs
    from api.helpers import j
    from api.routes import bad, _sanitize_error
    try:
        raw_days = (parse_qs(parsed.query).get("days", ["7"])[0] or "7").strip()
        try:
            days = max(0, min(365, int(raw_days)))
        except ValueError:
            return bad(handler, "days must be an integer")
        from api.bots_overview import build_bots_overview
        profiles = [b["id"] for b in build_bots_overview().get("bots", []) if b.get("has_bot_chat")]
        return j(handler, audit_relays(profiles, days=days))
    except Exception as exc:
        logger.exception("bot channel audit failed")
        return bad(handler, _sanitize_error(exc), status=500)
