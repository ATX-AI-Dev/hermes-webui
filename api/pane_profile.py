"""Le profil d'une requête peut venir d'un en-tête, pas seulement du cookie.

LE VERROU QUE CE MODULE LÈVE
----------------------------
WebUI résout le profil actif **par requête**, depuis le cookie ``hermes_profile``
(``server.py`` → ``api.profiles.set_request_profile``). Un navigateur envoie le
même cookie pour toutes les requêtes d'un onglet : deux zones de la même page ne
peuvent donc pas parler à deux bots différents. Ce n'est pas une limite
d'affichage, c'est **le** verrou du cockpit multi-bots — le spike C1 a montré que
le moteur, lui, sait déjà exécuter deux bots en parallèle sans les mélanger
(``docs/fork/SPIKE-C1-execution-concurrente.md``).

Un panneau secondaire épinglé sur un autre bot ajoute donc un en-tête
``X-Hermes-Profile`` à ses appels ; le reste de la page continue d'utiliser le
cookie. Aucun état global n'est déplacé : c'est ce qui rend l'étape suivante (N
panneaux) une généralisation plutôt qu'une réécriture.

POURQUOI UN JETON SIGNÉ ET PAS LE NOM DU PROFIL
-----------------------------------------------
Quand l'authentification est active, l'amont **signe** le cookie de profil
(``auth.sign_profile_cookie_value``) et refuse un nom nu : sans ça, un client
pourrait écrire ``hermes_profile=<autre-profil>`` et passer outre les garde-fous
de visibilité. Accepter un en-tête en clair rouvrirait exactement ce trou.

L'en-tête porte donc **la même valeur signée que le cookie**, obtenue du serveur
via ``POST /api/profile/pane-token``. La propriété de sécurité est inchangée :
seul le serveur peut fabriquer la valeur, et elle est liée au jeton de session.
En mode sans authentification, le nom nu est accepté — même comportement
historique que le cookie, qui n'y est qu'une préférence de navigateur.

Un en-tête personnalisé ne peut être posé que par du JS de même origine (une
requête cross-origin déclencherait un préflight), donc ceci n'ouvre pas de
nouveau vecteur CSRF.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PANE_PROFILE_HEADER = "X-Hermes-Profile"


def _valid_profile_name(value: str) -> bool:
    from api.profiles import _PROFILE_ID_RE
    return value == "default" or bool(_PROFILE_ID_RE.fullmatch(value))


def profile_from_header(handler) -> str | None:
    """Profil demandé par l'en-tête, ou None. Ne lève jamais.

    Applique exactement le contrôle du cookie : valeur signée et liée à la
    session quand l'auth est active, nom nu validé sinon.
    """
    try:
        raw = (handler.headers.get(PANE_PROFILE_HEADER) or "").strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        from api.auth import is_auth_enabled, parse_cookie, verify_profile_cookie_value
        if is_auth_enabled():
            name = verify_profile_cookie_value(raw, parse_cookie(handler))
            return name if name and _valid_profile_name(name) else None
    except Exception:
        logger.warning("pane profile header verification failed", exc_info=True)
        return None
    return raw if _valid_profile_name(raw) else None


def request_profile(handler) -> str | None:
    """Profil de CETTE requête : en-tête s'il y en a un, cookie sinon.

    Remplace l'appel direct à ``get_profile_cookie`` dans ``server.py``. L'ordre
    compte : un panneau épinglé doit gagner sur le profil de l'onglet, sinon il
    afficherait le bon bot et enverrait au mauvais.
    """
    from api.helpers import get_profile_cookie
    return profile_from_header(handler) or get_profile_cookie(handler)


def handle_post_pane_token(handler, body) -> bool:
    """POST /api/profile/pane-token — ``{"profile": "<nom>"}`` → valeur signée.

    Ne donne aucun droit nouveau : la route exige déjà une session authentifiée
    (le contrôle d'auth précède le routage), et la valeur produite est celle que
    le serveur poserait en cookie si l'utilisateur basculait sur ce profil.
    """
    from api.helpers import j
    from api.routes import bad, _sanitize_error
    if not isinstance(body, dict):
        return bad(handler, "Request body must be a JSON object")
    profile = str(body.get("profile") or "").strip()
    if not profile or not _valid_profile_name(profile):
        return bad(handler, "invalid profile")
    try:
        from api.auth import is_auth_enabled, parse_cookie, sign_profile_cookie_value
        if not is_auth_enabled():
            # Sans auth, le cookie lui-même n'est qu'un nom : l'en-tête aussi.
            return j(handler, {"profile": profile, "token": profile, "signed": False})
        token = sign_profile_cookie_value(profile, parse_cookie(handler))
    except ValueError:
        # Pas de session valide : ce n'est pas une erreur serveur, c'est un refus.
        return bad(handler, "an active session is required", 401)
    except Exception as exc:
        logger.exception("pane token minting failed")
        return bad(handler, _sanitize_error(exc), status=500)
    return j(handler, {"profile": profile, "token": token, "signed": True})
