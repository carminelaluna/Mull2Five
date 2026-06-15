/**
 * organizer.js — Back-office organizzatore 100% online (nessun localStorage).
 *
 * Tutto passa dal backend: creazione/gestione tornei, iscritti (walk-in, check-in,
 * pagamento contanti, drop), classifica, report incassi. Accessibile da più PC:
 * ogni postazione vede gli stessi dati in tempo reale (refresh su ogni azione).
 */
const API       = '/api';
const TOKEN_KEY = 'manabind-jwt-v1';
const token     = localStorage.getItem(TOKEN_KEY);
if (!token) location.replace('login.html?next=organizer.html');

function decodeJwt(t) {
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); }
  catch { return null; }
}
const session = decodeJwt(token);
if (!session || session.exp < Date.now() / 1000) {
  localStorage.removeItem(TOKEN_KEY); location.replace('login.html?next=organizer.html');
}

async function apiFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, ...(opts.headers || {}) };
  const r = await fetch(API + path, { ...opts, headers });
  if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); location.replace('login.html'); return; }
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    // Un 404 con "Not Found" generico = route assente: backend probabilmente non aggiornato.
    if (r.status === 404 && (!detail || detail === 'Not Found')) {
      throw new Error('Endpoint non trovato: riavvia il backend (potrebbe eseguire una versione vecchia).');
    }
    throw new Error(detail || r.statusText);
  }
  return r.status === 204 ? null : r.json();
}

const $   = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const money = (c, cur = 'EUR') => ((c || 0) / 100).toLocaleString('it-IT', { style: 'currency', currency: cur });
const fmtDate = (d) => d ? d.substring(0, 10).split('-').reverse().join('/') : '—';
function toast(m) { const e = $('#toast'); e.textContent = m; e.classList.add('show'); clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove('show'), 3000); }

let _tab = 'tornei';
let _tournaments = [];
let _activeId = null;
let _classificaId = null;   // override: classifica di un torneo concluso dallo storico

async function init() {
  $('#publicAuth').innerHTML =
    `<a class="secondary-link" href="player.html?email=${encodeURIComponent(session.email)}">Profilo</a>
     <span style="color:var(--muted);font-size:.85rem">${esc(session.email)}</span>
     <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
  $('#logoutBtn').addEventListener('click', () => { localStorage.removeItem(TOKEN_KEY); location.replace('index.html'); });

  document.querySelectorAll('.bo-tab').forEach(b =>
    b.addEventListener('click', () => {
      _tab = b.dataset.tab;
      _classificaId = null;   // tornando alla tab si guarda il torneo attivo
      document.querySelectorAll('.bo-tab').forEach(x => x.classList.toggle('active', x === b));
      render();
    }));
  $('#activeTournament').addEventListener('change', (e) => { _activeId = e.target.value; _classificaId = null; render(); });

  await loadTournaments();
  render();
}

const isClosed = (t) => ['completed', 'cancelled'].includes(t.status);

async function loadTournaments() {
  try { _tournaments = (await apiFetch('/tournaments/mine')) || []; } catch { _tournaments = []; }
  _tournaments.sort((a, b) => String(b.starts_on).localeCompare(String(a.starts_on)));
  // Il selettore "evento attivo" mostra solo i tornei NON conclusi.
  // I conclusi restano nello storico (tab Tornei) e nello storico giocatore.
  const selectable = _tournaments.filter(t => !isClosed(t));
  if (!selectable.some(t => String(t.id) === String(_activeId))) _activeId = selectable[0] ? String(selectable[0].id) : null;
  $('#activeTournament').innerHTML = selectable.map(t =>
    `<option value="${t.id}">${esc(t.name)} · ${fmtDate(t.starts_on)}</option>`).join('') || '<option value="">— nessun torneo attivo —</option>';
  if (_activeId) $('#activeTournament').value = _activeId;
}

function activeT() { return _tournaments.find(t => String(t.id) === String(_activeId)); }

function render() {
  const t = activeT();
  $('#activeHint').textContent = t
    ? `Attivo: ${t.name} — ${t.status} · ${t.registered_players} iscritti`
    : 'Nessun torneo: creane uno nella tab Tornei.';
  if (_tab === 'tornei')     return renderTornei();
  if (_tab === 'iscritti')   return renderIscritti();
  if (_tab === 'liste')      return renderListe();
  if (_tab === 'annunci')    return renderAnnunci();
  if (_tab === 'penalita')   return renderPenalita();
  if (_tab === 'classifica') return renderClassifica();
  if (_tab === 'report')     return renderReport();
}

/* ── TORNEI ──────────────────────────────────────────── */
function tournamentRow(t, archived) {
  return `
    <tr>
      <td><strong>${esc(t.name)}</strong><br><small class="muted">${esc(t.format)} · ${fmtDate(t.starts_on)}${t.start_time ? ' ' + esc(t.start_time) : ''}</small></td>
      <td><span class="pill ${t.status === 'running' ? 'ok' : 'warn'}">${esc(t.status)}</span></td>
      <td>${t.registered_players}/${t.capacity}</td>
      <td class="row-actions">
        <a class="mini-button" href="control.html?t=${t.id}" target="_blank" rel="noopener">🎛 Regia</a>
        <a class="mini-button" href="../display.html?t=${t.id}" target="_blank" rel="noopener">📺 Display</a>
        <button class="mini-button" data-act="dup" data-id="${t.id}" type="button">Duplica</button>
        ${t.status === 'published' ? `<button class="mini-button" data-act="start" data-id="${t.id}" type="button">▶ Avvia</button>` : ''}
        ${archived ? `<button class="mini-button" data-act="standings" data-id="${t.id}" type="button">📊 Classifica</button>` : ''}
        ${!archived ? `<button class="mini-button" data-act="close" data-id="${t.id}" type="button">Chiudi</button>` : ''}
        ${!archived ? `<button class="mini-button" data-act="del" data-id="${t.id}" type="button" style="color:var(--danger,#e36363)">Elimina</button>` : ''}
      </td>
    </tr>`;
}

function renderTornei() {
  const active = _tournaments.filter(t => !isClosed(t));
  const closed = _tournaments.filter(isClosed);
  const rows = active.map(t => tournamentRow(t, false)).join('') || '<tr><td colspan="4" class="muted">Nessun torneo attivo.</td></tr>';
  const closedRows = closed.map(t => tournamentRow(t, true)).join('');

  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px">
      <h3>Nuovo torneo</h3>
      <form id="newT" class="bo-grid">
        <label>Nome<input id="nName" required placeholder="RCQ Modern" /></label>
        <label>Formato<input id="nFormat" value="Modern" /></label>
        <label>Data<input id="nDate" type="date" required /></label>
        <label>Orario inizio<input id="nTime" type="time" required value="20:00" /></label>
        <label>Capienza<input id="nCap" type="number" min="2" value="64" /></label>
        <label>Entry fee €<input id="nFee" type="number" min="0" step="0.01" value="25" /></label>
        <label style="display:flex;align-items:center;gap:6px"><input id="nDeck" type="checkbox" checked /> Lista obbligatoria</label>
        <label style="display:flex;align-items:center;gap:6px"><input id="nAtEvent" type="checkbox" checked /> Pagamento al banco</label>
        <label style="display:flex;align-items:center;gap:6px"><input id="nStripe" type="checkbox" /> Online Stripe</label>
        <label style="display:flex;align-items:center;gap:6px"><input id="nPaypal" type="checkbox" /> Online PayPal</label>
        <label style="display:flex;align-items:center;gap:6px"><input id="nPairPub" type="checkbox" checked /> Abbinamenti pubblici</label>
        <label style="display:flex;align-items:center;gap:6px"><input id="nStandPub" type="checkbox" checked /> Classifica pubblica</label>
        <button class="primary" type="submit" style="grid-column:1/-1">Crea torneo</button>
      </form>
    </div>
    <div class="panel">
      <h3>Tornei attivi</h3>
      <table class="bo"><thead><tr><th>Torneo</th><th>Stato</th><th>Iscritti</th><th>Azioni</th></tr></thead><tbody>${rows}</tbody></table>
    </div>
    ${closedRows ? `<div class="panel" style="margin-top:16px">
      <h3>Storico (conclusi)</h3>
      <p class="muted" style="margin-top:0;font-size:.85rem">I tornei conclusi restano nello storico e non possono essere eliminati.</p>
      <table class="bo"><thead><tr><th>Torneo</th><th>Stato</th><th>Iscritti</th><th>Azioni</th></tr></thead><tbody>${closedRows}</tbody></table>
    </div>` : ''}`;

  $('#newT').addEventListener('submit', createTournament);
  $('#panel').querySelectorAll('[data-act]').forEach(b =>
    b.addEventListener('click', () => tournamentAction(b.dataset.act, b.dataset.id)));
}

async function createTournament(e) {
  e.preventDefault();
  const body = {
    name: $('#nName').value.trim(),
    format: $('#nFormat').value.trim() || 'Modern',
    starts_on: $('#nDate').value,
    start_time: $('#nTime').value || null,
    capacity: +$('#nCap').value || 8,
    entry_fee_cents: Math.round((+$('#nFee').value || 0) * 100),
    currency: 'EUR',
    status: 'published',
    decklist_required: $('#nDeck').checked,
    pay_at_event: $('#nAtEvent').checked,
    pay_stripe: $('#nStripe').checked,
    pay_paypal: $('#nPaypal').checked,
    pairings_public: $('#nPairPub').checked,
    standings_public: $('#nStandPub').checked,
  };
  if (!body.name || !body.starts_on) { toast('Nome e data obbligatori.'); return; }
  if (!body.start_time) { toast('Inserisci l\'orario di inizio.'); return; }
  // C2: almeno un metodo di pagamento dev'essere selezionato
  if (!body.pay_at_event && !body.pay_stripe && !body.pay_paypal) {
    toast('Seleziona almeno un metodo di pagamento.'); return;
  }
  try {
    const t = await apiFetch('/tournaments', { method: 'POST', body: JSON.stringify(body) });
    toast('Torneo creato.');
    _activeId = String(t.id);
    await loadTournaments(); render();
  } catch (err) { toast('Errore: ' + err.message); }
}

async function tournamentAction(act, id) {
  // Vedi classifica di un torneo (anche concluso) senza renderlo "attivo".
  if (act === 'standings') {
    _classificaId = id;
    _tab = 'classifica';
    document.querySelectorAll('.bo-tab').forEach(x => x.classList.toggle('active', x.dataset.tab === 'classifica'));
    render();
    return;
  }
  const confirmMsg = act === 'del' ? 'Eliminare definitivamente il torneo e tutti i dati?' : null;
  if (confirmMsg && !window.confirm(confirmMsg)) return;
  try {
    if (act === 'start') await apiFetch(`/tournaments/${id}/start`, { method: 'POST' });
    if (act === 'close') await apiFetch(`/tournaments/${id}/close`, { method: 'POST' });
    if (act === 'del')   await apiFetch(`/tournaments/${id}`, { method: 'DELETE' });
    if (act === 'dup') {
      const t = await apiFetch(`/tournaments/${id}/duplicate`, { method: 'POST' });
      _activeId = String(t.id);
      toast('Torneo duplicato (data +7 giorni).');
    } else {
      toast('Fatto.');
    }
    await loadTournaments(); render();
  } catch (err) { toast('Errore: ' + err.message); }
}

/* ── ISCRITTI ────────────────────────────────────────── */
let _regs = [];
let _regPage = 1;

async function renderIscritti() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Seleziona un torneo.</p>'; return; }
  await loadRegs(t.id, true);
}

async function loadRegs(tid, reset) {
  if (reset) { _regs = []; _regPage = 1; }
  try {
    const page = await apiFetch(`/tournaments/${tid}/registrations?page=${_regPage}&page_size=100`);
    _regs = reset ? page : _regs.concat(page);
    if (Array.isArray(page) && page.length === 100) _regPage += 1; else _regPage = 0; // 0 = niente altre pagine
  } catch (err) { toast('Errore: ' + err.message); }
  drawIscritti(tid);
}

function drawIscritti(tid) {
  const rows = _regs.map(r => `
    <tr>
      <td><strong>${esc(r.player?.display_name || r.player_email)}</strong><br><small class="muted">${esc(r.player_email)}</small>
        ${r.waitlisted ? ' <span class="pill warn">attesa</span>' : ''}${r.dropped ? ' <span class="pill">drop</span>' : ''}</td>
      <td><span class="pill ${['paid', 'confirmed'].includes(r.payment_status) ? 'ok' : 'warn'}">${esc(r.payment_status)}</span></td>
      <td>${esc(r.decklist_status)}</td>
      <td>${r.checked_in ? '✓' : '—'}</td>
      <td class="row-actions">
        ${!['paid', 'confirmed'].includes(r.payment_status) ? `<button class="mini-button" data-r="${r.id}" data-act="pay" type="button">Segna pagato</button>` : ''}
        <button class="mini-button" data-r="${r.id}" data-act="checkin" data-val="${!r.checked_in}" type="button">${r.checked_in ? 'Annulla check-in' : 'Check-in'}</button>
        <button class="mini-button" data-r="${r.id}" data-act="drop" data-val="${!r.dropped}" type="button">${r.dropped ? 'Reintegra' : 'Drop'}</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="5" class="muted">Nessun iscritto.</td></tr>';

  const moreBtn = _regPage > 0 ? '<button class="secondary" id="loadMore" type="button">Carica altri</button>' : '';

  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px">
      <h3>Iscrivi al banco (walk-in)</h3>
      <form id="walkIn" class="bo-grid">
        <label>Email<input id="wEmail" type="email" required placeholder="player@email.com" /></label>
        <label>Nome<input id="wName" required placeholder="Mario Rossi" /></label>
        <label>Wizards<input id="wWiz" placeholder="##########" /></label>
        <label style="display:flex;align-items:center;gap:6px"><input id="wPaid" type="checkbox" checked /> Pagato (contanti)</label>
        <button class="primary" type="submit">Iscrivi</button>
      </form>
    </div>
    <div class="panel">
      <h3>Iscritti (${_regs.length})</h3>
      <input id="regFilter" placeholder="Filtra per nome/email…" style="margin-bottom:8px;width:100%" />
      <table class="bo"><thead><tr><th>Giocatore</th><th>Pagamento</th><th>Lista</th><th>Check-in</th><th>Azioni</th></tr></thead><tbody id="regBody">${rows}</tbody></table>
      <div style="margin-top:10px">${moreBtn}</div>
    </div>`;

  $('#walkIn').addEventListener('submit', (e) => doWalkIn(e, tid));
  $('#loadMore')?.addEventListener('click', () => loadRegs(tid, false));
  $('#regFilter').addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    $('#regBody').querySelectorAll('tr').forEach(tr =>
      tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none');
  });
  $('#panel').querySelectorAll('[data-act]').forEach(b =>
    b.addEventListener('click', () => regAction(tid, b.dataset.act, b.dataset.r, b.dataset.val)));
}

async function doWalkIn(e, tid) {
  e.preventDefault();
  const body = {
    email: $('#wEmail').value.trim(),
    display_name: $('#wName').value.trim(),
    wizards_account: $('#wWiz').value.trim(),
    mark_paid: $('#wPaid').checked,
  };
  if (!body.email || !body.display_name) { toast('Email e nome obbligatori.'); return; }
  try {
    await apiFetch(`/tournaments/${tid}/walk-in`, { method: 'POST', body: JSON.stringify(body) });
    toast('Iscritto.');
    await loadTournaments();   // aggiorna il conteggio
    await loadRegs(tid, true);
  } catch (err) { toast('Errore: ' + err.message); }
}

async function regAction(tid, act, rid, val) {
  const on = (val === 'true' || val === true);
  // Aggiornamento ottimistico: cambia subito lo stato e ridisegna, poi sincronizza.
  const reg = _regs.find(r => String(r.id) === String(rid));
  const prev = reg ? { payment_status: reg.payment_status, checked_in: reg.checked_in, dropped: reg.dropped } : null;
  if (reg) {
    if (act === 'pay')     reg.payment_status = 'paid';
    if (act === 'checkin') reg.checked_in = on;
    if (act === 'drop')    reg.dropped = on;
    drawIscritti(tid);
  }
  try {
    if (act === 'pay')     await apiFetch(`/tournaments/${tid}/registrations/${rid}/mark-paid`, { method: 'POST' });
    if (act === 'checkin') await apiFetch(`/tournaments/${tid}/registrations/${rid}/check-in?checked_in=${on}`, { method: 'PATCH' });
    if (act === 'drop')    await apiFetch(`/tournaments/${tid}/registrations/${rid}/drop?dropped=${on}`, { method: 'PATCH' });
  } catch (err) {
    if (reg && prev) { Object.assign(reg, prev); drawIscritti(tid); }   // rollback
    toast('Errore: ' + err.message);
  }
}

/* Carica TUTTE le iscrizioni (tutte le pagine) — usato da Liste e Penalità. */
async function fetchAllRegs(tid) {
  const all = [];
  for (let page = 1; page < 100; page++) {
    const batch = await apiFetch(`/tournaments/${tid}/registrations?page=${page}&page_size=200`);
    if (!Array.isArray(batch) || !batch.length) break;
    all.push(...batch);
    if (batch.length < 200) break;
  }
  return all;
}

/* ── LISTE (decklist iscritti) ───────────────────────── */
async function renderListe() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Seleziona un torneo.</p>'; return; }
  $('#panel').innerHTML = '<p class="empty">Caricamento liste…</p>';
  let regs = [];
  try { regs = await fetchAllRegs(t.id); } catch (err) { toast('Errore: ' + err.message); }
  const badge = (s) => ({ valid: 'ok', invalid: 'warn', missing: 'warn' }[s] || 'warn');
  const rows = regs.map(r => `
    <tr>
      <td><strong>${esc(r.player?.display_name || r.player_email)}</strong></td>
      <td><span class="pill ${badge(r.decklist_status)}">${esc(r.decklist_status)}</span></td>
      <td>${r.decklist_main_count ?? '—'} / ${r.decklist_side_count ?? '—'}</td>
      <td>${r.decklist_errors ? `<small style="color:var(--danger,#e36363)">${esc(r.decklist_errors)}</small>` : '—'}</td>
      <td class="row-actions">
        ${r.decklist_raw_text ? `<button class="mini-button" data-deck="${r.id}" type="button">Vedi</button>` : ''}
        <button class="mini-button" data-upload="${r.id}" type="button">${r.decklist_raw_text ? 'Modifica' : 'Carica'} lista</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="5" class="muted">Nessun iscritto.</td></tr>';
  $('#panel').innerHTML = `<div class="panel"><h3>Liste — ${esc(t.name)}</h3>
    <input id="listFilter" placeholder="Filtra…" style="margin-bottom:8px;width:100%" />
    <table class="bo"><thead><tr><th>Giocatore</th><th>Stato</th><th>Main/Side</th><th>Errori</th><th>Azioni</th></tr></thead><tbody id="listBody">${rows}</tbody></table>
    <pre id="deckView" style="display:none;white-space:pre-wrap;background:rgba(0,0,0,.25);padding:12px;border-radius:8px;margin-top:12px;max-height:320px;overflow:auto"></pre>
    <div id="deckUpload" style="display:none;margin-top:12px;border-top:1px solid var(--line,#3a352d);padding-top:12px">
      <h4 id="duName" style="margin:0 0 8px"></h4>
      <label style="display:block;margin-bottom:6px">Carica da file (.txt/.dec)
        <input id="duFile" type="file" accept=".txt,.dec,.csv,text/plain" /></label>
      <textarea id="duText" placeholder="4 Lightning Bolt&#10;4 Ragavan…&#10;&#10;Sideboard&#10;2 Blood Moon" style="width:100%;min-height:200px"></textarea>
      <label style="display:block;margin-top:6px">Archetipo<input id="duArch" placeholder="Izzet Murktide…" /></label>
      <div style="margin-top:8px;display:flex;gap:8px">
        <button class="primary" id="duSubmit" type="button">Salva lista</button>
        <button class="secondary" id="duCancel" type="button">Annulla</button>
      </div>
    </div></div>`;
  $('#listFilter').addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    $('#listBody').querySelectorAll('tr').forEach(tr => tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none');
  });
  $('#panel').querySelectorAll('[data-deck]').forEach(b => b.addEventListener('click', () => {
    const r = regs.find(x => String(x.id) === b.dataset.deck);
    const v = $('#deckView'); v.style.display = 'block';
    v.textContent = `${r.player?.display_name}\n\n${r.decklist_raw_text}`;
    v.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }));
  $('#panel').querySelectorAll('[data-upload]').forEach(b => b.addEventListener('click', () => {
    const r = regs.find(x => String(x.id) === b.dataset.upload);
    openDeckUpload(t.id, r);
  }));
  // Carica il testo da file nel textarea
  $('#duFile').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (f) $('#duText').value = await f.text();
  });
  $('#duCancel').addEventListener('click', () => { $('#deckUpload').style.display = 'none'; });
}

function openDeckUpload(tid, reg) {
  $('#duName').textContent = `Lista di ${reg.player?.display_name || reg.player_email}`;
  $('#duText').value = reg.decklist_raw_text || '';
  $('#duArch').value = reg.archetype || '';
  $('#duFile').value = '';
  const panel = $('#deckUpload');
  panel.style.display = 'block';
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  const submit = $('#duSubmit');
  submit.onclick = async () => {
    const raw = $('#duText').value.trim();
    if (raw.length < 5) { toast('Incolla o carica una lista valida.'); return; }
    submit.disabled = true;
    try {
      await apiFetch(`/tournaments/${tid}/registrations/${reg.id}/decklist`, {
        method: 'POST', body: JSON.stringify({ raw_text: raw, archetype: $('#duArch').value.trim() }),
      });
      toast('Lista salvata.');
      renderListe();   // ricarica con lo stato aggiornato
    } catch (err) { toast('Errore: ' + err.message); submit.disabled = false; }
  };
}

/* ── ANNUNCI ─────────────────────────────────────────── */
async function renderAnnunci() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Seleziona un torneo.</p>'; return; }
  let list = [];
  try { list = (await apiFetch(`/tournaments/${t.id}/announcements`)) || []; } catch (err) { toast('Errore: ' + err.message); }
  const items = list.map(a => `
    <div class="check-row" style="display:flex;justify-content:space-between;gap:8px;padding:8px 0;border-bottom:1px solid var(--line,#3a352d)">
      <span>📢 <strong>${esc(a.title)}</strong><br><small class="muted">${esc(a.body)}</small></span>
      <small class="muted">${new Date(a.created_at).toLocaleString('it-IT')}</small>
    </div>`).join('') || '<p class="muted">Nessun annuncio.</p>';
  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px"><h3>Nuovo annuncio</h3>
      <form id="annForm" class="bo-grid">
        <label style="grid-column:1/-1">Titolo<input id="aTitle" required placeholder="Pausa 10 minuti" /></label>
        <label style="grid-column:1/-1">Messaggio<textarea id="aBody" required placeholder="Verificate i tavoli, si riprende alle 15:00"></textarea></label>
        <label style="display:flex;align-items:center;gap:6px"><input id="aEmail" type="checkbox" /> Invia anche via email</label>
        <button class="primary" type="submit">Invia annuncio</button>
      </form>
    </div>
    <div class="panel"><h3>Annunci inviati</h3>${items}</div>`;
  $('#annForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { title: $('#aTitle').value.trim(), body: $('#aBody').value.trim(), send_email: $('#aEmail').checked };
    if (!body.title || !body.body) { toast('Titolo e messaggio obbligatori.'); return; }
    try { await apiFetch(`/tournaments/${t.id}/announcements`, { method: 'POST', body: JSON.stringify(body) }); toast('Annuncio inviato.'); renderAnnunci(); }
    catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── PENALITÀ ────────────────────────────────────────── */
async function renderPenalita() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Seleziona un torneo.</p>'; return; }
  let regs = [], penalties = [];
  try {
    [regs, penalties] = await Promise.all([
      fetchAllRegs(t.id),
      apiFetch(`/tournaments/${t.id}/penalties`).catch(() => []),
    ]);
  } catch (err) { toast('Errore: ' + err.message); }
  const nameById = Object.fromEntries(regs.map(r => [r.id, r.player?.display_name || r.player_email]));
  const opts = regs.map(r => `<option value="${r.id}">${esc(r.player?.display_name || r.player_email)}</option>`).join('');
  const rows = penalties.map(p => `
    <tr><td>${esc(nameById[p.registration_id] || '?')}</td><td><span class="pill warn">${esc(p.kind)}</span></td>
        <td>${esc(p.note || '—')}</td><td><small class="muted">${new Date(p.created_at).toLocaleString('it-IT')}</small></td></tr>`).join('')
    || '<tr><td colspan="4" class="muted">Nessuna penalità.</td></tr>';
  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px"><h3>Assegna penalità</h3>
      <form id="penForm" class="bo-grid">
        <label>Giocatore<select id="pReg">${opts}</select></label>
        <label>Tipo<select id="pKind">
          <option value="warning">Warning</option><option value="game_loss">Game Loss</option>
          <option value="match_loss">Match Loss</option><option value="disqualification">Squalifica</option>
          <option value="note">Nota</option></select></label>
        <label style="grid-column:1/-1">Nota<input id="pNote" placeholder="Slow play, deck error…" /></label>
        <button class="primary danger" type="submit">Registra penalità</button>
      </form>
    </div>
    <div class="panel"><h3>Penalità registrate</h3>
      <table class="bo"><thead><tr><th>Giocatore</th><th>Tipo</th><th>Nota</th><th>Quando</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  $('#penForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { registration_id: +$('#pReg').value, kind: $('#pKind').value, note: $('#pNote').value.trim() };
    if (!body.registration_id) { toast('Seleziona un giocatore.'); return; }
    try { await apiFetch(`/tournaments/${t.id}/penalties`, { method: 'POST', body: JSON.stringify(body) }); toast('Penalità registrata.'); renderPenalita(); }
    catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── CLASSIFICA ──────────────────────────────────────── */
async function renderClassifica() {
  // Se arrivi dallo storico (torneo concluso) usa quello, altrimenti il torneo attivo.
  const t = _classificaId
    ? _tournaments.find(x => String(x.id) === String(_classificaId))
    : activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Seleziona un torneo.</p>'; return; }
  let standings = [];
  try { standings = (await apiFetch(`/tournaments/${t.id}/standings`)) || []; } catch (err) { toast('Errore: ' + err.message); }
  const rows = standings.map(s => `
    <tr>
      <td>${s.position}</td>
      <td><strong>${esc(s.name)}</strong></td>
      <td>${s.points}</td>
      <td>${esc(s.record)}</td>
      <td>${s.opponent_match_win_percentage}%</td>
    </tr>`).join('') || '<tr><td colspan="5" class="muted">Nessun dato (genera round e inserisci risultati).</td></tr>';
  $('#panel').innerHTML = `<div class="panel"><h3>Classifica — ${esc(t.name)}</h3>
    <table class="bo"><thead><tr><th>#</th><th>Giocatore</th><th>Punti</th><th>V/S/P</th><th>OMW%</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

/* ── REPORT ──────────────────────────────────────────── */
async function renderReport() {
  let reports = [];
  try { reports = (await apiFetch('/tournaments/reports/mine')) || []; } catch (err) { toast('Errore: ' + err.message); }
  const totRev = reports.reduce((s, r) => s + r.revenue_cents, 0);
  const totPlayers = reports.reduce((s, r) => s + r.registrations, 0);
  const rows = reports.map(r => `
    <tr>
      <td><strong>${esc(r.tournament_name)}</strong><br><small class="muted">${esc(r.format)} · ${fmtDate(r.starts_on)}</small></td>
      <td>${r.registrations}</td>
      <td>${r.paid_count}</td>
      <td>${money(r.revenue_cents, r.currency)}</td>
    </tr>`).join('') || '<tr><td colspan="4" class="muted">Nessun torneo.</td></tr>';
  $('#panel').innerHTML = `
    <div class="bo-grid" style="margin-bottom:14px">
      <div class="panel" style="text-align:center"><small class="muted">Incasso totale</small><div style="font-size:1.5rem;font-weight:bold">${money(totRev)}</div></div>
      <div class="panel" style="text-align:center"><small class="muted">Presenze totali</small><div style="font-size:1.5rem;font-weight:bold">${totPlayers}</div></div>
      <div class="panel" style="text-align:center"><small class="muted">Tornei</small><div style="font-size:1.5rem;font-weight:bold">${reports.length}</div></div>
    </div>
    <div class="panel"><h3 style="display:flex;justify-content:space-between;align-items:center">Report incassi
      <button class="secondary" id="repCsv" type="button">⬇ Scarica CSV</button></h3>
      <table class="bo"><thead><tr><th>Torneo</th><th>Iscritti</th><th>Paganti</th><th>Incasso</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  $('#repCsv').addEventListener('click', () => downloadReportCsv(reports));
}

/* Genera e scarica il report incassi in CSV (lato client). */
function downloadReportCsv(reports) {
  const cell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const header = ['Torneo', 'Formato', 'Data', 'Iscritti', 'Paganti', 'Incasso', 'Valuta'];
  const lines = [header.join(',')];
  for (const r of reports) {
    lines.push([r.tournament_name, r.format, r.starts_on, r.registrations, r.paid_count,
                (r.revenue_cents / 100).toFixed(2), r.currency].map(cell).join(','));
  }
  const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `report-incassi-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

document.addEventListener('DOMContentLoaded', init);
