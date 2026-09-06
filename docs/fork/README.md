# Documents du fork `ATX-AI-Dev/hermes-webui`

Tout le raisonnement du chantier « bots Hermes dans WebUI » vit ici. Ces fichiers étaient à la
racine du dépôt jusqu'au 06/09/2026 ; ils ont été regroupés pour que la racine reste celle de
l'amont. **Les commentaires de code les citent par leur nom de fichier seul** (par exemple
`PLAN-B4-fusion-conversation.md`) — c'est volontaire : le nom est stable, le chemin non.

Le registre des divergences de fork, lui, reste à la racine : `FORK-CHANGES.md`. C'est le
document à lire avant tout rebase sur l'amont.

## Analyses — pourquoi le chantier est fait comme ça

| Fichier | Contenu |
| :-- | :-- |
| `ANALYSE-integration-bots.md` | Analyse d'origine (04/09/2026) : ce que WebUI sait déjà faire des bots, ce qui manque, et les trois paliers A / B / C. |
| `ANALYSE-integration-bots-palier-C.md` | Addendum : ce que « cockpit façon Hermes Desktop » veut dire réellement, et pourquoi C dépend d'une API agent amont. |

## Plans — ce qui a été décidé et exécuté

| Fichier | Contenu | État |
| :-- | :-- | :-- |
| `PLAN-palier-B.md` | Plan B1 → B3 : gateway multi-profils, panneau Bots, vue Bot Chat. | livré |
| `PLAN-B4-fusion-conversation.md` | Plan B4 : la conversation WebUI d'un bot **est** son fil agent-natif (lecture + écriture). | livré |
| `PLAN-ecarts-de-fond.md` | Les 8 écarts restants après B4, avec les décisions de Ludo du 06/09/2026. | en cours |

## Prompts de reprise — contexte pour une session à froid

| Fichier | Contenu |
| :-- | :-- |
| `HANDOFF-next-session.md` | Reprise complète du chantier palier B / B4 : état, découvertes techniques à ne pas re-découvrir, rappels opérationnels. |
| `PROMPT-bots-panel-ux-rework.md` | Feuille de route de l'itération 2 du panneau Bots. |
| `PROMPT-next-session.md` | Prompt court de reprise. |
| `PROMPT-lancelot-message-agent.md` | Diagnostic de la perte de `message_agent` chez Lancelot (résolue le 06/09/2026). |

## `maquettes/`

Maquettes HTML autonomes ayant servi à valider l'UX du panneau Bots et de la conversation avant
implémentation. Aucune n'est servie par l'application — ouvrir directement dans un navigateur.

---

Les fichiers `.patch` qui traînaient à la racine (`b4-continue-bots.patch`,
`b4-continue-prototype.patch`, `palier-b-b1-b2-b3.patch`) ont été supprimés le 06/09/2026 : ils
dupliquaient l'historique des branches `feat/b*`, qui fait foi.
