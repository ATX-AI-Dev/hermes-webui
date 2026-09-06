# Prompt de reprise — Lancelot a perdu `message_agent` (Hermes Agent)

> À coller tel quel au démarrage d'une session dédiée à **Hermes Agent** (pas au fork WebUI).
> Rédigé le 05/09/2026 à la fin de la session « panneau Bots itération 2 », qui a découvert le
> problème sans le traiter.

---

Enquête sur une régression de Hermes Agent sur le serveur de production `.178`.

## Le symptôme

Le 05/09/2026 vers 21:40 UTC, **Lancelot** (profil `lancelot`, manager de la branche Pro) a reçu
un message d'un autre bot dans sa session « Bot Chat », a voulu le relayer, et a obtenu :

```
Tool 'message_agent' does not exist. Available tools: browser_exec, clarify,
delegate_task, execute_code, memory, patch, read_file, search_files,
skill_manage, skill_view
```

**Ce n'est pas seulement `message_agent` qui manque : il n'a que 10 outils.** Pas de `terminal`,
pas de `cronjob`. C'est une liste **tronquée**, pas une simple absence d'injection — c'est
probablement l'indice principal.

## Pourquoi ça compte

Lancelot est le **pivot de la remontée hiérarchique** du « royaume » de bots de Ludo (voir le
vault, `infra/hermes-bots-hierarchie.md`). Toute chaîne `bot → Lancelot → Roi Arthur → Ludo`
passe par lui. S'il ne peut plus appeler `message_agent`, une bonne partie de la branche Pro est
muette — silencieusement, puisque le bot se rabat gracieusement sur du texte en clair.

## Ce qui est déjà établi — ne pas le refaire

Comparaison faite le 05/09/2026, même jour, même version d'agent (`ee5b5ec21e`) :

| | Venec (fonctionne) | Lancelot (échoue) |
| :-- | :-- | :-- |
| `is_bot_mode_managed(home)` | vrai | vrai |
| Session titrée « Bot Chat », `hidden=1` | une seule | une seule |
| **Messages dans la session** | **26** | **887** |
| Dernier `message_agent` réussi | **05/09 21:38** | **04/09 22:44** |
| Erreur « tool does not exist » | jamais | **05/09 21:40** |

C'est une **régression datée** : Lancelot envoyait encore normalement le 04/09 à 22:44, et
l'erreur apparaît à la toute première sollicitation suivante.

**Écarté par vérification directe :**

* **Pas le SOUL.md** — `is_bot_mode_managed()` renvoie vrai pour `venec`, `lancelot`,
  `roi-arthur`, `guenievre`, `perceval`.
* **Pas le titre de session** — la session qui porte l'erreur est bien `20260901_070436_73676c`,
  titrée « Bot Chat », `hidden=1`, et c'est la même que celle où le message est arrivé. Le gate
  `BOT_CHAT_TITLE` de `tools/bot_mode_dm.py` devrait donc passer.
* **Pas un gateway tombé** — `hermes-gateway-lancelot` était actif depuis 21:18 sans redémarrage
  pendant l'incident, et le journal ne contient rien au moment du tour.

**Angle mort à lever en premier :** les 8 autres bots n'ont **aucune** erreur enregistrée, mais
**aucun n'a été sollicité depuis le 04/09**. Rien ne dit qu'ils ne sont pas dans le même état.

## Hypothèse principale (non vérifiée)

**Perte d'outils sous pression de contexte.** La seule différence structurelle nette entre Venec
et Lancelot est la taille de session : 26 messages contre 887. Une liste d'outils tronquée est
cohérente avec un mécanisme de réduction (compaction, budget de contexte, registre dégradé pour
ce tour).

Pistes de code, dans `/home/atx/.hermes/hermes-agent` :

* `tools/bot_mode_dm.py::ensure_message_agent_tool` — le commentaire dit *« the gate is stable
  from the first turn »*, ce qui suggère une **mise en cache par session**. Si le gate a été
  calculé faux lors d'un tour, il pourrait rester faux pour la vie de la session.
* `agent/system_prompt.py:326` — `_bot_section` n'est calculé que si `_title == BOT_CHAT_TITLE`.
* `agent/conversation_loop.py:612` — lit `_bot_mode_protocol`.
* `tools/registry` — les journaux des gateways sont pleins de `check_fn ... returned False;
  dependent tools will be unavailable this turn`, donc la liste d'outils **est** recalculée et
  filtrée à chaque tour. Comprendre ce filtre est probablement la clé.

## Ce que j'attends de cette session

1. **Mesurer l'étendue avant de corriger.** Faire émettre un `message_agent` de test à 2-3 autres
   bots (au minimum `roi-arthur` et `perceval`) et déterminer si le problème est propre à
   Lancelot ou général. C'est la question qui change tout le reste.
2. **Trouver la cause racine**, pas un contournement.
3. **Proposer un correctif** et le faire valider par Ludo avant application.

## Contraintes à respecter

* **`.178` est une machine de production** (18 gateways de bots, Home Assistant, n8n, un tunnel
  Cloudflare). Accès SSH : `ssh -i C:\Users\Ludo\.ssh\id_ed25519_atx178 atx@192.168.1.178`.
  `sudo` demande un **mot de passe** — donc à faire lancer par Ludo en session interactive.
* **Ne pas patcher `hermes-agent` à la légère** : `hermes update --yes` tourne automatiquement
  toutes les heures (`~/.hermes/hermes_autoupdate.py`, timer utilisateur) et **écrasera tout
  patch local**. Si un correctif de code est nécessaire, c'est soit une contribution amont, soit
  un mécanisme qui survit à la mise à jour (configuration, surcharge, script externe).
* **Sauvegarde datée systématique** avant toute modification de fichier sous `~/.hermes/`
  (convention en place : `.bak-AAAAMMJJ`).
* **La session Bot Chat de Lancelot porte 887 messages d'historique du royaume.** Si le
  contournement envisagé est de l'archiver ou de la compacter, le dire clairement à Ludo et
  obtenir son accord — ce n'est pas une donnée jetable.
* **Ne pas masquer le problème** : contourner en donnant à Venec un chemin direct vers Roi Arthur
  ou vers Telegram est explicitement refusé. Ludo veut que l'information suive la chaîne
  hiérarchique.

## Contexte utile

* Vault : `infra/hermes-cron-jobs.md` (section « 🔴 Perte de `message_agent` chez Lancelot »,
  détail complet), `infra/hermes-bots-hierarchie.md`, `infra/hermes-webui.md` (section « Veille
  de Venec », le dispositif que ce bug bloque).
* Le mécanisme de relais (`relay_message_agent.py`, `hermes-relay-watcher.service`) n'est **pas**
  en cause : il achemine les réponses, il ne crée pas l'outil. Ses correctifs de fiabilité des
  04-05/09/2026 sont valides et vérifiés.
* Ce qui dépend de ce correctif : la veille de Venec, déployée le 05/09/2026, qui produit un
  changelog français à chaque mise à jour de l'agent et doit le faire remonter
  `Venec → Lancelot → Roi Arthur → Telegram`. Venec fait sa part correctement — vérifié en
  conditions réelles. La chaîne s'arrête à Lancelot.

Commence par la question 1 (l'étendue) avant toute hypothèse de correctif.
