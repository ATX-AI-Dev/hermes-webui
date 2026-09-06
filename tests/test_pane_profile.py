"""C2 — le profil d'une requête peut venir d'un en-tête (api/pane_profile.py).

WebUI résout le profil actif depuis le cookie ``hermes_profile``, et un
navigateur envoie le même cookie pour tout l'onglet : deux zones de la même page
ne peuvent donc pas parler à deux bots différents. C'est **le** verrou du
cockpit multi-bots — pas l'affichage, que le spike C1 a déjà disculpé.

Ces tests protègent les deux propriétés qui font que lever ce verrou reste sûr :

* **l'en-tête n'est pas plus faible que le cookie** — quand l'auth est active, il
  doit porter une valeur signée liée à la session, exactement comme le cookie.
  Un nom nu accepté ici rouvrirait le trou que la signature amont ferme
  (``auth.sign_profile_cookie_value``: « prevents a client from forging
  hermes_profile=<other-profile> ») ;
* **l'en-tête gagne sur le cookie** — un panneau épinglé qui afficherait le bon
  bot mais enverrait au profil de l'onglet serait pire que pas de panneau du tout.
"""

from __future__ import annotations

import pytest


class _Handler:
    """Le strict minimum que lisent get_profile_cookie / profile_from_header."""

    def __init__(self, header=None, cookie=None):
        self.headers = {}
        if header is not None:
            self.headers["X-Hermes-Profile"] = header
        if cookie is not None:
            self.headers["Cookie"] = f"hermes_profile={cookie}"

    # http.server expose .headers comme un mapping insensible à la casse ;
    # dict.get suffit ici, les deux modules n'utilisent que .get().


@pytest.fixture
def no_auth(monkeypatch):
    from api import auth
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: False)


@pytest.fixture
def with_auth(monkeypatch):
    from api import auth
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)


# ── Mode sans authentification : nom nu, comme le cookie ────────────────────

def test_header_accepts_a_plain_name_without_auth(no_auth):
    from api.pane_profile import profile_from_header
    assert profile_from_header(_Handler(header="lancelot")) == "lancelot"


@pytest.mark.parametrize("bad_value", ["", "   ", "../etc", "Pas Un Profil", "a" * 200])
def test_header_rejects_malformed_names(no_auth, bad_value):
    from api.pane_profile import profile_from_header
    assert profile_from_header(_Handler(header=bad_value)) is None


# ── Mode authentifié : la signature est obligatoire ─────────────────────────

def test_header_refuses_an_unsigned_name_when_auth_is_on(with_auth, monkeypatch):
    """Le cœur du sujet : sans ce refus, n'importe qui pourrait se déclarer
    n'importe quel profil en ajoutant un en-tête."""
    from api import auth, pane_profile
    monkeypatch.setattr(auth, "parse_cookie", lambda handler: "session-cookie")
    monkeypatch.setattr(auth, "verify_profile_cookie_value", lambda value, session: None)
    assert pane_profile.profile_from_header(_Handler(header="guenievre")) is None


def test_header_accepts_a_value_the_server_signed(with_auth, monkeypatch):
    from api import auth, pane_profile
    monkeypatch.setattr(auth, "parse_cookie", lambda handler: "session-cookie")
    monkeypatch.setattr(
        auth, "verify_profile_cookie_value",
        lambda value, session: "guenievre" if value == "guenievre.sig" else None,
    )
    assert pane_profile.profile_from_header(_Handler(header="guenievre.sig")) == "guenievre"


def test_verification_failure_denies_rather_than_crashes(with_auth, monkeypatch):
    from api import auth, pane_profile

    def _boom(*a, **k):
        raise RuntimeError("clé de signature absente")

    monkeypatch.setattr(auth, "parse_cookie", _boom)
    assert pane_profile.profile_from_header(_Handler(header="lancelot")) is None


# ── Priorité en-tête / cookie ───────────────────────────────────────────────

def test_header_wins_over_cookie(no_auth):
    from api.pane_profile import request_profile
    handler = _Handler(header="guenievre", cookie="lancelot")
    assert request_profile(handler) == "guenievre", (
        "un panneau épinglé afficherait un bot et écrirait à un autre"
    )


def test_cookie_still_used_when_no_header(no_auth):
    from api.pane_profile import request_profile
    assert request_profile(_Handler(cookie="lancelot")) == "lancelot"


def test_no_header_no_cookie_is_none(no_auth):
    from api.pane_profile import request_profile
    assert request_profile(_Handler()) is None


# ── Le serveur passe bien par le fork, et dégrade proprement ────────────────

def test_server_resolves_the_request_profile_through_the_fork():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert src.count("cookie_profile = _fork_request_profile(self)") == 2, (
        "les deux points d'entrée (GET et écriture) doivent résoudre le profil de la même façon"
    )
    assert "from api.pane_profile import request_profile" in src
    assert "return get_profile_cookie(handler)" in src, (
        "sans le module du fork, le serveur doit retomber sur le comportement amont"
    )


def test_fork_helper_falls_back_when_the_module_is_missing(monkeypatch):
    """Le serveur ne doit jamais tomber parce qu'un fichier du fork manque."""
    import builtins
    import server

    real_import = builtins.__import__

    def _fail_pane_profile(name, *args, **kwargs):
        if name == "api.pane_profile":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_pane_profile)
    handler = _Handler(cookie="lancelot")
    assert server._fork_request_profile(handler) == "lancelot"
