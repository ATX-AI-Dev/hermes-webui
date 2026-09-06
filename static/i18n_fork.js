// Fork-only translation keys (ATX-AI-Dev/hermes-webui) — merged into LOCALES
// after static/i18n.js has defined it.
//
// These keys used to be inlined into every one of the 15 locale blocks of
// static/i18n.js: ~500 added lines in an upstream file, which turned each
// upstream release into a conflict over strings upstream never touches. They
// live here instead, and only 'en' and 'fr' are supplied — t() already falls
// back to LOCALES.en for any key a locale is missing (see t() in i18n.js), so
// the other 13 locales behave exactly as they did when they carried the
// English text verbatim.
//
// Loaded from static/index.html right after i18n.js. Both are `defer`, so this
// runs after i18n.js has built LOCALES and bound _locale to one of its
// objects; assigning INTO those objects is therefore visible to the already
// bound _locale.
//
// See FORK-CHANGES.md (palier B / B2-B4) for the divergence ledger.
(function () {
  var FORK = {
    en: {
      tab_bots: 'Bots',
      bots_panel_title: 'Bots',
      bots_loading: 'Loading bots…',
      bots_none: 'No profiles found.',
      bots_summary_gateways: 'gateways up',
      bots_summary_sessions: 'active sessions',
      bots_summary_bots: 'bots',
      bots_col_sessions: 'sessions',
      bots_gateway_start: 'Start gateway',
      bots_gateway_stop: 'Stop gateway',
      bots_gateway_running: 'Gateway running',
      bots_gateway_stopped: 'Gateway stopped (on demand)',
      bots_open_thread: 'Open thread',
      bots_active: 'active',
      bots_permanent: 'permanent gateway',
      bots_refresh: 'Refresh',
      bots_action_failed: 'Gateway action failed',
      bots_thread: 'Inter-bot thread',
      bots_thread_empty: 'No inter-bot activity yet.',
      bots_continue: 'Continue',
      bots_relay_pending: 'pending',
      bots_relay_ok: 'delivered',
      bots_relay_error: 'error',
      bots_more: 'More',
      bots_unread: 'Unread messages',
      bots_customize: 'Customize',
      bots_custom_name: 'Display name',
      bots_custom_avatar: 'Profile picture',
      bots_custom_save: 'Save',
      bots_custom_remove_photo: 'Remove photo',
      relay_inbound_from: 'Message from',
      workspace_trace_tab: 'Trace',
      workspace_trace_empty: 'No background activity in this thread.',
      workspace_trace_tool: 'tool',
      workspace_trace_process: 'background',
      agent_drift_message: 'Hermes Agent was updated. This WebUI is still running the modules it loaded at startup.',
      agent_drift_restart: 'Restart WebUI',
      agent_drift_later: 'Later',
      agent_drift_restarting: 'Restarting WebUI… the page will reload on its own.',
    },
    fr: {
      tab_bots: 'Bots',
      bots_panel_title: 'Bots',
      bots_loading: 'Chargement des bots…',
      bots_none: 'Aucun profil trouvé.',
      bots_summary_gateways: 'passerelles actives',
      bots_summary_sessions: 'sessions en cours',
      bots_summary_bots: 'bots',
      bots_col_sessions: 'sessions',
      bots_gateway_start: 'Démarrer la passerelle',
      bots_gateway_stop: 'Arrêter la passerelle',
      bots_gateway_running: 'Passerelle démarrée',
      bots_gateway_stopped: 'Passerelle arrêtée (à la demande)',
      bots_open_thread: 'Ouvrir le fil',
      bots_active: 'actif',
      bots_permanent: 'passerelle permanente',
      bots_refresh: 'Rafraîchir',
      bots_action_failed: 'Action passerelle échouée',
      bots_thread: 'Fil inter-bots',
      bots_thread_empty: 'Aucune activité inter-bots.',
      bots_continue: 'Continuer',
      bots_relay_pending: 'en attente',
      bots_relay_ok: 'livré',
      bots_relay_error: 'erreur',
      bots_more: 'Plus d’options',
      bots_unread: 'Messages non lus',
      bots_customize: 'Personnaliser',
      bots_custom_name: 'Nom affiché',
      bots_custom_avatar: 'Image de profil',
      bots_custom_save: 'Enregistrer',
      bots_custom_remove_photo: 'Retirer la photo',
      relay_inbound_from: 'Message de',
      workspace_trace_tab: 'Trace',
      workspace_trace_empty: 'Aucune activité en arrière-plan dans ce fil.',
      workspace_trace_tool: 'outil',
      workspace_trace_process: 'arrière-plan',
      agent_drift_message: 'Hermes Agent a été mis à jour. Ce WebUI tourne encore sur les modules chargés à son démarrage.',
      agent_drift_restart: 'Redémarrer le WebUI',
      agent_drift_later: 'Plus tard',
      agent_drift_restarting: 'Redémarrage du WebUI… la page se rechargera toute seule.',
    },
  };
  if (typeof LOCALES === 'undefined' || !LOCALES) {
    console.warn('[fork-i18n] LOCALES is not defined; is i18n.js loaded first?');
    return;
  }
  Object.keys(FORK).forEach(function (loc) {
    if (!LOCALES[loc]) return;   // upstream dropped a locale: skip, never create one
    Object.assign(LOCALES[loc], FORK[loc]);
  });
})();
