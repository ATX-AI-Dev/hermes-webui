// ── Panneau bot épinglé (palier C2, étape 1) ────────────────────────────────
//
// Garder une seconde conversation ouverte à côté de la principale : parler à
// Roi Arthur pendant que Lancelot travaille, sans basculer de profil.
//
// CE QUI REND ÇA POSSIBLE
// -----------------------
// Le spike C1 (docs/fork/SPIKE-C1-execution-concurrente.md) a montré que le
// moteur sait déjà exécuter deux bots en parallèle sans les mélanger : le home
// est épinglé par un ContextVar, le profil actif est un thread-local, et les
// garde-fous « busy » sont par session. Le seul vrai verrou était que le profil
// d'une requête vient d'un COOKIE — un onglet, un bot. api/pane_profile.py le
// lève : ce panneau envoie ses appels avec un en-tête X-Hermes-Profile signé.
//
// UN OBJET, PAS UN SECOND CONTENEUR
// ---------------------------------
// L'état du panneau (bot, session, jeton, rafraîchissement) vit dans `_pane`,
// jamais dans l'état global `S` de la page. C'est délibéré : à l'étape suivante
// (N panneaux), la conversation principale devient une instance de plus, et
// c'est la seule façon d'y arriver sans réécrire la couche d'état du front.
//
// CE QUE LE PANNEAU N'A PAS, ET POURQUOI
// --------------------------------------
// Pas de panneau workspace, pas d'onglet Trace, pas d'approbation d'outil : ces
// surfaces lisent l'état global. Un tour du panneau qui demanderait une
// approbation resterait bloqué — d'où le bouton « Basculer ici », qui échange le
// panneau et la conversation principale. C'est aussi ce qui prépare l'étape
// suivante : des panneaux symétriques.

const BOT_PANE_POLL_MS = 4000;      // fil au repos
const BOT_PANE_BUSY_POLL_MS = 1500; // pendant qu'un tour tourne

let _pane = null; // {profile, sessionId, token, busy, timer, lastCount}

function botPaneActive() {
  return !!(_pane && _pane.profile);
}

function botPaneProfile() {
  return _pane ? _pane.profile : null;
}

// Toutes les requêtes du panneau passent par ici : l'en-tête est ce qui fait
// qu'elles parlent à SON bot et pas au profil de l'onglet.
function _paneApi(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (_pane && _pane.token) headers['X-Hermes-Profile'] = _pane.token;
  return api(path, { ...opts, headers, timeoutToast: false });
}

async function _paneMintToken(profile) {
  // En mode sans authentification le serveur renvoie le nom nu : même
  // comportement que le cookie, qui n'y est qu'une préférence de navigateur.
  const r = await api('/api/profile/pane-token', {
    method: 'POST',
    body: JSON.stringify({ profile }),
    timeoutToast: false,
  });
  return (r && r.token) || null;
}

async function pinBotPane(profile) {
  if (!profile) return;
  // Le même bot des deux côtés partagerait une session : l'agent n'a qu'un bail
  // d'exclusivité par Bot Chat, les deux surfaces se battraient pour lui.
  if (typeof S !== 'undefined' && S && S.activeProfile === profile) {
    if (typeof showToast === 'function') showToast(t('bot_pane_same_bot'));
    return;
  }
  const host = document.getElementById('botPane');
  if (!host) return;
  try {
    const token = await _paneMintToken(profile);
    // L'import résout son profil côté serveur (api/bot_mesh.py), il n'a pas
    // besoin de l'en-tête — mais il doit précéder tout envoi : sans sidecar,
    // /api/chat/start ne trouverait pas la session.
    const imported = await api('/api/bot-chat/continue', {
      method: 'POST', body: JSON.stringify({ profile }), timeoutToast: false,
    });
    if (!imported || imported.ok === false || !imported.session_id) {
      if (typeof showToast === 'function') showToast((imported && imported.error) || t('bots_action_failed'));
      return;
    }
    _pane = { profile, sessionId: imported.session_id, token, busy: false, timer: null, lastCount: null };
    host.hidden = false;
    document.body.classList.add('has-bot-pane');
    _renderPaneShell();
    await refreshBotPane();
    _startPanePoll();
  } catch (e) {
    if (typeof showToast === 'function') showToast(t('bots_action_failed') + ': ' + String((e && e.message) || e));
  }
}

function unpinBotPane() {
  _stopPanePoll();
  _pane = null;
  const host = document.getElementById('botPane');
  if (host) { host.hidden = true; host.innerHTML = ''; }
  document.body.classList.remove('has-bot-pane');
  if (typeof loadBotsPanel === 'function') loadBotsPanel(true);
}

// « Basculer ici » : le bot du panneau devient la conversation principale, et
// l'ancienne conversation prend sa place dans le panneau. C'est la sortie de
// secours quand le panneau ne suffit pas (approbation d'outil, workspace), et
// le premier pas vers des panneaux symétriques.
async function promoteBotPane() {
  if (!botPaneActive()) return;
  const target = _pane.profile;
  const previous = (typeof S !== 'undefined' && S) ? S.activeProfile : null;
  unpinBotPane();
  try {
    if (typeof _botsOpenConversation === 'function') {
      await _botsOpenConversation(target, 'continue', null);
    }
    if (previous && previous !== target) await pinBotPane(previous);
  } catch (e) {
    if (typeof showToast === 'function') showToast(t('bots_action_failed'));
  }
}

function _renderPaneShell() {
  const host = document.getElementById('botPane');
  if (!host || !_pane) return;
  host.innerHTML = `
    <div class="bot-pane-head">
      <span class="bot-pane-title" title="${esc(_pane.profile)}">${esc(_pane.profile)}</span>
      <span class="bot-pane-spacer"></span>
      <button class="bot-pane-btn" data-pane-act="promote" title="${esc(t('bot_pane_promote_hint'))}">${esc(t('bot_pane_promote'))}</button>
      <button class="bot-pane-btn bot-pane-close" data-pane-act="close" aria-label="${esc(t('bot_pane_close'))}" title="${esc(t('bot_pane_close'))}">×</button>
    </div>
    <div class="bot-pane-body" id="botPaneBody"></div>
    <div class="bot-pane-composer">
      <textarea id="botPaneInput" rows="2" placeholder="${esc(t('bot_pane_placeholder'))}"></textarea>
      <button class="bot-pane-send" data-pane-act="send">${esc(t('bot_pane_send'))}</button>
    </div>`;
}

async function refreshBotPane() {
  if (!botPaneActive()) return;
  const body = document.getElementById('botPaneBody');
  if (!body) return;
  try {
    const data = await _paneApi('/api/bot-chat?profile=' + encodeURIComponent(_pane.profile) + '&limit=40');
    const turns = (data && data.turns) || [];
    // Ne pas re-rendre à l'identique : ça sauterait le scroll de l'utilisateur
    // toutes les 4 secondes pour rien.
    if (_pane.lastCount === turns.length && !_pane.busy) return;
    _pane.lastCount = turns.length;
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 60;
    body.innerHTML = _botsRenderChatTurns(turns);
    if (atBottom) body.scrollTop = body.scrollHeight;
  } catch (e) {
    // Silencieux : un panneau secondaire ne doit pas noyer l'utilisateur de
    // toasts pendant qu'il travaille dans la conversation principale.
  }
}

async function sendInBotPane() {
  if (!botPaneActive() || _pane.busy) return;
  const input = document.getElementById('botPaneInput');
  const text = (input && input.value || '').trim();
  if (!text) return;
  _pane.busy = true;
  if (input) { input.value = ''; input.disabled = true; }
  _startPanePoll();
  try {
    // L'en-tête est indispensable ici : /api/chat/start refuse une session qui
    // n'appartient pas au profil de la requête ("Session not found"). C'est
    // exactement le verrou que api/pane_profile.py lève.
    const r = await _paneApi('/api/chat/start', {
      method: 'POST',
      body: JSON.stringify({ session_id: _pane.sessionId, message: text, profile: _pane.profile }),
      timeoutMs: 120000,
    });
    if (r && r.error) {
      if (typeof showToast === 'function') showToast(String(r.error));
    }
  } catch (e) {
    if (typeof showToast === 'function') showToast(t('bots_action_failed') + ': ' + String((e && e.message) || e));
  } finally {
    _pane.busy = false;
    if (input) { input.disabled = false; input.focus(); }
    await refreshBotPane();
    _startPanePoll();
  }
}

function _startPanePoll() {
  _stopPanePoll();
  if (!botPaneActive()) return;
  _pane.timer = setInterval(() => {
    if (document.hidden) return;
    refreshBotPane();
  }, _pane.busy ? BOT_PANE_BUSY_POLL_MS : BOT_PANE_POLL_MS);
}

function _stopPanePoll() {
  if (_pane && _pane.timer) { clearInterval(_pane.timer); _pane.timer = null; }
}

// Un seul écouteur délégué, comme le panneau Bots : les boutons sont recréés à
// chaque rendu de la coquille.
document.addEventListener('click', (ev) => {
  const btn = ev.target.closest && ev.target.closest('#botPane [data-pane-act]');
  if (!btn) return;
  const act = btn.dataset.paneAct;
  if (act === 'close') unpinBotPane();
  else if (act === 'send') sendInBotPane();
  else if (act === 'promote') promoteBotPane();
});

document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Enter' || ev.shiftKey) return;
  if (!ev.target || ev.target.id !== 'botPaneInput') return;
  ev.preventDefault();
  sendInBotPane();
});
