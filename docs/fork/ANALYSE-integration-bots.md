# Analyse — intégration du système de bots Hermes dans Hermes WebUI

> Dépôt analysé : fork `ATX-AI-Dev/hermes-webui` (miroir exact de `nesquena/hermes-webui`
> au commit `e168b67e`, release `exp-v0.52.264`). Aucun commit propre au fork à ce jour.
> Analyse réalisée le 2026-09-04. Contexte écosystème : voir vault Obsidian
> `infra/hermes-webui.md`, `infra/hermes-bots-hierarchie.md`, `infra/hermes-discord-integration.md`.

---

## 1. Résumé exécutif

**L'intégration est possible et, pour l'essentiel, déjà amorcée** : dans Hermes WebUI, un
**profil = un bot**. Les 18 profils de la hiérarchie (`roi-arthur`, `lancelot`, `pere-blaise`,
les bots Pro, les bots Perso, `merlin`, `default`) sont déjà visibles dans le sélecteur de
profil, avec pour chacun l'état du gateway, le modèle et le nombre de skills.

Ce que WebUI sait faire aujourd'hui vis-à-vis des bots : **basculer** de l'un à l'autre sans
redémarrage, **isoler** leur contexte (env, mémoire, skills, cron, workspace, sessions),
**afficher** en temps réel les sessions de messagerie (Telegram/Discord/Slack) de n'importe quel
bot, et **piloter le cron** de chaque profil (y compris les jobs « ping de rattrapage
`message_agent` »).

Ce que WebUI **ne sait pas faire** : représenter la **communication entre bots**
(`message_agent` / `bot_mode_dm`) comme un objet de première classe. Le terme n'apparaît nulle
part dans le code. WebUI *observe* les échanges inter-bots (via les sessions Telegram/Discord
par bot, ou via les tours de rattrapage cron) mais ne les *orchestre* pas et n'offre aucune
visualisation « qui parle à qui ». Il n'existe pas non plus de vue multi-bots simultanée, ni de
pilotage de gateway pour un profil autre que le profil actif.

**Recommandation** : viser un palier **additif et léger** (nouveau panneau « Bots / Hiérarchie »
en lecture seule + contrôle gateway multi-profils + carte d'appel d'outil dédiée pour
`message_agent`). Éviter le « cockpit multi-panneaux » tant que le découplage agent/WebUI amont
(#1925) n'est pas livré : il se heurterait au modèle d'exécution mono-requête de WebUI et
imposerait une divergence de fork coûteuse à maintenir contre un amont très actif.

---

## 2. Analyse du système existant

### 2.1 Architecture générale

| Aspect | État |
| :--- | :--- |
| Backend | Serveur HTTP `http.server` (stdlib Python), routage `if/elif` dans `api/routes.py` (~224 routes), pas de framework |
| Frontend | JS vanilla, pas de build/bundler (`static/*.js`, fichiers volumineux mono-blocs) |
| Exécution agent | **En processus** : WebUI importe `run_agent`, `tools/*`, `cron/*` depuis le venv Hermes et lit directement `HERMES_HOME`. Pas d'appel à une API externe pour le chat par défaut. |
| Couplage | **Fort et assumé** : `api/config.py`, `api/providers.py`, `api/streaming.py` importent des modules internes de hermes-agent. Le découplage (API stable) est suivi dans les issues amont #1925 et #2491, **non livré**. |
| Modèle de concurrence | `HERMES_HOME` et consorts sont posés dans `os.environ` **au niveau processus** avant chaque run agent puis restaurés. `ARCHITECTURE.md` : *« Two concurrent chat requests will clobber each other. This is safe only for single-user, single-concurrent-request use. »* Correctif = « Phase B », non fait. |
| État runtime | Hors dépôt : `~/.hermes/webui/` (sessions JSON, settings, projects, workspaces). |

**Conséquence pour le projet bots** : tout ce qui suppose **plusieurs bots actifs en parallèle
dans la même page** entre en collision frontale avec le modèle mono-profil/mono-requête. Toute
fonctionnalité « un bot à la fois, on observe les autres » est en revanche dans le grain du
projet.

### 2.2 Profils = bots (ce qui est déjà là)

- **`api/profiles.py`** (~2700 lignes) : CRUD complet, `switch_profile()` recharge config /
  skills / mémoire / cron / modèles **sans redémarrage**, isolation par profil du `.env`
  (secrets), du `HERMES_HOME`, du workspace, des sessions, du cache d'instances agent.
- **`list_profiles_api()`** renvoie pour chaque profil : `gateway_running` (bool, vérifié par
  `_check_gateway_running(home)` profil par profil), modèle par défaut, stats skills.
- **Frontend** : sélecteur de profil dans le *composer footer* + panneau Profils (CRUD) ;
  pastille verte = gateway du profil en cours d'exécution ; le modèle et le compte de skills
  sont affichés par profil.
- **`ROADMAP.md`** : « Multi-profile support » (#28), « Concurrent per-profile isolation
  (context-local home override so parallel workers can't clobber each other) » — l'isolation
  *par worker détaché* existe (`profile_env_for_background_worker`, `profile_scope_for_detached_worker`),
  mais le run de chat interactif reste process-global.

C'est la brique la plus solide : **la notion de bot est native**, il « suffit » d'ajouter des
vues d'ensemble.

### 2.3 Gateways de messagerie (Telegram / Discord / Slack…)

- **`api/gateway_watcher.py`** : thread démon qui *poll* `state.db` toutes les 5 s et pousse en
  SSE les changements de sessions gateway. Effet : **les échanges d'un bot sur Telegram/Discord
  apparaissent comme des sessions dans la sidebar**, en quasi temps réel, avec un badge de
  source.
- **`api/routes.py`** : `/api/gateway/status` (état du gateway **du profil actif** :
  `running`, `configured`, `platforms`, `session_count`, `last_active`) et
  `/api/gateway/start|stop|restart` → `_run_gateway_lifecycle_command(action)`.
- **Limite forte** : `_handle_gateway_lifecycle` fait `del body  # Reserved for future
  per-gateway naming without changing the route contract` et
  `_run_gateway_lifecycle_command` résout **toujours le profil actif**
  (`get_active_profile_name()`). On **ne peut pas** démarrer le gateway de `bohorth` pendant
  que `lancelot` est le profil actif. Le contrat de route est cependant *déjà prévu* pour
  recevoir un `profile` dans le corps.
- **`api/gateway_chat.py`** (~1500 lignes) : pont **optionnel** (`HERMES_WEBUI_CHAT_BACKEND=gateway`)
  pour router le chat navigateur via un Hermes Gateway API server. Concerne le transport du
  chat, **pas** la messagerie inter-bots.

### 2.4 Délégation / sous-agents (ce qui existe et ne doit pas être confondu)

- **README** : « Subagent delegation cards — child agent activity shown with distinct icon and
  indented border » et « Orchestrates other agents — can spawn Claude Code or Codex ».
- **`api/process_event_utils.py`**, **`api/background_process.py`** : plomberie de **livraison
  durable** des complétions de `delegate_task` / `async_delegation` (événements `type ==
  "async_delegation"`, `delegation_id`, claim/retry/restore). PR amont #2279.
- ⚠️ **C'est le sous-agent *intra-session* de Hermes** (spawn Claude Code / Codex / sous-agent
  interne dans le fil courant), **pas** le mesh `message_agent` entre profils Hermes distincts.
  Les deux mécanismes sont différents ; seul le premier a une UI.

### 2.5 Cron par profil (utile pour le rattrapage `message_agent`)

- Routes : `/api/crons`, `/api/crons/create` (`{prompt, schedule, name?, deliver?, skills?,
  model?}`), `/update`, `/delete`, `/pause`, `/resume`, `/run`, `/history`, `/output`,
  `/status`, **`/api/crons/delivery-options`**.
- Le cron est résolu **dans le contexte du profil** (`cron_profile_context()`,
  `install_cron_scheduler_profile_isolation()`).
- Effet concret : les jobs « `ping-rattrapage-<profil>` » documentés dans
  `infra/hermes-bots-hierarchie.md` (mitigation du défaut fire-and-forget de `message_agent`)
  sont **visibles, éditables, pausables** depuis le panneau Tasks, profil par profil. Le
  paramètre `--deliver bot-chat:<profil>` correspond aux `delivery-options`.

### 2.6 `mcp_server.py`

Expose en MCP (stdio) **uniquement** la gestion des projets/sessions WebUI (`list_projects`,
`create_project`, `rename_session`, `move_session`, `list_sessions`). Aucun outil de messagerie
inter-bots. Piste marginale pour ce projet.

### 2.7 Agrégation multi-profils déjà présente (sous-exploitée)

`api/models.py` sait déjà projeter les sessions **tous profils confondus** :
`_all_profiles_cli_contexts()`, paramètre `all_profiles=True` dans les projections de sessions,
et `kanban_bridge` mentionne un mode `all_profiles=True`. Il existe donc **déjà** un chemin
serveur pour lister l'activité de tous les bots — il n'est simplement pas exposé comme une vue
« hiérarchie ».

---

## 3. Écart entre l'existant et le besoin « bots qui communiquent »

| Besoin | Couvert par WebUI ? | Détail |
| :--- | :--- | :--- |
| Adresser un bot précis | ✅ | Sélecteur de profil ; devenir le contexte du bot |
| Mémoire / skills / cron cloisonnés par bot | ✅ | Isolation native `api/profiles.py` |
| Voir l'activité de messagerie d'un bot (Telegram/Discord) | ✅ | `gateway_watcher.py` → sessions en sidebar, temps réel |
| Voir/éditer le cron d'un bot (dont rattrapage `message_agent`) | ✅ | Panneau Tasks, contexte profil |
| Démarrer/arrêter le gateway d'un **autre** bot que l'actif | ❌ | `_run_gateway_lifecycle_command` = profil actif seulement (contrat de route déjà prévu pour un `profile`) |
| Vue d'ensemble de tous les bots (état, modèle, dernière activité, sessions actives) | ❌ (briques présentes) | `list_profiles_api` + `all_profiles` existent, pas de panneau qui les agrège |
| Représenter `message_agent` / `bot_mode_dm` comme événement de première classe | ❌ | Terme absent du dépôt. Un appel `message_agent` dans un tour *piloté par WebUI* s'affiche en carte d'outil générique (nom + args + résultat) ; un appel dans un tour piloté par le gateway/CLI n'est visible qu'indirectement |
| Visualiser la hiérarchie / le routage (pilote → manager → bots) | ❌ | Aucune notion d'organigramme ni de graphe de routage |
| Vue multi-bots simultanée (« war room ») | ❌ | Modèle mono-profil / mono-requête, `HERMES_HOME` process-global |
| Faire respecter le cloisonnement Pro/Perso dans l'UI | ❌ | Signalé comme risque à tester dans `infra/hermes-webui.md` (fuite de contexte entre branches via sessions/historique/workspace) |

---

## 4. Options d'intégration

### Palier A — Observation seule (effort ~nul, zéro dérive de fork)

N'ajoute **aucun code**. On s'appuie sur : sélecteur de profil + sessions gateway en sidebar +
panneau Tasks (cron). Les échanges inter-bots sont visibles via les sessions Telegram/Discord
de chaque bot et via les tours de rattrapage cron. C'est exactement le « cap visé » décrit dans
`infra/hermes-webui.md`.

- **Pour** : rien à maintenir, aucune rebase, aucun risque de couplage.
- **Contre** : pas de vue d'ensemble ; le `message_agent` reste illisible en tant que tel ;
  contrôle gateway limité au profil actif ; cloisonnement Pro/Perso non garanti.
- **À faire** : tester explicitement la fuite de contexte Pro/Perso lors d'un changement de
  profil dans le même navigateur (sessions, historique, fichiers workspace).

### Palier B — Ajouts légers et additifs (effort moyen, maintenable en patches de fork) — **recommandé**

Trois fonctionnalités, toutes additives, sans toucher au modèle d'exécution :

1. **Contrôle gateway multi-profils.**
   `POST /api/gateway/{start,stop,restart}` accepte déjà un `body` réservé. Faire passer
   `profile` (validé par `_PROFILE_ID_RE`), et passer ce profil à
   `_run_gateway_lifecycle_command` (qui construit déjà `--profile <name>` pour le restart dans
   `gateway_restart.py`). `/api/gateway/status?profile=<name>` de même.
   → Depuis l'UI : démarrer/arrêter le canal de n'importe quel bot sans le rendre actif.
   *Charge* : ~1 fichier backend, 1 bouton par ligne dans un futur panneau Bots.

2. **Panneau « Bots / Hiérarchie » en lecture seule.**
   Nouvel onglet (comme Tasks/Skills/Memory dans `panels.js`). Agrège, pour les 18 profils :
   `list_profiles_api()` (gateway on/off, modèle, skills) + `hermes -p <profil> cron status`
   (scheduler actif, prochain run — utile pour vérifier les jobs de rattrapage) + projection
   `all_profiles=True` de `api/models.py` (nb de sessions actives, dernière activité par bot).
   Optionnel : rendre l'arbre hiérarchique (pilote → managers → bots, branches Pro/Perso) à
   partir d'un simple fichier de config statique (le vault a déjà l'organigramme).
   *Charge* : 1 route d'agrégation backend + 1 panneau frontend. Pas de dépendance nouvelle.

3. **Carte d'outil dédiée pour `message_agent` / `bot_mode_dm`.**
   Dans le rendu des tool-calls (`static/ui.js`, `static/messages.js`), détecter le nom d'outil
   `message_agent` (et `bot_mode_dm`) et afficher une carte distincte « Message inter-bots »
   (émetteur → destinataire, contenu, accusé), sur le modèle de la carte sous-agent existante.
   Ça ne fonctionne que pour les tours **pilotés par WebUI** ; pour les tours gateway/CLI,
   documenter que la source de vérité reste `~/.hermes/profiles/<bot>/logs/agent.log` (comme
   déjà noté dans le vault).
   *Charge* : rendu frontend uniquement, ~1 carte.

- **Pour** : couvre l'essentiel du besoin (adresser, observer, superviser l'ensemble),
  patches petits et localisés, rebase gérable.
- **Contre** : toujours pas de pilotage *actif* du mesh depuis l'UI (envoyer un message
  bot→bot) ; toujours mono-bot simultané.
- **Risque de couplage** : la carte `message_agent` dépend du nom d'outil exposé par
  hermes-agent (stable en pratique, mais non contractuel avant #1925).

### Palier C — Cockpit multi-bots (effort élevé, forte divergence de fork, hostile à l'amont)

Vues multi-panneaux simultanées, organigramme vivant, graphe de routage temps réel, **envoi**
de `message_agent` depuis l'UI, sessions de plusieurs bots ouvertes en parallèle.

- **Bloqueurs** :
  - Modèle `HERMES_HOME` process-global + hypothèse « single-user, single-concurrent-request »
    (`ARCHITECTURE.md`). Prérequis : la « Phase B » (isolation concurrente du run de chat),
    non faite.
  - Couplage non découplé (#1925 / #2491) : atteindre `tools/bot_mode_dm.py` ou les internes de
    `message_agent` expose à la casse à chaque release « exp » (fréquentes — l'amont a 326
    contributeurs).
  - Contrainte machine `.178` (i5-2520M, 12 Go) : un cockpit qui suppose tous les gateways
    permanents contredit la politique de Ludo (5 permanents max).
- **Verdict** : à ne pas engager tant que le découplage amont n'a pas atterri. Sinon, fork
  quasi-permanent à maintenir à la main.

---

## 5. Recommandation

1. **Court terme** : palier **A** immédiatement (rien à coder), + **test de cloisonnement
   Pro/Perso** dans l'UI (point de vigilance déjà listé au vault).
2. **Moyen terme** : palier **B**, dans l'ordre B1 → B2 → B3. B1 (gateway multi-profils) est le
   meilleur rapport valeur/effort et le plus sûr (le contrat de route l'anticipe déjà). B2
   (panneau Bots read-only) transforme WebUI en véritable poste de supervision de la hiérarchie
   sans rien casser. B3 (carte `message_agent`) est cosmétique mais rend le mesh lisible.
3. **Ne pas faire** : palier C avant la livraison de l'API agent stable amont (#1925). Le
   suivre dans le vault (`suivi/taches-en-attente.md`) comme dépendance externe.
4. **Discipline de fork** : garder chaque ajout dans des fichiers/patches isolés et petits,
   documenter chaque divergence, et rebaser régulièrement sur `nesquena/hermes-webui` (le fork
   `ATX-AI-Dev` est aujourd'hui un miroir sans commit propre — c'est le bon moment pour poser
   une convention).

---

## 6. Points à confirmer avant de coder (questions ouvertes)

- Le mesh intra-branche et la remontée managers→pilote sont-ils appliqués **nativement** par
  Hermes, ou à configurer dans les instructions de chaque bot ? (déjà listé au vault — impacte
  si B3 doit juste *afficher* ou aussi *expliquer* le routage)
- `hermes-agent` expose-t-il un nom d'outil stable pour la messagerie inter-bots
  (`message_agent` vs `bot_mode_dm` — le vault cite les deux) ? À vérifier sur `.178` :
  `grep -rn "def message_agent\|bot_mode_dm" <venv Hermes>/tools/`.
- WebUI en changement de profil : y a-t-il fuite de sessions/historique/workspace entre
  branches Pro et Perso ? (test bloquant avant usage courant multi-bots)
- Souhait réel : **superviser** les bots depuis le navigateur (palier B suffit), ou **piloter
  activement** les échanges bot→bot depuis l'UI (palier C, non recommandé pour l'instant) ?
