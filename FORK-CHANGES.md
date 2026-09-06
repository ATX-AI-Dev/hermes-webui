# Divergences du fork `ATX-AI-Dev/hermes-webui`

Base amont : `nesquena/hermes-webui` @ `e168b67e` (`exp-v0.52.264`, 25/08/2026).
Chaque entrée = un écart à rebaser. Voir `docs/fork/PLAN-palier-B.md` pour le contexte, et la section
**Surface de conflit avec l'amont** en fin de fichier pour la procédure de rebase et le
garde-fou à lancer après chaque mise à jour amont.

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

### Validé (run complet `.178`, 04/09/2026)

14996 passed / 10 failed sur la suite entière (13 min). Les 10 échecs ne touchent ni B1 ni B2 :
2 `test_tls_aware_probe` préexistants (confirmé sur arbre sans nos modifs suivies —
`health_probe.sh` renvoie 1, problème shell/openssl de `.178`) + 8 flakes d'ordonnancement de
la grande suite (`test_passkey_auth`, `test_issue3825_oidc_auth`, `test_issue803`,
`test_issue2929_settings_max_tokens`) qui **passent tous en isolation**.

**Déployé** : `feat/b2-bots-panel` poussé sur `ATX-AI-Dev/hermes-webui` (commits réécrits sur
l'email noreply GitHub pour passer GH007). `.178` à repointer sur ce remote (voir §6).

---

## B3 — vue « Bot Chat » + carte d'échange inter-bots

**Branche** : `feat/b3-bot-chat-viewer` (part de `feat/b2-bots-panel`).
**Objectif** : rendre visible et lisible le mesh `message_agent`, aujourd'hui invisible dans
WebUI (session canonique « Bot Chat » masquée, `hidden=1`).

### Recon préalable (voir docs/fork/PLAN-palier-B.md §1)

Schéma réel vérifié sur `.178` : `sessions.title='Bot Chat'`, `hidden=1`, `profile_name`.
`messages` : `role, content, tool_call_id, tool_calls (JSON), tool_name, timestamp (epoch)`.
Un appel `message_agent` = ligne `assistant` avec `tool_calls` contenant la fonction
`message_agent`/`bot_mode_dm`, appariée à sa ligne `tool` (accusé JSON) via `tool_call_id`.
La réponse différée arrive comme n'importe quel tour ultérieur (pas de corrélation spéciale
nécessaire — cas (b) du plan confirmé).

### B3a — backend (commit `5142abce`)

| Fichier | Rôle | Couplage amont |
| :-- | :-- | :-- |
| `api/bot_mesh.py` (nouveau) | `find_bot_chat_session`, `list_bot_chat_profiles`,
  `read_bot_chat_transcript` — lecture seule directe de `state.db`, fusionne un appel relais
  avec son accusé en un tour `relay_out` (`target`, `message`, `ok`, `error`). | Schéma SQL de
  `state.db` (colonnes vérifiées en direct, non contractuelles côté amont). |
| `api/routes.py` | `GET /api/bot-chat?profile=<name>&limit=<n>`, profil validé. | — |
| `api/bots_overview.py` | `has_bot_chat` ajouté par bot (une requête de plus, lecture seule). | — |
| `tests/test_bot_mesh_b3.py` (nouveau) | 9 tests : session absente, filtre hidden/titre,
  fusion accusé ok/erreur, tours non-relais intacts, ordre chronologique, route, `has_bot_chat`. | — |

### B3b — frontend (commit `4f9ce1bf`)

Bouton « Fil inter-bots » par ligne (si `has_bot_chat`), accordéon chargé à la demande
(`GET /api/bot-chat`), carte dédiée pour les tours `relay_out` (cible, message, état
livré/en attente/erreur), reste du fil en texte/outil brut. 5 clés i18n × 15 locales.
`tests/test_bot_mesh_frontend_b3.py` (3 tests grep).

### Limites connues B3 (lecture seule)

- **Pas d'envoi depuis WebUI.** Reste à vérifier en live si `run_agent` en processus obtient
  l'injection de `message_agent` sur une session titrée « Bot Chat » (le gate
  `ensure_message_agent_tool` côté agent) — tant que ce n'est pas confirmé, la vue reste
  lecture seule par choix, pas par limitation technique constatée.
- Le nom d'outil (`message_agent`/`bot_mode_dm`) et la forme de l'accusé JSON ne sont pas
  contractuels côté hermes-agent — tout le couplage est isolé dans `api/bot_mesh.py`.
- Un seul thread « Bot Chat » par profil est supporté (le seul cas observé en prod ce jour).

### Validé sur `.178` puis corrigé (04/09/2026)

29/29 tests ciblés OK, panneau Bots inspecté visuellement — conforme (branches, pastilles,
compteurs, boutons). **Mais** : bouton « Fil inter-bots » absent sur `lancelot` alors qu'il a
des appels `message_agent` en masse dans ses logs.

**Cause trouvée par recon live** : `find ~/.hermes -maxdepth 3 -name state.db` → **chaque
profil a son propre `state.db`** (`~/.hermes/profiles/<nom>/state.db`), aucune base partagée.
`api/bot_mesh.py` et `api/bots_overview.py` ne lisaient que `~/.hermes/state.db` (celui du
profil racine `default`) — `has_bot_chat`, `active_sessions` et `last_activity` étaient donc
faux pour tous les profils sauf `default`. **Corrigé** (commit `94c4246d`) : chaque lecture
résout d'abord `get_hermes_home_for_profile(profil)` et ouvre la base de CE profil. Tests
réécrits pour donner à chaque profil sa propre base (comme en prod) + un test de non-régression
« un profil sans base n'hérite jamais des sessions d'un autre ». Bug d'affichage additionnel
corrigé au passage (commit `76bab0ec`) : les rangées débordaient dans le panneau latéral étroit
(grid à colonnes fixes) — passé en flex-wrap.

### Non lancé ici

- Le correctif per-profile-db (`94c4246d`) et le correctif de mise en page (`76bab0ec`)
  **n'ont pas encore été revalidés sur `.178`** — à faire avant de considérer B3 clos.
- Les 2 vérifs live du plan restent ouvertes : pilotage depuis WebUI, fuite Pro/Perso.

---

## B4 — continuer la vraie conversation d'un bot depuis WebUI

**Branche** : `feat/b4-continue-bots` (part de `feat/b3-bot-chat-viewer`).
**Objectif** : lever la limite « lecture seule » de B3 — répondre dans WebUI doit continuer la
session agent-native du bot (« Bot Chat »), pas ouvrir une session WebUI parallèle.

### Backend

| Fichier | Rôle | Couplage amont |
| :-- | :-- | :-- |
| `api/bot_mesh.py` | `continue_bot_chat(profil)` : importe la session réelle du bot dans le store WebUI **sous son vrai `session_id`**, en déléguant à `get_cli_session_messages` + `import_cli_session`. `resync_bot_chat_if_stale` : re-import quand la base du bot a grossi hors WebUI. `last_bot_chat_snippet*` : aperçu du dernier tour. | **`api.models.get_cli_session_messages` / `import_cli_session`** — le pont « importer une session CLI » déjà en place côté amont. |
| `api/streaming.py` | WebUI devient participant du bail d'exclusivité de session de l'agent (`_bot_chat_lease`) : deux surfaces ne streament plus la même session Bot Chat en même temps. | Protocole de bail côté hermes-agent — non contractuel, isolé dans `api/bot_mesh.py`. |
| `api/routes.py` | `POST /api/bot-chat/continue`. Live-refresh branché dans le `GET /api/session` métadonnées-seules (réutilise le heartbeat 30 s existant du front plutôt qu'un 2e polling). | — |

### Frontend

Rendu dédié des tours de relais **entrants** (`_relayInboundMatch`, texte
`Message from 🤖 x (@x): …` écrit par l'agent) et des appels `message_agent` **sortants**
(carte outil `relay`). Tests : `tests/test_bot_mesh_continue.py`,
`test_bot_mesh_session_lease.py`, `test_bot_chat_live_refresh.py`,
`test_relay_inbound_message_card.py`, `test_message_agent_tool_card.py`.

### Validé

Déployé et vérifié sur `.178` — voir `docs/fork/PLAN-B4-fusion-conversation.md` pour le journal des
validations live (import multi-bots, tours réels, bots à la demande).

---

## B4-UX — refonte du panneau Bots, itérations 1 et 2

**Branche** : `feat/b4-continue-bots` (suite).

### Itération 1 (commit `05a7da0a`) — déployée

Vignette avatar par bot (`emoji` + `color` dans `api/bots_hierarchy.json`, repli couleur par
hash côté front), aperçu du dernier message, polling 15 s du panneau.

### Itération 2 (commits `b36b9832` → `d6679839`)

Demandée par Ludo après avoir vu l'itération 1 en prod. Feuille de route d'origine :
`docs/fork/PROMPT-bots-panel-ux-rework.md`.

| # | Changement | Fichiers |
| :-- | :-- | :-- |
| 1-5 | Vignette entière cliquable (`data-card-act`, `role="button"`, clavier) ; actions secondaires, pastille « N sessions » et badge passerelle permanente repliés derrière un `···` ; nom du modèle retiré. | `static/bots_panel.js`, `static/bots_panel.css` |
| 6 | Panneau Bots **collant** : `switchPanel(name, {keepSidebarPanel:true})` ne change que la vue centrale, la sidebar garde son panneau affiché. Le polling de la liste se cale sur la visibilité réelle de `#panelBots`, plus sur `_currentPanel`. | `static/panels.js` (hooks), `static/bots_panel.js` |
| 7 | Fil « Bot Chat » épuré : `#messages[data-bot-chat]` masque les réveils machine (`[IMPORTANT: Background process …]`, `[Cronjob "…" …]`) et la barre de trace ; le contenu masqué est listé à la demande dans un onglet **Trace** du panneau Workspace. | `static/ui.js`, `static/workspace.js`, `static/bots_panel.js` |
| 8 | Doublon `default` : `list_profiles_api` renvoie deux lignes homonymes quand `<HERMES_HOME>/profiles/default/` existe **en plus** du home de base (confirmé sur `.178`), parce que `_build_profile_rows_fast` code en dur le nom `'default'` pour le home de base. Dédoublonnage par nom **dans le panneau seulement**. | `api/bots_overview.py` |
| 9 | Profil racine affiché **« Assistant »** : `root_profile_display_label()` + `display_name` sur chaque ligne de `list_profiles_api`, résolu côté front par `profileDisplayName()`. Affichage seul — `default` reste l'identifiant partout. | `api/profiles.py`, `static/panels.js`, `static/boot.js` |
| 10 | Bouton Bots en 2e position du rail (deux copies), icône tête de robot. | `static/index.html` |
| 11 | Branche `"hidden": true` dans `bots_hierarchy.json` : les profils internes sortent de la liste **et** des compteurs, avant même le scan des `state.db`. | `api/bots_overview.py`, `api/bots_hierarchy.json` |
| 12 | Personnalisation par bot (nom + photo) : store dédié `<HERMES_HOME>/webui/bot_customization.json` + `bot_avatars/`. Format d'image déterminé en **reniflant les octets**, jamais d'après le nom du fichier envoyé. | `api/bot_customization.py` (nouveau) |

**Réserve assumée (point 7)** : les tableaux de statut consolidés sont du markdown d'assistant
ordinaire — c'est le bot qui les écrit. Les masquer masquerait du contenu légitime ; c'est le
prompt du bot qu'il faut changer, pas le front.

**Limite connue (point 8)** : le doublon est corrigé **dans le panneau Bots seulement**. Il
reste visible partout où `list_profiles_api` alimente l'UI (sélecteur de profil, panneau Agent
profiles). Corriger à la source déplacerait ces deux surfaces — à traiter séparément.

---

## Heure exacte dans le prompt WebUI

**Objectif** : qu'un bot cesse d'inventer l'heure. Constat du 06/09/2026 : Roi-arthur annonce
« Heures d'envoi (UTC) : 06/09/2026 ~15:22 » alors que l'horloge de `.178` lit 10:22 UTC
(12:22 CEST). Les horloges sont justes et le rendu WebUI n'est pas en cause.

**Cause** : l'amont Hermes (`agent/system_prompt.py`, `_timestamp_line()`) n'injecte que la
**date**, délibérément — la ligne est rendue byte-stable pour la journée afin que le préfixe de
prompt reste caché — et renvoie le modèle vers un outil pour l'heure exacte
(« query tools for exact time »). Les modèles gratuits sur lesquels tournent les bots ne font
jamais cet appel : ils estiment une heure et l'affirment, parfois en étiquetant « UTC » une
heure locale.

| Fichier | Changement | Couplage amont |
| :-- | :-- | :-- |
| `api/fork_time_context.py` (nouveau, 100 % fork) | `webui_time_context_prompt(now=None)` : bloc « Current time (authoritative…) » avec heure locale (abréviation + décalage) **et** UTC, plus la consigne de s'en servir, de ne jamais estimer une heure et de ne jamais rebaptiser en UTC une heure locale. Sortie ASCII pure et format numérique (`%A`/`%B`/`%Z` sont localisés — `turn_recovery` de l'agent dépouille le prompt éphémère de son non-ASCII chez certains fournisseurs). | aucun |
| `api/streaming.py` | 10 lignes dans `_webui_ephemeral_system_prompt()` : le bloc est ajouté après `_WEBUI_PROGRESS_PROMPT`, import à l'intérieur de la fonction, `try/except` — une panne de l'horloge ne doit pas casser un tour. | fonction amont `_webui_ephemeral_system_prompt` (déjà touchée par l'amont pour la surface/livraison). |
| `tests/test_fork_time_context.py` (nouveau) | 6 tests : locale + UTC affichés, consignes présentes, sortie ASCII, entrée UTC, suivi de l'horloge serveur, présence effective dans le prompt éphémère (les blocs amont restant intacts). | — |

**Coût assumé** : le prompt éphémère est injecté à l'appel API (jamais persisté), mais il est
**en tête** de la requête ; une précision à la minute fait donc tomber le cache de préfixe entre
deux tours espacés de plus d'une minute. Arbitrage explicite retenu avec Ludo : une heure fausse
affirmée avec aplomb coûte plus cher qu'un cache manqué. Sans effet sur les modèles gratuits
(OpenRouter), facturable sur Vertex/Anthropic si l'usage y bascule.

**Portée** : les tours pilotés depuis WebUI (dont le manager qu'on relance via « Continuer »).
Un bot qui répond à un `message_agent` **hors** WebUI tourne sous la passerelle et ne voit pas ce
bloc — il reste sur la date seule de l'amont. Étendre côté agent serait un patch amont, non fait.

---

## E — correction des écarts de fond (06/09/2026)

Suite de `docs/fork/PLAN-ecarts-de-fond.md`, exécutée avec les décisions de Ludo du 06/09/2026
(D1 détection seule, D2 panneau transverse, D3 spike C1, D4 redémarrage conditionné, D5 les 18
gateways restent permanents). Quatre des huit écarts se sont réglés **hors code** — c'est le
résultat, pas un raccourci.

### E1a — canaux inter-bots : détecter, pas bloquer

| Fichier | Changement | Couplage amont |
| :-- | :-- | :-- |
| `api/bots_hierarchy.json` | clé `channels` : les 26 arêtes bot-à-bot de la spéc du vault (les 30 canaux annoncés incluent 4 canaux Ludo↔bot, hors `message_agent`), plus `wildcard_senders` pour Merlin (règle assouplie le 05/09). Lue bidirectionnellement, et la carte se vérifie elle-même. | aucun (données) |
| `api/bot_channels.py` (nouveau, 100 % fork) | `is_allowed` (`True`/`False`/`None`), `classify_relay`, `audit_relays`, `map_inconsistencies`, `GET /api/bot-channels/audit`. | `api.bot_mesh` (fork), `api.bots_overview._operator_hierarchy_path` (fork) |
| `api/bot_mesh.py` | chaque tour `relay_out` porte `channel_ok` / `channel_target`. Sans carte : `None`, le fil s'affiche comme avant. | — |
| `static/bots_panel.js` / `.css` | pastille « hors spec » sur la carte de relais, bouton « Canaux » + rendu de l'audit. | — |

**Détection seule, par décision.** L'agent (`tools/bot_mode_dm.py`) valide la cible contre le
roster **complet** et présente les 17 autres bots comme « teammates » : rien n'empêche un envoi
hors spec, et ce fork ne l'empêche pas non plus. Un test (`test_audit_is_read_only`) verrouille
cette propriété — le jour où ça deviendra un garde-fou, ce sera une décision, pas un effet de bord.

**Un couple hors carte donne `None`, jamais « hors spec »** : accuser un profil simplement
inconnu (créé après la spéc, cible sur une machine pair) discréditerait tous les autres verdicts.

**Coût assumé** : l'audit scanne les Bot Chats, bien plus cher que les 8 lignes que lit le poll
de 15 s. D'où une route à la demande, pas un compteur temps réel.

### E3 — badge « non lu » par bot

| Fichier | Changement |
| :-- | :-- |
| `api/bot_seen.py` (nouveau, 100 % fork) | store `<HERMES_HOME>/webui/bot_seen.json` (même patron que `bot_customization.json` : écriture atomique, lecture qui n'échoue jamais), `mark_seen`, `unread_for`, `baseline_unseen_profiles`, `POST /api/bots/seen`. |
| `api/bots_overview.py` | `_bot_chat_stats_on_connection` remplace `_last_message_preview_on_connection` : même connexion `state.db`, un `COUNT(*)` de plus. Chaque bot porte `bot_chat_messages` + `unread` ; `counts.unread` pour le rail. |
| `api/routes.py` | +4 lignes : aiguillage de `POST /api/bots/seen` et `GET /api/bot-channels/audit`. |
| `static/bots_panel.js` / `.css` / `i18n_fork.js` | badge sur la carte, badge sur le bouton Bots du rail (injecté en JS — zéro ligne dans `index.html`), poll de 60 s **quand le panneau est masqué**, marquage lu à l'ouverture. |

**Repère côté serveur, pas `localStorage`** : WebUI sert de porte d'entrée depuis le téléphone
comme depuis le poste ; un badge par navigateur rendrait « non lus » des messages déjà lus
ailleurs, et un compteur qui ment selon l'appareil cesse d'être consulté.

**Démarrage silencieux** : au premier passage, la ligne de base est posée au compte courant.
Sans ça, la première ouverture afficherait 18 badges portant tout l'historique.

**Unité** : le nombre de lignes de la Bot Chat dans le `state.db` du bot — le même compteur que
`resync_bot_chat_if_stale`, donc juste même quand un message arrive par le relais ou un cron.

### E2 / E4 / E5 / E7 — réglés hors du code de l'application

* **E2 (cloisonnement Pro/Perso)** — campagne menée : sessions et projets étaient déjà scopés par
  l'amont ; le **workspace** ne l'était pas (les 18 profils partageaient `/home/atx/workspace`,
  `guenievre` comprise). Le dossier était vide : rien n'avait fuité. Corrigé **côté exploitation**
  — l'amont résout déjà `last_workspace.txt` par profil, chaque bot a reçu son dossier.
  `tests/test_profile_isolation.py` verrouille ce contrat amont : s'il redevenait global, les 18
  bots repartageraient un workspace en silence. Le panneau Bots reste transverse (décision D2),
  et un test l'acte pour qu'un futur durcissement ne le « corrige » pas par zèle.
* **E4 (doublon `default`)** — cause trouvée : `~/.hermes/profiles/default/` ne contenait que des
  copies du script de relais déployées le 04/09 ; ce n'était pas un profil. Le job cron résout
  `<HERMES_HOME>/cron/../scripts`, donc le home de base — le dossier était vestigial. Déplacé en
  `~/.hermes/retired/`. Le doublon disparaît **partout** (sélecteur de profil et panneau Agent
  profiles compris), à coût de code nul. Le dédoublonnage du panneau Bots reste en place comme
  filet.
* **E5 (heure hors WebUI)** — la règle « tu n'as aucune horloge » existait déjà dans les 17
  `SOUL.md`. Elle **contredisait** le bloc d'heure que le fork injecte dans les tours WebUI : un
  bot serait allé chercher `date` pour une heure qu'on venait de lui donner. Une exception
  explicite a été ajoutée aux 17 fiches (idempotent, sauvegardes `.bak-20260906-clock`). Aucun
  patch de l'agent : celui-ci ferait payer un cache de préfixe cassé à 18 gateways.
* **E7 (dérive de code)** — l'agent s'est mis à jour **6 fois** le 06/09/2026 ; la dérive est le
  régime permanent, pas un incident. Trois scripts côté `.178` (hors dépôt) :
  `verify_agent_patches.py` (vérifie l'**effet** des patches locaux, pas le code retour de
  `git apply`, et alerte sur Telegram), `agent_update_impact.py` (redémarrage du WebUI **seulement**
  si la mise à jour touche du code qu'il importe — décision D4), et le nettoyage du marqueur
  `fleet_restart_pending` périmé qui produisait de fausses alertes. Validé de bout en bout sur une
  vraie mise à jour.

### E6 / D3 — spike « exécution concurrente »

`tests/test_concurrent_bot_isolation_c1.py` + `docs/fork/SPIKE-C1-execution-concurrente.md`.
Mesure sur agent réel : l'override de home est un **ContextVar** (l'amont refuse explicitement
`os.environ`), `api.profiles._tls` est un thread-local, et les garde-fous « busy » sont par
session. **Deux bots peuvent déjà tourner en même temps sans se mélanger** — le runner du palier
C1 n'est pas ce qui manque. Ce qui manque est l'affichage (C2).

---

## Surface de conflit avec l'amont

`master` est un **miroir pur** de `nesquena/hermes-webui` (aucun commit fork dessus). Tout le
fork vit sur les branches `feat/b*`, rebasées sur `upstream/master` à chaque release amont —
**rebase, jamais merge de l'amont dans la branche**, sinon la pile de divergences devient
illisible et ce fichier perd son sens.

### Fichiers 100 % fork (ne peuvent jamais entrer en conflit)

`api/bot_mesh.py`, `api/bots_overview.py`, `api/bot_customization.py`, `api/bots_hierarchy.json`,
`api/fork_time_context.py`, `api/bot_seen.py`, `api/bot_channels.py`,
`static/bots_panel.js`, `static/bots_panel.css`, `static/i18n_fork.js`, et tous les
`tests/test_bot*.py` / `tests/test_bots*.py` / `test_gateway_multiprofile_b1.py` /
`test_relay_inbound_message_card.py` / `test_message_agent_tool_card.py` /
`test_root_profile_display_name.py` / `test_fork_upstream_contract.py` / `test_fork_time_context.py` /
`test_profile_isolation.py` / `test_concurrent_bot_isolation_c1.py`.

### Extraction (05/09/2026) — pourquoi ces trois fichiers existent

Le front du panneau Bots vivait dans `static/panels.js` (+522 lignes), ses styles à la fin de
`static/style.css` (+134), et ses ~34 clés i18n étaient recopiées dans les **15** blocs de
locale de `static/i18n.js` (+497). Soit ~1 150 lignes ajoutées dans trois des fichiers les plus
chauds de l'amont, pour du code que l'amont ne touche jamais : chaque release devenait un
conflit de rebase gratuit. Extraits vers `bots_panel.js` / `bots_panel.css` / `i18n_fork.js` :

* `static/i18n.js` et `static/style.css` sont désormais **identiques à l'amont** (zéro conflit).
* `i18n_fork.js` ne fournit que **en + fr** : `t()` retombe déjà sur `LOCALES.en` pour toute clé
  manquante, donc les 13 autres locales se comportent exactement comme quand elles portaient le
  texte anglais recopié.
* Les corps des handlers HTTP du fork ont quitté `api/routes.py` pour les modules qui possèdent
  la fonctionnalité (`bot_mesh`, `bots_overview`, `bot_customization`) — chaque route du fork
  n'est plus qu'un aiguillage de deux lignes. `j` / `bad` / `_sanitize_error` sont importés
  **dans** les fonctions : `api.routes` importe ces modules au moment de l'aiguillage, un import
  au niveau module serait circulaire.

Ordre de chargement (dans `static/index.html`, et à répliquer dans `static/sw.js`) :
`bots_panel.css` **après** `style.css` (une règle fork gagne une égalité de spécificité),
`i18n_fork.js` **après** `i18n.js` (il écrit dans `LOCALES`), `bots_panel.js` **avant**
`panels.js`.

### Ce qui reste dans les fichiers amont (surface irréductible)

| Fichier | Lignes | Pourquoi ça ne peut pas sortir |
| :-- | --: | :-- |
| `api/routes.py` | ~190 | B1 modifie l'**intérieur** de fonctions amont (`_gateway_status_payload`, `_run_gateway_lifecycle_command`, `_handle_gateway_lifecycle`) ; le reste est l'aiguillage des routes du fork. |
| `static/ui.js` | ~100 | Rendu des relais et des cartes d'outil **entrelacé** avec le code amont (`_toolActionKind`, tables de verbes, mappes d'icônes). Extraire les ~55 lignes autonomes laisserait quand même ~45 lignes entrelacées : un rebase devrait ouvrir le fichier de toute façon. Non fait délibérément. |
| `api/streaming.py` | ~55 | Bail d'exclusivité de session, à l'intérieur de la boucle de streaming amont ; + 10 lignes d'appel du bloc d'heure dans `_webui_ephemeral_system_prompt`. |
| `api/profiles.py` | ~36 | `list_profiles_api` devient un wrapper autour de `_list_profiles_rows`. |
| `static/index.html` | ~18 | Chargement des 3 assets fork, bouton Bots du rail (×2), panneau `#panelBots`, onglet Trace. |
| `static/workspace.js` | ~17 | Branche `trace` dans `switchWorkspacePanelTab` (fonction amont). |
| `static/panels.js` | ~51 | Hooks `switchPanel` (`keepSidebarPanel`, `loadBotsPanel`) + `profileDisplayName`. |
| `static/sw.js` | 3 | Les 3 assets fork dans le cache du service worker. |
| `static/boot.js` | 3 | Libellé du profil actif au boot. |

Total : **~1 176 lignes ajoutées avant l'extraction, ~460 après**.

### Garde-fou

`tests/test_fork_upstream_contract.py` vérifie que chaque helper **privé** de l'amont dont le
fork dépend existe toujours (`api.profiles._tls`, `_PROFILE_ID_RE`, `_resolve_base_hermes_home`,
`_build_profile_rows_fast`, `api.models.get_cli_session_messages` / `import_cli_session`,
`api.upload.parse_multipart`, `hermes_cli.profiles._check_gateway_running`), ainsi que les
contrats implicites (titre de session `'Bot Chat'`, grammaire des réveils de processus, repli
`LOCALES.en` de `t()`, ordre de chargement des assets). La plupart de ces appels vivent dans des
`try/except` — sans ce test, une disparition côté amont serait **silencieuse**. À lancer en
premier après chaque `git rebase upstream/master`.
