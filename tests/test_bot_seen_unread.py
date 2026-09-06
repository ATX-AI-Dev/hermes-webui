"""E3 — badge « non lu » par bot (api/bot_seen.py + /api/bots).

Le panneau Bots affichait déjà l'aperçu du dernier message de chaque bot, mais
rien ne disait s'il était nouveau : il fallait ouvrir les dix-huit conversations
pour savoir laquelle avait bougé. Le repère de lecture vit côté serveur, pas
dans le navigateur, parce que WebUI est la porte d'entrée depuis n'importe quel
appareil — un badge par navigateur ferait réapparaître sur le téléphone des
messages déjà lus sur le poste.

Ce que ces tests verrouillent, dans l'ordre d'importance :

* le **démarrage silencieux** — un bot jamais ouvert ne doit pas afficher tout
  son historique comme non lu, sinon le badge naît déjà inutile ;
* le **compteur qui ne recule pas** — deux onglets, ou un marquage en retard, ne
  doivent pas ressusciter des non-lus déjà consommés ;
* la **tolérance** — store absent, cassé, compte inconnu : zéro non lu, jamais
  d'exception, jamais un chiffre inventé.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Isole le store dans un home factice."""
    from api import bot_seen, profiles
    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: tmp_path)
    return bot_seen


# ── Lecture / écriture du repère ────────────────────────────────────────────

def test_unknown_bot_has_no_seen_record(store):
    assert store.seen_count("lancelot") is None


def test_mark_seen_persists_and_reloads(store, tmp_path):
    store.mark_seen("lancelot", 42)
    assert store.seen_count("lancelot") == 42
    on_disk = json.loads((tmp_path / "webui" / "bot_seen.json").read_text(encoding="utf-8"))
    assert on_disk["lancelot"]["count"] == 42
    assert on_disk["lancelot"]["at"]


def test_seen_count_never_goes_backwards(store):
    """Deux onglets ouverts sur le même bot ne doivent pas faire revivre des
    non-lus déjà lus : le marquage le plus avancé gagne."""
    store.mark_seen("lancelot", 90)
    store.mark_seen("lancelot", 30)
    assert store.seen_count("lancelot") == 90


def test_invalid_profile_is_refused(store):
    for bad_name in ("", "   ", "../etc", "Not A Profile"):
        with pytest.raises(ValueError):
            store.mark_seen(bad_name, 1)


def test_invalid_count_is_refused(store):
    with pytest.raises(ValueError):
        store.mark_seen("lancelot", "beaucoup")


def test_broken_store_reads_as_empty(store, tmp_path):
    path = tmp_path / "webui" / "bot_seen.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ ceci n'est pas du json", encoding="utf-8")
    assert store.load_seen() == {}
    assert store.seen_count("lancelot") is None


# ── Calcul des non-lus ──────────────────────────────────────────────────────

@pytest.mark.parametrize(("total", "seen", "expected", "why"), [
    (10, 4, 6, "six messages sont arrivés depuis la dernière lecture"),
    (10, 10, 0, "tout est lu"),
    (4, 10, 0, "un compte total plus petit que le repère ne donne jamais un négatif"),
    (None, 4, 0, "pas de Bot Chat lisible : pas de badge inventé"),
    (10, None, 0, "bot jamais vu : la ligne de base est posée ailleurs, pas de badge ici"),
])
def test_unread_for(store, total, seen, expected, why):
    assert store.unread_for(total, seen) == expected, why


def test_baseline_starts_bots_at_zero_unread(store):
    """Premier passage : la ligne de base est posée au compte courant, donc le
    panneau ne s'ouvre pas sur dix-huit badges portant tout l'historique."""
    counts = {"lancelot": 120, "guenievre": 8}
    seen = store.baseline_unseen_profiles(counts)
    assert seen == {"lancelot": 120, "guenievre": 8}
    assert store.unread_for(120, seen["lancelot"]) == 0


def test_baseline_does_not_touch_known_bots(store):
    store.mark_seen("lancelot", 100)
    seen = store.baseline_unseen_profiles({"lancelot": 130})
    assert seen["lancelot"] == 100, "la ligne de base a écrasé un repère réel"
    assert store.unread_for(130, seen["lancelot"]) == 30


def test_baseline_ignores_bots_without_a_bot_chat(store):
    seen = store.baseline_unseen_profiles({"yvain": None})
    assert "yvain" not in seen


# ── Intégration dans /api/bots ──────────────────────────────────────────────

def _fake_overview(monkeypatch, tmp_path, *, messages, seen=None):
    """Un profil, une Bot Chat de ``messages`` lignes, repère optionnel."""
    from api import bots_overview, profiles

    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(profiles, "list_profiles_api", lambda: [
        {"name": "lancelot", "path": "/x/lancelot", "gateway_running": True, "is_active": False},
    ])
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda n: tmp_path / "profiles" / n)
    monkeypatch.setattr(bots_overview, "_sessions_by_profile", lambda names: {
        "lancelot": {"active": 0, "last_activity": None, "last_message_preview": "salut",
                     "bot_chat_messages": messages},
    })
    if seen is not None:
        from api import bot_seen
        bot_seen.mark_seen("lancelot", seen)
    bots_overview.invalidate_cache()
    return bots_overview


def test_overview_reports_unread_against_the_seen_marker(monkeypatch, tmp_path):
    bo = _fake_overview(monkeypatch, tmp_path, messages=50, seen=42)
    payload = bo.build_bots_overview(use_cache=False)
    bot = payload["bots"][0]
    assert bot["bot_chat_messages"] == 50
    assert bot["unread"] == 8
    assert payload["counts"]["unread"] == 8


def test_overview_first_sight_is_quiet(monkeypatch, tmp_path):
    """Sans repère préalable, le premier appel pose la ligne de base et ne
    signale rien — c'est ce qui rend le badge utilisable dès le premier jour."""
    bo = _fake_overview(monkeypatch, tmp_path, messages=200)
    payload = bo.build_bots_overview(use_cache=False)
    assert payload["bots"][0]["unread"] == 0
    assert payload["counts"]["unread"] == 0

    from api import bot_seen
    assert bot_seen.seen_count("lancelot") == 200

    # ...et un message qui arrive ensuite est bien compté.
    bo2 = _fake_overview(monkeypatch, tmp_path, messages=203)
    assert bo2.build_bots_overview(use_cache=False)["bots"][0]["unread"] == 3


# ── Câblage front ───────────────────────────────────────────────────────────

def _static(name):
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "static" / name).read_text(
        encoding="utf-8", errors="replace"
    )


def test_panel_renders_the_badge_and_marks_seen_on_open():
    js = _static("bots_panel.js")
    assert "bots-unread" in js, "la carte n'affiche pas de badge"
    assert "_botsMarkSeen" in js and "/api/bots/seen" in js, (
        "ouvrir une conversation ne marque pas le bot comme lu"
    )
    assert js.index("await _botsMarkSeen(bot)") > js.index("loadSession(r.session_id)"), (
        "le marquage doit suivre l'ouverture réelle, pas la précéder"
    )


def test_rail_badge_polls_while_the_panel_is_hidden():
    """Le badge du rail n'a d'intérêt QUE quand on regarde ailleurs : son poll
    ne doit pas être conditionné à la visibilité du panneau Bots."""
    js = _static("bots_panel.js")
    assert "_ensureBotsBadgePoll" in js
    assert "if (_botsPanelVisible()) return; // le poll du panneau s'en charge déjà" in js


def test_badge_styles_and_labels_exist():
    css = _static("bots_panel.css")
    assert ".bots-unread" in css and ".bots-rail-badge" in css
    i18n = _static("i18n_fork.js")
    assert i18n.count("bots_unread:") == 2, "clé i18n manquante en/fr"
