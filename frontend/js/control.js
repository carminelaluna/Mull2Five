/**
 * control.js — Console "Regia torneo" online (organizzatore o staff/judge).
 *
 * Tutto passa dal backend: timer round (restart/extend), estensione per-tavolo,
 * inserimento risultati, generazione round. Lo stato è condiviso su ogni device:
 * gli schermi pubblici (display.html, timer.html?t=ID) si aggiornano da soli.
 */
const API       = '/api';
const TOKEN_KEY = 'manabind-jwt-v1';
const token     = localStorage.getItem(TOKEN_KEY);
if (!token) location.replace('login.html?next=control.html');

function decodeJwt(t) {
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); }
  catch { return null; }
}
const session = decodeJwt(token);
if (!session || session.exp < Date.now() / 1000) {
  localStorage.removeItem(TOKEN_KEY); location.replace('login.html?next=control.html');
}

async function apiFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, ...(opts.headers || {}) };
  const r = await fetch(API + path, { ...opts, headers });
  if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); location.replace('login.html'); return; }
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    if (r.status === 404 && (!detail || detail === 'Not Found')) {
      throw new Error('Endpoint non trovato: riavvia il backend (potrebbe eseguire una versione vecchia).');
    }
    throw new Error(detail || r.statusText);
  }
  return r.status === 204 ? null : r.json();
}

const $   = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function toast(msg) {
  const el = $('#toast'); el.textContent = msg; el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove('show'), 3000);
}

/* Mappa "score" mostrato → corpo richiesta risultato */
const SCORES = ['2-0', '2-1', '1-1', '1-2', '0-2'];
function scoreToBody(score) {
  const [a, b] = score.split('-').map(Number);
  return { match_wins_a: a, match_wins_b: b, draws: 0 };
}
function fmt(sec) {
  const neg = sec < 0, abs = Math.floor(Math.abs(sec));
  return `${neg ? '-' : ''}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, '0')}`;
}

let _tid = null;
let _rounds = [];
let _activeRoundId = null;
let _judge = false;
const _editing = new Set();   // pairingId in modifica

/* ── Bootstrap ───────────────────────────────────────── */
async function init() {
  $('#publicAuth').innerHTML =
    `<span style="color:var(--muted);font-size:.85rem">${esc(session.email)}</span>
     <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
  $('#logoutBtn').addEventListener('click', () => { localStorage.removeItem(TOKEN_KEY); location.replace('index.html'); });

  let mine = [];
  try { mine = await apiFetch('/tournaments/mine'); } catch { mine = []; }
  const running = mine.filter(t => ['running', 'published'].includes(t.status));
  const list = running.length ? running : mine;
  if (!list.length) { $('#ctlTables').innerHTML = '<p class="empty">Nessun torneo gestibile su questo account.</p>'; return; }

  $('#tournamentSelect').innerHTML = list.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
  const urlTid = new URLSearchParams(location.search).get('t');
  _tid = urlTid && list.some(t => String(t.id) === urlTid) ? urlTid : String(list[0].id);
  $('#tournamentSelect').value = _tid;
  $('#tournamentSelect').addEventListener('change', (e) => { _tid = e.target.value; _activeRoundId = null; refresh(); });

  // Controlli timer round
  $('#ctlRestart').addEventListener('click', async () => {
    await call(() => apiFetch(`/tournaments/${_tid}/timer/restart`, { method: 'POST', body: JSON.stringify({ minutes: +$('#ctlMinutes').value || 50 }) }), 'Timer avviato.');
  });
  $('#ctlStop').addEventListener('click', () => call(
    () => apiFetch(`/tournaments/${_tid}/timer/stop`, { method: 'POST' }), 'Timer fermato.'));
  $('#ctlExtend5').addEventListener('click',  () => call(() => apiExtend(5),  '+5 minuti al round.'));
  $('#ctlExtend10').addEventListener('click', () => call(() => apiExtend(10), '+10 minuti al round.'));
  $('#ctlGenRound').addEventListener('click', () => call(async () => {
    // Il timer NON parte da solo: l'organizzatore lo avvia con "Avvia / Reset".
    const rnd = await apiFetch(`/tournaments/${_tid}/rounds`, { method: 'POST' });
    if (rnd?.id) _activeRoundId = rnd.id;   // passa subito alla tab del nuovo round
  }, 'Round generato.'));

  refresh();
  setInterval(refresh, 4000);   // riallinea con il backend (modifiche di altri)
  setInterval(tick, 250);       // countdown locale fluido
}

function apiExtend(min) {
  return apiFetch(`/tournaments/${_tid}/timer/extend`, { method: 'POST', body: JSON.stringify({ minutes: min }) });
}

async function call(fn, okMsg) {
  try { await fn(); toast(okMsg); await refresh(); }
  catch (e) { toast('Errore: ' + e.message); }
}

/* ── Refresh dati ────────────────────────────────────── */
async function refresh() {
  if (!_tid) return;
  try {
    _rounds = (await apiFetch(`/tournaments/${_tid}/rounds`) || []).sort((a, b) => a.number - b.number);
  } catch { _rounds = []; }
  if (!_rounds.some(r => String(r.id) === String(_activeRoundId))) _activeRoundId = _rounds.at(-1)?.id ?? null;
  render();
  renderScreenLinks();
}

function renderScreenLinks() {
  const base = location.origin;
  $('#screenLinks').innerHTML = `
    <a class="secondary-link" href="timer.html?t=${_tid}" target="_blank" rel="noopener">🖥 Timer schermo</a> ·
    <a class="secondary-link" href="display.html?t=${_tid}" target="_blank" rel="noopener">📺 Display abbinamenti</a>
    <small style="color:var(--muted);margin-left:8px">${base}/display.html?t=${_tid}</small>`;
}

function activeRound() { return _rounds.find(r => String(r.id) === String(_activeRoundId)); }

function render() {
  const round = activeRound();
  $('#ctlTabs').innerHTML = _rounds.map(r =>
    `<button class="ctl-tab${String(r.id) === String(_activeRoundId) ? ' active' : ''}" data-round="${r.id}" type="button">Round ${r.number}</button>`
  ).join('') + `<button class="ctl-tab judge${_judge ? ' active' : ''}" id="judgeToggle" type="button">⚖ Judge</button>`;

  $('#ctlTabs').querySelectorAll('[data-round]').forEach(b =>
    b.addEventListener('click', () => { _activeRoundId = b.dataset.round; render(); }));
  $('#judgeToggle').addEventListener('click', () => { _judge = !_judge; render(); });

  if (!round) { $('#ctlTables').innerHTML = '<p class="empty">Nessun round. Avvia il torneo e genera il primo round.</p>'; $('#ctlRoundLabel').textContent = ''; return; }
  $('#ctlRoundLabel').textContent = `Round ${round.number}`;

  const pairings = round.pairings
    .filter(p => !_judge || (p.player_b && !p.result))
    .sort((a, b) => a.table_number - b.table_number);

  $('#ctlTables').innerHTML = pairings.length
    ? pairings.map(p => renderRow(round, p)).join('')
    : '<p class="empty" style="margin:0">Tutti i tavoli hanno un risultato. ✓</p>';

  // Handlers risultato
  $('#ctlTables').querySelectorAll('[data-action="result"]').forEach(sel =>
    sel.addEventListener('change', () => submitResult(p_id(sel), sel.value)));
  $('#ctlTables').querySelectorAll('[data-action="edit"]').forEach(btn =>
    btn.addEventListener('click', () => { _editing.add(btn.dataset.pid); render(); }));
  $('#ctlTables').querySelectorAll('[data-action="extend-table"]').forEach(btn =>
    btn.addEventListener('click', () => call(
      () => apiFetch(`/tournaments/${_tid}/pairings/${btn.dataset.pid}/extend`, { method: 'PATCH', body: JSON.stringify({ minutes: +btn.dataset.min }) }),
      `+${btn.dataset.min} minuti al tavolo.`)));
}

function p_id(el) { return el.dataset.pid; }

function renderRow(round, p) {
  const isBye = !p.player_b;
  const finalScore = p.result && p.result !== '' ? `${p.match_wins_a}-${p.match_wins_b}` : '';
  const editing = _editing.has(String(p.id));

  let control;
  if (isBye) {
    control = '<span class="badge ok">BYE · 2 – 0</span>';
  } else if (finalScore && !editing) {
    control = `<span class="badge ok">${finalScore.replace('-', ' – ')} 🔒</span>
      <button class="mini-button" data-action="edit" data-pid="${p.id}" type="button">Modifica</button>`;
  } else {
    const opts = ['<option value="">— in corso</option>']
      .concat(SCORES.map(s => `<option value="${s}"${finalScore === s ? ' selected' : ''}>${s.replace('-', ' – ')}</option>`));
    control = `<select data-action="result" data-pid="${p.id}">${opts.join('')}</select>`;
  }

  // Timer per-tavolo (round.ends_at + extra)
  let tableClock = '';
  if (!isBye && !finalScore) {
    const extra = p.extra_seconds || 0;
    const clockSpan = round.ends_at
      ? `<span class="tbl-clock" data-ends="${round.ends_at}" data-extra="${extra}"></span>` : '';
    const extraLbl = extra ? `<span class="tbl-extra">+${Math.round(extra / 60)}′</span>` : '';
    tableClock = `${clockSpan}${extraLbl}
      <button class="mini-button" data-action="extend-table" data-pid="${p.id}" data-min="2" type="button">+2′</button>
      <button class="mini-button" data-action="extend-table" data-pid="${p.id}" data-min="5" type="button">+5′</button>`;
  }

  return `<div class="ctl-row">
    <span class="table-num">T${p.table_number}</span>
    <span class="names"><strong>${esc(p.player_a)}</strong> vs <strong>${esc(p.player_b || 'BYE')}</strong></span>
    ${tableClock}
    <span>${control}</span>
  </div>`;
}

async function submitResult(pairingId, score) {
  if (!score) return;
  _editing.delete(String(pairingId));
  await call(
    () => apiFetch(`/tournaments/${_tid}/pairings/${pairingId}/result`, { method: 'PATCH', body: JSON.stringify(scoreToBody(score)) }),
    'Risultato registrato.');
}

/* ── Tick: countdown round + per-tavolo ──────────────── */
function tick() {
  const round = activeRound();
  if (round?.ends_at) {
    const rem = (new Date(round.ends_at) - Date.now()) / 1000;
    const el = $('#ctlClock');
    el.textContent = fmt(rem);
    el.className = 'ctl-clock ' + (rem <= 0 ? 'over' : rem <= 300 ? 'warning' : '');
  } else {
    $('#ctlClock').textContent = '--:--';
    $('#ctlClock').className = 'ctl-clock';
  }
  document.querySelectorAll('.tbl-clock[data-ends]').forEach(span => {
    const end = new Date(span.dataset.ends).getTime() + (+span.dataset.extra) * 1000;
    const rem = (end - Date.now()) / 1000;
    span.textContent = fmt(rem);
    span.classList.toggle('over', rem <= 0);
  });
}

document.addEventListener('DOMContentLoaded', init);
