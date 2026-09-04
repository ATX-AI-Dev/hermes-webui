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

### Validé

- `.178` (agent réel, Python 3.11.16) : **49/49** — `test_gateway_multiprofile_b1` +
  `test_gateway_lifecycle_controls` + `test_gateway_status_agent_health` +
  `test_issue3194_gateway_configured_banner` + `test_health_restart`. Aucune régression.

---

## B2 — panneau « Bots / Hiérarchie »

**Branche** : `feat/b2-bots-panel` (part de `feat/b1-gateway-multiprofile` — B2 dépend de B1
pour le contrôle gateway par-profil).
**Objectif** : un poste de supervision de la hiérarchie des bots, en lecture seule, avec
Démarrer/Arrêter par bot (via B1) et « Ouvrir le fil » (bascule de profil).

### B2a — backend (commit `9a1c8332`)

| Fichier | Rôle | Couplage amont |
| :-- | :-- | :-- |
| `api/bots_hierarchy.json` (nouveau) | Carte fork-locale pilote/managers/bots des 18 profils. Copie opérateur possible à `<HERMES_HOME>/webui/bots_hierarchy.json`. Profils hors carte → branche `autre`. | aucun (données) |
| `api/bots_overview.py` (nouveau) | `build_bots_overview()` : fusionne `list_profiles_api()` + la carte + un scan **lecture seule** de `state.db` (`sessions` : `profile_name`, `ended_at`, `last_activity_at`, `archived`) pour `active_sessions` / `last_activity`. Cache 3 s. | `api.profiles.list_profiles_api`, `api.profiles._resolve_base_hermes_home` (helper privé — stable). Schéma `state.db` lu en SQL direct (mêmes colonnes que la recon du 04/09). |
| `api/routes.py` | `GET /api/bots` (`?fresh=1` bypass cache). | — |
| `tests/test_bots_overview_b2.py` (nouveau) | 7 tests : fusion carte/profils, profil inconnu→`autre`, counts, tri par branche, override opérateur + JSON cassé ignoré, route. | — |

### B2b — frontend

| Fichier | Changement |
| :-- | :-- |
| `static/index.html` | Bouton nav (rail + sidebar mobile) `data-panel="bots"` ; `<div id="panelBots">` + `#botsPanel`. |
| `static/panels.js` | `'bots'` dans `MAIN_VIEW_PANELS` ; hook `switchPanel` → `loadBotsPanel()` ; `loadBotsPanel()` + délégation de clic : Démarrer/Arrêter → `POST /api/gateway/{start,stop}` `{profile}` (B1), « Ouvrir le fil » → `switchToProfile()` + `switchPanel('chat')`. Aucune écriture hors gateway. |
| `static/style.css` | Bloc `.bots-*` en fin de fichier (préfixe scopé, ajout append-only). |
| `static/i18n.js` | 17 clés `bots_*` / `tab_bots` ajoutées dans **les 15 blocs de langue** (valeurs FR pour `fr`, EN pour `en` et les 13 autres — rattrapage de traduction ultérieur). Insertion après `tab_profiles:` de chaque bloc. Contrat de couverture des locales respecté. |
| `tests/test_bots_panel_frontend_b2.py` (nouveau) | 4 tests grep : nav+panel dans `index.html`, hook+loader dans `panels.js`, clés i18n en+fr, scope CSS. |

### Limites connues B2

- `active_sessions` = sessions non archivées et non terminées (`ended_at IS NULL`).
  `last_activity` = `MAX(last_activity_at)` sur les non archivées (inclut les terminées — c'est
  volontaire, c'est « dernière activité du bot »).
- Pas de sonde cron live par bot (18 sous-process = trop cher en synchrone). `permanent_gateway`
  vient de la carte statique, pas d'une vérif temps réel. À ajouter en B2c si besoin.
- Le panneau ne surface **pas** la « Bot Chat » — c'est le périmètre de B3.
- Frontend non testé en navigateur ici (pas d'agent + smoke browser). Tests grep + `node --check`
  seulement ; à valider visuellement sur `.178`.

### Non lancé ici

- Suite complète non exécutée sur le poste dev (Windows, agent absent). Échecs locaux
  `test_optionz_liveview_perf`, `test_model_picker_escaping`, `test_issue1255_refine_selection`,
  `test_clarify_sse` = **préexistants** (vérifié en stashant : ils tombent aussi sur
  `origin/master`). Les 8 tests de couverture de locale **passent** après le rattrapage des
  clés `bots_*`.
- À valider sur `.178` : `./scripts/test.sh tests/test_bots_overview_b2.py
  tests/test_bots_panel_frontend_b2.py tests/test_gateway_multiprofile_b1.py -v` + run complet
  + inspection visuelle du panneau.
