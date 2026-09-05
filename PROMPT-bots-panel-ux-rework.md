# Prompt de reprise — refonte UX du panneau Bots (persistant, façon Discord)

Reprends le chantier du panneau "Bots" de Hermes WebUI (dépôt local `D:\Projets\Hermes WebUI`,
fork `ATX-AI-Dev/hermes-webui`, branche `feat/b4-continue-bots`).

## Contexte

Le commit `05a7da0a` (déployé et vérifié en prod sur `.178`) a ajouté une première itération :
vignette avatar (emoji + couleur, déclarés dans `api/bots_hierarchy.json`), aperçu texte du
dernier message (`api/bot_mesh.py::last_bot_chat_snippet*`, `api/bots_overview.py`), et un
polling 15s côté `static/panels.js::loadBotsPanel`. Vu en prod, Ludo valide la direction
générale ("on approche bien de l'idée") mais demande une deuxième passe de refonte assez
profonde — plus proche d'un client façon Discord/Grok avec un panneau bots **permanent**, pas
un onglet plein écran qu'on ouvre/ferme.

Lis d'abord le fichier de plan de la première itération (déjà exécuté) pour le contexte
technique complet du panneau actuel : cherche dans l'historique git le commit `05a7da0a` et
son message, ainsi que `api/bots_overview.py`, `api/bot_mesh.py`, `static/panels.js` (fonction
`loadBotsPanel` ~ligne 6711 et son voisinage), `static/style.css` (bloc `.bots-*` ~ligne 7333).

## Demandes de Ludo (captures d'écran en prod à l'appui, toutes à traiter)

1. **Vignette entière cliquable** — aujourd'hui seuls les boutons ("Continue", "Inter-bot
   thread", "Stop gateway") sont cliquables. Toute la carte du bot doit ouvrir sa conversation
   (comportement actuel du bouton "Continue" / `data-act="continue"`, avec fallback
   `data-act="open"` pour les bots sans Bot Chat).

2. **Actions secondaires repliées** — "Inter-bot thread" et "Stop gateway" ne doivent plus être
   visibles en permanence : les masquer dans une zone repliable (accordéon/menu "···") en bas de
   la vignette, ouverte à la demande. Le clic sur ces actions ne doit pas déclencher le clic
   "ouvrir la conversation" de la carte entière (attention à la propagation d'événement, cf.
   `_botsOnClick` dans `panels.js`).

3. **Retirer le nom du modèle** (ex. `longcat-2.0:free`, `.bots-model` dans le rendu actuel) de
   l'affichage de la carte — plus besoin de l'avoir visible.

4. **Le badge "P"** = passerelle permanente (`bot.permanent_gateway`, i18n `bots_permanent` =
   "passerelle permanente" / "permanent gateway"). Il indique que le gateway de ce bot tourne en
   continu au lieu d'être démarré à la demande. À décider avec Ludo s'il doit rester visible en
   façade (icône plus parlante ?) ou rejoindre lui aussi les détails repliés du point 5.

5. **Compteur de sessions replié** — le badge "N sessions" (`.bots-pill`, `bot.active_sessions`)
   doit rejoindre la même zone de détails repliés que le point 2, pas rester visible par défaut.

6. **Panneau Bots permanent** — actuellement `switchPanel('bots')` bascule tout le `<main>` en
   vue plein écran façon les autres onglets (`MAIN_VIEW_PANELS`, `panels.js` ~ligne 47), en
   remplaçant la zone de chat. Ludo veut que la liste des bots reste **affichée en permanence**,
   comme une colonne latérale toujours visible à côté de la conversation active — comparable à la
   sidebar "CHAT" des sessions déjà présente à gauche. C'est un changement d'architecture (pas
   juste de CSS) : il faut concevoir comment ce panneau persistant cohabite avec la sidebar
   sessions existante et le panneau de chat central (bots en permanence à gauche ou en overlay
   redimensionnable ? Remplace-t-il la sidebar sessions, ou vient-il à côté ?). **Poser la
   question à Ludo avant de se lancer** — plusieurs dispositions sont possibles et la capture
   d'écran fournie montre le panneau bots occupant toute la colonne gauche (donc probablement en
   remplacement/onglet de la sidebar sessions plutôt qu'une 3e colonne).

7. **Nettoyer la vue "Continue"** — cliquer "Continue" importe le Bot Chat et bascule sur la
   conversation (`continue_bot_chat`, `api/bot_mesh.py`), mais affiche en fil de discussion des
   informations que Ludo ne veut pas voir en permanence : logs `[IMPORTANT: Background process
   ...]`, bloc "Trace / Expand all / Collapse all", tableaux de statut consolidés, etc. Cette
   info doit être masquée par défaut dans le fil et déportée en accès à la demande dans le
   panneau latéral droit "WORKSPACE" (déjà existant, onglets "Files" / "Artifacts" visibles dans
   les captures) — probablement un nouvel onglet "Trace" ou "Détails de session" dans ce panneau
   Workspace plutôt que dans le flux de messages. À explorer : où ce rendu riche est produit
   côté front (rendu des tool calls / trace dans le composant de chat principal, pas dans
   `panels.js` bots) avant de décider du point d'accroche exact.

8. **Bug : le profil interne "default" apparaît deux fois** dans la branche "Profil interne" du
   panneau bots (voir capture — deux cartes identiques "default · Chat standard"). Piste
   d'investigation : `api/profiles.py` a une gestion non triviale de l'alias `'default'` vs un
   nom d'affichage renommé pour le "root profile" (voir les commentaires autour des lignes
   365-458 et 2021-2092 de `api/profiles.py` : `_is_root_profile`, `_root_profile_name_cache`,
   le commentaire "Upstream hardcodes the base home's display name to 'default' even when...").
   `build_bots_overview` (`api/bots_overview.py`) itère sur `list_profiles_api()` sans dédoublonnage
   explicite par alias — vérifier si `list_profiles_api()` retourne deux lignes distinctes pour
   le même profil root dans certaines configurations (nom renommé + alias legacy 'default').

9. **Renommer le profil `default`, pas le bouton "Chat"** — le bouton "Chat" de la barre latérale
   gauche (`data-panel="chat"`, `static/index.html` ~ligne 155 et ~175) reste tel quel : il ouvre
   déjà la conversation avec le profil actif, et dans le nouveau découpage (points 9-11) ce sera
   systématiquement le profil `default`. Ce qui doit changer, c'est le **nom d'affichage** du
   profil `default` lui-même, aujourd'hui affiché tel quel ("default") — pas assez explicite pour
   un utilisateur non technique. Il existe déjà dans `api/profiles.py` un mécanisme de nom
   d'affichage distinct de l'alias legacy `'default'` pour le "root profile" (voir les
   commentaires autour des lignes 365-458 et 2021-2092 : `_is_root_profile`,
   `_root_profile_name_cache`, le commentaire "Upstream hardcodes the base home's display name to
   'default' even when..."). Vérifier si ce mécanisme permet déjà de définir un nom d'affichage
   personnalisé pour le root profile (auquel cas il suffit de l'utiliser/l'exposer dans l'UI de
   renommage) plutôt que d'en recréer un nouveau — probablement le même endroit à corriger que le
   bug de duplication du point 8, les deux viennent de la même zone de code. Nom proposé à
   valider avec Ludo (ex. "Assistant", "Moi", "Perso" — ne pas décider seul).

10. **Repositionner et réicôner le bouton "Bots"** de la barre latérale gauche
    (`data-panel="bots"`, `static/index.html` ligne 162, actuellement après "Agent profiles" et
    avant "Todos") : le déplacer juste **sous** le bouton "Chat" (donc en 2e position dans le
    rail), et remplacer son icône SVG actuelle (un petit diagramme en arbre) par une icône plus
    évocatrice d'un "système de bots" (ex. icône robot/tête de robot). Il y a deux copies du
    rail à modifier en cohérence (`rail-btn` desktop ligne ~162, `sidebar-nav` mobile ligne
    ~182).

11. **Exclure les profils internes du panneau Bots** — les branches `interne` (`default`) ne
    doivent plus apparaître du tout dans la liste des bots (cohérent avec le point 9 : ce profil
    garde son accès dédié via le bouton "Chat" existant, sous son nouveau nom d'affichage).
    Filtrage à faire côté
    `build_bots_overview` (`api/bots_overview.py`) ou côté rendu (`loadBotsPanel`) — probablement
    le premier, pour ne pas non plus le compter dans `counts.total`/`counts.gateways_up`. Vérifier
    l'impact sur `api/bots_hierarchy.json` (branche `"interne"` déclarée dans `branches`) et sur
    les tests existants (`tests/test_bots_overview_b2.py`, `tests/test_bots_avatar_preview.py`)
    qui pourraient référencer ce profil.

12. **Personnalisation par bot (nom d'affichage + image de profil circulaire)** — chaque bot
    (= profil Hermes) doit pouvoir avoir un nom d'affichage et une image de profil (au lieu du
    seul emoji actuel) définis par l'utilisateur, pas seulement le champ `emoji`/`color` statique
    de `api/bots_hierarchy.json`. Points à trancher avec Ludo avant de coder :
    - Où stocker cette personnalisation : étendre `api/bots_hierarchy.json` (aujourd'hui
      fork-local, avec une notion d'override opérateur déjà en place via
      `<HERMES_HOME>/webui/bots_hierarchy.json`, voir `api/bots_overview.py::_load_hierarchy`),
      ou un nouveau petit store dédié (JSON séparé, plus adapté à de l'upload d'image) ?
    - Upload d'image : où sont stockés les fichiers uploadés ailleurs dans le projet (chercher
      un précédent, ex. avatars utilisateur, pièces jointes du composer) pour rester cohérent
      avec le pattern existant plutôt que d'inventer un nouveau mécanisme de stockage de
      fichiers.
    - UI d'édition : probablement dans le futur menu replié de la carte bot (point 2), ou dans le
      panneau "Agent profiles" existant (`data-panel="profiles"`) — à clarifier avec Ludo.

## Méthode

- Ce chantier touche à la fois de l'architecture front (panneau permanent, point 6) et plusieurs
  ajustements plus contenus (points 1-5, 8-11) — commencer par cadrer le point 6 avec Ludo
  (questions ouvertes ci-dessus) avant d'attaquer le reste, car il conditionne la structure DOM
  de tout le reste du panneau.
- Utiliser `EnterPlanMode` : c'est un changement multi-fichiers avec plusieurs décisions de
  disposition (UI) où Ludo doit trancher — ne pas coder avant validation du plan.
- Vérifier `tests/test_bots_panel_frontend_b2.py`, `tests/test_bots_overview_b2.py`,
  `tests/test_bots_avatar_preview.py` après chaque changement de structure (ce sont des tests
  "garde-fou" qui vérifient des chaînes littérales dans `panels.js`/`style.css`/`index.html` —
  les mettre à jour plutôt que les laisser rouges).
- Déploiement sur `.178` : `cd /home/atx/hermes-webui && git pull && sudo systemctl restart
  hermes-webui.service` (session SSH interactive requise pour le `sudo`) — voir vault
  `infra/hermes-webui.md` / `infra/ssh-access.md`.

Une fois le contexte chargé, commence par poser à Ludo les questions ouvertes des points 6, 9 et
12 avant de proposer un plan.

---
*Généré le 05/09/2026, suite au retour visuel de Ludo sur le déploiement du commit `05a7da0a`.*
