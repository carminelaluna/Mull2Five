/**
 * organizer.js — Back-office organizzatore 100% online (nessun localStorage).
 *
 * Tutto passa dal backend: creazione/gestione tornei, iscritti (walk-in, check-in,
 * pagamento contanti, drop), classifica, report incassi. Accessibile da più PC:
 * ogni postazione vede gli stessi dati in tempo reale (refresh su ogni azione).
 */
import { EVENT_TYPES, RELS, typeLabel } from './catalog.js';
import { mountConsole } from './console.js';
import { renderDeck } from './deck-view.js';
import { esc } from './escape.js';

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
const money = (c, cur = 'EUR') => ((c || 0) / 100).toLocaleString('it-IT', { style: 'currency', currency: cur });
const fmtDate = (d) => d ? d.substring(0, 10).split('-').reverse().join('/') : '—';
function toast(m) { const e = $('#toast'); e.textContent = m; e.classList.add('show'); clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove('show'), 3000); }

let _section = 'eventi';     // eventi | community | negozio
let _tab = 'giocatori';      // sezione attiva DENTRO un evento
let _tagEventId = null;      // da quale evento pescare i giocatori in Community
let _tournaments = [];
let _activeId = null;        // evento aperto; null = lista eventi

/* Le sezioni dentro un evento. Meno di prima: classifica e report erano due
   letture degli stessi dati e stanno insieme sotto "Risultati". */
const EVENT_TABS = [
  { id: 'regia',      label: '🎛 Regia' },
  { id: 'giocatori',  label: 'Giocatori' },
  { id: 'annunci',    label: 'Annunci' },
  { id: 'staff',      label: 'Staff' },
  { id: 'risultati',  label: 'Risultati' },
];

async function init() {
  $('#publicAuth').innerHTML =
    `<a class="secondary-link" href="player.html?email=${encodeURIComponent(session.email)}">Profilo</a>
     <span style="color:var(--muted);font-size:.85rem">${esc(session.email)}</span>
     <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
  $('#logoutBtn').addEventListener('click', () => { localStorage.removeItem(TOKEN_KEY); location.replace('index.html'); });

  document.querySelectorAll('.bo-nav-item').forEach(b =>
    b.addEventListener('click', () => {
      _section = b.dataset.section;
      _activeId = null;            // cambiando sezione si esce dall'evento
      _openEventId = null;
      document.querySelectorAll('.bo-nav-item').forEach(x => x.classList.toggle('active', x === b));
      render();
    }));

  // ?t=ID apre direttamente quell'evento: ci si arriva dai link della regia.
  const wanted = new URLSearchParams(location.search).get('t');
  await loadTournaments();
  // Passa da openEvent, cosi il link profondo prende la stessa scheda di default
  // di un clic sulla scheda dell'evento.
  if (wanted && _tournaments.some(t => String(t.id) === wanted)) openEvent(wanted);
  else render();
}

const isClosed = (t) => ['completed', 'cancelled'].includes(t.status);

// tournament_id -> avvisi. Riempita dalla lista, aggiornata entrando nel torneo.
let _warnings = {};

async function loadTournaments() {
  const [tornei, avvisi] = await Promise.all([
    apiFetch('/tournaments/mine').catch(() => []),
    // Solo chi organizza ha avvisi: a un judge l'endpoint dice di no, ed e giusto.
    apiFetch('/tournaments/warnings/mine').catch(() => ({})),
  ]);
  _tournaments = tornei || [];
  _warnings = avvisi || {};
  _tournaments.sort((a, b) => String(b.starts_on).localeCompare(String(a.starts_on)));
}

/** Il contatore sulle schede conta solo gli avvisi veri: le note restano dentro
    il torneo, altrimenti i badge si accendono ovunque e si smette di guardarli. */
function warnChip(list) {
  const veri = (list || []).filter(w => w.level === 'warn');
  if (!veri.length) return '';
  return `<span class="warn-chip" title="${esc(veri.map(w => w.message).join('\n'))}">⚠ ${veri.length} ${veri.length === 1 ? 'avviso' : 'avvisi'}</span>`;
}

function activeT() { return _tournaments.find(t => String(t.id) === String(_activeId)); }

/** Entra in un evento e mostra le sue sezioni. */
function openEvent(id, tab = null) {
  const t = _tournaments.find(x => String(x.id) === String(id));
  tab = tab || (t?.status === 'running' ? 'regia' : 'giocatori');
  _activeId = String(id);
  _tab = tab;
  render();
}

function closeEvent() {
  stopConsole();
  _activeId = null;
  render();
}

function renderCrumb() {
  const t = activeT();
  const crumb = $('#boCrumb');
  const tabs = $('#boEventTabs');
  if (!t) {
    crumb.style.display = 'none';
    tabs.style.display = 'none';
    renderWarnings(null);
    return;
  }
  crumb.style.display = '';
  crumb.innerHTML = `
    <button class="bo-back" id="boBack" type="button">← Eventi</button>
    <div class="bo-crumb-title">
      <strong>${esc(t.name)}</strong>
      <span class="muted">${esc(t.format)} · ${fmtDate(t.starts_on)} · ${t.registered_players} iscritti
        <span class="pill ${t.status === 'running' ? 'ok' : 'warn'}">${esc(statusLabel(t.status))}</span></span>
    </div>
    <div class="bo-crumb-actions">
      <a class="mini-button" href="control.html?t=${t.id}" target="_blank" rel="noopener"
         title="Apre la stessa console a tutto schermo: per un secondo monitor o per i judge">🖥 Regia a parte</a>
      <a class="mini-button" href="display.html?t=${t.id}" target="_blank" rel="noopener">📺 Display</a>
      <a class="mini-button" href="event.html?id=${t.id}" target="_blank" rel="noopener">↗ Pagina pubblica</a>
      ${isClosed(t) ? `<a class="mini-button" href="coverage.html?t=${t.id}" target="_blank" rel="noopener">🖼 Scheda social</a>` : ''}
    </div>`;
  $('#boBack').addEventListener('click', closeEvent);

  tabs.style.display = '';
  tabs.innerHTML = EVENT_TABS.map(x =>
    `<button class="bo-tab${x.id === _tab ? ' active' : ''}" data-tab="${x.id}" type="button">${esc(x.label)}</button>`
  ).join('');
  tabs.querySelectorAll('[data-tab]').forEach(b =>
    b.addEventListener('click', () => { _tab = b.dataset.tab; render(); }));
  renderWarnings(t);
}

/* Gli avvisi del torneo aperto, sopra ogni scheda. Si rileggono a ogni cambio
   di scheda perche a scioglierli e proprio quello che si fa qui dentro:
   nominare un capojudge, spostare la scadenza delle liste. */
const WARNING_ACTIONS = {
  no_head_judge:                 { tab: 'staff',     label: 'Apri Staff' },
  missing_decklists:             { tab: 'annunci',   label: 'Manda un annuncio' },
  decklist_deadline_after_start: { tab: 'giocatori', label: 'Apri Giocatori' },
};

async function renderWarnings(t) {
  const box = $('#boWarnings');
  // Gli avvisi sono di chi organizza: un judge nel back-office non li vede.
  if (!t || isClosed(t) || String(t.organizer_id) !== String(session.sub)) {
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }
  let avvisi;
  try {
    avvisi = (await apiFetch(`/tournaments/${t.id}/warnings`)) || [];
  } catch (err) {
    box.style.display = '';
    box.innerHTML = `<div class="bo-warning info"><span class="bo-warning-text">Avvisi non disponibili: ${esc(err.message)}</span></div>`;
    return;
  }
  if (String(_activeId) !== String(t.id)) return;   // nel frattempo si e cambiato torneo
  _warnings[t.id] = avvisi;
  box.style.display = avvisi.length ? '' : 'none';
  box.innerHTML = avvisi.map(w => {
    const azione = WARNING_ACTIONS[w.code];
    return `
      <div class="bo-warning ${w.level === 'warn' ? 'warn' : 'info'}">
        <span class="bo-warning-icon" aria-hidden="true">${w.level === 'warn' ? '⚠' : 'ℹ'}</span>
        <span class="bo-warning-text">${esc(w.message)}</span>
        ${azione && _tab !== azione.tab
          ? `<button class="mini-button" data-warn-tab="${azione.tab}" type="button">${esc(azione.label)}</button>`
          : ''}
      </div>`;
  }).join('');
  box.querySelectorAll('[data-warn-tab]').forEach(b =>
    b.addEventListener('click', () => { _tab = b.dataset.warnTab; render(); }));
}

const STATUS_LABEL = {
  draft: 'Bozza', published: 'Aperto', running: 'In corso',
  completed: 'Concluso', cancelled: 'Annullato',
};
const statusLabel = (s) => STATUS_LABEL[s] || s;

let _console = null;

/* La console tiene due intervalli attivi: senza spegnerla continuerebbe a
   riscrivere un pannello che non esiste piu. */
function stopConsole() {
  _console?.destroy();
  _console = null;
}

function render() {
  if (_tab !== 'regia' || !_activeId) stopConsole();
  renderCrumb();
  if (_section === 'manifestazioni') return renderManifestazioni();
  if (_section === 'community') return renderTag();
  if (_section === 'negozio')   return renderNegozio();
  if (!_activeId)               return renderEventList();
  if (_tab === 'regia')         return renderRegia();
  if (_tab === 'giocatori')     return renderGiocatori();
  if (_tab === 'annunci')       return renderAnnunci();
  if (_tab === 'staff')         return renderStaff();
  if (_tab === 'risultati')     return renderRisultati();
}

/* ── REGIA ───────────────────────────────────────────────
   La stessa console di control.html, qui dentro l'evento: chi gestisce il
   torneo non deve cambiare scheda per far partire un timer. I link agli schermi
   pubblici restano fuori: in back-office ci sono gia nella briciola. */
function renderRegia() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Apri un evento dalla lista.</p>'; return; }
  if (_console?.tournamentId === String(t.id) && $('#panel').querySelector('.ctl-console')) return;
  stopConsole();
  _console = mountConsole($('#panel'), t.id, {
    screenLinks: false,
    onClosed: async () => { await loadTournaments(); render(); },
  });
}

/* ── EVENTI (livello 0) ──────────────────────────────────
   La prima cosa che vedi sono i tuoi eventi, non un form da quindici campi:
   quello sta in una modale dietro "Nuovo evento". */

function eventCard(t) {
  const posti = Math.max((t.capacity || 0) - (t.registered_players || 0), 0);
  return `
    <article class="bo-event" data-open="${t.id}">
      <div class="bo-event-main">
        <div class="tile-meta">
          <span class="type-badge type-${esc(t.event_type || 'other')}">${esc(typeLabel(t.event_type))}</span>
          <span class="pill ${t.status === 'running' ? 'ok' : 'warn'}">${esc(statusLabel(t.status))}</span>
          ${warnChip(_warnings[t.id])}
        </div>
        <div class="bo-event-name">${esc(t.name)}</div>
        <div class="tile-meta">
          <span>${fmtDate(t.starts_on)}${t.start_time ? ' · ' + esc(t.start_time) : ''}</span>
          <span>${esc(t.format)}</span>
          <span>${t.registered_players}/${t.capacity} iscritti · ${posti} posti</span>
        </div>
      </div>
      <div class="bo-event-actions row-actions">
        ${t.status === 'published' ? `<button class="mini-button" data-act="start" data-id="${t.id}" type="button">▶ Avvia</button>` : ''}
        <a class="mini-button" href="control.html?t=${t.id}" target="_blank" rel="noopener">🖥 Regia a parte</a>
        <button class="mini-button" data-act="dup" data-id="${t.id}" type="button">Duplica</button>
        ${isClosed(t) ? '' : `<button class="mini-button" data-act="close" data-id="${t.id}" type="button">Chiudi</button>`}
        ${isClosed(t) ? '' : `<button class="mini-button" data-act="del" data-id="${t.id}" type="button" style="color:var(--danger)">Elimina</button>`}
      </div>
    </article>`;
}

function renderEventList() {
  const attivi = _tournaments.filter(t => !isClosed(t));
  const conclusi = _tournaments.filter(isClosed);

  $('#panel').innerHTML = `
    <div class="bo-head">
      <h2>I tuoi eventi</h2>
      <button class="primary" id="boNew" type="button">+ Nuovo evento</button>
    </div>

    ${attivi.length
      ? `<div class="bo-event-list">${attivi.map(eventCard).join('')}</div>`
      : `<p class="empty">Nessun evento in corso. Creane uno con "Nuovo evento".</p>`}

    ${conclusi.length ? `
      <h2 class="rail-sub">Conclusi</h2>
      <p class="muted" style="margin:-6px 0 12px;font-size:.85rem">
        Restano consultabili e non si possono eliminare: sono lo storico del negozio.</p>
      <div class="bo-event-list">${conclusi.map(eventCard).join('')}</div>` : ''}`;

  $('#boNew').addEventListener('click', openNewEventDialog);
  $('#panel').querySelectorAll('[data-open]').forEach(card =>
    card.addEventListener('click', (e) => {
      // I pulsanti dentro la scheda hanno la precedenza sull'apertura.
      if (e.target.closest('[data-act], a')) return;
      openEvent(card.dataset.open);
    }));
  $('#panel').querySelectorAll('[data-act]').forEach(b =>
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      tournamentAction(b.dataset.act, b.dataset.id);
    }));
}

function openNewEventDialog() {
  const dlg = $('#newEventDialog');
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header>
        <div><span class="eyebrow">Evento</span><h2>Nuovo evento</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button>
      </header>
      <div class="bo-grid">
        <label>Nome<input id="nName" required placeholder="RCQ Modern" /></label>
        <label>Formato<input id="nFormat" value="Modern" /></label>
        <label>Tipo evento<select id="nType">
          ${EVENT_TYPES.map(t => `<option value="${t.value}">${esc(t.label)}</option>`).join('')}
        </select></label>
        <label>Livello (REL)<select id="nRel">
          ${RELS.map(r => `<option ${r === 'Competitive' ? 'selected' : ''}>${esc(r)}</option>`).join('')}
        </select></label>
        <label style="grid-column:1/-1">Luogo<input id="nVenue" placeholder="Nome e citta" /></label>
        <label>Data<input id="nDate" type="date" required /></label>
        <label>Orario inizio<input id="nTime" type="time" required value="20:00" /></label>
        <label>Capienza<input id="nCap" type="number" min="2" value="64" /></label>
        <label>Entry fee €<input id="nFee" type="number" min="0" step="0.01" value="25" /></label>
      </div>
      <details class="bo-more">
        <summary>Opzioni avanzate</summary>
        <div class="bo-grid" style="margin-top:10px">
          <label class="bo-check"><input id="nDeck" type="checkbox" checked /> Lista obbligatoria</label>
          <label class="bo-check"><input id="nAtEvent" type="checkbox" checked /> Pagamento al banco</label>
          <label class="bo-check"><input id="nStripe" type="checkbox" /> Online Stripe</label>
          <label class="bo-check"><input id="nPaypal" type="checkbox" /> Online PayPal</label>
          <label class="bo-check"><input id="nPairPub" type="checkbox" checked /> Abbinamenti pubblici</label>
          <label class="bo-check"><input id="nStandPub" type="checkbox" checked /> Classifica pubblica</label>
          <label class="bo-check"><input id="nDeckPub" type="checkbox" /> Liste pubbliche a fine torneo</label>
        </div>
      </details>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>Annulla</button>
        <button class="primary" id="nSubmit" type="button">Crea evento</button>
      </menu>
    </form>`;
  dlg.showModal();
  $('#nSubmit').addEventListener('click', createTournament);
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
    event_type: $('#nType').value,
    rules_enforcement_level: $('#nRel').value,
    venue: $('#nVenue').value.trim(),
    decklist_required: $('#nDeck').checked,
    pay_at_event: $('#nAtEvent').checked,
    pay_stripe: $('#nStripe').checked,
    pay_paypal: $('#nPaypal').checked,
    pairings_public: $('#nPairPub').checked,
    standings_public: $('#nStandPub').checked,
    decklists_public: $('#nDeckPub').checked,
  };
  if (!body.name || !body.starts_on) { toast('Nome e data obbligatori.'); return; }
  if (!body.start_time) { toast('Inserisci l\'orario di inizio.'); return; }
  // C2: almeno un metodo di pagamento dev'essere selezionato
  if (!body.pay_at_event && !body.pay_stripe && !body.pay_paypal) {
    toast('Seleziona almeno un metodo di pagamento.'); return;
  }
  try {
    const t = await apiFetch('/tournaments', { method: 'POST', body: JSON.stringify(body) });
    $('#newEventDialog').close();
    toast('Evento creato.');
    await loadTournaments();
    openEvent(t.id);   // si entra subito dentro: il passo dopo e iscrivere gente
  } catch (err) { toast('Errore: ' + err.message); }
}

async function tournamentAction(act, id) {
  const confirmMsg = act === 'del' ? 'Eliminare definitivamente il torneo e tutti i dati?' : null;
  if (confirmMsg && !window.confirm(confirmMsg)) return;
  try {
    if (act === 'start') await apiFetch(`/tournaments/${id}/start`, { method: 'POST' });
    if (act === 'close') await apiFetch(`/tournaments/${id}/close`, { method: 'POST' });
    if (act === 'del')   await apiFetch(`/tournaments/${id}`, { method: 'DELETE' });
    if (act === 'dup') {
      const t = await apiFetch(`/tournaments/${id}/duplicate`, { method: 'POST' });
      toast('Evento duplicato (data +7 giorni).');
      await loadTournaments();
      openEvent(t.id);
      return;
    }
    toast('Fatto.');
    await loadTournaments(); render();
  } catch (err) { toast('Errore: ' + err.message); }
}

/* ── ISCRITTI ────────────────────────────────────────── */

/* ── GIOCATORI ───────────────────────────────────────────
   Iscritti, liste e penalità erano tre schede sulle stesse persone: si finiva
   per rimbalzare fra loro per capire se Tizio aveva pagato, consegnato la lista
   e preso un warning. Qui è una riga sola per giocatore, con tutto sopra.

   Le azioni che richiedono spazio (walk-in, lista, penalità) stanno in modali:
   così la tabella resta leggibile anche con sessanta iscritti. */

let _players = [];          // iscrizioni, complete di tag e stato lista
let _penalties = [];        // penalità del torneo, per contarle sulla riga

const DECK_BADGE = { valid: 'ok', invalid: 'warn', submitted: 'ok', missing: '' };
const PENALTY_LABEL = {
  warning: 'Warning', game_loss: 'Game Loss', match_loss: 'Match Loss',
  disqualification: 'Squalifica', note: 'Nota',
};

async function renderGiocatori() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Apri un evento dalla lista.</p>'; return; }
  $('#panel').innerHTML = '<p class="empty">Caricamento giocatori…</p>';
  try {
    [_players, _penalties] = await Promise.all([
      fetchAllRegs(t.id),
      apiFetch(`/tournaments/${t.id}/penalties`).catch(() => []),
    ]);
  } catch (err) {
    $('#panel').innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`;
    return;
  }
  drawGiocatori(t);
}

function penaltiesOf(regId) {
  return _penalties.filter(p => String(p.registration_id) === String(regId));
}

function playerRow(r) {
  const name = r.player?.display_name || r.player_email;
  const paid = ['paid', 'confirmed'].includes(r.payment_status);
  const deck = r.decklist_status || 'missing';
  const hasDeck = deck !== 'missing';
  const pen = penaltiesOf(r.id);
  const tags = (r.tags || []).map(x =>
    `<span class="player-tag" style="color:${esc(x.color)}">${esc(x.name)}</span>`).join('');

  return `<tr data-reg="${r.id}">
    <td>
      <strong>${esc(name)}</strong>
      ${r.waitlisted ? '<span class="pill warn">attesa</span>' : ''}${r.dropped ? '<span class="pill">drop</span>' : ''}
      <br><small class="muted">${esc(r.player_email)}</small>
      ${tags ? `<br>${tags}` : ''}
    </td>
    <td>
      <span class="pill ${paid ? 'ok' : 'warn'}">${esc(r.payment_status)}</span>
      ${paid ? '' : '<br><button class="mini-button" data-act="pay" type="button">Segna pagato</button>'}
    </td>
    <td>
      <button class="mini-button" data-act="checkin" data-val="${!r.checked_in}" type="button">
        ${r.checked_in ? '✓ presente' : 'Check-in'}
      </button>
    </td>
    <td>
      <span class="pill ${DECK_BADGE[deck] || 'warn'}">${esc(deck)}</span>
      ${(() => {
        const attesi = activeT()?.decklist_formats || [''];
        if (attesi.length < 2) return '';
        const avute = new Set(r.decklist_formats || []);
        const mancanti = attesi.filter((f) => !avute.has(f)).map((f) => f || 'Costruito');
        return mancanti.length
          ? `<br><small style="color:var(--warn)">manca: ${esc(mancanti.join(', '))}</small>`
          : '<br><small style="color:var(--green)">tutti i segmenti</small>';
      })()}
      ${r.decklist_errors ? `<br><small style="color:var(--danger)">${esc(r.decklist_errors)}</small>` : ''}
      <br>${hasDeck ? '<button class="mini-button" data-act="deck-view" type="button">Vedi</button>' : ''}
      <button class="mini-button" data-act="deck-edit" type="button">${hasDeck ? 'Modifica' : 'Carica'}</button>
    </td>
    <td>
      ${pen.length ? `<span class="pill warn">${pen.length}</span>` : '<span class="muted">—</span>'}
      <br><button class="mini-button" data-act="penalty" type="button">Gestisci</button>
    </td>
    <td class="row-actions">
      <button class="mini-button" data-act="drop" data-val="${!r.dropped}" type="button">
        ${r.dropped ? 'Reintegra' : 'Drop'}
      </button>
    </td>
  </tr>`;
}

function drawGiocatori(t) {
  const rows = _players.map(playerRow).join('')
    || '<tr><td colspan="6" class="muted">Nessun iscritto: usa "Iscrivi al banco".</td></tr>';
  const conLista = _players.filter(r => (r.decklist_status || 'missing') !== 'missing').length;
  const pagati = _players.filter(r => ['paid', 'confirmed'].includes(r.payment_status)).length;
  const presenti = _players.filter(r => r.checked_in).length;

  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px">
      <div class="bo-head" style="margin-bottom:12px">
        <h3 style="margin:0">Giocatori (${_players.length})</h3>
        <button class="primary" id="gWalkIn" type="button">+ Iscrivi al banco</button>
      </div>
      <div class="profile-stats" style="margin-bottom:14px">
        <div class="profile-stat"><strong>${pagati}</strong><span>paganti</span></div>
        <div class="profile-stat"><strong>${presenti}</strong><span>presenti</span></div>
        <div class="profile-stat"><strong>${conLista}</strong><span>liste consegnate</span></div>
        <div class="profile-stat"><strong>${_penalties.length}</strong><span>penalità</span></div>
      </div>

      <details class="bo-more" style="margin-bottom:12px">
        <summary>Controlli liste — scadenza e visibilità</summary>
        <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end;margin-top:10px">
          <label>Scadenza invio liste
            <input id="ctlDeadline" type="datetime-local" value="${t.decklist_deadline ? toLocalInput(t.decklist_deadline) : ''}" />
          </label>
          <label class="bo-check">
            <input id="ctlDeckPub" type="checkbox" ${t.decklists_public ? 'checked' : ''} /> Liste pubbliche nello Storico
          </label>
          <button class="primary" id="ctlSaveControls" type="button">Salva</button>
        </div>
        <p class="muted" style="margin:8px 0 0;font-size:.85rem">
          ${t.decklist_locks_at
            ? `Le liste ${t.decklist_locked ? 'sono chiuse dal' : 'si chiudono il'} ${fmtLocal(t.decklist_locks_at)}.`
            : 'Nessuna scadenza impostata: valgono le regole di default.'}
          Senza scadenza esplicita le liste chiudono 30 minuti prima dell'orario di inizio.
        </p>
      </details>

      <input id="gFilter" placeholder="Filtra per nome, email o tag…" style="width:100%;margin-bottom:10px" />
      <table class="bo">
        <thead><tr>
          <th>Giocatore</th><th>Pagamento</th><th>Check-in</th><th>Lista</th><th>Penalità</th><th></th>
        </tr></thead>
        <tbody id="gBody">${rows}</tbody>
      </table>
    </div>`;

  $('#gWalkIn').addEventListener('click', () => openWalkInDialog(t.id));
  $('#ctlSaveControls').addEventListener('click', () => saveDecklistControls(t.id));
  $('#gFilter').addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    $('#gBody').querySelectorAll('tr').forEach(tr =>
      tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none');
  });

  $('#gBody').querySelectorAll('[data-act]').forEach(btn =>
    btn.addEventListener('click', () => {
      const regId = btn.closest('[data-reg]').dataset.reg;
      const reg = _players.find(r => String(r.id) === String(regId));
      const act = btn.dataset.act;
      if (act === 'deck-view')  return openDeckViewDialog(reg);
      if (act === 'deck-edit')  return openDeckDialog(t.id, reg);
      if (act === 'penalty')    return openPenaltyDialog(t.id, reg);
      return regAction(t.id, act, regId, btn.dataset.val);
    }));
}

/* ── Modali ──────────────────────────────────────────── */

function openWalkInDialog(tid) {
  const dlg = $('#boDialog');
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">Iscrizione</span><h2>Iscrivi al banco</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      <div class="bo-grid">
        <label>Email<input id="wEmail" type="email" required placeholder="player@email.com" /></label>
        <label>Nome<input id="wName" required placeholder="Mario Rossi" /></label>
        <label>Wizards<input id="wWiz" placeholder="##########" /></label>
        <label class="bo-check"><input id="wPaid" type="checkbox" checked /> Pagato (contanti)</label>
      </div>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>Annulla</button>
        <button class="primary" id="wSubmit" type="button">Iscrivi</button>
      </menu>
    </form>`;
  dlg.showModal();
  $('#wSubmit').addEventListener('click', async () => {
    const body = {
      email: $('#wEmail').value.trim(),
      display_name: $('#wName').value.trim(),
      wizards_account: $('#wWiz').value.trim(),
      mark_paid: $('#wPaid').checked,
    };
    if (!body.email || !body.display_name) { toast('Email e nome obbligatori.'); return; }
    try {
      await apiFetch(`/tournaments/${tid}/walk-in`, { method: 'POST', body: JSON.stringify(body) });
      dlg.close();
      toast('Iscritto.');
      await loadTournaments();   // aggiorna il conteggio sulla briciola
      renderGiocatori();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

async function openDeckViewDialog(reg) {
  const body = $('#deckViewBody');
  $('#deckViewTitle').textContent = reg.player?.display_name || reg.player_email;
  body.innerHTML = '<p class="empty">Caricamento lista…</p>';
  $('#deckViewDialog').showModal();
  await renderDeck(body, reg.decklist_raw_text, { title: reg.archetype || '' });
}

function openDeckDialog(tid, reg) {
  const dlg = $('#boDialog');
  const name = reg.player?.display_name || reg.player_email;
  // I segmenti del torneo: con uno solo la scelta non si mostra nemmeno.
  const segmenti = activeT()?.decklist_formats?.length ? activeT().decklist_formats : [''];
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">Decklist</span><h2>Lista di ${esc(name)}</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      ${segmenti.length > 1 ? `<label>Segmento<select id="duFormat">
        ${segmenti.map((f) => `<option value="${esc(f)}">${esc(f || 'Costruito')}</option>`).join('')}
      </select></label>` : ''}
      <label>Carica da file (.txt/.dec)<input id="duFile" type="file" accept=".txt,.dec,.csv,text/plain" /></label>
      <label>…oppure incolla
        <textarea id="duText" style="min-height:220px">${esc(reg.decklist_raw_text || '')}</textarea></label>
      <label>Archetipo<input id="duArch" value="${esc(reg.archetype || '')}" placeholder="Izzet Murktide…" /></label>
      <p class="muted" style="font-size:.85rem;margin:6px 0 0">
        Caricata dallo staff: non è soggetta alla scadenza che vale per i giocatori.</p>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>Annulla</button>
        <button class="primary" id="duSubmit" type="button">Salva lista</button>
      </menu>
    </form>`;
  dlg.showModal();
  $('#duFile').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (f) $('#duText').value = await f.text();
  });
  $('#duSubmit').addEventListener('click', async () => {
    const raw = $('#duText').value.trim();
    if (raw.length < 5) { toast('Incolla o carica una lista valida.'); return; }
    const btn = $('#duSubmit');
    btn.disabled = true;
    try {
      await apiFetch(`/tournaments/${tid}/registrations/${reg.id}/decklist`, {
        method: 'POST',
        body: JSON.stringify({
          raw_text: raw,
          archetype: $('#duArch').value.trim(),
          format: $('#duFormat')?.value || '',
        }),
      });
      dlg.close();
      toast('Lista salvata.');
      renderGiocatori();
    } catch (err) { toast('Errore: ' + err.message); btn.disabled = false; }
  });
}

function openPenaltyDialog(tid, reg) {
  const dlg = $('#boDialog');
  const name = reg.player?.display_name || reg.player_email;
  const storico = penaltiesOf(reg.id).map(p => `
    <tr>
      <td><span class="pill warn">${esc(PENALTY_LABEL[p.kind] || p.kind)}</span></td>
      <td>${esc(p.note || '—')}</td>
      <td><small class="muted">${new Date(p.created_at).toLocaleString('it-IT')}</small></td>
    </tr>`).join('') || '<tr><td colspan="3" class="muted">Nessuna penalità.</td></tr>';

  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">Penalità</span><h2>${esc(name)}</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      <div class="bo-grid">
        <label>Tipo<select id="pKind">
          ${Object.entries(PENALTY_LABEL).map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join('')}
        </select></label>
        <label>Nota<input id="pNote" placeholder="Slow play, deck error…" /></label>
      </div>
      <button class="primary" id="pSubmit" type="button" style="width:100%;margin-top:8px">Registra penalità</button>
      <h3 style="margin:18px 0 6px">Storico</h3>
      <table class="bo"><thead><tr><th>Tipo</th><th>Nota</th><th>Quando</th></tr></thead><tbody>${storico}</tbody></table>
      <menu><button class="secondary" value="cancel" formnovalidate>Chiudi</button></menu>
    </form>`;
  dlg.showModal();
  $('#pSubmit').addEventListener('click', async () => {
    try {
      await apiFetch(`/tournaments/${tid}/penalties`, {
        method: 'POST',
        body: JSON.stringify({ registration_id: reg.id, kind: $('#pKind').value, note: $('#pNote').value.trim() }),
      });
      toast('Penalità registrata.');
      dlg.close();
      renderGiocatori();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

async function regAction(tid, act, rid, val) {
  const on = (val === 'true' || val === true);
  const reg = _players.find(r => String(r.id) === String(rid));
  if (!reg) return;
  // Aggiornamento ottimistico: al banco il feedback dev'essere immediato.
  // Se la chiamata fallisce si torna indietro e si dice perché.
  const prev = { payment_status: reg.payment_status, checked_in: reg.checked_in, dropped: reg.dropped };
  if (act === 'pay')     reg.payment_status = 'paid';
  if (act === 'checkin') reg.checked_in = on;
  if (act === 'drop')    reg.dropped = on;
  drawGiocatori(activeT());
  try {
    if (act === 'pay')     await apiFetch(`/tournaments/${tid}/registrations/${rid}/mark-paid`, { method: 'POST' });
    if (act === 'checkin') await apiFetch(`/tournaments/${tid}/registrations/${rid}/check-in?checked_in=${on}`, { method: 'PATCH' });
    if (act === 'drop')    await apiFetch(`/tournaments/${tid}/registrations/${rid}/drop?dropped=${on}`, { method: 'PATCH' });
  } catch (err) {
    Object.assign(reg, prev);
    drawGiocatori(activeT());
    toast('Errore: ' + err.message);
  }
}


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


function toLocalInput(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}


function fmtLocal(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—'
    : d.toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}


async function saveDecklistControls(tid) {
  const raw = $('#ctlDeadline').value;
  try {
    await apiFetch(`/tournaments/${tid}/controls`, {
      method: 'PATCH',
      body: JSON.stringify({
        decklist_deadline: raw ? new Date(raw).toISOString() : null,
        decklists_public: $('#ctlDeckPub').checked,
      }),
    });
    toast('Controlli liste salvati.');
    await loadTournaments();
    render();
  } catch (err) {
    toast('Errore: ' + err.message);
  }
}

/* ── ANNUNCI ─────────────────────────────────────────────
   Un annuncio senza tag va a tutti gli iscritti. Scegliendo dei tag va a chi ne
   porta almeno uno: il conteggio si aggiorna prima di scrivere, perche mandare a
   un sottoinsieme senza sapere quanto e grande e un errore facile da fare. */
async function renderAnnunci() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Apri un evento dalla lista.</p>'; return; }
  $('#panel').innerHTML = '<p class="empty">Caricamento annunci…</p>';

  let lista = [];
  let tags = [];
  // Se i tag non arrivano si puo ancora mandare a tutti, che e il caso normale:
  // l'errore non blocca il modulo, ma va detto, non confuso con "non ci sono tag".
  let erroreTag = null;
  try {
    [lista, tags] = await Promise.all([
      apiFetch(`/tournaments/${t.id}/announcements`).then(r => r || []),
      apiFetch('/tags').then(r => r || []).catch((err) => { erroreTag = err; return []; }),
    ]);
  } catch (err) {
    $('#panel').innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`;
    return;
  }

  const inviati = lista.map(a => `
    <div class="ann-row">
      <div>
        <strong>${esc(a.title)}</strong>
        ${a.targeted
          ? `<span class="pill warn" title="Annuncio mirato">${esc(a.audience || 'mirato')}</span>`
          : '<span class="pill">tutti</span>'}
        <br><small class="muted">${esc(a.body)}</small>
      </div>
      <small class="muted">${new Date(a.created_at).toLocaleString('it-IT')}</small>
    </div>`).join('') || '<p class="muted">Nessun annuncio.</p>';

  const scelta = tags.length
    ? `<fieldset class="tag-picker" style="grid-column:1/-1">
         <legend>Destinatari</legend>
         <label class="bo-check"><input type="checkbox" id="aAll" checked /> Tutti gli iscritti</label>
         <div id="aTags" class="tag-picker-list">
           ${tags.map(tag => `
             <label class="bo-check"><input type="checkbox" class="a-tag" value="${tag.id}" disabled />
               <span class="player-tag" style="color:${esc(tag.color)}">${esc(tag.name)}</span>
               <small class="muted">${tag.player_count}</small></label>`).join('')}
         </div>
         <p class="muted" id="aCount" style="margin:6px 0 0;font-size:.82rem">&nbsp;</p>
       </fieldset>`
    : erroreTag
      ? `<p class="muted" style="grid-column:1/-1;font-size:.85rem;color:var(--danger)">
           Tag non caricati (${esc(erroreTag.message)}): per ora l'annuncio va a tutti
           gli iscritti. Ricarica la scheda per sceglierne i destinatari.</p>`
      : `<p class="muted" style="grid-column:1/-1;font-size:.85rem">
           L'annuncio va a tutti gli iscritti. Per mandarlo a un sottoinsieme, crea dei
           tag in <strong>Community</strong> e assegnali ai giocatori.</p>`;

  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px">
      <h3>Nuovo annuncio</h3>
      <form id="annForm" class="bo-grid">
        <label style="grid-column:1/-1">Titolo<input id="aTitle" required placeholder="Pausa 10 minuti" /></label>
        <label style="grid-column:1/-1">Messaggio<textarea id="aBody" required
          placeholder="Verificate i tavoli, si riprende alle 15:00"></textarea></label>
        ${scelta}
        <div class="a-email">
          <label class="bo-check"><input id="aEmail" type="checkbox" /> Invia anche via email</label>
          <small id="aEmailNote" class="muted"></small>
        </div>
        <button class="primary" type="submit" id="aSend">Invia annuncio</button>
      </form>
    </div>
    <div class="panel"><h3>Annunci inviati</h3>${inviati}</div>`;

  const caselle = () => [...$('#panel').querySelectorAll('.a-tag')];
  const scelti = () => caselle().filter(c => c.checked).map(c => Number(c.value));
  const aTutti = () => !$('#aAll') || $('#aAll').checked;

  /* Il conteggio arriva dal backend invece di essere stimato qui: e la stessa
     query che decidera i destinatari, quindi non puo divergere da cio che parte. */
  /* L'email parte solo se il server ha un SMTP e il torneo ha le notifiche
     accese. Prima la casella c'era sempre e, senza una delle due, non mandava
     niente senza dirlo. */
  function applicaEmail(stato) {
    const casella = $('#aEmail');
    const nota = $('#aEmailNote');
    casella.disabled = stato !== 'ok';
    if (casella.disabled) casella.checked = false;
    if (stato === 'no_smtp') {
      nota.textContent = 'Il server non ha un servizio email: l’annuncio arriva in pagina e come notifica, non per email.';
    } else if (stato === 'tournament_off') {
      nota.innerHTML = `Le email sono spente per questo torneo.
        <button class="mini-button" id="aEmailOn" type="button">Accendi le email del torneo</button>`;
      $('#aEmailOn').addEventListener('click', async () => {
        try {
          await apiFetch(`/tournaments/${t.id}/controls`, {
            method: 'PATCH', body: JSON.stringify({ email_notifications_enabled: true }),
          });
          // Vale per tutto il torneo, non solo per gli annunci: va detto.
          toast('Email accese: partiranno anche conferme d’iscrizione e abbinamenti.');
          aggiornaConteggio();
        } catch (err) { toast('Errore: ' + err.message); }
      });
    } else {
      nota.textContent = '';
    }
  }

  async function aggiornaConteggio() {
    const box = $('#aCount');   // assente se il negozio non ha tag
    const tagIds = aTutti() ? [] : scelti();
    if (!aTutti() && !tagIds.length) {
      if (box) box.textContent = 'Nessun tag selezionato: scegline almeno uno, o torna a "Tutti gli iscritti".';
      return;
    }
    if (box) box.textContent = 'Conteggio…';
    try {
      const qs = tagIds.map(id => `tag_ids=${id}`).join('&');
      const r = await apiFetch(`/tournaments/${t.id}/announcements/audience${qs ? '?' + qs : ''}`);
      applicaEmail(r.email_status);
      if (box) {
        box.textContent = r.recipients === r.total
          ? `Lo leggeranno tutti e ${r.total} gli iscritti.`
          : `Lo leggeranno ${r.recipients} iscritti su ${r.total}${r.label ? ` (${r.label})` : ''}.`;
      }
    } catch (err) {
      const msg = 'Conteggio non riuscito: ' + err.message;
      if (box) box.textContent = msg; else $('#aEmailNote').textContent = msg;
    }
  }

  $('#aAll')?.addEventListener('change', () => {
    caselle().forEach(c => { c.disabled = aTutti(); if (aTutti()) c.checked = false; });
    aggiornaConteggio();
  });
  caselle().forEach(c => c.addEventListener('change', aggiornaConteggio));
  aggiornaConteggio();

  $('#annForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const tagIds = aTutti() ? [] : scelti();
    if (!aTutti() && !tagIds.length) { toast('Scegli almeno un tag, o manda a tutti.'); return; }
    const invia = $('#aSend');
    invia.disabled = true;
    try {
      await apiFetch(`/tournaments/${t.id}/announcements`, { method: 'POST', body: JSON.stringify({
        title: $('#aTitle').value.trim(),
        body: $('#aBody').value.trim(),
        send_email: $('#aEmail').checked,
        tag_ids: tagIds,
      })});
      toast('Annuncio inviato.');
      renderAnnunci();
    } catch (err) { toast('Errore: ' + err.message); invia.disabled = false; }
  });
}

/* ── RISULTATI ───────────────────────────────────────────
   Classifica e report erano due schede separate sugli stessi dati. La classifica
   sta sopra: durante il torneo e quella che si guarda. */
async function renderRisultati() {
  await renderReport();
  await renderClassifica({ prepend: true });
}

/* ── CLASSIFICA ──────────────────────────────────────── */
async function renderClassifica({ prepend = false } = {}) {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Apri un evento.</p>'; return; }
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
  const html = `<div class="panel" style="margin-bottom:16px"><h3>Classifica</h3>
    <table class="bo"><thead><tr><th>#</th><th>Giocatore</th><th>Punti</th><th>V/S/P</th><th>OMW%</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  if (prepend) $('#panel').insertAdjacentHTML('afterbegin', html);
  else $('#panel').innerHTML = html;
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
      <td><button class="secondary" data-meta="${r.tournament_id}" type="button">📊 Meta</button></td>
    </tr>`).join('') || '<tr><td colspan="5" class="muted">Nessun torneo.</td></tr>';
  $('#panel').innerHTML = `
    <div class="bo-grid" style="margin-bottom:14px">
      <div class="panel" style="text-align:center"><small class="muted">Incasso totale</small><div style="font-size:1.5rem;font-weight:bold">${money(totRev)}</div></div>
      <div class="panel" style="text-align:center"><small class="muted">Presenze totali</small><div style="font-size:1.5rem;font-weight:bold">${totPlayers}</div></div>
      <div class="panel" style="text-align:center"><small class="muted">Tornei</small><div style="font-size:1.5rem;font-weight:bold">${reports.length}</div></div>
    </div>
    <div class="panel"><h3 style="display:flex;justify-content:space-between;align-items:center">Report incassi
      <button class="secondary" id="repCsv" type="button">⬇ Scarica CSV</button></h3>
      <table class="bo"><thead><tr><th>Torneo</th><th>Iscritti</th><th>Paganti</th><th>Incasso</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <div id="metaBox"></div>`;
  $('#repCsv').addEventListener('click', () => downloadReportCsv(reports));
  $('#panel').querySelectorAll('[data-meta]').forEach(btn =>
    btn.addEventListener('click', () => loadMetaStats(btn.dataset.meta)));
}

/* #41 Statistiche meta: archetipi più giocati + win rate per archetipo. */
async function loadMetaStats(tid) {
  const box = $('#metaBox');
  box.innerHTML = '<div class="panel">Carico statistiche meta…</div>';
  let stats = [];
  try { stats = (await apiFetch(`/tournaments/${tid}/meta-stats`)) || []; }
  catch (err) { box.innerHTML = `<div class="panel muted">Errore: ${esc(err.message)}</div>`; return; }
  if (!stats.length) { box.innerHTML = '<div class="panel muted">Nessun dato meta per questo torneo.</div>'; return; }
  const rows = stats.map(s => `
    <tr>
      <td><strong>${esc(s.archetype)}</strong></td>
      <td>${s.players}</td>
      <td>${s.wins}-${s.draws}-${s.losses}</td>
      <td>${s.win_rate.toFixed(1)}%</td>
    </tr>`).join('');
  box.innerHTML = `<div class="panel"><h3>Statistiche meta</h3>
    <table class="bo"><thead><tr><th>Archetipo</th><th>Giocatori</th><th>Record (W-D-L)</th><th>Win rate</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
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

/* ── NEGOZIO ─────────────────────────────────────────────
   Il profilo che i giocatori vedono su store.html. Le coordinate servono alla
   ricerca per distanza: senza, il negozio non compare in "vicino a me". */
async function renderNegozio() {
  $('#panel').innerHTML = '<p class="empty">Caricamento profilo…</p>';
  let orgs = [];
  try { orgs = await apiFetch('/organizations'); } catch (err) { toast('Errore: ' + err.message); }
  const org = orgs[0];
  if (!org) { $('#panel').innerHTML = '<p class="empty">Nessun negozio configurato.</p>'; return; }

  $('#panel').innerHTML = `<div class="panel">
    <h3>Profilo pubblico — ${esc(org.name)}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">
      Visibile su <a class="secondary-link" href="store.html?s=${esc(org.slug)}" target="_blank" rel="noopener">store.html?s=${esc(org.slug)}</a>
    </p>
    <form id="storeForm" class="bo-grid">
      <label>Nome<input id="sName" value="${esc(org.name)}" /></label>
      <label>Città<input id="sCity" value="${esc(org.city)}" /></label>
      <label style="grid-column:1/-1">Indirizzo<input id="sAddr" value="${esc(org.address)}" /></label>
      <label style="grid-column:1/-1">Descrizione
        <textarea id="sDesc" style="min-height:90px">${esc(org.description)}</textarea></label>
      <label>Sito web<input id="sSite" value="${esc(org.website)}" placeholder="https://…" /></label>
      <label>Logo (URL)<input id="sLogo" value="${esc(org.logo_url)}" placeholder="https://…" /></label>
      <label>Latitudine<input id="sLat" type="number" step="0.0001" value="${org.latitude ?? ''}" /></label>
      <label>Longitudine<input id="sLng" type="number" step="0.0001" value="${org.longitude ?? ''}" /></label>
      <div style="grid-column:1/-1;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="secondary" id="sGeocode" type="button">Trova coordinate dall'indirizzo</button>
        <span class="muted" style="font-size:.82rem">Senza coordinate il negozio non esce nella ricerca per distanza.</span>
      </div>
      <button class="primary" type="submit" style="grid-column:1/-1">Salva profilo</button>
    </form>
  </div>`;

  $('#sGeocode').addEventListener('click', async () => {
    const q = [$('#sAddr').value, $('#sCity').value].filter(Boolean).join(', ');
    if (!q) { toast('Inserisci prima indirizzo o città.'); return; }
    try {
      // Nominatim: servizio pubblico OSM, nessuna chiave. Una richiesta per clic.
      const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`);
      const [hit] = await r.json();
      if (!hit) { toast('Indirizzo non trovato.'); return; }
      $('#sLat').value = (+hit.lat).toFixed(4);
      $('#sLng').value = (+hit.lon).toFixed(4);
      toast('Coordinate trovate: controlla e salva.');
    } catch { toast('Geocoding non disponibile: inserisci le coordinate a mano.'); }
  });

  $('#storeForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const num = (id) => ($(id).value === '' ? null : +$(id).value);
    try {
      await apiFetch(`/organizations/${encodeURIComponent(org.slug)}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: $('#sName').value.trim(), city: $('#sCity').value.trim(),
          address: $('#sAddr').value.trim(), description: $('#sDesc').value.trim(),
          website: $('#sSite').value.trim(), logo_url: $('#sLogo').value.trim(),
          latitude: num('#sLat'), longitude: num('#sLng'),
        }),
      });
      toast('Profilo salvato.');
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── TAG ─────────────────────────────────────────────────
   Etichette sui giocatori del negozio, assegnabili in blocco partendo dagli
   iscritti del torneo attivo. */
async function renderTag() {
  $('#panel').innerHTML = '<p class="empty">Caricamento tag…</p>';
  let tags = [];
  try { tags = await apiFetch('/tags'); } catch (err) { toast('Errore: ' + err.message); }

  // Community e una sezione di primo livello: non eredita nessun evento attivo.
  // Da quale evento pescare i giocatori si sceglie qui, in chiaro.
  if (!_tagEventId) _tagEventId = _tournaments[0] ? String(_tournaments[0].id) : null;
  const t = _tournaments.find(x => String(x.id) === String(_tagEventId));
  let regs = [];
  if (t) { try { regs = await fetchAllRegs(t.id); } catch { regs = []; } }

  const tagRows = tags.map(tag => `
    <tr>
      <td><span class="player-tag" style="color:${esc(tag.color)}">${esc(tag.name)}</span></td>
      <td class="muted">${esc(tag.description || '—')}</td>
      <td>${tag.player_count}</td>
      <td class="row-actions">
        <button class="mini-button" data-drop-tag="${tag.id}" type="button" style="color:var(--danger,#ef6a5e)">Elimina</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="4" class="muted">Nessun tag: creane uno qui sotto.</td></tr>';

  const regRows = regs.map(r => `
    <tr>
      <td><label style="display:flex;align-items:center;gap:6px">
        <input type="checkbox" data-player="${r.player_id}" /> ${esc(r.player?.display_name || r.player_email)}
      </label></td>
      <td>${(r.tags || []).map(x => `<span class="player-tag" style="color:${esc(x.color)}">${esc(x.name)}</span>`).join('') || '<span class="muted">—</span>'}</td>
    </tr>`).join('') || '<tr><td colspan="2" class="muted">Nessun iscritto nel torneo attivo.</td></tr>';

  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px">
      <h3>Tag del negozio</h3>
      <table class="bo"><thead><tr><th>Tag</th><th>Descrizione</th><th>Giocatori</th><th></th></tr></thead>
        <tbody>${tagRows}</tbody></table>
      <form id="newTag" class="bo-grid" style="margin-top:12px">
        <label>Nome<input id="tgName" required maxlength="60" placeholder="Habitué" /></label>
        <label>Colore<input id="tgColor" type="color" value="#c6ff3d" /></label>
        <label style="grid-column:1/-1">Descrizione<input id="tgDesc" maxlength="240" placeholder="A cosa serve questo tag" /></label>
        <button class="primary" type="submit" style="grid-column:1/-1">Crea tag</button>
      </form>
    </div>

    <div class="panel">
      <h3>Assegna agli iscritti</h3>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
        <label style="display:flex;align-items:center;gap:6px">Giocatori di
          <select id="tgEvent">${_tournaments.map(x =>
            `<option value="${x.id}" ${String(x.id) === String(_tagEventId) ? 'selected' : ''}>${esc(x.name)}</option>`).join('')
            || '<option value="">— nessun evento —</option>'}</select>
        </label>
        <select id="tgPick">${tags.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select>
        <button class="primary" id="tgAssign" type="button" ${tags.length ? '' : 'disabled'}>Assegna ai selezionati</button>
        <button class="secondary" id="tgAll" type="button">Seleziona tutti</button>
      </div>
      <table class="bo"><thead><tr><th>Giocatore</th><th>Tag</th></tr></thead><tbody>${regRows}</tbody></table>
    </div>`;

  $('#newTag').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch('/tags', { method: 'POST', body: JSON.stringify({
        name: $('#tgName').value.trim(), color: $('#tgColor').value,
        description: $('#tgDesc').value.trim(),
      })});
      toast('Tag creato.');
      renderTag();
    } catch (err) { toast('Errore: ' + err.message); }
  });

  $('#panel').querySelectorAll('[data-drop-tag]').forEach(btn =>
    btn.addEventListener('click', async () => {
      if (!window.confirm('Eliminare il tag? Sparisce da tutti i giocatori.')) return;
      try {
        await apiFetch(`/tags/${btn.dataset.dropTag}`, { method: 'DELETE' });
        toast('Tag eliminato.');
        renderTag();
      } catch (err) { toast('Errore: ' + err.message); }
    }));

  $('#tgEvent')?.addEventListener('change', (e) => { _tagEventId = e.target.value; renderTag(); });

  $('#tgAll')?.addEventListener('click', () => {
    const boxes = $('#panel').querySelectorAll('[data-player]');
    const turnOn = [...boxes].some(b => !b.checked);
    boxes.forEach(b => { b.checked = turnOn; });
  });

  $('#tgAssign')?.addEventListener('click', async () => {
    const ids = [...$('#panel').querySelectorAll('[data-player]:checked')].map(b => +b.dataset.player);
    if (!ids.length) { toast('Seleziona almeno un giocatore.'); return; }
    try {
      await apiFetch(`/tags/${$('#tgPick').value}/players`, {
        method: 'POST', body: JSON.stringify({ user_ids: ids }),
      });
      toast(`Tag assegnato a ${ids.length} giocatori.`);
      renderTag();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── MANIFESTAZIONI ──────────────────────────────────────
   Il contenitore di piu tornei che si svolgono insieme: un weekend con main
   event e side event. Si chiama cosi in interfaccia perche "Eventi", qui in
   back-office, sono gia i singoli tornei; nel modello resta `Event`.

   Il motivo per cui esiste: lo staff si nomina una volta sola e vale su tutte
   le tappe. */

let _events = [];
let _openEventId = null;

async function renderManifestazioni() {
  if (_openEventId) return renderManifestazione(_openEventId);
  $('#panel').innerHTML = '<p class="empty">Caricamento…</p>';
  try { _events = await apiFetch('/events/mine') || []; }
  catch (err) { $('#panel').innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`; return; }

  const card = (e) => `
    <article class="bo-event" data-open-event="${e.id}">
      <div class="bo-event-main">
        <div class="tile-meta">
          <span class="pill ${e.is_public ? 'ok' : 'warn'}">${e.is_public ? 'pubblica' : 'privata'}</span>
          ${warnChip(e.warnings)}
        </div>
        <div class="bo-event-name">${esc(e.name)}</div>
        <div class="tile-meta">
          <span>${fmtDate(e.starts_on)}${e.ends_on ? ' → ' + fmtDate(e.ends_on) : ''}</span>
          ${e.venue ? `<span>${esc(e.venue)}</span>` : ''}
          <span>${e.tournament_count} tappe</span>
        </div>
      </div>
    </article>`;

  $('#panel').innerHTML = `
    <div class="bo-head">
      <h2>Manifestazioni</h2>
      <button class="primary" id="evNew" type="button">+ Nuova manifestazione</button>
    </div>
    <p class="muted" style="margin:-8px 0 16px;max-width:64ch">
      Raggruppa piu tornei che si svolgono insieme. Chi nomini capojudge qui lo e
      su tutte le tappe, senza rinominarlo torneo per torneo.
    </p>
    ${_events.length
      ? `<div class="bo-event-list">${_events.map(card).join('')}</div>`
      : '<p class="empty">Nessuna manifestazione. Creane una per raggruppare i tornei di un weekend.</p>'}`;

  $('#evNew').addEventListener('click', openManifestazioneDialog);
  $('#panel').querySelectorAll('[data-open-event]').forEach((c) =>
    c.addEventListener('click', () => { _openEventId = c.dataset.openEvent; render(); }));
}

function openManifestazioneDialog() {
  const dlg = $('#boDialog');
  const oggi = new Date().toISOString().slice(0, 10);
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">Manifestazione</span><h2>Nuova manifestazione</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      <div class="bo-grid">
        <label style="grid-column:1/-1">Nome<input id="evName" required placeholder="Weekend di primavera" /></label>
        <label>Dal<input id="evFrom" type="date" required value="${oggi}" /></label>
        <label>Al<input id="evTo" type="date" /></label>
        <label style="grid-column:1/-1">Luogo<input id="evVenue" placeholder="Nome e citta" /></label>
        <label style="grid-column:1/-1">Descrizione<textarea id="evDesc" style="min-height:70px"></textarea></label>
        <label class="bo-check"><input id="evPub" type="checkbox" checked /> Pagina pubblica</label>
      </div>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>Annulla</button>
        <button class="primary" id="evSave" type="button">Crea</button>
      </menu>
    </form>`;
  dlg.showModal();
  $('#evSave').addEventListener('click', async () => {
    const body = {
      name: $('#evName').value.trim(),
      starts_on: $('#evFrom').value,
      ends_on: $('#evTo').value || null,
      venue: $('#evVenue').value.trim(),
      description: $('#evDesc').value.trim(),
      is_public: $('#evPub').checked,
    };
    if (!body.name || !body.starts_on) { toast('Nome e data di inizio obbligatori.'); return; }
    try {
      const created = await apiFetch('/events', { method: 'POST', body: JSON.stringify(body) });
      dlg.close();
      toast('Manifestazione creata.');
      _openEventId = String(created.id);   // si entra subito: il passo dopo e aggiungere tappe
      render();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── Dentro una manifestazione ───────────────────────── */

async function renderManifestazione(eventId) {
  $('#panel').innerHTML = '<p class="empty">Caricamento…</p>';
  let staff = [];
  try {
    if (!_events.length) _events = await apiFetch('/events/mine') || [];
    staff = await apiFetch(`/events/${eventId}/staff`) || [];
  } catch (err) { toast('Errore: ' + err.message); }

  const ev = _events.find((e) => String(e.id) === String(eventId));
  if (!ev) { _openEventId = null; return renderManifestazioni(); }

  const avvisi = ev.warnings || [];
  const fuoriPeriodo = new Set(avvisi
    .filter(w => w.code === 'stage_outside_period')
    .map(w => String(w.tournament_id)));

  // Le tappe si scelgono fra i propri tornei: quelli gia dentro e quelli liberi.
  const dentro = _tournaments.filter((t) => t.event_slug === ev.slug);
  const fuori = _tournaments.filter((t) => !t.event_slug);

  const tappa = (t, inside) => `
    <tr>
      <td><strong>${esc(t.name)}</strong><br><small class="muted">${esc(t.format)} · ${fmtDate(t.starts_on)}</small>
        ${inside && fuoriPeriodo.has(String(t.id))
          ? '<span class="pill warn" title="La data cade fuori dal periodo della manifestazione">fuori periodo</span>'
          : ''}</td>
      <td><span class="pill ${t.status === 'running' ? 'ok' : 'warn'}">${esc(statusLabel(t.status))}</span></td>
      <td class="row-actions">
        <button class="mini-button" data-${inside ? 'detach' : 'attach'}="${t.id}" type="button">
          ${inside ? 'Togli' : 'Aggiungi'}
        </button>
      </td>
    </tr>`;

  const staffRows = staff.map((m) => `
    <tr>
      <td><strong>${esc(m.display_name)}</strong><br><small class="muted">${esc(m.email)}</small></td>
      <td><span class="pill ${m.role === 'head_judge' ? 'ok' : ''}">${m.role === 'head_judge' ? 'capojudge' : 'judge'}</span></td>
      <td class="row-actions">
        <button class="mini-button" data-drop-staff="${m.id}" type="button" style="color:var(--danger)">Rimuovi</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="3" class="muted">Nessuno: nomina qui il capojudge del weekend.</td></tr>';

  $('#panel').innerHTML = `
    <div class="bo-crumb">
      <button class="bo-back" id="evBack" type="button">← Manifestazioni</button>
      <div class="bo-crumb-title">
        <strong>${esc(ev.name)}</strong>
        <span class="muted">${fmtDate(ev.starts_on)}${ev.ends_on ? ' → ' + fmtDate(ev.ends_on) : ''}
          · ${ev.tournament_count} tappe
          <span class="pill ${ev.is_public ? 'ok' : 'warn'}">${ev.is_public ? 'pubblica' : 'privata'}</span></span>
      </div>
      <div class="bo-crumb-actions">
        ${ev.is_public ? `<a class="mini-button" href="event-page.html?e=${esc(ev.slug)}" target="_blank" rel="noopener">↗ Pagina pubblica</a>` : ''}
      </div>
    </div>

    ${avvisi.length ? `
      <div class="bo-warnings" style="margin-bottom:16px">
        ${avvisi.map(w => `
          <div class="bo-warning ${w.level === 'warn' ? 'warn' : 'info'}">
            <span class="bo-warning-icon" aria-hidden="true">${w.level === 'warn' ? '⚠' : 'ℹ'}</span>
            <span class="bo-warning-text">${esc(w.message)}</span>
          </div>`).join('')}
      </div>` : ''}

    <div class="panel" style="margin-bottom:16px">
      <h3>Tappe (${dentro.length})</h3>
      <table class="bo"><thead><tr><th>Torneo</th><th>Stato</th><th></th></tr></thead>
        <tbody>${dentro.map((t) => tappa(t, true)).join('')
          || '<tr><td colspan="3" class="muted">Nessuna tappa.</td></tr>'}</tbody></table>
      ${fuori.length ? `
        <h4 style="margin:16px 0 6px;font-size:.9rem">Tornei liberi</h4>
        <table class="bo"><tbody>${fuori.map((t) => tappa(t, false)).join('')}</tbody></table>` : ''}
    </div>

    <div class="panel" style="margin-bottom:16px">
      <h3>Staff della manifestazione</h3>
      <p class="muted" style="margin-top:0;font-size:.85rem">
        Vale su tutte le tappe. Se qualcuno ha anche un incarico su un singolo
        torneo, conta il piu alto dei due.</p>
      <table class="bo"><thead><tr><th>Persona</th><th>Ruolo</th><th></th></tr></thead>
        <tbody>${staffRows}</tbody></table>
      <form id="evStaffForm" class="bo-grid" style="margin-top:12px">
        <label>Email<input id="evStaffEmail" type="email" required placeholder="judge@email.com" /></label>
        <label>Ruolo<select id="evStaffRole">
          <option value="judge">Judge</option>
          <option value="head_judge">Capojudge</option>
        </select></label>
        <button class="primary" type="submit">Nomina</button>
      </form>
    </div>

    <div class="panel">
      <h3>Anagrafica</h3>
      <form id="evEditForm" class="bo-grid">
        <label style="grid-column:1/-1">Nome<input id="evEName" value="${esc(ev.name)}" /></label>
        <label>Dal<input id="evEFrom" type="date" value="${esc(String(ev.starts_on).slice(0, 10))}" /></label>
        <label>Al<input id="evETo" type="date" value="${ev.ends_on ? esc(String(ev.ends_on).slice(0, 10)) : ''}" /></label>
        <label style="grid-column:1/-1">Luogo<input id="evEVenue" value="${esc(ev.venue)}" /></label>
        <label style="grid-column:1/-1">Descrizione<textarea id="evEDesc" style="min-height:70px">${esc(ev.description)}</textarea></label>
        <label class="bo-check"><input id="evEPub" type="checkbox" ${ev.is_public ? 'checked' : ''} /> Pagina pubblica</label>
        <button class="primary" type="submit" style="grid-column:1/-1">Salva</button>
      </form>
    </div>`;

  const reload = async () => {
    _events = await apiFetch('/events/mine') || [];
    await loadTournaments();
    render();
  };

  $('#evBack').addEventListener('click', () => { _openEventId = null; render(); });

  $('#panel').querySelectorAll('[data-attach]').forEach((b) =>
    b.addEventListener('click', async () => {
      try {
        const r = await apiFetch(`/events/${eventId}/tournaments/${b.dataset.attach}`, { method: 'POST' });
        const fuori = (r?.warnings || []).some(w =>
          w.code === 'stage_outside_period' && String(w.tournament_id) === b.dataset.attach);
        toast(fuori ? 'Tappa aggiunta, ma cade fuori dal periodo della manifestazione.' : 'Tappa aggiunta.');
        await reload();
      } catch (err) { toast('Errore: ' + err.message); }
    }));
  $('#panel').querySelectorAll('[data-detach]').forEach((b) =>
    b.addEventListener('click', async () => {
      try {
        await apiFetch(`/events/${eventId}/tournaments/${b.dataset.detach}`, { method: 'DELETE' });
        toast('Tappa tolta.');
        await reload();
      } catch (err) { toast('Errore: ' + err.message); }
    }));
  $('#panel').querySelectorAll('[data-drop-staff]').forEach((b) =>
    b.addEventListener('click', async () => {
      try {
        await apiFetch(`/events/${eventId}/staff/${b.dataset.dropStaff}`, { method: 'DELETE' });
        toast('Rimosso.');
        render();
      } catch (err) { toast('Errore: ' + err.message); }
    }));

  $('#evStaffForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch(`/events/${eventId}/staff`, { method: 'POST', body: JSON.stringify({
        email: $('#evStaffEmail').value.trim(), role: $('#evStaffRole').value,
      })});
      toast('Nominato.');
      render();
    } catch (err) { toast('Errore: ' + err.message); }
  });

  $('#evEditForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch(`/events/${eventId}`, { method: 'PATCH', body: JSON.stringify({
        name: $('#evEName').value.trim(),
        starts_on: $('#evEFrom').value,
        ends_on: $('#evETo').value || null,
        venue: $('#evEVenue').value.trim(),
        description: $('#evEDesc').value.trim(),
        is_public: $('#evEPub').checked,
      })});
      toast('Salvato.');
      await reload();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── STAFF DEL TORNEO ────────────────────────────────────
   La catena di comando di una singola tappa: l'organizzatore nomina il
   capojudge, il capojudge nomina i judge sotto di lui. Chi ha un incarico
   sulla manifestazione ce l'ha gia qui e non va rinominato.

   Il backend e testato dalla prima iterazione; fino a ora si governava solo
   via API. */

async function renderStaff() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Apri un evento dalla lista.</p>'; return; }
  $('#panel').innerHTML = '<p class="empty">Caricamento staff…</p>';

  let membri = [];
  let ruolo = 'none';
  try {
    [membri, ruolo] = await Promise.all([
      apiFetch(`/tournaments/${t.id}/staff`),
      apiFetch(`/tournaments/${t.id}/my-role`).then((r) => r?.role || 'none'),
    ]);
  } catch (err) {
    $('#panel').innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`;
    return;
  }

  // Promuovere e degradare spetta al solo organizzatore: il capojudge non si
  // sceglie un successore. Nominare judge invece lo fa anche lui.
  const sonoOrganizzatore = ruolo === 'organizer';
  const possoNominare = ['organizer', 'head_judge'].includes(ruolo);
  const ceGiaUnCapo = membri.some((m) => m.role === 'head_judge');

  const righe = membri.map((m) => `
    <tr>
      <td><strong>${esc(m.display_name)}</strong><br><small class="muted">${esc(m.email)}</small></td>
      <td><span class="pill ${m.role === 'head_judge' ? 'ok' : ''}">
        ${m.role === 'head_judge' ? 'capojudge' : 'judge'}</span></td>
      <td class="row-actions">
        ${sonoOrganizzatore ? `<button class="mini-button" data-promote="${m.id}"
          data-to="${m.role === 'head_judge' ? 'judge' : 'head_judge'}" type="button">
          ${m.role === 'head_judge' ? 'Degrada a judge' : 'Promuovi a capojudge'}</button>` : ''}
        ${(sonoOrganizzatore || m.role !== 'head_judge')
          ? `<button class="mini-button" data-drop="${m.id}" type="button" style="color:var(--danger)">Rimuovi</button>`
          : ''}
      </td>
    </tr>`).join('') || '<tr><td colspan="3" class="muted">Nessuno nello staff di questa tappa.</td></tr>';

  const avviso = sonoOrganizzatore && ceGiaUnCapo
    ? '<p class="muted" style="margin:8px 0 0;font-size:.82rem">Di capojudge ne vale uno: degrada o rimuovi quello attuale prima di nominarne un altro.</p>'
    : '';

  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px">
      <h3>Staff della tappa</h3>
      <p class="muted" style="margin-top:0;font-size:.85rem">
        L'organizzatore nomina il capojudge, uno solo per torneo; il capojudge nomina
        i judge. Chi ha un incarico sulla manifestazione lo ha gia qui e non compare
        in questo elenco.</p>
      <table class="bo"><thead><tr><th>Persona</th><th>Ruolo</th><th></th></tr></thead>
        <tbody>${righe}</tbody></table>

      ${possoNominare ? `
        <form id="stForm" class="bo-grid" style="margin-top:12px">
          <label>Email<input id="stEmail" type="email" required placeholder="judge@email.com" /></label>
          <label>Ruolo<select id="stRole">
            <option value="judge">Judge</option>
            ${sonoOrganizzatore && !ceGiaUnCapo ? '<option value="head_judge">Capojudge</option>' : ''}
          </select></label>
          <button class="primary" type="submit">Nomina</button>
        </form>${avviso}`
        : '<p class="muted" style="margin-top:12px;font-size:.85rem">Solo organizzatore e capojudge nominano staff.</p>'}
    </div>`;

  $('#stForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch(`/tournaments/${t.id}/staff`, { method: 'POST', body: JSON.stringify({
        email: $('#stEmail').value.trim(), role: $('#stRole').value,
      })});
      toast('Nominato.');
      render();
    } catch (err) { toast('Errore: ' + err.message); }
  });

  $('#panel').querySelectorAll('[data-promote]').forEach((b) =>
    b.addEventListener('click', async () => {
      try {
        await apiFetch(`/tournaments/${t.id}/staff/${b.dataset.promote}`, {
          method: 'PATCH', body: JSON.stringify({ role: b.dataset.to }),
        });
        toast('Ruolo aggiornato.');
        render();
      } catch (err) { toast('Errore: ' + err.message); }
    }));

  $('#panel').querySelectorAll('[data-drop]').forEach((b) =>
    b.addEventListener('click', async () => {
      try {
        await apiFetch(`/tournaments/${t.id}/staff/${b.dataset.drop}`, { method: 'DELETE' });
        toast('Rimosso.');
        render();
      } catch (err) { toast('Errore: ' + err.message); }
    }));
}
