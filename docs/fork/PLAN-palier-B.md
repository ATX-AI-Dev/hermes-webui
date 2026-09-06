# Palier B — plan d'implémentation

> Objectif : faire de Hermes WebUI un poste de supervision + conversation multi-bots
> « façon Hermes Desktop, en full web », sans toucher au modèle d'exécution en processus
> ni dépendre du découplage amont #1925.
>
> Base : fork `ATX-AI-Dev/hermes-webui` au commit `e168b67e` (`exp-v0.52.264`), aujourd'hui
> miroir exact de `nesquena/hermes-webui`. Déployé sur `.178` en service `hermes-webui.service`.

---

## 0. Périmètre

Trois fonctionnalités, toutes **additives** (nouveaux fichiers / nouvelles branches de code,
aucune réécriture) :

| # | Fonctionnalité | Cœur du travail | Dépend de `.178` ? |
| :-- | :-- | :-- | :-- |
| **B1** | Contrôle de passerelle **multi-profils** | Backend : `profile` dans `/api/gateway/*` | non |
| **B3** | **Vue « Bot Chat » + renderer inter-bots** | Surfacer une session masquée + renderer frontend | recon faite ✔ |
| **B2** | Panneau **« Bots / Hiérarchie »** en lecture seule | Route d'agrégation + onglet frontend | non |

Séquence retenue : **B1 → B3 → B2**. B1 débloque les boutons start/stop de B2 ; B3 porte la
valeur que tu as demandée en priorité ; B2 agrège et referme l'ensemble.

Maquettes de référence : `maquette-panneau-bots.html` (B2), `maquette-conversation-bot.html` (B3).

---

## 1. Reconnaissance sur `.178` — résultats (2026-09-04)

Recon menée par Ludo en SSH. **À consigner dans le vault** (`infra/hermes-webui.md`).

### Acquis

1. **Outil** : `message_agent` (constante `MESSAGE_AGENT_TOOL_NAME`), source `tools/bot_mode_dm.py`
   (+ `tools/bot_relay.py` cross-gateway, `tools/bot_mode_probe.py` gating).
   Signature `message_agent_tool(target, message, task_id=None) -> str` → **renvoie une chaîne
   JSON d'accusé** (`{"ok":…}` / `{"error":…, "reason":…}`), jamais la réponse.
2. **Confinement (structurant)** : le schéma de l'outil est **injecté uniquement dans la session
   canonique « Bot Chat » d'un bot**, sur un install Bot-Mode-managed (`ensure_message_agent_tool`).
   Absent des sessions CLI, chats gateway ordinaires, rooms « Group: … », crons, subagents.
   Double gating (injection + exécution). → **Un chat WebUI ordinaire avec `lancelot` n'a pas
   l'outil** : le mesh ne vit que dans la « Bot Chat ».
3. **Réponse différée = cas (b)** : transport `terminal_tool(background=True,
   notify_on_complete=True)` → `hermes -p <cible> chat -c "Bot Chat" …` ; la réponse revient
   comme **completion notification au tour suivant de l'émetteur**, via le background-process
   notification path. Tables dédiées présentes dans `state.db` : `async_delegations`,
   `delivery_obligations`. → **Pas de corrélation backend custom à écrire** ; WebUI a déjà cette
   plomberie (`api/background_process.py`, `api/process_event_utils.py`).
4. **`state.db` unique et partagé** : `/home/atx/.hermes/state.db` (pas de DB par profil).
   Table `sessions` avec colonnes utiles : `profile_name`, `hidden`, `title`, `source`,
   `chat_type`, `session_key`, `archived`, `pinned`, `last_activity_at`, `tool_names`.
5. **La « Bot Chat » est masquée** : 1 seule session `title='Bot Chat'`, `source='tui'`,
   **`hidden=1`**, `message_count=61`. WebUI exclut `hidden=1` (et `source∈{cron,webui}`) de sa
   projection sidebar → **WebUI ne la montre pas aujourd'hui**. Les « Bot Chat » sont créées à
   la demande (`--create-if-missing`) : seuls les bots ayant reçu/émis via le mesh en ont une.
6. **Preuve terrain** : `message_agent` massivement utilisé par roi-arthur, lancelot, perceval,
   pere-blaise, guenievre, angharad, sefriane, gauvain… toujours dans des sessions `tui`
   « Bot Chat », jamais dans une session WebUI.

### Reste à vérifier (live, non bloquant pour B1)

- **B3 pilotable ?** WebUI peut-il *lancer un tour* dans la « Bot Chat » en processus avec
  `message_agent` injecté (`ensure_message_agent_tool` passe-t-il le gate quand `run_agent`
  tourne sur une session titrée « Bot Chat » ?). Décide : B3 lecture seule vs lecture + envoi.
- **Fuite Pro/Perso** au changement de profil dans WebUI (sessions / historique / workspace).
- Combien de bots ont réellement une « Bot Chat » à ce jour (création à la demande).

---

## 2. B1 — Contrôle de passerelle multi-profils

**Constat** : `/api/gateway/{start,stop,restart}` → `_handle_gateway_lifecycle` fait
`del body  # Reserved for future per-gateway naming` ; `_run_gateway_lifecycle_command` résout
**toujours** `get_active_profile_name()`. `/api/gateway/status` idem (profil actif seul).
`api/gateway_restart.py` sait déjà construire `--profile <name>` (paramètre `profile`).

**Changements** (`api/routes.py`, `api/gateway_restart.py`) :

1. `_handle_gateway_lifecycle` : lire `body.get("profile")`, valider avec `_PROFILE_ID_RE`
   (déjà importé dans `gateway_restart.py`), refuser un profil inconnu en 400.
2. `_run_gateway_lifecycle_command(action, profile=None)` : si `profile` fourni et valide,
   l'utiliser au lieu de `get_active_profile_name()` — résoudre `HERMES_HOME` via
   `get_hermes_home_for_profile(profile)` (déjà utilisé par `gateway_restart.py`), ajouter
   `--profile <profile>` sauf pour `default` racine.
3. `_gateway_status_payload(profile=None)` : accepter `?profile=<name>` sur `GET
   /api/gateway/status` et calculer l'état pour ce profil (l'`identity_map` et le health check
   sont déjà résolus par `HERMES_HOME` — les scoper).
4. Garder le comportement actuel quand `profile` est absent (rétrocompat totale).
5. `_GATEWAY_ACTION_LOCK` : passer d'un verrou global unique à un verrou **par profil**
   (`dict[str, Lock]`) pour ne pas sérialiser inutilement des actions sur des bots différents.

**Tests** (`tests/`) : start/stop/status sur un profil non actif ; profil invalide → 400 ;
deux profils en parallèle ne se bloquent pas ; absence de `profile` = comportement legacy.

**Risque** : faible. Contrat de route déjà prévu pour ça. **Effort : ~2–3 j.**

---

## 3. B3 — Vue « Bot Chat » + renderer des échanges inter-bots

**Recadrage après recon §1** : l'échange inter-bots ne se produit **pas** dans une conversation
WebUI ordinaire (l'outil `message_agent` y est absent). Il vit dans la session canonique
**« Bot Chat »** de chaque bot, aujourd'hui **`hidden=1` donc invisible dans WebUI**. B3 =
la rendre visible et lisible, pas ajouter une carte dans le chat courant.

**Constat frontend** : `static/ui.js` a déjà un renderer riche pour `delegate_task` /
`subagent_progress` (icône distincte, bordure indentée, dépliable, ~lignes 18200–18760) et un
renderer générique par `tc.name` (`_toolShortName`, ~ligne 12186) — un appel `message_agent`
s'affiche donc déjà, en carte générique « message_agent ».

**Changements** :

1. **Backend — surfacer la « Bot Chat » (opt-in).** Étendre la projection de sessions
   (`api/agent_sessions.py` / `api/models.py` / `api/gateway_watcher.py`,
   `_WATCHER_EXCLUDED_SOURCES`) pour inclure, sur demande explicite, les sessions
   `hidden=1 AND title='Bot Chat'`, tagguées `bot-chat`, groupées par `profile_name`.
   Nouveau flag `?include=bot-chat` sur la liste de sessions, ou entrée dédiée par bot dans le
   panneau B2 (« Ouvrir le fil inter-bots »). Aucune écriture, lecture seule de `state.db`.
2. **Frontend — renderer dédié `message_agent`** dans la transcript de la « Bot Chat »,
   calqué sur la carte sous-agent :
   - en-tête : `⇄  <émetteur> → <target>` (mono), pastille d'état, heure, chevron ; repliée par
     défaut sauf état « en attente ».
   - corps : bloc « Message envoyé » + bloc « Réponse » (texte, ou état d'attente + note
     fire-and-forget).
   - 3 états : `envoyé / en attente`, `réponse reçue`, `réponse différée (rattrapée)` — la
     transition se fait sur l'événement de complétion **déjà livré** par
     `api/background_process.py` (cas b confirmé). Rien à corréler à la main.
   - tours entrants « Message from &lt;bot&gt; … » : traitement visuel distinct (bandeau émetteur).
   - i18n dans `static/i18n.js` (`fr`, `en` au minimum).
3. **Point d'entrée** : depuis le panneau B2, « Ouvrir le fil inter-bots » d'un bot = ouvre sa
   « Bot Chat » dans la vue chat (bascule profil + session). C'est le « je clique mon bot →
   j'ai sa conversation inter-bots ».
4. **Envoi depuis WebUI** (conditionnel au test live §1) : si `run_agent` en processus obtient
   bien `message_agent` sur une session « Bot Chat », autoriser la saisie dans cette vue →
   B3 devient lecture + envoi. Sinon B3 reste lecture seule (la conduite du mesh reste au
   client Hermes Desktop / Telegram / cron).

**Isolation du couplage** : un seul module neuf `api/bot_mesh.py` (détection `title='Bot Chat'`,
parsing de l'accusé JSON `message_agent`, tag des sessions) + la fonction de rendu. Un
changement amont du nom d'outil ou du format d'accusé = 2 points à toucher.

**Tests** : projection inclut/exclut correctement la « Bot Chat » selon le flag ; rendu des
3 états depuis des fixtures ; pas de doublon si la complétion arrive deux fois (tour + cron de
rattrapage) — réutiliser la dédup par id de `process_event_utils.py`.

**Risque** : moyen-faible. `message_agent` et le format d'accusé ne sont pas contractuels amont
(stables en pratique). **Effort : ~1 sem** (lecture seule) ; +2–3 j si envoi depuis WebUI.

---

## 4. B2 — Panneau « Bots / Hiérarchie » (lecture seule)

**Constat** : les briques existent, non agrégées — `list_profiles_api()` (gateway on/off,
modèle, skills par profil), projection `all_profiles=True` dans `api/models.py`
(sessions actives / dernière activité tous profils), `hermes -p <p> cron status` (scheduler +
prochain run, pour les jobs de rattrapage).

**Changements** :

1. **Backend — nouvelle route `GET /api/bots`** (`api/routes.py`, logique dans un nouveau
   `api/bots_overview.py`) qui renvoie, pour les 18 profils :
   `{id, description, gateway_running, model, skills_count, active_sessions, last_activity,
   cron_scheduler_running, cron_next_run, branch}`.
   - `branch` (`pilote` / `pro` / `perso` / `conseil` / `interne`) : dérivé d'un fichier de
     config statique versionné dans le fork, `api/bots_hierarchy.json` (l'organigramme est
     déjà dans le vault — on le fige côté fork, pas de lecture du vault depuis WebUI).
   - Agréger sans multiplier les `os.walk` : réutiliser le cache `_LIST_PROFILES_CACHE` et la
     projection `all_profiles`.
2. **Frontend — nouvel onglet « Bots »** (`static/panels.js`, à côté de Tasks/Skills/Memory ;
   entrée dans le rail de `static/boot.js` / `index.html`) :
   - bandeau de synthèse (4 tuiles), arbre hiérarchique Pro / Perso avec séparation visuelle,
     `perceval` parent de `yvain`/`gauvain`, tags « intendance ».
   - par ligne : pastille passerelle, slug, fonction, dernière activité, sessions, pastille
     cron, bouton **Démarrer / Arrêter** → appelle `/api/gateway/*` avec `profile` (B1).
   - volet détail : passerelle + plateformes, job cron, chemin mémoire vault, sessions
     récentes, boutons « Ouvrir le fil » (bascule profil + ouvre/crée la session) / « Arrêter
     la passerelle ».
   - clic sur une ligne « Ouvrir le fil » = point d'entrée « je clique mon bot → j'ai sa
     conversation ».
3. i18n dans `static/i18n.js`.

**Tests** : `/api/bots` renvoie 18 entrées avec le bon `branch` ; tolérance si un profil n'a
pas de scheduler cron ; le bouton start/stop passe bien le `profile`.

**Risque** : faible (lecture seule + réutilise B1 pour les seules mutations).
**Effort : ~1–1,5 sem.**

---

## 5. Discipline de fork

- `git remote add upstream https://github.com/nesquena/hermes-webui.git`
- Une branche par fonctionnalité : `feat/b1-gateway-multiprofile`, `feat/b3-bot-mesh-card`,
  `feat/b2-bots-panel`. Merge dans une branche d'intégration `atx/palier-b`, pas dans `main`.
- Nouveau fichier `FORK-CHANGES.md` : lister chaque divergence (fichier, raison, point de
  couplage amont concerné) — indispensable pour les rebases.
- Concentrer le couplage aux internes de l'agent dans **2 fichiers neufs** (`api/bot_mesh.py`,
  `api/bots_overview.py`) + les 2 fonctions de rendu, jamais éparpillé.
- Avant chaque push : `./scripts/test.sh` (crée un `.venv` Python 3.11–3.13). Le fork a
  ~11 500 tests ; ne pas en casser.
- Rebase sur `upstream/main` à cadence fixe (hebdo tant que le chantier est ouvert) — l'amont
  fait des releases « exp » fréquentes.
- Pinner : la base est `exp-v0.52.264`. Noter la version d'`hermes-agent` correspondante sur
  `.178` (contrainte de compatibilité documentée dans le README : « upgrade both together »).

## 6. Déploiement sur `.178` — à signaler à Ludo (pas fait par un agent)

Le checkout `/home/atx/hermes-webui` suit aujourd'hui `nesquena/hermes-webui`. Passer au fork
= changer l'`origin` du checkout **ou** cherry-pick de `atx/palier-b`, puis
`sudo systemctl restart hermes-webui.service`. C'est une modif d'infra → **mise à jour du vault
`infra/hermes-webui.md` requise** (nouvelle origine, procédure de MAJ, divergence assumée).

---

## 7. État et prochaine étape

- **Recon §1 : faite** (2026-09-04). B3 recadré : « Bot Chat » masquée à surfacer + renderer,
  cas (b) confirmé (pas de corrélation backend). 2 vérifs live restantes, non bloquantes.
- **B1 : codé et validé** — branche `feat/b1-gateway-multiprofile`, commit `850f2c63`.
  ✅ 49/49 tests sur `.178` (agent réel, Python 3.11.16), dont `test_health_restart.py` qui
  échouait seulement sur le poste Windows sans agent. Reste : push du fork + bascule `.178` (§6).
  `api/routes.py` (+138/-14) + `tests/test_gateway_multiprofile_b1.py` (8 tests) + `FORK-CHANGES.md`.
  Local (Windows, sans agent Hermes) : 38/38 tests gateway ciblés OK, ruff gate OK, **0 régression
  introduite**. Les échecs `test_health_restart.py` / `test_gateway_yolo_webui_compat.py` /
  `test_session_duplicate_fields.py` observés localement **préexistent** (dépendances agent /
  fins de ligne Windows) — vérifié en stashant le patch.
  **À valider sur `.178`** : `./scripts/test.sh tests/test_gateway_multiprofile_b1.py
  tests/test_gateway_lifecycle_controls.py tests/test_gateway_status_agent_health.py
  tests/test_issue3194_gateway_configured_banner.py tests/test_health_restart.py -v`
  puis un run complet.
- **B2 : codé et validé** — branche `feat/b2-bots-panel` (part de B1), commits `9a1c8332`
  (backend `GET /api/bots` + `bots_overview.py` + `bots_hierarchy.json`) et `ff95c5bd` (panneau
  frontend + i18n 15 locales). ✅ 38/38 tests sur `.178` (agent réel) ; inspection visuelle
  faite — « ok pour une première version ». Suites restantes possibles (B2c) : sonde cron live
  par bot, volet détail, filtre inter-bots.
- **B3 : codé (lecture seule)** — branche `feat/b3-bot-chat-viewer` (part de B2), commits
  `5142abce` (backend `api/bot_mesh.py` + `GET /api/bot-chat` + `has_bot_chat`) et `4f9ce1bf`
  (viewer frontend dans le panneau Bots). Local : 38/38 tests ciblés OK, couverture locale 8/8
  OK, ruff OK. **Non encore validé sur `.178`.**
- §6 : `feat/b2-bots-panel` **poussé** sur `ATX-AI-Dev/hermes-webui` (émails réécrits pour GH007).
  `.178` reste à repointer dessus.
- Ordre d'attaque : ~~B1~~ → ~~B2~~ → ~~B3 lecture seule~~ → valider B3 sur `.178` → les 2 vérifs
  live (pilotage WebUI de la Bot Chat, fuite Pro/Perso) → décider si B3 passe en lecture+envoi.
