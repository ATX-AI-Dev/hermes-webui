# Spike C1 — « exécution concurrente réelle » : ce que la mesure dit

> Mené le 06/09/2026 sur `.178`, agent `c5594ec4`. Décision D3 de Ludo :
> *exécution concurrente (spike)*. Réponse au **critère de succès** posé dans
> `PLAN-ecarts-de-fond.md` §E6 : « deux tours de deux bots différents, lancés en même temps,
> restent isolés (mémoire, workspace, état) ».
>
> **Verdict : le critère est déjà tenu par la voie actuelle.** Le gros chantier C1 — un
> runtime d'exécution découplé derrière `/v1/runs` — n'est **pas** nécessaire pour obtenir
> l'exécution concurrente. Ce qui manque est côté affichage (C2).

---

## 1. Pourquoi la question se posait

L'analyse d'origine (`ANALYSE-integration-bots-palier-C.md`) déconseillait le palier C tant que
l'API agent amont (#1925) n'aurait pas atterri, au motif que WebUI a un « modèle d'exécution
mono-requête » : deux bots ne pourraient pas travailler en parallèle sans se marcher dessus,
parce que le profil actif est une notion **ambiante** (thread-local WebUI, variables
d'environnement côté agent).

C'était une hypothèse raisonnable, jamais mesurée. Elle conditionnait des mois de travail.

## 2. Ce qui a été mesuré, et comment

On ne mesure pas un tour LLM : l'isolation ne se joue pas dans le modèle, elle se joue dans la
**portée des variables** que le chemin de streaming utilise pour épingler un profil. Deux
threads épinglent chacun un bot (`lancelot` / `guenievre` — le pire cas, une arête Pro/Perso),
se synchronisent sur une barrière pour être **simultanément** épinglés, puis relisent leur état.

Sans la barrière, chaque thread lirait sa valeur avant que l'autre n'écrive la sienne, et un
état partagé passerait pour isolé. C'est le point de méthode qui fait toute la valeur du test.

## 3. Résultat

| Mécanisme | Portée réelle | Verdict |
| :-- | :-- | :-- |
| `hermes_constants.set_hermes_home_override` (ce qu'utilise `api/streaming.py`) | **ContextVar** — le code amont précise *« Deliberately does not mutate os.environ »* | ✅ isolé |
| `api.profiles._tls` (profil actif de WebUI, socle de B1) | thread-local | ✅ isolé |
| `os.environ['HERMES_HOME']` (repli des agents anciens) | process-global | ❌ **racé** : dans la mesure, le thread `lancelot` a lu le home de `guenievre` |

Deux constats complémentaires, lus dans le code amont :

* **Les garde-fous « busy » sont par session, pas par processus** (`Session busy, try again`,
  `Session is busy (streaming)`), et `STREAMS` est un registre de flux multiples. Rien ne
  sérialise deux tours de deux bots différents.
* **L'amont durcit activement la concurrence** : `_ENV_LOCK` est volontairement étroit (« le
  verrou n'est pas tenu pendant tout le run »), et une RCA amont (`t_f62ff1e8`) a déjà corrigé
  une course entre **deux tours WebUI simultanés** sur la clé de session, en passant de
  `os.environ` à des context-locals. La concurrence n'est pas un cas non prévu : c'est un cas
  déjà débogué en production chez l'amont.

Tests figeant tout ceci : `tests/test_concurrent_bot_isolation_c1.py` — **5/5 sur `.178`**
(le test d'isolation du home se met en `skip` sur le poste Windows, où l'agent est absent).

## 4. Ce que ça change pour la feuille de route

**C1 n'est pas le chantier à faire.** Le découplage d'exécution servirait à obtenir une
isolation… qui est déjà là sur cet agent. Ce serait payer une divergence de fork majeure, contre
un amont qui publie plusieurs releases par jour, pour une propriété acquise.

**Le vrai reste-à-faire est C2, l'affichage.** WebUI sait exécuter plusieurs bots en même temps ;
il ne sait pas les **montrer** en même temps : une conversation centrale à la fois, une sidebar
de sessions scopée au profil actif, et un basculement de profil qui recentre toute l'interface.
C'est un chantier front, contenu, sans dépendance amont — d'une autre nature que C1.

## 5. Risque résiduel à connaître

Tout code de l'agent qui lit `HERMES_HOME` **dans l'environnement** plutôt que par l'override
context-local verra le home d'un autre bot pendant un tour concurrent. Ça n'est pas corrigeable
depuis le fork, et ça ne se voit pas : ça se traduirait par un fichier écrit au mauvais endroit,
pas par une erreur.

Deux garde-fous posés :

* le test `test_environment_home_is_the_racy_fallback_and_stays_documented` fige la différence —
  si quelqu'un « simplifiait » un jour l'override en écriture d'environnement, l'isolation
  tomberait en silence et le test tomberait avec ;
* `test_streaming_prefers_the_context_local_override` vérifie que le chemin de streaming passe
  bien par l'override tant qu'il existe.

## 6. Avant d'ouvrir C2 — la question à trancher

Le spike répond à « est-ce techniquement possible ». Il ne répond pas à « qu'est-ce que Ludo
veut voir ». Trois formes possibles, de la moins à la plus coûteuse :

1. **Badges d'activité** (déjà à moitié fait) : le panneau Bots montre qui travaille et qui a
   répondu, on ouvre une conversation à la fois. Livré par le badge « non lu » + les pastilles.
2. **Deux conversations côte à côte** : un panneau secondaire épinglé sur un autre bot. Contenu :
   une deuxième zone de messages, un deuxième flux SSE, pas de refonte de l'état front.
3. **Cockpit complet** : N panneaux, organigramme, graphe de routage en direct. C'est la
   réécriture de la couche d'état du front — le vrai C2 de l'analyse d'origine.

La 2 est probablement le bon rapport valeur/effort, et elle se teste avec de vrais bots dès le
premier jour. À trancher avec Ludo avant d'écrire une ligne.
