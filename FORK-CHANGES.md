# Divergences du fork `ATX-AI-Dev/hermes-webui`

Base amont : `nesquena/hermes-webui` @ `e168b67e` (`exp-v0.52.264`).
Chaque entrée = un écart à rebaser. Voir `PLAN-palier-B.md` pour le contexte.

---

## B1 — contrôle de passerelle multi-profils

**Branche** : `feat/b1-gateway-multiprofile`
**Objectif** : `/api/gateway/{start,stop,restart,status}` acceptent un `profile` explicite pour
agir sur / inspecter la passerelle d'un bot **non actif**, sans changer le profil actif de WebUI.

### `api/routes.py`

| Zone | Changement | Point de couplage amont |
| :-- | :-- | :-- |
| import `contextlib` | ajout de `contextmanager` | — |
| `_GATEWAY_ACTION_LOCK` | + `_GATEWAY_ACTION_LOCKS` (dict par profil) + `_gateway_action_lock_for()`. Le chemin **sans** `profile` garde le lock module d'origine (compat tests). | aucun |
| `_active_profile_override()` (nouveau) | CM qui pin `api.profiles._tls.profile` puis restaure (y compris l'état « non défini »). | dépend de `api.profiles._tls` (thread-local privé — stable, mais privé). |
| `_check_gateway_running_for_home()` (nouveau) | wrappe `hermes_cli.profiles._check_gateway_running(home)` ; renvoie `None` si indisponible. | **couplage** : helper privé `hermes_cli.profiles._check_gateway_running`. Déjà utilisé par `_build_profile_rows_fast()` en amont → risque partagé, pas nouveau. |
| `_run_gateway_lifecycle_command(action)` | → `(action, profile=None)`. Si `profile`, l'utilise pour `--profile` au lieu de `get_active_profile_name()`. `default` → pas de flag (inchangé). Appelé sans le kwarg quand `profile` est absent (compat monkeypatch `lambda action:` des tests existants). | aucun |
| `_gateway_status_payload()` | → `_gateway_status_payload(profile=None)` : wrapper. Corps d'origine renommé `_gateway_status_payload_impl()`. Avec `profile` : exécute l'impl sous `_active_profile_override`, puis recale `running` via `_check_gateway_running_for_home`, ajoute la clé `profile`. Sans `profile` : strictement identique. | aucun (les tests qui montkeypatchent `_gateway_status_payload` ou `build_agent_health_payload`/`_load_gateway_session_identity_map` restent valides). |
| `_handle_gateway_lifecycle()` | supprime `del body`. Lit/valide `body["profile"]` (`_PROFILE_ID_RE`, `default` accepté). Lock par profil. Passe `profile` à la commande et au payload de statut. Ajoute `profile` aux réponses (succès / échec / 409). | `api.profiles._PROFILE_ID_RE` (déjà importé ailleurs dans `routes.py`). |
| GET `/api/gateway/status` | parse `?profile=`, valide, passe à `_gateway_status_payload`. | — |

### `tests/test_gateway_multiprofile_b1.py` (nouveau)

8 tests : profil explicite ciblé (≠ actif), `default` sans flag, profil invalide rejeté sans
spawn, non-contention entre profils différents, compat du lock module sans profil, `?profile=`
sur le statut (+ rejet invalide, + inchangé sans profil).

### Limites connues

- `{"profile": "<profil-actif>"}` et un appel sans `profile` utilisent des locks différents →
  concurrence possible sur la même passerelle. Acceptable (endpoint basse fréquence, boutons UI
  désactivés pendant l'action) ; le chemin sans `profile` est inchangé.
- `_gateway_status_payload(profile=...)` : les fichiers `gateway.pid` / `gateway_state.json`
  peuvent vivre sous le home racine même pour une passerelle profilée (cf.
  `api/agent_health.py`) — d'où le recalage via `_check_gateway_running_for_home`. Si
  `hermes_cli.profiles._check_gateway_running` disparaît en amont, on retombe sur l'estimation
  métadonnées (pas de crash).

### Non fait / non lancé ici

- Suite de tests **non exécutée** sur le poste de dev (Windows, Python 3.14 seulement, agent
  Hermes absent). À valider sur `.178` : `./scripts/test.sh tests/test_gateway_multiprofile_b1.py
  tests/test_gateway_lifecycle_controls.py tests/test_gateway_status_agent_health.py
  tests/test_issue3194_gateway_configured_banner.py -v`.
- Frontend : le panneau B2 câblera les boutons Démarrer/Arrêter par bot sur ce `profile`. Pas
  de changement frontend dans B1.
