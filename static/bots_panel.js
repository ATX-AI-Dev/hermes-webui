// Bots panel — fork-only front-end (ATX-AI-Dev/hermes-webui).
//
// Lives in its own file ON PURPOSE. Everything here is fork code with no
// upstream counterpart, and keeping it inside static/panels.js meant ~500 added
// lines in one of upstream's hottest files — every upstream release turned
// into a merge conflict over code upstream never touches. Extracted so a
// `git rebase upstream/master` only has to reconcile the handful of real
// integration points left behind in panels.js (the switchPanel hooks).
//
// Loaded from static/index.html BEFORE panels.js. Every symbol it needs from
// the host ($ , api, esc, t, S, showToast, switchPanel, switchToProfile,
// loadSession) is resolved at call time, so load order only matters for the
// two hooks panels.js guards with `typeof`.
//
// See FORK-CHANGES.md (palier B / B2-B4) for the divergence ledger.
// ── Bots panel (palier B / B2) ─────────────────────────────────────────────
// Read-only supervision of every Hermes profile in its pilote/managers/bots
// hierarchy (GET /api/bots). Start/Stop targets that bot's gateway via the
// per-profile /api/gateway/* endpoints (B1). "Open thread" switches to the
// bot's profile and drops you on the chat view.
let _botsPanelBusy = false;
let _botsDelegderBound = false;

function _botsRelTime(iso) {
  if (!iso) return '';
  const ts = Date.parse(iso);
  if (isNaN(ts)) return '';
  return _botsRelTimeMs(ts);
}
function _botsRelTimeEpoch(sec) {
  if (!sec && sec !== 0) return '';
  return _botsRelTimeMs(sec * 1000);
}
function _botsRelTimeMs(ts) {
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 60) return 'à l’instant';
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  return `il y a ${Math.floor(s / 86400)} j`;
}
const _botsChatLoaded = new Set();

// Fallback palette for bots not (yet) declared with an emoji/color in
// bots_hierarchy.json — a stable hash on the bot id picks one of these so a
// given bot always gets the same fallback color across reloads.
const _BOTS_AVATAR_FALLBACK_PALETTE = [
  '#3a4fb0', '#2fb3a6', '#c0392b', '#8e44ad', '#4a9d5c',
  '#d9a53c', '#c0397f', '#2f9e8f', '#7c5fc0', '#3f9142',
];
function _botsAvatarFallbackColor(id) {
  let h = 0;
  const s = String(id || '');
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return _BOTS_AVATAR_FALLBACK_PALETTE[h % _BOTS_AVATAR_FALLBACK_PALETTE.length];
}
// Priority: the user's own picture (api/bot_customization.py) > the emoji and
// colour declared in bots_hierarchy.json > a hash-based fallback colour.
function _botAvatarHTML(bot) {
  if (bot.avatar_url) {
    return `<img class="bots-avatar bots-avatar--img" src="${esc(bot.avatar_url)}" alt="" aria-hidden="true">`;
  }
  const color = bot.color || _botsAvatarFallbackColor(bot.id);
  const glyph = bot.emoji || (String(bot.id || '?').charAt(0).toUpperCase());
  return `<span class="bots-avatar" style="background:${esc(color)}" aria-hidden="true">${esc(glyph)}</span>`;
}
// A bot the user has named displays under that name; otherwise under its
// profile id, which is what the monospace styling is for.
function _botDisplayName(bot) {
  return (bot && bot.display_name) || (bot && bot.id) || '';
}

// Panel-local poll: refreshes the Bots list every ~15s while the Bots panel
// is the active panel and the tab is visible, so avatars' live-activity
// preview updates without a manual refresh. Independent from the
// session-specific external-refresh poll in sessions.js (da1f2323), which is
// scoped to a single open CLI/Bot-Chat session via GET /api/session, not
// this multi-profile list.
let _botsPollTimer = null;
// The list keeps polling as long as it is on screen — which, since the panel
// became sticky, is no longer the same thing as _currentPanel === 'bots':
// opening a bot's conversation moves _currentPanel to 'chat' while #panelBots
// stays the visible sidebar view.
function _botsPanelVisible() {
  const el = document.getElementById('panelBots');
  return !!(el && el.classList.contains('active'));
}
function _ensureBotsPanelPoll() {
  if (_botsPollTimer) return;
  _botsPollTimer = setInterval(() => {
    if (document.hidden) return;
    if (!_botsPanelVisible()) return;
    loadBotsPanel(true);
  }, 15000);
}
function _stopBotsPanelPoll() {
  if (!_botsPollTimer) return;
  clearInterval(_botsPollTimer);
  _botsPollTimer = null;
}

async function loadBotsPanel(fresh) {
  const panel = $('botsPanel');
  if (!panel) return;
  if (!_botsDelegderBound) {
    _botsDelegderBound = true;
    panel.addEventListener('click', _botsOnClick);
    panel.addEventListener('keydown', _botsOnKeydown);
  }
  _ensureBotsPanelPoll();
  // Bot Chat accordions and "···" detail areas the user already expanded
  // should stay open across a poll-driven re-render instead of silently
  // collapsing under them.
  const openChats = new Set();
  panel.querySelectorAll('.bots-chat:not([hidden])').forEach(box => {
    const id = box.getAttribute('data-chat-for');
    if (id) openChats.add(id);
  });
  const openDetails = new Set();
  panel.querySelectorAll('.bots-details:not([hidden])').forEach(box => {
    const id = box.getAttribute('data-details-for');
    if (id) openDetails.add(id);
  });
  try {
    const data = await api('/api/bots' + (fresh ? '?fresh=1' : ''));
    const bots = Array.isArray(data.bots) ? data.bots : [];
    if (!bots.length) {
      panel.innerHTML = `<div style="padding:16px;color:var(--muted);font-size:12px">${esc(t('bots_none'))}</div>`;
      return;
    }
    const c = data.counts || {};
    const branchLabels = {};
    (data.branches || []).forEach(b => { if (b && b.id) branchLabels[b.id] = b.label || b.id; });

    let html = `<div class="bots-summary">
      <span><strong>${c.gateways_up || 0}</strong> / ${c.total || bots.length} ${esc(t('bots_summary_gateways'))}</span>
      <span><strong>${c.active_sessions || 0}</strong> ${esc(t('bots_summary_sessions'))}</span>
    </div>`;

    const activeProfile = (typeof S !== 'undefined' && S && S.activeProfile) ? S.activeProfile : '';

    let lastBranch = null;
    for (const bot of bots) {
      if (bot.branch !== lastBranch) {
        lastBranch = bot.branch;
        html += `<div class="bots-branch-label">${esc(branchLabels[bot.branch] || bot.branch)}</div>`;
      }
      const running = !!bot.gateway_running;
      const child = bot.parent ? ' bots-row--child' : '';
      // Survives the 15s re-render: _botsMarkCurrent handles the immediate
      // highlight, this keeps it after the list is rebuilt.
      const current = (activeProfile && bot.id === activeProfile) ? ' is-current' : '';
      const sessions = bot.active_sessions > 0
        ? `<span class="bots-pill">${bot.active_sessions} ${esc(t('bots_col_sessions'))}</span>` : '';
      const last = bot.last_activity ? `<span class="bots-when">${esc(_botsRelTime(bot.last_activity))}</span>` : '';
      const perm = bot.permanent_gateway ? `<span class="bots-pill bots-pill--perm" title="${esc(t('bots_permanent'))}">P</span>` : '';
      const activeBadge = bot.is_active ? `<span class="bots-pill bots-pill--active">${esc(t('bots_active'))}</span>` : '';
      const gwTitle = running ? t('bots_gateway_running') : t('bots_gateway_stopped');
      const gwBtn = running
        ? `<button class="bots-btn bots-btn--stop" data-bot="${esc(bot.id)}" data-act="stop">${esc(t('bots_gateway_stop'))}</button>`
        : `<button class="bots-btn" data-bot="${esc(bot.id)}" data-act="start">${esc(t('bots_gateway_start'))}</button>`;
      const chatBtn = bot.has_bot_chat
        ? `<button class="bots-btn bots-btn--ghost" data-bot="${esc(bot.id)}" data-act="chat" aria-expanded="false">${esc(t('bots_thread'))}</button>`
        : '';
      // B4 (PLAN-B4-fusion-conversation.md): "Continuer" imports the bot's
      // real Bot Chat session into WebUI and opens it, so replying continues
      // THAT session (message_agent included) instead of a fresh WebUI-only
      // one. This is now the single entry point for bots with a Bot Chat;
      // "Open thread" remains only as a fallback for bots that don't have
      // one yet (has_bot_chat === false).
      //
      // Iteration 2: that entry point is no longer a button — the WHOLE card
      // opens the conversation (data-card-act), the way a row in a chat
      // client's conversation list does. The secondary actions (inter-bot
      // thread, gateway) and the low-frequency badges (permanent gateway,
      // session count) moved into a folded "···" area so the card front
      // carries only what a human reads at a glance.
      const cardAct = bot.has_bot_chat ? 'continue' : 'open';
      const cardTitle = bot.has_bot_chat ? t('bots_continue') : t('bots_open_thread');
      const preview = bot.last_message_preview
        ? `<span class="bots-preview">${esc(bot.last_message_preview)}</span>` : '';
      html += `<div class="bots-row${child}${current}" role="button" tabindex="0"
        data-bot="${esc(bot.id)}" data-card-act="${cardAct}" title="${esc(cardTitle)}">
        ${_botAvatarHTML(bot)}
        <span class="bots-row-main">
          <span class="bots-row-id">
            <span class="bots-dot ${running ? 'up' : ''}" title="${esc(gwTitle)}"></span>
            <span class="bots-id${bot.display_name ? ' bots-id--named' : ''}">${esc(_botDisplayName(bot))}</span>
            <span class="bots-role">${esc(bot.role || '')}${bot.tag ? ` <span class="bots-tag">${esc(bot.tag)}</span>` : ''}</span>
          </span>
          ${preview}
          <span class="bots-meta">${activeBadge}${last}</span>
        </span>
        <button class="bots-more-btn" data-bot="${esc(bot.id)}" data-act="details"
          aria-expanded="false" title="${esc(t('bots_more'))}" aria-label="${esc(t('bots_more'))}">···</button>
      </div>
      <div class="bots-details" data-details-for="${esc(bot.id)}" hidden>
        ${perm || sessions ? `<span class="bots-details-meta">${perm}${sessions}</span>` : ''}
        <span class="bots-actions">
          ${chatBtn}
          ${gwBtn}
          <button class="bots-btn bots-btn--ghost" data-bot="${esc(bot.id)}" data-act="customize"
            aria-expanded="false">${esc(t('bots_customize'))}</button>
        </span>
        ${_botsCustomizeFormHTML(bot)}
      </div>`;
      if (bot.has_bot_chat) {
        html += `<div class="bots-chat" data-chat-for="${esc(bot.id)}" hidden></div>`;
      }
    }
    panel.innerHTML = html;
    _botsChatLoaded.clear(); // the accordion DOM nodes above are fresh; re-fetch on next open
    // Restore what the user had open before this (poll-driven) re-render.
    // Details first: the Bot Chat accordion is reached through them.
    openDetails.forEach(id => {
      const btn = panel.querySelector(`[data-act="details"][data-bot="${CSS.escape(id)}"]`);
      _botsToggleDetails(id, btn);
    });
    openChats.forEach(id => {
      const btn = panel.querySelector(`[data-act="chat"][data-bot="${CSS.escape(id)}"]`);
      _botsToggleChat(id, btn);
    });
  } catch (e) {
    panel.innerHTML = `<div style="padding:16px;color:var(--danger,#c0392b);font-size:12px">${esc(String(e && e.message || e))}</div>`;
  }
}

function _botsRelayLabel(target) {
  return target ? `→ ${target}` : '';
}

function _botsRenderChatTurns(turns) {
  if (!turns || !turns.length) {
    return `<div class="bots-chat-empty">${esc(t('bots_thread_empty'))}</div>`;
  }
  return turns.map(turn => {
    const when = turn.timestamp ? `<span class="bots-turn-time">${esc(_botsRelTimeEpoch(turn.timestamp))}</span>` : '';
    if (turn.kind === 'relay_out') {
      const state = turn.ok === true ? 'ok' : (turn.ok === false ? 'err' : 'pending');
      const status = turn.ok === true ? t('bots_relay_ok') : (turn.ok === false ? t('bots_relay_error') : t('bots_relay_pending'));
      return `<div class="bots-relay bots-relay--${state}">
        <div class="bots-relay-head">
          <span class="bots-relay-arrow" aria-hidden="true">⇄</span>
          <span class="bots-relay-target">${esc(_botsRelayLabel(turn.target))}</span>
          <span class="bots-relay-status">${esc(status)}</span>
          ${when}
        </div>
        ${turn.message ? `<div class="bots-relay-msg">${esc(turn.message)}</div>` : ''}
        ${turn.error ? `<div class="bots-relay-error">${esc(turn.error)}</div>` : ''}
      </div>`;
    }
    if (turn.kind === 'tool') {
      return `<div class="bots-turn bots-turn--tool">
        <span class="bots-turn-role">${esc(turn.tool_name || 'tool')}</span>
        <span class="bots-turn-text">${esc(turn.content || '')}</span>
        ${when}
      </div>`;
    }
    return `<div class="bots-turn bots-turn--${esc(turn.role || 'text')}">
      <span class="bots-turn-role">${esc(turn.role || '')}</span>
      <span class="bots-turn-text">${esc(turn.content || '')}</span>
      ${when}
    </div>`;
  }).join('');
}

async function _botsToggleChat(bot, btn) {
  const box = document.querySelector('.bots-chat[data-chat-for="' + CSS.escape(bot) + '"]');
  if (!box) return;
  const opening = box.hidden;
  box.hidden = !opening;
  if (btn) btn.setAttribute('aria-expanded', String(opening));
  if (!opening || _botsChatLoaded.has(bot)) return;
  box.innerHTML = `<div class="bots-chat-loading">${esc(t('bots_loading'))}</div>`;
  try {
    const data = await api('/api/bot-chat?profile=' + encodeURIComponent(bot));
    _botsChatLoaded.add(bot);
    box.innerHTML = data && data.exists
      ? _botsRenderChatTurns(data.turns)
      : `<div class="bots-chat-empty">${esc(t('bots_thread_empty'))}</div>`;
  } catch (e) {
    box.innerHTML = `<div class="bots-chat-empty">${esc(String(e && e.message || e))}</div>`;
  }
}

// Per-bot customization form, folded inside the "···" area. The user's name
// and picture are stored per profile by api/bot_customization.py, separately
// from bots_hierarchy.json (which describes the org, not preferences).
function _botsCustomizeFormHTML(bot) {
  const removeBtn = bot.avatar_url
    ? `<button class="bots-btn bots-btn--ghost" data-bot="${esc(bot.id)}" data-act="customize-clear">${esc(t('bots_custom_remove_photo'))}</button>`
    : '';
  return `<div class="bots-custom" data-custom-for="${esc(bot.id)}" hidden>
    <label class="bots-custom-row">
      <span>${esc(t('bots_custom_name'))}</span>
      <input type="text" class="bots-custom-name" maxlength="64"
        value="${esc(bot.display_name || '')}" placeholder="${esc(bot.id)}">
    </label>
    <label class="bots-custom-row">
      <span>${esc(t('bots_custom_avatar'))}</span>
      <input type="file" class="bots-custom-file" accept="image/png,image/jpeg,image/gif,image/webp">
    </label>
    <span class="bots-actions">
      <button class="bots-btn" data-bot="${esc(bot.id)}" data-act="customize-save">${esc(t('bots_custom_save'))}</button>
      ${removeBtn}
    </span>
  </div>`;
}

function _botsToggleCustomize(bot, btn) {
  const box = document.querySelector('.bots-custom[data-custom-for="' + CSS.escape(bot) + '"]');
  if (!box) return;
  const opening = box.hidden;
  box.hidden = !opening;
  if (btn) btn.setAttribute('aria-expanded', String(opening));
  if (opening) {
    const input = box.querySelector('.bots-custom-name');
    if (input) input.focus();
  }
}

async function _botsSaveCustomization(bot, btn) {
  const box = document.querySelector('.bots-custom[data-custom-for="' + CSS.escape(bot) + '"]');
  if (!box) return;
  const nameInput = box.querySelector('.bots-custom-name');
  const fileInput = box.querySelector('.bots-custom-file');
  btn.disabled = true;
  try {
    await api('/api/bots/customization', {
      method: 'POST',
      body: JSON.stringify({ profile: bot, display_name: nameInput ? nameInput.value : '' }),
      timeoutToast: false,
    });
    // Separate request: the picture is multipart, the name is JSON. Sent
    // second so a rejected image (wrong format, too big) doesn't discard a
    // perfectly good name change.
    const file = fileInput && fileInput.files && fileInput.files[0];
    if (file) {
      const fd = new FormData();
      fd.append('profile', bot);
      fd.append('file', file, file.name);
      // headers:{} lets the browser set multipart/form-data with its boundary
      // — api() otherwise forces application/json (see workspace.js upload).
      await api('/api/bots/avatar', { method: 'POST', body: fd, headers: {}, timeoutToast: false });
    }
    await loadBotsPanel(true);
  } catch (e) {
    if (typeof showToast === 'function') showToast(t('bots_action_failed') + ': ' + String(e && e.message || e));
  } finally {
    btn.disabled = false;
  }
}

async function _botsClearAvatar(bot, btn) {
  btn.disabled = true;
  try {
    await api('/api/bots/customization', {
      method: 'POST',
      body: JSON.stringify({ profile: bot, clear_avatar: true }),
      timeoutToast: false,
    });
    await loadBotsPanel(true);
  } catch (e) {
    if (typeof showToast === 'function') showToast(t('bots_action_failed') + ': ' + String(e && e.message || e));
  } finally {
    btn.disabled = false;
  }
}

// Fold/unfold one card's secondary actions ("Inter-bot thread", gateway) and
// its low-frequency badges. Mirrors _botsToggleChat's accordion contract so
// loadBotsPanel can restore both the same way after a poll re-render.
function _botsToggleDetails(bot, btn) {
  const box = document.querySelector('.bots-details[data-details-for="' + CSS.escape(bot) + '"]');
  if (!box) return;
  const opening = box.hidden;
  box.hidden = !opening;
  if (btn) btn.setAttribute('aria-expanded', String(opening));
}

// Opening a bot's conversation is one action reachable from two places: the
// whole card (data-card-act) and, for bots without a Bot Chat, nothing else.
// Both go through here so the continue → switchToProfile → loadSession chain
// exists once. _botsOpening guards against a double-click firing two imports.
let _botsOpening = false;
// Keep the Bots list beside the conversation on desktop. On a phone the
// sidebar is a drawer that closes on selection anyway, and
// _syncMobileSidebarPanelFromMainView owns the drawer's panel state, so the
// sticky mode would only fight it.
function _botsSwitchToChat() {
  if (typeof switchPanel !== 'function') return;
  const desktop = typeof _isDesktopWidth === 'function' ? _isDesktopWidth() : true;
  switchPanel('chat', desktop ? { keepSidebarPanel: true } : {});
}
// Highlight the bot whose conversation is open, the way the session list
// highlights the open session. The panel only re-renders every 15s, so mark
// the row directly instead of waiting for the next poll.
function _botsMarkCurrent(bot) {
  const panel = $('botsPanel');
  if (!panel) return;
  panel.querySelectorAll('.bots-row').forEach(row => {
    row.classList.toggle('is-current', row.dataset.bot === bot);
  });
}
// Switch profile the way upstream's session list does when the user clicks a
// session belonging to another profile: behind `_profileSwitchOpeningExistingSession`.
// That flag is switchToProfile's contract for "I will load an existing session
// the moment you return" — without it, a switch away from a conversation that
// HAS messages takes the `sessionInProgress` branch, which mints a blank
// session for the target profile, awaits its workspace tree, re-renders the
// session list, expands the sidebar and toasts "new conversation started" —
// all of it thrown away microseconds later by our own loadSession(). The
// server side was never the slow part (continue 33-100 ms, switch 5-18 ms).
// See _ensureSidebarSessionProfile() in sessions.js for the same pattern.
async function _botsSwitchProfileForExistingSession(bot) {
  if (typeof switchToProfile !== 'function') return;
  const flagExists = typeof _profileSwitchOpeningExistingSession !== 'undefined';
  if (flagExists) _profileSwitchOpeningExistingSession = true;
  try {
    await switchToProfile(bot);
  } finally {
    if (flagExists) _profileSwitchOpeningExistingSession = false;
  }
}

async function _botsOpenConversation(bot, act, srcEl) {
  if (!bot || _botsOpening) return;
  _botsOpening = true;
  if (srcEl) srcEl.setAttribute('aria-busy', 'true');
  try {
    if (act === 'open') {
      // No Bot Chat to import: a fresh conversation IS the destination here,
      // so this path deliberately keeps switchToProfile's default branch.
      if (typeof switchToProfile === 'function') await switchToProfile(bot);
      _botsSwitchToChat();
      _botsMarkCurrent(bot);
      return;
    }
    // The import and the profile switch don't depend on each other — the
    // import resolves its own profile server-side (api/bot_mesh.py passes
    // `profile=` explicitly all the way down) rather than reading the profile
    // cookie the switch sets. So start both and wait once instead of twice.
    // Behaviour note: the profile switch now also happens when the import
    // fails (the card only offers "continue" when has_bot_chat is true, so
    // that means the Bot Chat vanished under us). The user lands on the bot
    // they asked for, with the error toast, instead of staying put.
    const importing = api('/api/bot-chat/continue', { method: 'POST', body: JSON.stringify({ profile: bot }), timeoutToast: false });
    const switching = _botsSwitchProfileForExistingSession(bot);
    const [r] = await Promise.all([importing, switching]);
    if (!r || r.ok === false) {
      if (typeof showToast === 'function') showToast((r && r.error) || t('bots_action_failed'));
      return;
    }
    _botsSwitchToChat();
    _botsMarkCurrent(bot);
    if (typeof loadSession === 'function' && r.session_id) await loadSession(r.session_id);
  } catch (e) {
    if (typeof showToast === 'function') showToast(t('bots_action_failed') + ': ' + String(e && e.message || e));
  } finally {
    _botsOpening = false;
    if (srcEl) srcEl.removeAttribute('aria-busy');
  }
}

function _botsOnKeydown(ev) {
  if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
  // Buttons inside the card handle their own Enter/Space natively.
  if (ev.target.closest('button')) return;
  const card = ev.target.closest('.bots-row[data-card-act]');
  if (!card) return;
  ev.preventDefault();
  _botsOpenConversation(card.dataset.bot, card.dataset.cardAct, card);
}

async function _botsOnClick(ev) {
  // Order matters: a click on one of the folded action buttons is handled
  // here and returns, so it never falls through to the card's "open this
  // conversation" branch below. One delegated listener, no event-propagation
  // juggling between nested handlers.
  const btn = ev.target.closest('button[data-bot][data-act]');
  if (!btn) {
    const card = ev.target.closest('.bots-row[data-card-act]');
    if (card) await _botsOpenConversation(card.dataset.bot, card.dataset.cardAct, card);
    return;
  }
  const bot = btn.dataset.bot;
  const act = btn.dataset.act;
  if (act === 'details') {
    _botsToggleDetails(bot, btn);
    return;
  }
  if (act === 'customize') {
    _botsToggleCustomize(bot, btn);
    return;
  }
  if (act === 'customize-save') {
    await _botsSaveCustomization(bot, btn);
    return;
  }
  if (act === 'customize-clear') {
    await _botsClearAvatar(bot, btn);
    return;
  }
  if (act === 'open' || act === 'continue') {
    await _botsOpenConversation(bot, act, btn);
    return;
  }
  if (act === 'chat') {
    await _botsToggleChat(bot, btn);
    return;
  }
  if ((act === 'start' || act === 'stop') && !_botsPanelBusy) {
    _botsPanelBusy = true;
    btn.disabled = true;
    try {
      const r = await api('/api/gateway/' + act, { method: 'POST', body: JSON.stringify({ profile: bot }), timeoutToast: false });
      if (r && r.ok === false && typeof showToast === 'function') showToast(r.error || t('bots_action_failed'));
    } catch (e) {
      if (typeof showToast === 'function') showToast(t('bots_action_failed') + ': ' + String(e && e.message || e));
    } finally {
      _botsPanelBusy = false;
      await loadBotsPanel(true);
    }
  }
}


// ── Bot Chat trace (iteration 2, point 7) ─────────────────────────────────
// The plumbing the quiet thread hides — tool calls the bot ran, and the
// process/cronjob wakeups the agent injected into its own session — listed
// here on demand instead of interleaved with the conversation. Derived from
// S.messages rather than by moving DOM nodes, so the thread's own rendering
// (anchors, virtualization) is untouched.
function _workspaceTraceEntries(){
  const out = [];
  const msgs = (typeof S !== 'undefined' && S && Array.isArray(S.messages)) ? S.messages : [];
  for(const m of msgs){
    if(!m || !m.role) continue;
    const text = String((typeof msgContent === 'function' ? msgContent(m) : m.content) || '');
    if(m.role === 'tool'){
      out.push({kind:'tool', name:m.tool_name || 'tool', text, ts:m.timestamp});
    }else if(m.role === 'user'
        && (m._source === 'process_wakeup'
            || (typeof _isMachineNoticeText === 'function' && _isMachineNoticeText(text)))){
      out.push({kind:'process', name:'', text, ts:m.timestamp});
    }
  }
  return out;
}

function _workspaceTraceRelTime(ts){
  if(!ts && ts !== 0) return '';
  const ms = Number(ts) * 1000;
  if(!Number.isFinite(ms)) return '';
  try{ return new Date(ms).toLocaleString(); }catch(_){ return ''; }
}

function _loadWorkspacePanelTrace(){
  const panel = $('workspaceTracePanel');
  if(!panel) return;
  const entries = _workspaceTraceEntries();
  if(!entries.length){
    panel.innerHTML = `<div class="ws-trace-empty">${esc(t('workspace_trace_empty'))}</div>`;
    return;
  }
  panel.innerHTML = entries.map(e => {
    const label = e.kind === 'tool' ? t('workspace_trace_tool') : t('workspace_trace_process');
    const when = _workspaceTraceRelTime(e.ts);
    return `<div class="ws-trace-item ws-trace-item--${esc(e.kind)}">
      <div class="ws-trace-head">
        <span class="ws-trace-kind">${esc(label)}</span>
        ${e.name ? `<span class="ws-trace-name">${esc(e.name)}</span>` : ''}
        ${when ? `<span class="ws-trace-when">${esc(when)}</span>` : ''}
      </div>
      ${e.text ? `<div class="ws-trace-body">${esc(e.text)}</div>` : ''}
    </div>`;
  }).join('');
}

// The tab only exists for Bot Chats that actually carry trace: no empty tab in
// an ordinary conversation. Called from renderMessages, so it follows the open
// session. Leaving the tab while it is active falls back to Files.
function syncWorkspaceTraceTab(){
  const tab = $('workspaceTraceTab');
  if(!tab) return;
  const show = (typeof isBotChatSession === 'function' && isBotChatSession())
    && _workspaceTraceEntries().length > 0;
  tab.hidden = !show;
  if(!show && _workspacePanelActiveTab === 'trace') switchWorkspacePanelTab('files');
  else if(show && _workspacePanelActiveTab === 'trace') _loadWorkspacePanelTrace();
}
