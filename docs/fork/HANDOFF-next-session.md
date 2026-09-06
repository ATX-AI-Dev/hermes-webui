# Handoff — intégration des bots Hermes dans Hermes WebUI (palier B / B4)

> À lire en entier avant de reprendre. Rédigé le 2026-09-04, mis à jour en fin de la même
> journée (session de généralisation B4), puis à nouveau le 04/09/2026 (session suivante :
> déploiement B4 en prod + durcissement du verrou d'exclusivité) pour permettre une reprise à
> froid sans perdre le contexte accumulé.

---

## 0. Contexte projet (à lire aussi dans le vault Obsidian)

Ludo a forké `nesquena/hermes-webui` → `ATX-AI-Dev/hermes-webui` et veut y intégrer sa
hiérarchie de 18 bots Hermes (pilote/managers/bots spécialisés, cf.
`infra/hermes-bots-hierarchie.md` du vault) qui communiquent entre eux via l'outil
`message_agent`. Lire dans le vault, dans l'ordre : `00-INDEX.md`,
`infra/hermes-webui.md`, `infra/hermes-bots-hierarchie.md`.

**Dépôt local** : `D:\Projets\Hermes WebUI` (checkout git complet, plusieurs branches
`feat/*`). **Dépôt distant** : `https://github.com/ATX-AI-Dev/hermes-webui`. **Serveur** :
`.178` = `192.168.1.178`, utilisateur `atx`, clé SSH `C:\Users\Ludo\.ssh\id_ed25519_atx178`.
Checkout prod sur `.178` : `/home/atx/hermes-webui`, service systemd `hermes-webui.service`.
Venv de l'agent (le seul avec les vraies dépendances) : `~/.hermes/hermes-agent/venv`.

**Note git** : GitHub rejette les push si les commits portent l'email privé de Ludo (GH007).
`git config user.email` est déjà réglé sur `269487518+ATX-AI-Dev@users.noreply.github.com`
dans le checkout local `D:\Projets\Hermes WebUI` — ne pas le changer.

## 1. État du chantier « palier B »

| Palier | Contenu | État |
| :-- | :-- | :-- |
| **B1** | `/api/gateway/{start,stop,restart,status}` acceptent un `profile` explicite | ✅ codé, testé, **poussé**, **déployé sur `.178`** |
| **B2** | Panneau « Bots » : `GET /api/bots`, hiérarchie visuelle, boutons Démarrer/Arrêter | ✅ codé, testé, **poussé**, **déployé sur `.178`** |
| **B3** | Vue « Fil inter-bots » en lecture seule (session « Bot Chat » masquée, cartes `message_agent`) | ✅ codé, testé, **poussé**, **déployé sur `.178`** |
| **B4** | Fusion lecture + écriture, généralisée à tous les bots, + rendu riche `message_agent` + verrou d'exclusivité côté WebUI | ✅ **codé, testé, poussé, DÉPLOYÉ sur `.178`** |

**`.178` tourne en prod sur la branche `feat/b4-continue-bots`, commit `3b83dc62`** (déployé et
service redémarré le 04/09/2026, `/health` confirmé `ok`). C'est désormais l'état de référence
stable — `feat/b3-bot-chat-viewer` est dépassée.

### B4 — détail de ce qui est fait

Branche `feat/b4-continue-bots` (renommée depuis `feat/b4-continue-prototype`), **poussée sur
`origin` et déployée en prod**, 7 commits par-dessus `feat/b3-bot-chat-viewer` (dernier :
`3b83dc62`).

1. **Généralisation** — `continue_bot_chat()` (renommé, plus de « prototype ») est le point
   d'entrée unique « Continuer » du panneau Bots pour tout bot ayant une Bot Chat ; « Open
   thread » ne reste que pour les bots qui n'en ont pas. Validé en live sur `.178` :
   - **Import seul** (sans effet sur l'agent) : 7/7 profils testés (`lancelot`, `pere-blaise`,
     `yvain`, `gauvain`, `guenievre`, `roi-arthur`, `venec`), mélange permanent/à la demande.
   - **Tour complet réel** (vrai navigateur, vrai appel LLM, `message_agent` déclenché) : 2
     arêtes testées en respectant la hiérarchie — `lancelot → roi-arthur` et
     `guenievre → roi-arthur` (toutes deux « Managers vers Pilote »). Confirmées reçues côté
     `roi-arthur` en lisant directement `state.db`.
   - **Toujours pas testé** : un tour complet réel sur un bot « à la demande » (aurait exigé de
     démarrer son gateway) — voir §4 point 1, en cours d'attaque.
2. **Rendu riche `message_agent`** — nouveau kind de tool-card `relay` dans `static/ui.js` pour
   `message_agent`/`bot_mode_dm` : icône dédiée, bot cible en aperçu (au lieu de JSON brut),
   message en détail déplié, statut d'ack extrait proprement. Validé en live contre la vraie
   Bot Chat de `lancelot`. 9 tests dans `tests/test_message_agent_tool_card.py`. **Non fait** :
   les tours entrants « Message from X » (texte simple, pas un tool-call) n'ont pas de carte
   dédiée façon Hermes Desktop — chantier distinct, pas engagé.
3. **§3.3 tranché** (Telegram/cron partagent-ils le `session_id` de la Bot Chat ?) :
   - **Cron : OUI.** Le job actif est `relais-message-agent-<profil>` (mode script `no-agent`,
     `relay_message_agent.py`, `--deliver bot-chat:<profil>`), actif sur les 5 profils à
     gateway permanent. Confirmé au niveau des lignes `state.db`, pas juste à l'écran.
   - **Telegram : NON**, jamais — chaque conversation Telegram a sa propre session séparée.
   - **Découverte** : l'ancien job documenté dans le vault (`ping-rattrapage-<profil>`, mode
     agent complet) n'existe plus (remplacé, pas juste désactivé) et, quand il tournait, créait
     en fait sa propre session à chaque exécution — il n'écrivait PAS dans la Bot Chat,
     contrairement à ce que disait le vault. **Le vault a été corrigé le 04/09/2026**
     (`infra/hermes-bots-hierarchie.md`, section « Cron de rattrapage `message_agent` »).
4. **Verrou d'exclusivité — WebUI en fait maintenant partie** (résolu §3 point 4 / PLAN-B4 §6
   point 4, session suivante du 04/09/2026). Recon du code source agent sur `.178`
   (`hermes_cli/active_sessions.py`) : la découverte réelle n'était pas « message d'erreur peu
   clair » mais plus grave — **WebUI n'appelait jamais** `try_acquire_active_session()` (seuls
   `gateway/run.py`, `tui_gateway/server.py`, `cli.py` le font). Cette fonction ne lève jamais
   d'exception : elle renvoie `(lease, None)` ou `(None, refusal)`, `refusal` étant un message
   humain propre (`ActiveSessionRefusal`, str avec `.reason`). Sans appel côté WebUI, une
   collision réelle aurait été un **double-écrivain silencieux**, pas un refus.

   Correctif : `api/bot_mesh.py` (`is_bot_chat_session`, `acquire_bot_chat_lease`,
   `release_bot_chat_lease`, `BotChatSessionLockedError`) + `api/streaming.py` (acquisition
   après la bascule `HERMES_HOME` par profil, libération dans le `finally` existant,
   classification dédiée `bot_chat_session_locked` qui bypass `_classify_provider_error` pour
   ne déclencher aucune relance). Scope limité aux sessions Bot Chat — zéro coût sur les tours
   WebUI ordinaires. 17 tests (`tests/test_bot_mesh_session_lease.py`), commit `3b83dc62`,
   **déployé en prod**. **Non fait** : collision réelle jamais reproduite en conditions live
   (le message affiché est correct par construction — lu directement dans la source agent —
   mais jamais vu à l'écran).

## 2. Documents de référence dans le dépôt

- `ANALYSE-integration-bots.md` + `ANALYSE-integration-bots-palier-C.md` — analyse initiale de
  faisabilité (paliers A/B/C).
- `PLAN-palier-B.md` — plan détaillé B1/B2/B3, avec la recon complète (schéma `state.db`,
  comportement de `message_agent`, etc.). **Lire en premier pour le détail technique.**
- `PLAN-B4-fusion-conversation.md` — cadrage B4 **à jour au 04/09/2026 (session suivante)** :
  validation live initiale (lancelot), généralisation (§6 point 1), rendu riche (§6 point 2),
  §3.3 tranché (§6 point 3), **verrou d'exclusivité résolu (§6 point 4)**. Tous les points de
  §6 sont maintenant faits.
- `FORK-CHANGES.md` — journal détaillé de chaque divergence du fork, fichier par fichier.
- `maquette-panneau-bots.html` / `maquette-conversation-bot.html` — maquettes visuelles
  produites avant le code (pour référence esthétique).

## 3. Découvertes techniques critiques (ne pas re-découvrir à froid)

1. **Chaque profil Hermes a son propre `state.db`** à `~/.hermes/profiles/<nom>/state.db` —
   **aucune base partagée**. Un bug initial (B2/B3) lisait seulement celle de `default` ;
   corrigé (`api/bot_mesh.py`, `api/bots_overview.py` résolvent maintenant
   `get_hermes_home_for_profile(profil)` avant toute lecture).
2. **`message_agent`** n'est injecté que dans la session canonique **« Bot Chat »**
   (`title='Bot Chat'`, `hidden=1`) d'un profil — jamais dans une session CLI/WebUI/Telegram
   ordinaire. Confirmé en live (session `roi-arthur` normale → *« L'outil message_agent
   n'existe pas dans mon environnement »*).
3. **`api/models.py::import_cli_session()`** + **`get_cli_session_messages(sid,
   profile=...)`** — mécanisme WebUI déjà existant (« CLI session bridge », badge doré « cli »)
   qui importe une session agent-native par son `session_id` réel et permet d'y répondre en
   continuant la **même** session. Les deux acceptent déjà un `profile` explicite. C'est le
   moteur de `api/bot_mesh.py::continue_bot_chat()` (B4).
4. **Verrou d'exclusivité de session** côté agent, mécanisme exact (source lue directement dans
   `~/.hermes/hermes-agent/hermes_cli/active_sessions.py` sur `.178`) :
   `try_acquire_active_session(session_id, surface, config, metadata, registry_home)` renvoie
   `(lease, None)` ou `(None, refusal)` — **ne lève jamais d'exception**. `refusal` est un
   `ActiveSessionRefusal` (str avec `.reason` machine-readable : `SESSION_NOT_OWNED`,
   `SESSION_COORDINATION_UNAVAILABLE`, `MAX_CONCURRENT_SESSIONS`), message déjà propre pour
   l'utilisateur (`session_already_owned_message()`). Seuls trois appelants dans tout le code
   agent : `gateway/run.py`, `tui_gateway/server.py`, `cli.py` — **WebUI n'en faisait pas
   partie**, donc une collision réelle était un double-écrivain silencieux, pas un refus.
   **Résolu le 04/09/2026 (session suivante)** : WebUI acquiert désormais ce bail
   (`surface="webui"`) pour tout tour sur une session Bot Chat — voir point 4 juste au-dessus.
   Toujours **jamais reproduit en conditions live** (aucune collision réelle provoquée).
5. **Un tour réel sur un bot « à la demande » ne nécessite PAS de démarrer son gateway.**
   Validé le 04/09/2026 (session suivante) sur `pere-blaise` (gateway `stopped`, confirmé par
   `hermes profile list`) : WebUI importe et répond dans sa Bot Chat exactement comme pour un
   profil à gateway permanent — `continue_bot_chat()` invoque `AIAgent` **en process**, jamais
   via le gateway externe du profil (celui-ci ne sert que Telegram/CLI). Turn réel confirmé au
   niveau `state.db` : `message_agent` déclenché vers `@lancelot`, reçu côté lancelot **~2
   secondes** plus tard (pas besoin d'attendre le cron de rattrapage — lancelot a un gateway
   permanent qui traite le tour immédiatement). Instance jetable `/tmp/webui-b4-onDemand`
   (port 8794), nettoyée après usage. **Découverte annexe** : `pere-blaise` a en fait un job
   cron `relais-message-agent-pere-blaise` configuré (`hermes -p pere-blaise cron list --all`),
   contrairement à ce que dit le vault (« bots à la demande : aucun job cron, vérifié sur
   pere-blaise/bohorth/venec ») — mais il ne peut pas se déclencher (`Gateway is not running —
   jobs won't fire automatically`), donc sans effet pratique. Signalé pour mise à jour du
   vault, pas corrigé par l'agent (règle CLAUDE.md).
6. **`is_cli_session_row()`** (`api/agent_sessions.py`) ne reconnaîtrait pas la Bot Chat comme
   « CLI importable » via la découverte automatique (elle n'a que `source='tui'`, jamais testé
   directement par ce classifieur) — sans importance pour B4 : `import_cli_session()` ne passe
   pas par ce classifieur, on l'appelle directement avec le `session_id` connu via
   `bot_mesh.find_bot_chat_session(profile)`.
7. **Discipline de fork** : chaque palier a suivi recon → code → tests locaux (`.venv`
   Python 3.12 via `uv`, voir commandes dans `PLAN-palier-B.md`) → validation sur `.178` (clone
   jetable dans `/tmp`, jamais le checkout prod, toujours nettoyé après usage) → push →
   déploiement (`git fetch` + `checkout` + `sudo systemctl restart hermes-webui.service`, fait
   par Ludo). **Chaque hypothèse d'architecture non vérifiée a coûté cher une fois codée** (bug
   state.db partagé, bug de troncature CSS, vault documentant un job cron qui n'écrivait pas où
   il était censé écrire) — toujours vérifier en live avant de généraliser ou de documenter.
8. **Sécurité** : ne jamais taper le mot de passe WebUI (`HERMES_WEBUI_PASSWORD`) dans un champ
   de login, même pour un test — c'est une action interdite par les règles de sécurité de
   l'agent. Solution utilisée pour tester en live : lancer l'instance jetable SANS cette
   variable (elle passe alors en mode sans authentification), toujours en loopback strict
   (`127.0.0.1`) + tunnel SSH depuis le poste de dev, jamais exposée publiquement.

## 4. Prochaines étapes (à trancher avec Ludo)

**✅ Fait le 04/09/2026 (session suivante)** : déploiement B4 en prod (`.178` sur `3b83dc62`,
service redémarré, `/health` `ok`) + robustesse du verrou d'exclusivité (WebUI participe
maintenant au bail agent-side, voir §1 point 4 et §3 point 4) + tour complet réel sur un bot à
la demande (`pere-blaise`, voir §3 point 5 — aucun gateway à démarrer, confirmé au niveau
`state.db`, réception côté `lancelot` en ~2s) + **rafraîchissement live des Bot Chat** (voir
plus bas) + **rendu des tours entrants « Message from X »** (voir plus bas — dernier item
ouvert de B4, maintenant fait). **Plus aucun item ouvert côté B4.**

### Rendu des tours entrants « Message from X » (04/09/2026, session suivante)

Dernier point ouvert de PLAN-B4-fusion-conversation.md §6 point 2 : une livraison
`message_agent` entrante s'écrit comme un simple message `role='user'` avec un préfixe fixe
construit par l'agent (`tools/bot_mode_dm.py`, source lue directement sur `.178`) :
`f"Message from 🤖 {sender_handle} (@{sender_handle}): {body}"` (même handle des deux côtés).
Comme ce n'est pas un tool-call, `buildToolCard` (le mécanisme du rendu riche sortant, voir
plus haut) ne le voit jamais — le préfixe brut s'affichait comme texte normal.

**Fait** : `static/ui.js` — `_relayInboundMatch` (regex stricte sur le préfixe exact, y compris
la contrainte handle identique des deux côtés — un vrai message humain qui ressemblerait
vaguement au préfixe ne doit jamais être requalifié) + `_relayInboundHeaderHtml` (icône
`message-square` + libellé "Message from @<bot>", même traitement visuel que la carte sortante).
Branché directement dans `renderMessages()` (pas une branche séparée façon `process_wakeup` —
juste `bodyHtml` et la classe de la ligne, réutilise 100% du pipeline de rendu/cache/
virtualisation existant). Clé i18n `relay_inbound_from` ajoutée (`en` + `fr` ; les autres
locales retombent sur l'anglais via le mécanisme de fallback existant de `t()`).

**Validé en live** sur `.178` (instance jetable, port 8796) contre la vraie Bot Chat de
`pere-blaise`, qui contenait déjà un tour entrant réel de `lancelot` — carte affichée
correctement (icône, "MESSAGE FROM @LANCELOT", corps du message séparé). 9 tests
(`tests/test_relay_inbound_message_card.py`, même pattern que
`test_message_agent_tool_card.py`). Un test existant
(`tests/test_anchor_fallback_ownership.py`) a dû être mis à jour pour stubber le nouveau
helper — corrigé, régression comprise et fixée avant de considérer le travail terminé.

### Rafraîchissement live des Bot Chat (04/09/2026, session suivante)

Suite à la demande de Ludo d'une communication inter-bots « fluide et dynamique » : le vrai
goulot n'était pas côté infra (un démon temps réel existe déjà sur `.178`, voir le vault
`infra/hermes-cron-jobs.md` — et un bug réel y a été trouvé et corrigé le même jour, liste de
profils figée au démarrage du démon) mais côté **WebUI lui-même**. WebUI a déjà un mécanisme
générique de rafraîchissement live pour toute session externe/CLI (`static/sessions.js`,
`refreshActiveSessionIfExternallyUpdated` — poll 30s + SSE + focus/visibilité), mais il ne
comparait que le compteur de messages du **sidecar WebUI** à lui-même — jamais une relecture du
`state.db` agent-natif où vit réellement une Bot Chat. Une réponse déposée par
`hermes-relay-watcher.service` (ou toute autre surface) restait donc invisible tant que
l'utilisateur ne rouvrait pas manuellement la session.

**Corrigé** : `api/bot_mesh.py` (`bot_chat_state_db_message_count`, `resync_bot_chat_if_stale`)
+ `api/routes.py` (appelé dans le handler `GET /api/session` en mode métadonnées seules, juste
après la vérification de profil). Réutilise le poll existant côté frontend — **aucun changement
frontend nécessaire** : le check est ajouté côté backend, cheap (`COUNT(*)` seul tant que rien
n'a changé), et ne déclenche un re-import complet (`continue_bot_chat`) que si `state.db` a
réellement grandi depuis le dernier `message_count` connu du sidecar.

**Validé en live** sur `.178` (instance jetable, port 8795, insertion directe d'un message de
test dans le `state.db` réel de `pere-blaise` pendant que sa Bot Chat était ouverte dans WebUI) :
confirmé côté backend que `GET /api/session?...&messages=0` reflète bien le nouveau
`message_count`/`last_message_at` après l'insertion, sans action manuelle. Le poll frontend
lui-même n'a pas pu être observé en action dans l'environnement de test automatisé
(`document.hidden=true` sur l'onglet piloté par l'agent — comportement de garde déjà existant
et volontaire de WebUI, pas un défaut du correctif) ; le mécanisme de reprise sur focus/visibilité
n'est donc pas remis en cause, juste non observable dans ce contexte de test précis. 8 tests
unitaires (`tests/test_bot_chat_live_refresh.py`).

**Limite connue** : ne concerne que les sessions **actuellement ouvertes** dans un onglet actif
— une conversation en arrière-plan (autre profil, sidebar) ne se rafraîchit pas toute seule
(comportement hérité, pas modifié ici). Un badge « non lu » en direct sur les autres bots serait
un chantier distinct, pas engagé.

**Recommandation** : avancer par étapes testées comme B1→B2→B3→B4 (petits patches, validation
live systématique avant généralisation) — cette discipline a payé à chaque palier jusqu'ici,
y compris pour corriger une doc vault erronée découverte en cours de route et pour découvrir
que WebUI était absente du verrou d'exclusivité alors que le symptôme attendu était juste
« message peu clair ».

## 5. Rappels opérationnels

- Toujours lire `00-INDEX.md` + `infra/hermes-webui.md` + `infra/hermes-bots-hierarchie.md`
  du vault Obsidian avant de commencer (instruction globale CLAUDE.md de Ludo).
- Ne jamais lancer `sudo` sur `.178` soi-même dans une session non interactive de l'agent —
  c'est Ludo qui exécute les commandes `sudo systemctl restart ...` (mot de passe requis).
- Test local (poste dev Windows) : `.venv` Python 3.12 déjà construit dans
  `D:\Projets\Hermes WebUI\.venv` (via `uv`), suffisant pour les tests unitaires
  backend/frontend (pas l'agent complet). Validation fonctionnelle réelle = toujours sur
  `.178`, sur un **clone jetable dans `/tmp`** (jamais le checkout prod
  `/home/atx/hermes-webui`), toujours nettoyé après usage (process tué, dossier supprimé,
  tunnel SSH fermé côté poste de dev).
- Patch de transfert : `git format-patch <base>..<branche> --stdout > x.patch`, `scp` vers
  `.178`, puis dans le clone jetable `git config user.email/user.name` (identité locale
  jetable) + `git am x.patch` (pas `git apply` seul — la mbox contient plusieurs commits).
- Pour driver un vrai tour depuis un navigateur contre une instance jetable : copier le `.env`
  de `/home/atx/hermes-webui/.env`, changer le port + `HERMES_WEBUI_ALLOWED_ORIGINS` pour
  matcher, mettre `HERMES_WEBUI_SECURE=0` + `HERMES_WEBUI_TRUST_FORWARDED_PROTO=0` (test en
  clair via tunnel SSH, pas de TLS), et **ne jamais renseigner `HERMES_WEBUI_PASSWORD`** —
  lancer sans cette variable pour un accès sans authentification, strictement en loopback +
  tunnel SSH depuis le poste de dev.
