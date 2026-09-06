# Plan — correction des écarts de fond (bots Hermes + fork WebUI)

> Rédigé le 06/09/2026, après l'audit complet du chantier (hiérarchie, liens de communication,
> fork WebUI B1→B4+UX). Les paliers B1 à B4 sont livrés, déployés et vérifiés — ce plan ne les
> retouche pas. Il traite les **8 écarts de fond** restants, c'est-à-dire ce qui ne répond pas
> encore à la demande d'origine ou ce qui repose sur une décision non prise.
>
> Convention du dépôt : ce document suit `PLAN-palier-B.md` / `PLAN-B4-fusion-conversation.md`.
> Toute divergence de fork produite ici doit être enregistrée dans `FORK-CHANGES.md`.

---

## 0. Constats mesurés le 06/09/2026 (base factuelle du plan)

Vérifiés en direct sur `.178`, pas repris de la doc :

| Constat | Valeur |
| :-- | :-- |
| Prod == dépôt local | `768639d7`, arbre propre, service `active` |
| Tests fork | 156 passés / 1 ignoré (157 cas, 18 fichiers) |
| Dette de rebase amont | **nulle** (`upstream/master` figé au 25/08) |
| 18 gateways permanents | tous `running`, load 0.61, 6 Go RAM dispo → **l'essai du 05/09 tient** |
| Chaîne `Venec → Lancelot → Roi Arthur → Telegram` | a fonctionné en réel à 17:02 → 17:18 (marqueur conservé verbatim) |
| Mises à jour de l'agent dans la journée | **5** (11:01, 12:00, 13:00, 17:01, 18:02) |
| Patches locaux de l'agent après la dernière update | présents (réinjection `message_agent`, horodatage relais) |
| `~/.hermes/fleet_restart_pending` | présent (18:01) alors que les gateways ont redémarré à 18:02:59 |
| `~/.hermes/profiles/default/` | ne contient **que** `scripts/` — pas de `state.db`, pas de `config.yaml` |

Deux de ces lignes changent la lecture d'un écart :

* la cadence de mise à jour de l'agent (5/jour) fait de la **dérive de code** un problème
  permanent, pas un incident ponctuel — voir **E7** ;
* le doublon `default` vient d'un dossier **que nous avons créé nous-mêmes** le 04/09 en
  déployant les scripts de relais — voir **E4**, la correction peut être gratuite.

---

## E1 — Les 30 canaux de communication ne sont appliqués par rien

**Écart.** `infra/hermes-communication-paths.md` spécifie 30 canaux directs + 4 passerelles vers
le Perso. Rien ne les fait respecter : ils vivent dans les prompts et le vault.

**Cause, vérifiée dans le code de l'agent** (`tools/bot_mode_dm.py` sur `.178`) :

```python
roster = [name for name, _dir in _roster(root)]        # ~ligne 182 : TOUS les profils
teammates = [_handle(n) for n in roster if n != me]    # ~ligne 184 : présenté au modèle
resolved = _resolve_local_name(raw_target, roster)     # ~ligne 229 : valide contre TOUT le roster
```

Le modèle reçoit la liste complète des 17 autres bots comme « teammates », et la validation de
cible ne connaît aucune notion d'autorisation. Un bot Perso peut écrire à un bot Pro ; rien ne
le refuse, rien ne le signale.

### Deux leviers, à ne pas confondre

**Option A — détecter (dans le fork, zéro couplage agent).**
`api/bot_mesh.py` extrait déjà la cible de chaque tour `relay_out`. On ajoute la carte des
canaux à `api/bots_hierarchy.json` (clé `channels`), et chaque relais lu est qualifié
conforme / hors-spec. Rendu : pastille sur la carte de relais dans le fil, compteur
« N échanges hors spec (7 j) » dans le panneau Bots.

* Coût : petit (un module de validation + un champ dans la réponse `/api/bot-chat`, front léger).
* Risque : nul — lecture seule, testable hors ligne, aucun patch amont.
* Bénéfice immédiat : on **mesure** enfin le respect de la spec au lieu de le supposer.

**Option B — appliquer (patch local de l'agent).**
Aux deux points d'accroche ci-dessus : filtrer `roster`/`teammates` par expéditeur (le modèle ne
voit que ses interlocuteurs autorisés) et refuser au dispatch avec une erreur structurée
listant les cibles permises.

* Coût : un **patch local supplémentaire à rejouer après chaque `hermes update`** — soit 5 fois
  aujourd'hui. Dépend donc de **E7a**.
* Risque réel : une allowlist fausse casse une chaîne qui marche. Rappel des cas à ne pas
  interdire par accident : la chaîne changelog `Venec → Lancelot → Roi Arthur`, et
  `Merlin → n'importe quel bot` (règle assouplie le 05/09).

**Recommandation : A d'abord, B ensuite — et seulement si A montre des violations réelles.**
Verrouiller un mesh qu'on n'a jamais observé, c'est risquer de casser plus que ce qu'on protège.
Une semaine de mesure suffit à trancher.

**Prérequis commun.** La spec existe en deux exemplaires partiellement contradictoires :
`hermes-communication-paths.md` déclare caduques trois sections de
`hermes-bots-hierarchie.md`. Avant tout code, produire **une** source machine-lisible
(`bots_hierarchy.json`, clé `channels`) et faire pointer les deux notes du vault vers elle.

> **Décision attendue (D1)** : observer d'abord (A) ou verrouiller tout de suite (A+B) ?

---

## E2 — Le cloisonnement Pro/Perso dans WebUI n'a jamais été testé

**Écart.** Le vault le signale comme **bloquant avant usage courant multi-bots** depuis le
03/09. Personne ne l'a vérifié. Ce n'est pas une correction, c'est une campagne de test qui
produira (ou non) des correctifs.

### Protocole — surfaces à éprouver une par une

| # | Surface | Question |
| :-- | :-- | :-- |
| 1 | Liste des sessions (sidebar) | En basculant `lancelot` → `guenievre`, reste-t-il des sessions de l'autre branche ? |
| 2 | Workspace / explorateur de fichiers | Les profils partagent-ils `/home/atx/workspace` ? Un fichier écrit sous un bot Pro est-il lisible sous un bot Perso ? |
| 3 | Recherche et commandes | Une recherche remonte-t-elle des contenus hors profil actif ? |
| 4 | Onglet Trace (itération 2) | Ne montre-t-il que la session courante ? |
| 5 | Upload / pièces jointes | Rangés par profil ou dans un dossier commun ? |
| 6 | Panneau Bots lui-même | Il affiche **volontairement** les deux branches, aperçus compris. |

Le point 6 mérite une décision explicite : c'est Ludo qui regarde, pas un bot — ce n'est donc
pas une fuite au sens de la règle de cloisonnement (qui vise les bots entre eux). À acter, sinon
on « corrigera » une non-fuite.

**Livrables.** `tests/test_profile_isolation.py` (unitaire, homes factices, un test par surface)
+ une checklist de vérification manuelle en prod + les correctifs éventuels. Le point 2 est le
plus probable porteur de fuite (workspace partagé par défaut) et se traite, s'il se confirme,
par un workspace par profil.

> **Décision attendue (D2)** : le panneau Bots reste-t-il transverse aux deux branches ?

---

## E3 — Pas de badge « non lu », pas de rafraîchissement en arrière-plan

**Écart.** Seule la conversation ouverte dans l'onglet actif se rafraîchit. Pour savoir qui t'a
répondu, il faut ouvrir chaque bot. C'est l'écart qui coûte le plus au quotidien.

**Ce qui existe déjà et qu'on réutilise** : `/api/bots` renvoie `last_activity` et
`last_bot_chat_snippet` par bot, et le panneau se rafraîchit toutes les 15 s. Il ne manque
qu'un « vu jusqu'où » par bot.

**Conception retenue** — état **côté serveur**, pas `localStorage` :

* nouveau store `<HERMES_HOME>/webui/bot_seen.json` (même patron que
  `bot_customization.json`), `{profil: {seen_message_count, seen_at}}` ;
* `/api/bots` renvoie `unread` par bot (delta entre le compte de `state.db` et le compte vu) ;
* marquage lu à l'ouverture de la conversation (route `POST /api/bots/seen`) ;
* badge sur la carte + total sur le bouton Bots du rail.

Le stockage serveur est ce qui fait la différence d'usage : le badge doit être le même sur le
téléphone et sur le poste — c'est précisément la raison d'être de WebUI comme porte d'entrée.

* Coût : petit backend (1 module + 2 routes), petit front (badge + appel de marquage).
* Tests : hors ligne, sur homes factices, comme le reste de la suite bots.
* Hors périmètre assumé : notification push. Un badge visible à l'ouverture suffit au besoin
  exprimé.

---

## E4 — Doublon `default` hors du panneau Bots

**Écart.** Corrigé dans le panneau Bots seulement ; toujours visible dans le sélecteur de profil
et le panneau Agent profiles.

**Cause, désormais complète.** `_build_profile_rows_fast` code en dur le nom `'default'` pour le
home de base **et** `~/.hermes/profiles/default/` existe. Or ce dossier ne contient **que**
`scripts/` (copie du script de relais déployée le 04/09) — ni `state.db`, ni `config.yaml`.
**C'est un dossier que nous avons créé nous-mêmes**, pas un profil réel.

### Correction, par ordre de préférence

1. **Recon (5 min)** : déterminer quel chemin le job `relais-message-agent-default`
   (`c56185e8136e`) résout réellement — `~/.hermes/scripts/relay_message_agent.py` (présent) ou
   la copie sous `profiles/default/scripts/`. Lire le résolveur de scripts du runner cron.
2. **Si c'est le chemin de base** : supprimer le dossier vestigial (après sauvegarde). Le
   doublon disparaît **partout**, à coût de code nul, et la cause racine est éliminée.
3. **Sinon** : déplacer le script vers le home de base, adapter le job, puis supprimer.
4. **Repli code** (seulement si 2 et 3 sont impossibles) : dédoublonner par nom dans
   `list_profiles_api` plutôt que dans le seul panneau — avec tests de non-régression sur le
   sélecteur de profil et le panneau Agent profiles, deux surfaces **amont**.

---

## E5 — Heure exacte : les tours hors WebUI restent aveugles

**Écart.** `api/fork_time_context.py` ne couvre que les tours pilotés depuis WebUI. Un bot qui
répond sous son gateway ne voit pas le bloc d'heure.

**Cause.** C'est délibéré côté amont : une session « Bot Chat » a un prompt **volontairement
sans horloge** (`_bot_chat_timeless_prompt` → seulement `Timezone: …`), pour garder le préfixe
byte-stable et le cache utile. Hors Bot Chat, l'amont ne donne que la **date** et renvoie le
modèle vers un outil pour l'heure — que les modèles gratuits n'appellent jamais.

**Mitigation déjà en place** : chaque message relayé porte `[sent <horodatage> — sender clock,
UTC]`.

### Options

| | Coût | Survit aux updates | Effet cache |
| :-- | :-- | :-- | :-- |
| (a) Patch agent de `_timestamp_line` | patch à rejouer + réécriture d'un chemin amont sensible | non | **casse le préfixe pour les 18 gateways** |
| (b) Consigne dans les `SOUL.md` : « tu n'as pas d'horloge ; ne jamais affirmer une heure ; se référer à la ligne `[sent]` » | rédactionnel | oui | nul |
| (c) Ne rien faire hors WebUI | nul | — | nul |

**Recommandation : (b).** C'est le même arbitrage que le point 7 de l'itération 2 — quand c'est
le bot qui écrit une bêtise, c'est le prompt du bot qu'on corrige, pas la plateforme. (a) fait
payer un coût de cache permanent à 18 gateways pour un défaut rédactionnel.

---

## E6 — Palier C : la question de cadrage n'a jamais reçu de réponse

Ce n'est pas un défaut à corriger, c'est une décision qui conditionne tout le reste de la
feuille de route. Question fermée, deux réponses possibles :

* **Supervision unifiée** (un sélecteur de bot, toutes les sessions, l'activité de chaque bot,
  **une conversation à la fois**) → c'est ce qu'est Hermes Desktop, et c'est **déjà atteint**
  par le palier B. Rien de plus à faire.
* **Exécution concurrente réelle** (plusieurs bots qui travaillent et s'affichent en parallèle,
  organigramme, graphe de routage) → C1 + C2, plusieurs mois, dépendance à l'API agent amont
  (#1925), forte divergence de fork.

Si la seconde : ne pas coder C1 d'emblée mais un **spike jetable** — adaptateur runtime devant
2 profils, critère de succès mesurable (*deux tours de deux bots différents, lancés en même
temps, restent isolés en mémoire, workspace et état*). On investit seulement si le spike tient
et si #1925 avance.

> **Décision attendue (D3)** : supervision (statu quo) ou exécution concurrente (spike C1) ?

---

## E7 — (transverse) Dérive de code et rejeu des patches locaux

**Écart révélé par la mesure du jour.** L'agent s'est mis à jour **5 fois** aujourd'hui. Trois
conséquences, toutes structurelles :

### E7a — Le rejeu des patches locaux n'est pas vérifié

Deux patches locaux tiennent des fonctions critiques : la réinjection de `message_agent` après
compaction (sans elle, le bug Lancelot revient) et l'horodatage des messages relayés. Ils sont
présents après la mise à jour de 18:02 — **aujourd'hui**. Rien ne le vérifie ni ne l'alerte.

**Correction** : `verify_agent_patches.py` — idempotent, lancé par `hermes_autoupdate.py` juste
après une mise à jour réelle, qui contrôle la présence de chaque patch et **alerte** (canal
d'egress déterministe existant) si l'un n'a pas pu être rejoué. Sans ça, un patch sautera un
jour en silence et on rejouera un incident déjà résolu.

### E7b — Le WebUI sert des modules d'agent périmés jusqu'à redémarrage

La bannière de dérive rend le problème visible, mais à 5 mises à jour par jour elle devient un
bruit permanent. Le redémarrage est techniquement anodin : `os.execv`, PID et socket conservés,
`_wait_until_restart_safe()` vide d'abord les flux en cours.

**Option** : redémarrage automatique du WebUI après une mise à jour **réelle** de l'agent
(SHA changé), en réutilisant le point 4 de `hermes_autoupdate.py` qui redémarre déjà la flotte.
Ce n'est **pas** contraire à la règle « le WebUI ne se met jamais à jour tout seul » : le code
WebUI n'est pas touché, on recharge seulement les modules de l'agent qu'il importe.

> **Décision attendue (D4)** : redémarrage automatique du WebUI après update d'agent, ou
> bannière manuelle conservée ?

### E7c — Marqueur `fleet_restart_pending` périmé

Présent (18:01) alors que les gateways ont redémarré à 18:02:59. C'est exactement le marqueur
qui a déjà produit une fausse alerte d'infrastructure. **Correction** : nettoyage + garde dans
le health-check existant (marqueur dont le `expected_sha` correspond au SHA courant *et* dont
les gateways ont démarré après son écriture ⇒ périmé, à supprimer).

---

## E8 — Hygiène du dépôt

10 fichiers non suivis à la racine : 5 documents d'analyse/plan/prompt, 3 `.patch` (redondants
avec les branches git, qui font foi), 2 maquettes HTML.

**Correction** : déplacer les documents dans `docs/fork/` et les committer (ils portent le
raisonnement de tout le chantier — les perdre coûterait cher à la prochaine reprise à froid),
supprimer les `.patch`, archiver les maquettes.

---

## 9. Séquencement

| Lot | Contenu | Pourquoi cet ordre |
| :-- | :-- | :-- |
| **0 — immédiat** | E4 (recon + suppression), E7c (marqueur), E8 (hygiène) | Gratuit ou quasi, supprime deux causes racines et le bruit |
| **1 — fiabilité** | E7a (vérification des patches), E2 (campagne d'étanchéité) | E2 est déclaré bloquant depuis le 03/09 ; E7a protège des acquis déjà payés |
| **2 — usage** | E3 (badge non lu), E5b (consigne `SOUL.md`) | Le gain quotidien le plus direct, sans dépendance |
| **3 — gouvernance du mesh** | E1a (détection), puis décision E1b | Mesurer avant de verrouiller |
| **4 — cap** | E6 (cadrage), puis spike C1 si retenu | Dépend d'une décision, pas d'un développement |

Les lots 0 à 2 sont indépendants les uns des autres et peuvent être menés dans n'importe quel
ordre. Le lot 3 dépend de la réconciliation de la spec des canaux ; le lot 4 ne dépend de rien
d'autre qu'une réponse.

## 10. Décisions à prendre (bloquantes)

| | Question | Défaut si pas de réponse |
| :-- | :-- | :-- |
| **D1** | Canaux : observer d'abord (A) ou verrouiller tout de suite (A+B) ? | A seul — on mesure une semaine |
| **D2** | Le panneau Bots reste-t-il transverse Pro/Perso ? | Oui — c'est Ludo qui regarde, pas un bot |
| **D3** | Palier C : supervision (statu quo) ou exécution concurrente (spike) ? | Statu quo |
| **D4** | Redémarrage automatique du WebUI après update d'agent ? | Bannière manuelle conservée |
| **D5** | Essai des 18 gateways permanents (05/09) : confirmé ? | À confirmer — la mesure du jour (load 0.61, 6 Go dispo) est favorable |

## 11. Discipline à tenir sur tout ce plan

* Toute divergence de fork produite ici → `FORK-CHANGES.md`, et code fork dans des **fichiers
  fork** (`api/bot_*.py`, `static/bots_panel.*`, `i18n_fork.js`).
* `pytest tests/test_fork_upstream_contract.py` d'abord après tout rebase amont.
* Avant de réutiliser une fonction de l'amont depuis le code fork, lire **comment l'amont
  lui-même l'appelle** (leçon du drapeau `_profileSwitchOpeningExistingSession`).
* Aucun `sudo` sur `.178` depuis une session d'agent ; redémarrage du WebUI par
  `kill -9 $(systemctl show hermes-webui.service -p MainPID --value)`.
* Déploiement : `git pull` sur `/home/atx/hermes-webui` **puis** redémarrage — sans quoi les
  assets restent en cache `immutable` sous l'ancien jeton de version.
