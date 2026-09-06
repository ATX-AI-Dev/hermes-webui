# Addendum — Palier C : faire de Hermes WebUI un cockpit multi-bots « façon Hermes Desktop »

> Complément à [ANALYSE-integration-bots.md](ANALYSE-integration-bots.md), suite à l'intérêt
> exprimé pour le palier C. Objectif : dire précisément ce que « ressemble à Hermes Desktop »
> implique, ce que le dépôt permet déjà, et le coût réel.

---

## 1. Ce qu'est réellement Hermes Desktop (rappel d'architecture)

Hermes Desktop est un **client léger** qui parle à `hermes-serve` (port `9119`,
JSON-RPC/WebSocket) — voir vault `infra/hermes-webui.md` §« Distinct de hermes-serve ».
Il **n'exécute pas** de boucle agent lui-même. Toute l'exécution multi-profils, l'isolation
par bot, les gateways : c'est le serveur qui les porte, avec **un processus gateway par
profil**. Desktop se contente d'afficher des sessions et d'envoyer des messages sur le fil.

**C'est exactement pour ça que Desktop fait du multi-bot sans peine : il est découplé.**
Le problème de WebUI est l'inverse : il lance l'agent **en processus**, avec `HERMES_HOME`
posé dans `os.environ` au niveau processus (cf. `ARCHITECTURE.md` : *« Two concurrent chat
requests will clobber each other »*).

Donc « WebUI comme Hermes Desktop » = **découpler WebUI de l'exécution**, puis, si voulu,
ajouter une UI multi-panneaux. Deux sous-projets distincts.

---

## 2. Bonne nouvelle : le dépôt construit déjà ce découplage (#1925 / #2491)

Le *seam* existe dans le code, en opt-in, **non branché sur le chat live** :

| Brique | Fichier | État |
| :--- | :--- | :--- |
| Protocole `RuntimeAdapter` (start/observe/cancel/approval/clarify/queue/goal) | `api/runtime_adapter.py` | présent |
| `StartRunRequest` **porte `profile`** (+ provider, model, workspace, toolsets) | `api/runtime_adapter.py` | présent |
| `HttpRunnerClient` → `POST /v1/runs` avec `"profile": request.profile` dans le corps | `api/runner_client.py` (156 lignes) | présent |
| Modes : `legacy-direct` (défaut), `legacy-journal`, `runner-local` | `HERMES_WEBUI_RUNTIME_ADAPTER` | `runner-local` = opt-in |
| Contrat de dépendance WebUI→agent (ce qui doit passer par HTTP) | `docs/architecture/agent-api-contract.md` | audit only |

Citation du code (`runtime_adapter.py`) : *« live chat routes still stay on the legacy path
until a separate route-wiring slice is reviewed »*, et *« this function does not create
process-global runner state or wire live chat to the runner backend »*.

**Traduction** : l'échafaudage du modèle Desktop est là. Il manque (a) le branchement sur
`/api/chat/start`, et (b) un serveur qui implémente `/v1/runs` **avec routage par `profile`**.

### Ce qui ne suffit PAS

Le pont `gateway_chat.py` (`HERMES_WEBUI_CHAT_BACKEND=gateway`, ~1500 lignes) route le chat
via `/v1/chat/completions` ou `/v1/runs` d'un Hermes Gateway — **mais mono-profil** : le
`profile` n'y sert qu'à construire le *system prompt* (`_webui_ephemeral_system_prompt`,
`surface_context`), **pas** de champ de routage dans la requête. Le gateway répond avec le
profil pour lequel il est configuré. Ce n'est donc pas un raccourci vers le multi-bot.

---

## 3. Le palier C se découpe en deux chantiers indépendants

### C1 — Découplage de l'exécution (backend) — *le vrai cœur du « façon Desktop »*

Adopter le chemin runner API :

1. Câbler `build_runtime_adapter(mode="runner-local", runner_client_factory=…)` dans
   `/api/chat/start` (aujourd'hui : chemin legacy en dur). ~1 slice de route, plus les
   contrôles (cancel/approval/clarify/queue) à rerouter vers l'adaptateur.
2. Disposer d'un serveur `/v1/runs` **qui route par `profile`** :
   - soit `hermes-serve` expose déjà un équivalent (à vérifier sur `.178` — protocole
     JSON-RPC actuel ≠ `/v1/runs` REST ; probablement à adapter côté agent) ;
   - soit un petit *runner* dédié devant les gateways par profil.
3. Migrer les lectures/écritures d'état qui importent `hermes_state.SessionDB` en direct
   (`api/streaming.py`, `api/goals.py`, `api/state_sync.py`, `api/models.py`) vers des
   endpoints agent — sinon le découplage est cosmétique (cf. `agent-api-contract.md`,
   classe `runtime_session_state`).

**Gain** : plus de `HERMES_HOME` process-global, concurrence possible, plusieurs bots peuvent
tourner sans se marcher dessus. **C'est la condition sine qua non de tout le reste.**

**Coût** : moyen-élevé. Dépend d'un composant côté hermes-agent non vérifié dans ton install.
Fort risque de couplage tant que #1925/#2491 ne sont pas livrés en amont.

### C2 — Cockpit multi-panneaux (frontend)

Panneaux simultanés par bot, organigramme pilote→managers→bots, graphe de routage live,
éventuellement envoi de `message_agent` depuis l'UI.

**Obstacle structurel** : le frontend est mono-contexte par construction —
`const S = { session:null, …, activeProfile:'default', … }` dans `static/ui.js` (fichier
mono-bloc ~1 Mo, sans bundler). Tout — rendu, SSE, sidebar, composer — suppose **une** session
et **un** profil actifs. Le multi-panneaux n'est pas un patch, c'est une réécriture de la
couche état du frontend.

**Coût** : élevé. Indépendant de C1 techniquement, mais **inutile sans C1** (des panneaux
concurrents se clobbent mutuellement sur le chemin legacy).

**Utilité réelle vs Desktop** : Hermes Desktop lui-même n'a pas de « war room » multi-panneaux
— c'est aussi *une conversation à la fois* + sélecteur de profil + sidebar unifiée de toutes
les sessions tous profils. Une bonne partie de « l'expérience Desktop » est donc atteignable
**sans C2**, via le palier B (panneau « Bots » + sidebar cross-profils, qui existe déjà en
partie : `all_profiles=True` dans `api/models.py`).

---

## 4. Recommandation

1. **Ne pas fork-hacker le palier C.** L'audit de couplage (`agent-api-contract.md`) liste 6
   classes de dépendances aux internes de l'agent encore à migrer. Combiné aux releases « exp »
   fréquentes de l'amont, une divergence profonde du fork `ATX-AI-Dev` deviendrait ingérable.

2. **Chemin conseillé si WebUI doit devenir le cockpit :**
   - **Étape 0 — cadrer le besoin** (voir §5) : supervision façon Desktop, ou exécution
     concurrente réelle ?
   - **Étape 1 — palier B** en parallèle (valeur immédiate, zéro risque) : panneau
     « Bots / Hiérarchie » read-only + gateway multi-profils + carte `message_agent`.
   - **Étape 2 — spike C1 jetable** : `HERMES_WEBUI_RUNTIME_ADAPTER=runner-local`, un serveur
     `/v1/runs` minimal qui route par `profile` (devant 2 profils), branché sur
     `/api/chat/start`. **Critère de succès mesurable** : deux tours de deux bots différents,
     lancés en même temps, restent isolés (mémoire, workspace, état) — ce que le chemin legacy
     ne garantit pas.
   - **Étape 3 — décision** : si le spike tient et que l'amont #1925 avance, investir C1
     proprement (idéalement en contribuant en amont pour que ce soit maintenu). Sinon,
     s'arrêter au palier B + garder Hermes Desktop comme cockpit.
   - **Étape 4 — C2** seulement après C1 stable.

3. **Position par défaut recommandée** : WebUI = surface de **supervision + accès mobile**
   (palier B), Hermes Desktop = cockpit d'exécution. C'est déjà le rôle que lui donne le vault
   (`infra/hermes-webui.md` : « rôle actuel secondaire… candidate à devenir la porte d'entrée
   principale multi-bots depuis un navigateur »). Le palier B réalise ce « candidate » sans
   pari technique.

---

## 5. Question de cadrage (bloquante avant d'aller plus loin)

« Ressemble à Hermes Desktop » peut vouloir dire deux choses très différentes :

- **Supervision unifiée** : un sélecteur de bot, une sidebar de toutes les sessions de tous les
  bots, l'activité gateway (Telegram/Discord) de chaque bot en direct, **une conversation
  centrée à la fois**. → C'est ce qu'est Desktop. Atteignable au **palier B**, quelques
  semaines, sans dépendance amont.
- **Exécution concurrente réelle** : plusieurs bots qui travaillent et s'affichent
  véritablement en parallèle dans une même page, organigramme, graphe de routage. → Au-delà de
  Desktop. C1 + C2, plusieurs mois, dépendance à un composant hermes-agent + réécriture de la
  couche état frontend.

Le choix entre les deux détermine tout le reste.
