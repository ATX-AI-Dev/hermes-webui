// Agent-drift banner — fork-only front-end (ATX-AI-Dev/hermes-webui).
//
// WebUI imports Hermes Agent in-process. When the agent is updated underneath a
// running WebUI — which happens on its own, hourly, on the production host —
// this process keeps executing the modules it loaded at startup. The banner
// makes that visible and offers the one-click fix; api/agent_drift.py does the
// re-exec through upstream's own os.execv path, so no root is involved.
//
// Own file, and the banner's DOM is built here rather than declared in
// index.html, so the fork's footprint in upstream files stays a script tag.
// See FORK-CHANGES.md.

const AGENT_DRIFT_POLL_MS = 60000;
const AGENT_DRIFT_DISMISS_KEY = 'hermes-webui-agent-drift-dismissed';
let _agentDriftTimer = null;
let _agentDriftRestarting = false;

function _agentDriftDismissed(sha) {
  // Dismissal is keyed on the SHA: "later" silences THIS update, and the next
  // agent release brings the banner back on its own.
  try { return !!sha && localStorage.getItem(AGENT_DRIFT_DISMISS_KEY) === sha; }
  catch (_) { return false; }
}

function _agentDriftDismiss(sha) {
  try { if (sha) localStorage.setItem(AGENT_DRIFT_DISMISS_KEY, sha); } catch (_) {}
  _agentDriftHide();
}

function _agentDriftEl() {
  let el = document.getElementById('agentDriftBanner');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'agentDriftBanner';
  el.className = 'agent-drift-banner';
  el.setAttribute('role', 'status');
  el.hidden = true;
  document.body.appendChild(el);
  return el;
}

function _agentDriftHide() {
  const el = document.getElementById('agentDriftBanner');
  if (el) el.hidden = true;
}

function _agentDriftRender(status) {
  const el = _agentDriftEl();
  const short = String(status.current || '').slice(0, 10);
  if (_agentDriftRestarting) {
    el.innerHTML = `<span class="agent-drift-text">${esc(t('agent_drift_restarting'))}</span>`;
    el.hidden = false;
    return;
  }
  const version = status.agent_version ? ` (${esc(String(status.agent_version))})` : '';
  el.innerHTML =
    `<span class="agent-drift-text">${esc(t('agent_drift_message'))}${version}</span>` +
    `<span class="agent-drift-actions">` +
      `<button type="button" class="agent-drift-btn agent-drift-btn--primary" data-agent-drift="restart">${esc(t('agent_drift_restart'))}</button>` +
      `<button type="button" class="agent-drift-btn" data-agent-drift="later" data-sha="${esc(short && status.current || '')}">${esc(t('agent_drift_later'))}</button>` +
    `</span>`;
  el.hidden = false;
}

async function _agentDriftRestart() {
  _agentDriftRestarting = true;
  _agentDriftRender({});
  try {
    await api('/api/agent-drift/restart', { method: 'POST', body: '{}', timeoutToast: false });
  } catch (e) {
    // The re-exec can kill the connection before the response lands; that is a
    // successful restart, not an error. Fall through to the poll below.
    console.warn('[agent-drift] restart request ended early:', e);
  }
  // Poll until the process answers again with no drift, then reload. Bounded so
  // a restart blocked by a long-running stream can't spin forever.
  const deadline = Date.now() + 120000;
  const tick = async () => {
    if (Date.now() > deadline) { location.reload(); return; }
    try {
      const s = await api('/api/agent-drift', { timeoutToast: false, redirect401: false, retries: 0 });
      if (s && s.drifted === false) { location.reload(); return; }
    } catch (_) { /* down mid-exec: keep waiting */ }
    setTimeout(tick, 2000);
  };
  setTimeout(tick, 2500);
}

async function checkAgentDrift() {
  if (_agentDriftRestarting) return;
  let status;
  try {
    status = await api('/api/agent-drift', { timeoutToast: false, retries: 0 });
  } catch (_) {
    return;  // never let this background check surface an error to the user
  }
  if (!status || !status.drifted || _agentDriftDismissed(status.current)) {
    _agentDriftHide();
    return;
  }
  _agentDriftRender(status);
}

function _agentDriftOnClick(ev) {
  const btn = ev.target.closest('[data-agent-drift]');
  if (!btn) return;
  if (btn.dataset.agentDrift === 'later') { _agentDriftDismiss(btn.dataset.sha); return; }
  if (btn.dataset.agentDrift === 'restart') { _agentDriftRestart(); }
}

function startAgentDriftWatch() {
  if (_agentDriftTimer) return;
  document.addEventListener('click', _agentDriftOnClick);
  checkAgentDrift();
  _agentDriftTimer = setInterval(() => {
    if (document.hidden) return;   // the window of action is minutes, not seconds
    checkAgentDrift();
  }, AGENT_DRIFT_POLL_MS);
}

if (typeof window !== 'undefined') {
  window.addEventListener('load', () => setTimeout(startAgentDriftWatch, 3000), { once: true });
}
