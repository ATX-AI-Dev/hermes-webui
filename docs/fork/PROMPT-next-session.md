# Prompt de reprise — chantier bots Hermes / Hermes WebUI

Reprends le chantier d'intégration des bots Hermes dans Hermes WebUI (dépôt local
`D:\Projets\Hermes WebUI`, fork `ATX-AI-Dev/hermes-webui`).

Lis d'abord entièrement `HANDOFF-next-session.md` à la racine du dépôt — il contient l'état
complet à jour (B4 entièrement déployé en prod sur `.178`, commit `bafa9788` : fusion Bot Chat,
rendu riche sortant ET entrant des tours `message_agent`, verrou d'exclusivité côté WebUI,
rafraîchissement live des Bot Chat), les découvertes techniques critiques à ne pas
re-découvrir, et la liste des tâches restantes en section 4.

Lis aussi dans le vault Obsidian, dans l'ordre : `00-INDEX.md`, `infra/hermes-webui.md`,
`infra/hermes-bots-hierarchie.md`, `infra/hermes-cron-jobs.md` (cette dernière fait foi pour
tout ce qui concerne le mécanisme de relais temps réel `hermes-relay-watcher.service` — un vrai
bug de fiabilité y a été trouvé et corrigé dans la session précédente, liste de profils figée
au démarrage du démon).

**Tâches restantes identifiées (aucune côté hermes-webui — le chantier B4 est fermé) :**

1. **Contact direct Merlin → Lancelot** observé en usage réel alors que la règle l'interdit
   (Merlin ne devrait passer que par le Pilote). Décision à prendre : assouplir la règle, ou
   corriger le comportement de Merlin.
2. **Revalider jusqu'au bout** le correctif de fiabilité de livraison du relais `message_agent`
   — jamais observé transitionner complètement vers `"relayed"` sans verrou de session Desktop
   concurrent.
3. **Réévaluer le throttle de 30s** du démon `hermes-relay-watcher.service` après quelques
   jours d'usage réel.
4. **Décider** si les 13 bots "à la demande" doivent avoir un gateway permanent en filet de
   sécurité natif.
5. **Envisager un health-check périodique** comparant la liste de profils réellement chargée
   par le démon au nombre de jobs actifs (éviter une régression silencieuse du type de celle
   corrigée la session précédente).

Une fois le contexte chargé, présente un résumé bref de l'état et demande comment continuer.

---
*Généré le 04/09/2026 en fin de session (B4 complet + correctifs infra `.178`).*
