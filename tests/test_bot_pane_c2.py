"""C2 — le panneau bot épinglé (static/bot_pane.js).

Étape 1 du palier C2, telle que Ludo l'a cadrée : « on attaque le 2 dans
l'esprit de s'orienter par la suite sur le 3 ». D'où la forme du code, que ces
tests protègent — pas seulement son fonctionnement.

Ce qui est vérifié ici, et pourquoi ça compte :

* **le panneau porte son profil sur CHAQUE appel** — sans l'en-tête,
  `/api/chat/start` répond « Session not found » (il exige que la session
  appartienne au profil de la requête) ; le panneau afficherait le bon bot et
  écrirait dans le vide ;
* **il ne touche pas à l'état global `S`** — c'est la condition pour que
  l'étape suivante (N panneaux) soit une généralisation et non une réécriture ;
* **on ne peut pas épingler le bot déjà ouvert en principal** — les deux
  surfaces se battraient pour le même bail d'exclusivité de session côté agent ;
* **le panneau assume ce qu'il n'a pas** (workspace, Trace, approbations) et
  offre une sortie explicite : « Basculer ici ».
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def pane_js() -> str:
    return _read("bot_pane.js")


# ── Le profil voyage avec chaque requête du panneau ─────────────────────────

def test_every_pane_call_carries_the_profile_header(pane_js):
    assert "'X-Hermes-Profile'" in pane_js
    assert "function _paneApi(" in pane_js
    for endpoint in ("/api/bot-chat?profile=", "/api/chat/start"):
        assert endpoint in pane_js
    # Les appels du fil et de l'envoi doivent passer par _paneApi, pas par api()
    for call in ("_paneApi('/api/bot-chat?profile='", "_paneApi('/api/chat/start'"):
        assert call in pane_js, f"{call} n'utilise pas le canal porteur d'en-tête"


def test_send_would_be_refused_without_the_header_is_documented(pane_js):
    """Le pourquoi doit rester dans le code : c'est un piège invisible."""
    assert "Session not found" in pane_js


def test_pane_token_is_minted_by_the_server(pane_js):
    """Le panneau ne fabrique jamais lui-même la valeur du profil : en mode
    authentifié elle est signée côté serveur (api/pane_profile.py)."""
    assert "/api/profile/pane-token" in pane_js
    assert "_paneMintToken" in pane_js


# ── L'état reste local au panneau ───────────────────────────────────────────

def test_pane_state_never_touches_the_global_session_state(pane_js):
    """`S.session`, `S.messages`… appartiennent à la conversation principale.

    Le panneau n'y écrit pas : il lit `S.activeProfile` pour refuser d'épingler
    le bot déjà ouvert, et rien d'autre. Si ce test tombe, l'étape « N panneaux »
    vient de devenir une réécriture.
    """
    import re
    # Une AFFECTATION, pas une comparaison : `S.activeProfile === x` est une
    # lecture légitime, `S.activeProfile = x` ne l'est pas.
    assignment = re.compile(r"S\.(session|sessionId|messages|activeProfile)\s*=(?!=)")
    found = assignment.findall(pane_js)
    assert not found, f"le panneau écrit dans l'état global : {found}"


def test_pane_owns_its_own_refresh(pane_js):
    """Le rafraîchissement est une affaire du panneau, pas du poll de la page."""
    assert "_startPanePoll" in pane_js and "_stopPanePoll" in pane_js
    assert "BOT_PANE_BUSY_POLL_MS" in pane_js, (
        "un tour en cours doit être suivi plus vite qu'un fil au repos"
    )


# ── Garde-fous ──────────────────────────────────────────────────────────────

def test_cannot_pin_the_bot_already_open_as_main(pane_js):
    assert "S.activeProfile === profile" in pane_js
    assert "bot_pane_same_bot" in pane_js


def test_import_precedes_any_send(pane_js):
    """/api/chat/start ne trouverait pas la session sans le sidecar créé par
    l'import — l'ordre n'est pas cosmétique."""
    call_continue = pane_js.index("api('/api/bot-chat/continue'")
    call_start = pane_js.index("_paneApi('/api/chat/start'")
    assert call_continue < call_start, (
        "l'appel d'import doit précéder l'appel d'envoi (les mentions en "
        "commentaire ne comptent pas)"
    )


def test_promote_is_the_documented_way_out(pane_js):
    """Un tour du panneau qui demanderait une approbation d'outil resterait
    bloqué : le panneau doit offrir la bascule vers le principal."""
    assert "function promoteBotPane(" in pane_js
    assert "bot_pane_promote" in pane_js
    assert "approbation" in pane_js.lower() or "approval" in pane_js.lower()


# ── Câblage ─────────────────────────────────────────────────────────────────

def test_asset_is_loaded_and_precached():
    html = _read("index.html")
    sw = _read("sw.js")
    assert "static/bot_pane.js" in html
    assert "'./static/bot_pane.js'" in sw
    assert 'id="botPane"' in html
    # bots_panel.js expose pinBotPane au clic : il doit être chargé avant panels.js,
    # et bot_pane.js avant d'être appelé.
    assert html.index('src="static/bots_panel.js') < html.index('src="static/bot_pane.js'), (
        "bot_pane.js doit être chargé après bots_panel.js (il réutilise son "
        "moteur de rendu de tours)"
    )


def test_bots_panel_offers_the_pin_action():
    js = _read("bots_panel.js")
    assert "data-act=\"pin\"" in js or "data-act='pin'" in js
    assert "pinBotPane" in js
    assert "bot_pane_pin" in js


def test_pane_labels_exist_in_both_locales():
    i18n = _read("i18n_fork.js")
    for key in ("bot_pane_pin", "bot_pane_send", "bot_pane_promote",
                "bot_pane_placeholder", "bot_pane_same_bot", "bot_pane_close"):
        assert i18n.count(key + ":") == 2, f"clé {key} absente en/fr"


def test_layout_pushes_the_main_chat_rather_than_reflowing_main():
    """`.main` empile bannières + chat en colonne : la passer en ligne casserait
    les bannières. Le panneau est donc positionné, et pousse le chat."""
    css = _read("bots_panel.css")
    assert "body.has-bot-pane #mainChat" in css
    assert ".bot-pane { position: absolute" in css
