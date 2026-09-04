# B4 — la conversation WebUI d'un bot = son unique fil fusionné (lecture + écriture)

> Suite à B1–B3 (déployés). Objectif reformulé après retour de Ludo sur B3 (04/09/2026,
> captures Hermes Desktop) : **ouvrir un bot dans WebUI doit afficher tout ce qu'il a fait**
> (Bot Chat, Telegram, cron, CLI…) **dans un seul flux chronologique**, et **taper un message
> doit continuer ce même flux** — pas une session WebUI séparée de plus. Confirmé par Ludo :
> fusion complète lecture + écriture, effort accepté (plusieurs semaines, risque de divergence).

> **Validé en conditions réelles le 04/09/2026.** Prototype `feat/b4-continue-prototype`
> (bouton « Continuer » sur `lancelot`) testé live sur `.178` (instance jetable `:8791`,
> vrai venv agent) : import de la session « Bot Chat » réussi (`import_cli_session` +
> `get_cli_session_messages`, tous deux déjà profil-scopés), tour WebUI écrit dans la
> **même** `session_id` (`message_count` 743→745, `last_activity_at` à l'heure du test),
> **`message_agent` appelé avec succès depuis WebUI** (envoi à `@bohorth`), **réponse
> asynchrone livrée dans la même session**, et le **cron de rattrapage a vu et confirmé le
> même échange dans le même fil juste après** — cron et WebUI cohabitent sans conflit sur ce
> test. Les deux questions décisives (§3.1 pilotage, §3.2 injection de `message_agent`) sont
> **résolues : oui aux deux**. Reste §3.3 (Telegram/cron partagent-ils ce `session_id` ou pas)
> et le risque de verrou « already has a live owner » observé une fois dans l'historique
> (deux surfaces CLI en collision, pas WebUI — à surveiller, pas encore reproduit avec WebUI).

**Ne pas coder la version définitive avant d'avoir statué sur la portée finale (voir §7).** Ce
qui suit reste par ailleurs un bon compte-rendu de la démarche — B1/B2/B3 ont chacun montré
qu'une hypothèse d'architecture non vérifiée (« state.db partagé ») coûte cher une fois codée
puis testée en prod ; ça a payé de vérifier avant de généraliser ici aussi.

---

## 1. Ce que montrent les captures Desktop

- Tours richement typés dans **une seule fenêtre** : « 🟡 Message from roi-arthur » (dépliable),
  « → Replied to roi-arthur » (dépliable), blocs « Thought » (dépliables), cartes d'outil
  (`Ran date -u …`, `Message Agent`), texte normal — tout interleaved par ordre chronologique.
- Un panneau latéral « SCHEDULED JOBS » montre le cron `relais-message-agent-lancelot` (10 min)
  — le même job de rattrapage documenté dans le vault.
- Aucune bascule entre plusieurs sessions visibles : c'est **une** fenêtre pour `lancelot`.

## 2. Piste trouvée dans le code WebUI — le pont CLI existe déjà

Le README l'annonçait (« CLI session bridge … click to import with full history and reply
normally ») et le code le confirme :

- `api/models.py::import_cli_session(session_id, title, messages, …)` — crée une `Session`
  WebUI **avec le même `session_id`** que la session agent-native (state.db), pré-remplie de
  son historique, sauvegardée dans le sidecar WebUI. Sert au badge doré « cli » déjà documenté
  dans le README.
- Une fois importée, répondre dans WebUI continue vraisemblablement **la même session agent**
  (même `session_id`) plutôt que d'en créer une nouvelle — c'est le sens de « reply normally ».
- **Si c'est bien le cas, importer la session canonique « Bot Chat » d'un profil via ce
  mécanisme existant, puis en faire LA conversation WebUI de ce bot, réaliserait exactement ce
  que Ludo demande** — sans réinventer un moteur de fusion multi-sessions. C'est le chemin de
  moindre résistance architecturale.

### Obstacle identifié, non résolu

`api/agent_sessions.py::is_cli_session_row()` classe une ligne comme « CLI importable » via
`source == 'cli'` ou `source_tag/raw_source/source_name/source_label ∈ {'acp','cli','tui'}`.
La session « Bot Chat » réelle observée n'a que `source='tui'` peuplé (les autres champs
n'ont pas été vérifiés) — **`source` lui-même n'est testé que pour `'cli'`, pas `'tui'`**, dans
la branche qui suit celle des champs `_tag/raw_/_name/_label`. Donc soit ces champs annexes
valent bien `'tui'` eux aussi (et ça passe), soit la Bot Chat ne serait PAS reconnue comme
importable en l'état — sans compter que `hidden=1` est de toute façon exclu en amont de la
projection normale (raison pour laquelle B3 a dû la lire en direct dans `state.db`).

## 3. Questions à trancher avant de coder quoi que ce soit

1. **La session canonique « Bot Chat » est-elle réellement importable telle quelle** via
   `import_cli_session`, ou faut-il d'abord la faire passer le filtre `hidden`/`is_cli_session_row` ?
2. **Écrire depuis WebUI dans cette session continuée déclenche-t-il toujours l'injection de
   `message_agent`** (le gate `ensure_message_agent_tool` est basé sur le titre canonique
   « Bot Chat » + le statut Bot-Mode-managed — WebUI en processus doit reproduire exactement ce
   contexte) ? C'est la vérif live « pilotage » déjà identifiée dans le plan B — elle devient
   bloquante ici, plus seulement pour un bonus.
3. **Telegram et les tours cron écrivent-ils dans CE MÊME `session_id`**, ou dans des sessions
   séparées (un par canal) ? Si séparées, la « fusion » que Ludo demande n'est pas qu'un import
   de session — WebUI devrait en plus **fusionner l'affichage** de plusieurs `session_id` pour
   un même profil, ce qui est un chantier distinct et plus lourd (vue de lecture composée,
   l'écriture continuant de cibler la Bot Chat).
4. **Le rendu riche par type de tour** (Thought dépliable, carte Message Agent, carte
   Message from/Replied to) — WebUI a déjà l'équivalent pour les sous-agents (`delegate_task`)
   et les blocs de raisonnement (README : « Thinking/reasoning display »). Reste à vérifier que
   les *rôles*/*tool_calls* qu'on verrait dans le state.db de Bot Chat (vu en B3 :
   `role=assistant/tool/user`, `tool_calls` JSON, `reasoning_content`) sont déjà pris en charge
   par le renderer existant de `static/ui.js`/`messages.js`, ou s'il faut les étendre en plus
   des cartes `message_agent` déjà ajoutées en B3b.

## 4. Recon live proposée (lecture seule, avant tout code)

Sur `.178`, contexte de l'agent (pas juste sqlite brut cette fois — on veut la vraie fonction) :

```bash
cd /home/atx/hermes-webui && ~/.hermes/hermes-agent/venv/bin/python3 - <<'PY'
import sys, os
sys.path.insert(0, os.getcwd())
import sqlite3
db = "/home/atx/.hermes/profiles/lancelot/state.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
row = con.execute("SELECT * FROM sessions WHERE id='20260901_070436_73676c'").fetchone()
d = dict(row)
for k in ("source","session_source","source_tag","raw_source","source_name","source_label","is_cli_session"):
    print(k, "=", d.get(k))
PY
```

→ révèle si `is_cli_session_row()` classerait cette ligne comme importable telle quelle.

Puis, seulement si ça semble jouable, un test fonctionnel **manuel** (pas scripté) : dans WebUI,
onglet Bots → « Fil inter-bots » de `lancelot` (B3) montre déjà le contenu en lecture ; il
faudrait un point d'entrée temporaire (à créer, même bricolé) qui appelle
`import_cli_session('20260901_070436_73676c', …)` avec les messages lus par `bot_mesh.py`, puis
observer si un nouveau tour tapé dans WebUI (a) apparaît bien après dans
`~/.hermes/profiles/lancelot/logs/agent.log` comme faisant partie de la MÊME session, et (b) si
`message_agent` reste disponible pour ce tour.

## 5. Portée envisagée si la recon confirme la piste

- **Phase 1 (lecture seule, déjà faite en B3)** : garder tel quel — c'est la base d'affichage.
- **Phase 2** : remplacer « Open thread » du panneau Bots par un import+continue de la session
  canonique du profil (via `import_cli_session`), au lieu de basculer vers une session WebUI
  quelconque. Un seul point d'entrée par bot, plus de choix entre « Open thread » et
  « Fil inter-bots ».
- **Phase 3** : étendre le renderer du fil (déjà commencé en B3 pour `relay_out`) aux autres
  types de tours observés (Thought/reasoning, tours entrants « Message from X », sorties cron)
  avec un badge de source discret, dans l'esprit des captures Desktop.
- **Phase 4, seulement si §3.3 confirme des `session_id` séparés par canal** : vue de lecture
  composée multi-sessions (mérite son propre chiffrage — pas engagée sans confirmation).

## 6. Prochaines étapes (après validation live du 04/09/2026)

1. **✅ Fait le 04/09/2026 (session suivante)** : `continue_bot_chat()` (ex-
   `continue_bot_chat_prototype`, renommé — plus aucune trace de « prototype » dans le code,
   l'i18n ou l'UI) est désormais le point d'entrée unique de la ligne d'un bot dans le panneau
   Bots dès qu'il a une Bot Chat (`has_bot_chat`) : bouton « Continuer », plus de bouton
   « Open thread » à côté. « Open thread » ne reste que comme repli pour les bots sans Bot
   Chat. « Fil inter-bots » (lecture seule) reste disponible en accordéon comme aperçu rapide.
   Le backend (`api/bot_mesh.py::continue_bot_chat`) était déjà générique par profil — rien à
   changer côté logique d'import, seule l'UI/l'API restreignaient l'usage à un test manuel sur
   `lancelot`. **Non encore fait** : validation live sur `.178` avec un bot autre que
   `lancelot` (idéalement un bot « à la demande », pas à gateway permanent, pour couvrir le cas
   le plus différent) — voir points 3 et 4 ci-dessous, toujours ouverts.
2. **Rendu riche par type de tour** dans la vraie vue de chat (pas seulement mon viewer B3) :
   les tours `tool_name=message_agent` doivent s'afficher avec la carte dédiée déjà conçue en
   B3b (cible, message, état), pas comme un tool-call générique — ça veut dire étendre le
   renderer de `static/ui.js`/`messages.js`, pas seulement celui du panneau Bots.
3. **§3.3 à vérifier** : Telegram et les tours cron écrivent-ils dans ce même `session_id` pour
   tous les bots, ou seulement pour certains (le cas testé, `lancelot`, a un cron de rattrapage
   dédié — les bots sans gateway permanent n'ont peut-être pas cette propriété) ?
4. **Robustesse du verrou « live owner »** : que doit voir Ludo si WebUI tente d'écrire pendant
   qu'un cron/CLI tient déjà la session (collision réelle, pas juste observée dans l'historique) ?
   Un message d'erreur clair côté WebUI, pas un échec silencieux.
5. **✅ Fait le 04/09/2026** : renommage complet (`continue_bot_chat_prototype` →
   `continue_bot_chat`, retrait de « (prototype) » du libellé i18n FR/EN et du `title` du
   bouton, fichier de tests renommé `test_bot_mesh_continue.py`). `POST /api/bot-chat/continue`
   ne change pas de chemin.

## 7. Ce qui ne change pas

- Palier B (B1–B3) reste en l'état, déployé, ne se défait pas — B4 en est la suite naturelle,
  pas un remplacement.
- Discipline de fork inchangée : recon → plan → code → tests → validation `.178` → patch/push.
