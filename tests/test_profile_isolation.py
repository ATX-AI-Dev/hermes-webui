"""E2 — cloisonnement Pro/Perso dans WebUI.

Le vault (`procedures/delegation-regles.md`, `perso/00-README.md`) impose une
étanchéité totale entre la branche Pro et la branche Perso : ni les bots ni les
managers ne communiquent, et la règle vaut aussi pour la mémoire. WebUI est la
seule surface où les deux branches cohabitent dans une même fenêtre, ce qui en
fait le point de fuite le plus plausible. `infra/hermes-webui.md` le signalait
comme « à tester explicitement avant usage courant » depuis le 03/09/2026.

Campagne menée le 06/09/2026. Ce qu'elle a trouvé, et ce que ce fichier
verrouille :

1. **Sessions et projets** — l'amont scope déjà par profil actif via
   `_profiles_match`. Rien à corriger, mais la sémantique est verrouillée ici :
   si elle changeait, deux branches se mélangeraient dans la sidebar.

2. **Workspace — la vraie trouvaille.** Les 18 profils partageaient tous
   `/home/atx/workspace` en prod (vérifié dans les sidecars de session : neuf
   profils distincts, dont `guenievre`, tous sur le même chemin). Le dossier
   était **vide**, donc rien n'avait fuité — mais un bot Perso aurait pu lire ce
   qu'un bot Pro y écrivait. Corrigé côté exploitation, sans code : l'amont
   résout déjà `last_workspace.txt` **par profil**
   (`api.workspace._last_workspace_file`), il a suffi de donner à chaque bot son
   propre dossier. Le test ci-dessous protège ce contrat amont : s'il redevenait
   global, tous les bots repartiraient sur un workspace commun **en silence**.

3. **Panneau Bots** — transverse aux deux branches, volontairement (décision de
   Ludo, 06/09/2026) : c'est Ludo qui le regarde, pas un bot. Verrouillé aussi,
   pour qu'un futur « correctif » de cloisonnement ne le casse pas par zèle.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ── 1. Sessions / projets : le scope par profil de l'amont ──────────────────

@pytest.mark.parametrize(("row_profile", "active_profile", "expected", "why"), [
    ("lancelot", "guenievre", False, "un bot Pro ne doit jamais apparaître sous un bot Perso"),
    ("guenievre", "lancelot", False, "ni l'inverse"),
    ("angharad", "sefriane", False, "deux bots Perso restent séparés l'un de l'autre"),
    ("lancelot", "lancelot", True, "un bot voit ses propres sessions"),
    (None, "default", True, "une ligne sans profil appartient au profil racine"),
    ("", "default", True, "idem pour la chaîne vide"),
    (None, "lancelot", False, "une ligne sans profil ne remonte pas sous un bot nommé"),
])
def test_profiles_match_isolates_branches(row_profile, active_profile, expected, why):
    from api.profiles import _profiles_match
    assert _profiles_match(row_profile, active_profile) is expected, why


def test_session_and_project_listings_still_filter_by_profile():
    """Sentinelle : le filtre existe toujours dans les chemins de listing.

    Ce n'est pas un test de comportement (il faudrait un serveur complet) mais
    une alarme de rebase : si l'amont retirait ces filtres, la sidebar
    mélangerait les branches sans qu'aucun test du fork ne tombe.
    """
    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert '_profiles_match(s.get("profile"), active_profile)' in routes, (
        "le listing de sessions ne filtre plus par profil actif"
    )
    assert '_profiles_match(proj.get("profile"), active_profile)' in routes, (
        "le listing de projets ne filtre plus par profil actif"
    )


# ── 2. Workspace : un dossier par bot, pas un dossier commun ────────────────

def test_last_workspace_file_is_per_profile(monkeypatch, tmp_path):
    """Contrat amont dont dépend le cloisonnement des workspaces.

    Un bot nommé doit lire SON `last_workspace.txt`, sous son propre home. Si
    cette fonction redevenait globale, les 18 bots retomberaient sur un
    workspace partagé au prochain `hermes update` — exactement l'état trouvé en
    prod le 06/09/2026, mais cette fois sans que personne le voie.
    """
    from api import profiles, workspace

    bot_home = tmp_path / "profiles" / "guenievre"
    bot_home.mkdir(parents=True)
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "guenievre")
    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: bot_home)

    resolved = workspace._last_workspace_file()
    assert resolved.parent.parent == bot_home, (
        f"last_workspace.txt de guenievre résolu hors de son home : {resolved}"
    )
    assert resolved.name == "last_workspace.txt"


def test_two_bots_get_two_different_workspace_files(monkeypatch, tmp_path):
    """Le corollaire, dit explicitement : deux bots, deux fichiers distincts."""
    from api import profiles, workspace

    seen = {}
    for name in ("lancelot", "guenievre"):
        home = tmp_path / "profiles" / name
        home.mkdir(parents=True)
        monkeypatch.setattr(profiles, "get_active_profile_name", lambda n=name: n)
        monkeypatch.setattr(profiles, "get_active_hermes_home", lambda h=home: h)
        seen[name] = workspace._last_workspace_file()

    assert seen["lancelot"] != seen["guenievre"], (
        "un bot Pro et un bot Perso partagent le même fichier de workspace"
    )


# ── 3. Panneau Bots : transverse, et c'est voulu ────────────────────────────

def test_bots_panel_shows_both_branches(monkeypatch, tmp_path):
    """Décision de Ludo (06/09/2026) : le panneau Bots reste transverse.

    L'étanchéité vise les bots entre eux, pas la vue de supervision de Ludo. Ce
    test empêche qu'un futur durcissement du cloisonnement retire la branche
    Perso du panneau en croyant bien faire.
    """
    from api import bots_overview, profiles

    rows = [
        {"name": "lancelot", "path": "/x/lancelot", "gateway_running": True, "is_active": True},
        {"name": "guenievre", "path": "/x/guenievre", "gateway_running": True, "is_active": False},
    ]
    monkeypatch.setattr(profiles, "list_profiles_api", lambda: list(rows))
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda n: tmp_path / "profiles" / n)
    monkeypatch.setattr(profiles, "_resolve_base_hermes_home", lambda: tmp_path)
    bots_overview.invalidate_cache()

    payload = bots_overview.build_bots_overview(use_cache=False)
    branches = {b["id"]: b["branch"] for b in payload["bots"]}
    assert branches.get("lancelot") == "pro"
    assert branches.get("guenievre") == "perso"
