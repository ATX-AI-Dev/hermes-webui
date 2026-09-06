"""Spike C1 — deux bots qui tournent en même temps restent-ils isolés ?

Critère de succès posé dans `docs/fork/PLAN-ecarts-de-fond.md` (écart E6) :
*deux tours de deux bots différents, lancés en même temps, restent isolés
(mémoire, workspace, état)*. C'est ce qui décide si « WebUI façon cockpit »
demande le gros chantier C1 (un runtime d'exécution découplé) ou seulement C2
(l'affichage multi-panneaux).

Ce que ces tests mesurent — la **portée des variables**, pas une maquette : ce
sont les mêmes mécanismes que `api/streaming.py` utilise pour épingler le profil
d'un tour. Aucun appel LLM : l'isolation se joue là, pas dans le modèle.

Résultat mesuré sur `.178` le 06/09/2026 (agent `c5594ec4`) :

* `hermes_constants.set_hermes_home_override` est un **ContextVar** qui refuse
  explicitement de toucher `os.environ` → deux tours concurrents voient chacun
  le home de LEUR bot ;
* `api.profiles._tls` est un vrai thread-local → le profil actif de WebUI ne
  fuit pas d'un tour à l'autre ;
* `os.environ['HERMES_HOME']`, le repli des agents plus anciens, est **partagé
  et racé** : dans la mesure, le thread `lancelot` a lu le home de `guenievre`.

Conclusion : sur cet agent, la voie legacy tient déjà le critère. Le risque
résiduel est tout code qui lirait `HERMES_HOME` dans l'environnement au lieu de
passer par l'override — d'où le dernier test, qui fige cette différence pour que
personne ne « simplifie » un jour l'override en écriture d'environnement.
"""

from __future__ import annotations

import os
import threading

import pytest


def _require_agent():
    return pytest.importorskip(
        "hermes_constants",
        reason="hermes-agent absent (poste de dev Windows) — sonde à lancer sur .178",
    )


def _run_two_pinned_threads(pin, read):
    """Épingle deux valeurs en parallèle, relit APRÈS que les deux soient posées.

    La barrière est le cœur du test : sans elle, chaque thread lirait sa valeur
    avant que l'autre n'ait écrit la sienne, et un état partagé passerait pour
    isolé.
    """
    names = ["lancelot", "guenievre"]
    barrier = threading.Barrier(len(names), timeout=20)
    seen: dict[str, object] = {}
    failures: list[str] = []

    def worker(name):
        try:
            token = pin(name)
            barrier.wait()
            seen[name] = read(name)
            if token is not None and callable(getattr(token, "reset", None)):
                token.reset()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(n,), name=n) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not failures, failures
    return seen


def test_hermes_home_override_is_context_local(tmp_path):
    """Le home d'un tour ne doit pas fuir vers le tour concurrent."""
    hc = _require_agent()
    if not hasattr(hc, "set_hermes_home_override"):
        pytest.skip("agent trop ancien : pas d'override context-local, repli os.environ")

    homes = {n: str(tmp_path / n) for n in ("lancelot", "guenievre")}
    tokens: dict[str, object] = {}

    def pin(name):
        tokens[name] = hc.set_hermes_home_override(homes[name])
        return None

    def read(name):
        getter = getattr(hc, "get_hermes_home", None) or getattr(hc, "hermes_home", None)
        return str(getter()) if callable(getter) else None

    seen = _run_two_pinned_threads(pin, read)
    for name, home in homes.items():
        assert seen[name] == home, (
            f"{name} a vu {seen[name]} alors que son tour est épinglé sur {home} — "
            "deux bots concurrents partagent leur home"
        )


def test_webui_active_profile_is_thread_local():
    """`_tls` porte le profil actif de WebUI ; B1 s'appuie dessus pour piloter
    un bot NON actif sans changer celui de l'interface."""
    from api import profiles

    def pin(name):
        profiles._tls.profile = name
        return None

    def read(name):
        return getattr(profiles._tls, "profile", None)

    seen = _run_two_pinned_threads(pin, read)
    assert seen == {"lancelot": "lancelot", "guenievre": "guenievre"}


def test_environment_home_is_the_racy_fallback_and_stays_documented():
    """`os.environ` est partagé par tout le processus : c'est un constat, pas un
    défaut à corriger ici. Le test existe pour que la différence reste visible —
    si quelqu'un remplaçait un jour l'override context-local par une écriture
    d'environnement, l'isolation tomberait en silence.
    """
    saved = os.environ.get("HERMES_HOME")
    try:
        def pin(name):
            os.environ["HERMES_HOME"] = f"/tmp/{name}"
            return None

        def read(name):
            return os.environ.get("HERMES_HOME")

        seen = _run_two_pinned_threads(pin, read)
        assert len(set(seen.values())) == 1, (
            "os.environ s'est mis à isoler par thread — vérifier que le reste de "
            "cette analyse tient toujours"
        )
    finally:
        if saved is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = saved


def test_streaming_prefers_the_context_local_override():
    """Le chemin de streaming doit passer par l'override quand il existe, et ne
    retomber sur l'environnement que pour les agents anciens."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "api" / "streaming.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "_set_streaming_hermes_home_override" in src
    assert "set_hermes_home_override" in src
    assert "os.environ mirror" in src, (
        "le repli process-global n'est plus documenté comme tel"
    )


def test_run_guards_are_per_session_not_global():
    """Rien ne sérialise deux tours de DEUX bots différents : les garde-fous
    'busy' portent sur une session, pas sur le processus. C'est ce qui rend
    l'exécution concurrente possible sans le runner du palier C1."""
    from pathlib import Path
    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "Session busy, try again" in routes
    assert "Session is busy (streaming)" in routes
    assert '"active_streams": len(STREAMS)' in routes, (
        "STREAMS n'est plus un registre de flux multiples"
    )
