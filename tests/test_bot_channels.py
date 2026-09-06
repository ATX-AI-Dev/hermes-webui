"""E1a — détection des échanges inter-bots hors spec (api/bot_channels.py).

Ludo a spécifié le 03/09/2026 quels bots ont le droit de se parler. Rien ne
l'applique : côté agent, `message_agent` valide la cible contre le roster
COMPLET et présente au modèle tous les autres bots comme des « teammates ».

Décision du 06/09/2026 (écart E1, option A) : **mesurer avant de verrouiller**.
Ces tests garantissent donc deux choses opposées et également importantes :

* la détection dit vrai quand elle accuse — une allowlist qu'on croit fausse ne
  sert à rien, et une accusation à tort ferait ignorer toutes les autres ;
* la détection **n'empêche jamais rien**. Le jour où quelqu'un transformera
  cette carte en garde-fou, ce sera une décision explicite, pas un effet de bord.

La carte elle-même est vérifiée : une arête déclarée d'un seul côté est une
faute de frappe, et la lecture bidirectionnelle la ferait passer pour un canal
autorisé.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def channels(monkeypatch):
    """Carte réelle du dépôt (pas une carte de test) : c'est elle qui compte."""
    from api import bots_overview, bot_channels
    monkeypatch.setattr(bots_overview, "_operator_hierarchy_path", lambda: None)
    return bot_channels.load_channels()


# ── La carte livrée ─────────────────────────────────────────────────────────

def test_shipped_map_is_self_consistent(channels):
    from api.bot_channels import map_inconsistencies
    assert map_inconsistencies(channels) == []


def test_shipped_map_has_the_26_bot_to_bot_edges(channels):
    """Le vault annonce 30 canaux : 26 entre bots + 4 canaux Ludo↔bot, qui ne
    passent pas par `message_agent` et n'ont donc rien à faire ici."""
    edges = {
        tuple(sorted((a, b)))
        for a, peers in channels["allowed"].items()
        for b in peers
    }
    assert len(edges) == 26, sorted(edges)


# ── Les règles qui comptent vraiment ────────────────────────────────────────

@pytest.mark.parametrize(("sender", "target", "expected", "why"), [
    ("lancelot", "guenievre", False,
     "aucun lien direct entre managers Pro et Perso — la coordination passe par le Pilote"),
    ("guenievre", "lancelot", False, "idem dans l'autre sens"),
    ("venec", "guenievre", False, "canal veille→Perso retiré par l'amendement du 03/09/2026"),
    ("angharad", "sefriane", False, "deux bots Perso passent par leur manager"),
    ("lancelot", "yvain", False, "Yvain n'est atteint que par Perceval"),
    ("lancelot", "le-repurgateur", False, "le Répurgateur ne parle qu'à Perceval"),
    ("roi-arthur", "pere-blaise", False, "le Pilote ne descend jamais dans une branche"),
    ("lancelot", "perceval", True, "canal Pro normal"),
    ("perceval", "yvain", True, "Perceval est le manager direct de Yvain"),
    ("leodagan", "guenievre", True, "passerelle Intendance → Perso, sanctionnée"),
    ("pere-blaise", "maitre-darmes", True, "Intendance entre eux"),
    ("venec", "lancelot", True, "la chaîne du changelog doit rester autorisée"),
])
def test_spec_rules(channels, sender, target, expected, why):
    from api.bot_channels import is_allowed
    assert is_allowed(sender, target, channels) is expected, why


def test_merlin_may_contact_anyone(channels):
    """Règle assouplie le 05/09/2026 : Ludo a choisi d'élargir la règle plutôt
    que de corriger le comportement de Merlin. La détection doit suivre cette
    décision, sinon elle signalerait comme fautif un usage voulu."""
    from api.bot_channels import is_allowed
    for target in ("lancelot", "gauvain", "sefriane", "le-repurgateur"):
        assert is_allowed("merlin", target, channels) is True


@pytest.mark.parametrize(("sender", "target"), [
    ("lancelot", "un-nouveau-bot"),
    ("un-nouveau-bot", "lancelot"),
    ("lancelot", ""),
    ("lancelot", "lancelot"),
])
def test_unknown_pairs_are_not_accused(channels, sender, target):
    """Un bot hors carte (créé après la spec, ou sur une machine pair) donne
    « on ne sait pas », jamais « hors spec » : un badge injuste sur un bot
    inconnu ferait perdre confiance dans tous les autres."""
    from api.bot_channels import is_allowed
    assert is_allowed(sender, target, channels) is None


def test_no_map_means_no_verdict(monkeypatch):
    from api import bot_channels
    monkeypatch.setattr(bot_channels, "_load_raw", lambda: {})
    assert bot_channels.is_allowed("lancelot", "guenievre") is None


def test_one_sided_edge_is_reported_not_silently_accepted():
    from api.bot_channels import map_inconsistencies
    broken = {"allowed": {"a": {"b"}, "b": set()}, "wildcard_senders": {}}
    assert map_inconsistencies(broken) == ["arête a–b déclarée uniquement du côté de a"]


# ── Audit ───────────────────────────────────────────────────────────────────

def test_audit_counts_violations_per_bot(monkeypatch, channels):
    from api import bot_channels

    calls = {
        "lancelot": [{"target": "guenievre", "timestamp": 100},   # hors spec
                     {"target": "perceval", "timestamp": 101}],   # conforme
        "venec": [{"target": "lancelot", "timestamp": 102}],      # conforme
        "angharad": [{"target": "sefriane", "timestamp": 103}],   # hors spec
    }
    monkeypatch.setattr(bot_channels, "_relay_targets_for_profile",
                        lambda profile, since: calls.get(profile, []))

    report = bot_channels.audit_relays(["lancelot", "venec", "angharad"], days=7)
    assert report["violation_count"] == 2
    assert report["by_profile"]["lancelot"] == {"total": 2, "out_of_spec": 1, "unknown": 0}
    assert report["by_profile"]["venec"]["out_of_spec"] == 0
    assert {v["sender"] for v in report["violations"]} == {"lancelot", "angharad"}
    assert report["map_problems"] == []


def test_audit_is_read_only(monkeypatch, channels):
    """Garde-fou de conception : l'audit ne doit jamais rien envoyer ni écrire.

    Si quelqu'un transforme un jour la détection en blocage, ce sera une
    décision assumée — pas un module qui s'est mis à agir tout seul.
    """
    import subprocess
    from api import bot_channels

    def _boom(*a, **k):
        raise AssertionError("l'audit a tenté de lancer un processus")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(bot_channels, "_relay_targets_for_profile",
                        lambda profile, since: [{"target": "guenievre", "timestamp": 1}])
    report = bot_channels.audit_relays(["lancelot"], days=7)
    assert report["violation_count"] == 1

    source = __import__("pathlib").Path(bot_channels.__file__).read_text(encoding="utf-8")
    for forbidden in ("hermes send", "message_agent(", "_write", "os.remove"):
        assert forbidden not in source, f"api/bot_channels.py contient {forbidden!r}"


# ── Le verdict remonte bien dans le fil ─────────────────────────────────────

def test_transcript_tags_relay_turns(monkeypatch, channels):
    """La carte de relais du fil Bot Chat porte le verdict, sans quoi la
    détection resterait invisible là où elle est la plus parlante."""
    from api import bot_mesh
    verdict = bot_mesh._channel_verdict("lancelot", "guenievre", channels)
    assert verdict["channel_ok"] is False
    assert verdict["channel_target"] == "guenievre"


def test_transcript_survives_a_missing_channel_module(monkeypatch):
    """Sans carte, le fil s'affiche exactement comme avant l'ajout."""
    from api import bot_mesh
    assert bot_mesh._channel_verdict("lancelot", "guenievre", None) == {
        "channel_ok": None, "channel_target": "guenievre",
    }


def test_front_shows_the_off_spec_badge_and_audit_button():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "static"
    js = (static / "bots_panel.js").read_text(encoding="utf-8", errors="replace")
    assert "turn.channel_ok === false" in js, "le fil n'affiche pas le verdict"
    assert "/api/bot-channels/audit" in js
    css = (static / "bots_panel.css").read_text(encoding="utf-8", errors="replace")
    assert ".bots-relay-offspec" in css and ".bots-audit" in css
