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
import { bestOfLabel, gameInfo, gameLabel, loadGames, tiebreakerColumns } from './games.js';
import { t as tr } from './i18n.js';

const API       = '/api';
const TOKEN_KEY = 'mull2five-jwt-v1';
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
    const err = new Error(detail || r.statusText);
    err.status = r.status;
    throw err;
  }
  return r.status === 204 ? null : r.json();
}

const $   = (s) => document.querySelector(s);
const money = (c, cur = 'EUR') => ((c || 0) / 100).toLocaleString('it-IT', { style: 'currency', currency: cur });
const fmtDate = (d) => d ? d.substring(0, 10).split('-').reverse().join('/') : '—';
function toast(m) { const e = $('#toast'); e.textContent = m; e.classList.add('show'); clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove('show'), 3000); }

let _section = 'eventi';     // eventi | community | negozio
let _myStores = new Set();   // slug dei negozi di cui si fa parte
let _suspendSlug = null;     // il negozio del torneo aperto, se lo si gestisce: da lì si sospende
let _byesEditable = false;   // i bye si assegnano prima dell'inizio, e solo se ci sono turni
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
  { id: 'impostazioni', label: 'Impostazioni' },
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
  const [tornei, avvisi, negozi] = await Promise.all([
    apiFetch('/tournaments/mine').catch(() => []),
    // Solo chi organizza ha avvisi: a un judge l'endpoint dice di no, ed e giusto.
    apiFetch('/tournaments/warnings/mine').catch(() => ({})),
    apiFetch('/organizations/memberships').catch(() => []),
  ]);
  _myStores = new Set((negozi || []).map((s) => s.slug));
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
const registrationOnly = (t) => t?.structure === 'registration_only';

/* Senza turni la regia e i risultati non hanno niente da mostrare. */
const tabsFor = (t) => (registrationOnly(t)
  ? EVENT_TABS.filter((x) => !['regia', 'risultati'].includes(x.id))
  : EVENT_TABS);

function openEvent(id, tab = null) {
  const t = _tournaments.find(x => String(x.id) === String(id));
  tab = tab || (t?.status === 'running' && !registrationOnly(t) ? 'regia' : 'giocatori');
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
      ${registrationOnly(t) ? '' : `<a class="mini-button" href="control.html?t=${t.id}" target="_blank" rel="noopener"
         title="Apre la stessa console a tutto schermo: per un secondo monitor o per i judge">🖥 Regia a parte</a>
      <a class="mini-button" href="display.html?t=${t.id}" target="_blank" rel="noopener">📺 Display</a>`}
      <a class="mini-button" href="event.html?id=${t.id}" target="_blank" rel="noopener">↗ Pagina pubblica</a>
      ${isClosed(t) ? `<a class="mini-button" href="coverage.html?t=${t.id}" target="_blank" rel="noopener">🖼 Scheda social</a>` : ''}
    </div>`;
  $('#boBack').addEventListener('click', closeEvent);

  tabs.style.display = '';
  if (!tabsFor(t).some((x) => x.id === _tab)) _tab = 'giocatori';
  tabs.innerHTML = tabsFor(t).map(x =>
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
  suspended_players:             { tab: 'giocatori', label: 'Apri Giocatori' },
  missing_decklists:             { tab: 'annunci',   label: 'Manda un annuncio' },
  decklist_deadline_after_start: { tab: 'giocatori', label: 'Apri Giocatori' },
};

async function renderWarnings(t) {
  const box = $('#boWarnings');
  // Gli avvisi sono di chi organizza: un judge nel back-office non li vede.
  if (!t || isClosed(t) || !t.can_manage) {
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
  if (_tab === 'impostazioni')  return renderImpostazioni();
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

/** Quale della serie è: "Serie 3/8", contando le date dei tornei che si vedono. */
function seriesInfo(t) {
  if (!t.series_id) return null;
  const serie = _tournaments.filter((x) => x.series_id === t.series_id)
    .sort((a, b) => String(a.starts_on).localeCompare(String(b.starts_on)));
  return { position: serie.findIndex((x) => x.id === t.id) + 1, total: serie.length };
}

/** I tornei della serie dopo questo, non ancora iniziati: le modifiche possono andare anche a loro. */
function followingInSeries(t) {
  if (!t.series_id) return [];
  return _tournaments.filter((x) => x.series_id === t.series_id && x.id !== t.id
    && String(x.starts_on) > String(t.starts_on) && ['draft', 'published'].includes(x.status));
}

function eventCard(t) {
  const posti = Math.max((t.capacity || 0) - (t.registered_players || 0), 0);
  const serie = seriesInfo(t);
  return `
    <article class="bo-event" data-open="${t.id}">
      <div class="bo-event-main">
        <div class="tile-meta">
          <span class="type-badge type-${esc(t.event_type || 'other')}">${esc(typeLabel(t.event_type))}</span>
          <span class="game-badge game-${esc(t.game || 'mtg')}">${esc(gameLabel(t.game))}</span>
          <span class="pill ${t.status === 'running' ? 'ok' : 'warn'}">${esc(statusLabel(t.status))}</span>
          ${warnChip(_warnings[t.id])}
          ${serie ? `<span class="pill">${esc(tr('Serie {n}/{tot}', { n: serie.position, tot: serie.total }))}</span>` : ''}
        </div>
        <div class="bo-event-name">${esc(t.name)}</div>
        <div class="tile-meta">
          <span>${fmtDate(t.starts_on)}${t.start_time ? ' · ' + esc(t.start_time) : ''}</span>
          <span>${esc(t.format)}</span>
          <span>${t.registered_players}/${t.capacity} iscritti · ${posti} posti</span>
        </div>
      </div>
      <div class="bo-event-actions row-actions">
        ${t.status === 'published' && !registrationOnly(t) ? `<button class="mini-button" data-act="start" data-id="${t.id}" type="button">▶ Avvia</button>` : ''}
        ${registrationOnly(t) ? '' : `<a class="mini-button" href="control.html?t=${t.id}" target="_blank" rel="noopener">🖥 Regia a parte</a>`}
        <button class="mini-button" data-act="edit" data-id="${t.id}" type="button">✏ ${esc(tr('Modifica'))}</button>
        <button class="mini-button" data-act="dup" data-id="${t.id}" type="button">Duplica</button>
        <button class="mini-button" data-act="repeat" data-id="${t.id}" type="button">${esc(tr('Ripeti…'))}</button>
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
        <label id="nGameWrap">${esc(tr('Gioco'))}<select id="nGame"></select></label>
        <label>Formato<input id="nFormat" value="Modern" list="nFormatList" autocomplete="off" />
          <datalist id="nFormatList"></datalist></label>
        <label>Tipo evento<select id="nType">
          ${EVENT_TYPES.map(t => `<option value="${t.value}">${esc(t.label)}</option>`).join('')}
        </select></label>
        <label>Livello (REL)<select id="nRel">
          ${RELS.map(r => `<option ${r === 'Competitive' ? 'selected' : ''}>${esc(r)}</option>`).join('')}
        </select></label>
        <label style="grid-column:1/-1;display:none" id="nLocationWrap">${esc(tr('Sede'))}<select id="nLocation"></select></label>
        <label style="grid-column:1/-1" id="nVenueWrap">Luogo<input id="nVenue" placeholder="Nome e citta" /></label>
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
          <label>${esc(tr('Match in svizzera'))}<select id="nBestOf">
            ${[1, 2, 3].map((n) => `<option value="${n}">${esc(bestOfLabel(n))}</option>`).join('')}
          </select></label>
          <label class="bo-check"><input id="nIds" type="checkbox" checked /> ${esc(tr('Patte intenzionali'))}</label>
          <label>${esc(tr('Formula'))}<select id="nTeam">${[1, 2, 3].map((n) => `<option value="${n}"${n === 1 ? ' selected' : ''}>${esc(n === 1 ? tr('Individuale') : tr('Squadre da {n}', { n }))}</option>`).join('')}</select></label>
          <label class="bo-check" style="grid-column:1/-1"><input id="nRegOnly" type="checkbox" /> ${esc(tr('Solo iscrizioni: niente turni né classifica (serata casual, draft tra amici, presentazione)'))}</label>
        </div>
      </details>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>Annulla</button>
        <button class="primary" id="nSubmit" type="button">Crea evento</button>
      </menu>
    </form>`;
  dlg.showModal();
  $('#nSubmit').addEventListener('click', createTournament);
  fillGameChoices();
  fillLocationChoices('#nLocation', '#nLocationWrap', '#nVenueWrap', null);
}

/* ── Sedi ─────────────────────────────────────────────────
   Il negozio di chi è collegato e i posti dove gioca. Il torneo sceglie una
   sede e ne eredita indirizzo e coordinate; "Altro luogo" lascia scrivere a mano. */
let _myStore = null;
function myStore() {
  _myStore ??= apiFetch('/organizations/mine').catch((err) => { _myStore = null; throw err; });
  return _myStore;
}

async function myLocations() {
  const store = await myStore();
  return apiFetch(`/organizations/${encodeURIComponent(store.slug)}/locations`);
}

async function fillLocationChoices(selectSel, wrapSel, venueWrapSel, current) {
  let locations = [];
  try { locations = await myLocations(); } catch { return; }
  const select = $(selectSel);
  if (!select || !locations.length) return;   // nessuna sede: resta solo il luogo scritto
  select.innerHTML = `<option value="">${esc(tr('Altro luogo (scrivilo sotto)'))}</option>`
    + locations.map((loc) => `<option value="${loc.id}"${loc.id === current ? ' selected' : ''}>${esc(loc.label)}</option>`).join('');
  // Un negozio con una sola sede la propone già scelta per i tornei nuovi.
  if (current === null && locations.length === 1) select.value = String(locations[0].id);
  $(wrapSel).style.display = '';
  const sync = () => { $(venueWrapSel).style.display = select.value ? 'none' : ''; };
  select.addEventListener('change', sync);
  sync();
}

/* Coordinate da un indirizzo. Nominatim: servizio pubblico OSM, nessuna chiave;
   una richiesta per clic, come chiedono le sue regole d'uso. */
async function geocode(query) {
  const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(query)}`);
  const [hit] = await r.json();
  return hit ? { lat: (+hit.lat).toFixed(4), lng: (+hit.lon).toFixed(4) } : null;
}

/* Scegliere il gioco cambia l'elenco dei formati proposti e il formato dei match
   di partenza: One Piece si gioca al meglio di 1, gli altri di 3. */
async function fillGameChoices() {
  const games = await loadGames();
  const select = $('#nGame');
  if (!select || !games.length) return;
  select.innerHTML = games.map((g) => `<option value="${esc(g.code)}">${esc(g.name)}</option>`).join('');
  // Con un gioco solo acceso non c'è niente da scegliere.
  $('#nGameWrap').style.display = games.length > 1 ? '' : 'none';
  const apply = () => {
    const game = games.find((g) => g.code === select.value) || games[0];
    $('#nFormatList').innerHTML = game.formats.map((f) => `<option value="${esc(f)}"></option>`).join('');
    if (!game.formats.includes($('#nFormat').value)) $('#nFormat').value = game.formats[0];
    $('#nBestOf').value = String(game.default_best_of);
  };
  select.addEventListener('change', apply);
  apply();
}

async function createTournament(e) {
  e.preventDefault();
  const body = {
    name: $('#nName').value.trim(),
    format: $('#nFormat').value.trim() || 'Modern',
    game: $('#nGame').value || 'mtg',
    best_of: +$('#nBestOf').value || null,
    allow_intentional_draws: $('#nIds').checked,
    ...($('#nRegOnly').checked ? { structure: 'registration_only' } : {}),
    team_size: +$('#nTeam').value || 1,
    starts_on: $('#nDate').value,
    start_time: $('#nTime').value || null,
    capacity: +$('#nCap').value || 8,
    entry_fee_cents: Math.round((+$('#nFee').value || 0) * 100),
    currency: 'EUR',
    status: 'published',
    event_type: $('#nType').value,
    rules_enforcement_level: $('#nRel').value,
    // Con una sede scelta il luogo viene da lì: niente testo che lo copra.
    location_id: +$('#nLocation').value || null,
    venue: $('#nLocation').value ? '' : $('#nVenue').value.trim(),
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
  if (act === 'repeat') return openRepeatDialog(id);
  if (act === 'edit') return openEvent(id, 'impostazioni');
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

/* ── SERIE ──────────────────────────────────────────────
   Ripetere un torneo crea un torneo per data, con le stesse impostazioni.
   Prima di confermare si vedono le date: niente sorprese a fine mese. */
const FREQUENCIES = [
  { value: 'weekly', label: 'Ogni settimana' },
  { value: 'biweekly', label: 'Ogni due settimane' },
  { value: 'monthly', label: 'Ogni mese, stesso giorno della settimana' },
];

function openRepeatDialog(id) {
  const src = _tournaments.find((x) => String(x.id) === String(id));
  const dlg = $('#boDialog');
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">${esc(tr('Serie'))}</span><h2>${esc(tr('Ripeti {nome}', { nome: src?.name || '' }))}</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      <div class="bo-grid">
        <label style="grid-column:1/-1">${esc(tr('Quanto spesso'))}<select id="rpFreq">
          ${FREQUENCIES.map((f) => `<option value="${f.value}">${esc(tr(f.label))}</option>`).join('')}</select></label>
        <label>${esc(tr('Quante volte'))}<input id="rpCount" type="number" min="1" max="52" value="4" /></label>
        <label>${esc(tr('Oppure fino al'))}<input id="rpUntil" type="date" /></label>
      </div>
      <div id="rpPreview" class="muted" style="margin-top:10px;font-size:.88rem"></div>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>${esc(tr('Annulla'))}</button>
        <button class="primary" id="rpSubmit" type="button">${esc(tr('Crea i tornei'))}</button>
      </menu>
    </form>`;
  dlg.showModal();

  // Una data di fine vince sul numero: sono due modi di dire la stessa cosa.
  const body = () => ({
    frequency: $('#rpFreq').value,
    ...($('#rpUntil').value ? { until: $('#rpUntil').value } : { count: +$('#rpCount').value || 1 }),
  });
  let ask = 0;
  const preview = async () => {
    const mine = ++ask;
    try {
      const plan = await apiFetch(`/tournaments/${id}/repeat/preview`, { method: 'POST', body: JSON.stringify(body()) });
      if (mine !== ask) return;
      $('#rpPreview').innerHTML = plan.dates.length
        ? `${esc(tr('Nuovi tornei ({n}):', { n: plan.dates.length }))} ${plan.dates.map((d) => esc(fmtDate(d))).join(', ')}`
          + (plan.already_there.length ? `<br>${esc(tr('Già in serie, saltati: {date}', { date: plan.already_there.map((d) => fmtDate(d)).join(', ') }))}` : '')
        : esc(tr('Nessuna data nuova con queste scelte.'));
      $('#rpSubmit').disabled = !plan.dates.length;
    } catch (err) {
      if (mine === ask) $('#rpPreview').textContent = err.message;
    }
  };
  ['#rpFreq', '#rpCount', '#rpUntil'].forEach((sel) => $(sel).addEventListener('input', preview));
  preview();

  $('#rpSubmit').addEventListener('click', async () => {
    try {
      const created = await apiFetch(`/tournaments/${id}/repeat`, { method: 'POST', body: JSON.stringify(body()) });
      dlg.close();
      toast(tr('Creati {n} tornei della serie.', { n: created.length }));
      await loadTournaments();
      render();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── ISCRITTI ────────────────────────────────────────── */

/* ── GIOCATORI ───────────────────────────────────────────
   Iscritti, liste e penalità erano tre schede sulle stesse persone: si finiva
   per rimbalzare fra loro per capire se Tizio aveva pagato, consegnato la lista
   e preso un warning. Qui è una riga sola per giocatore, con tutto sopra.

   Le azioni che richiedono spazio (walk-in, lista, penalità) stanno in modali:
   così la tabella resta leggibile anche con sessanta iscritti. */

let _players = [];          // iscrizioni, complete di tag e stato lista
let _fields = [];           // domande all'iscrizione del torneo aperto
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
    [_players, _penalties, _fields] = await Promise.all([
      fetchAllRegs(t.id),
      apiFetch(`/tournaments/${t.id}/penalties`).catch(() => []),
      apiFetch(`/tournaments/${t.id}/fields`).catch(() => []),
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

/** Le risposte alle domande del torneo, in una riga sotto il nome. */
function answersLine(r) {
  const parts = _fields.filter((f) => r.answers?.[f.id]).map((f) => `${esc(f.label)}: ${esc(r.answers[f.id])}`);
  return parts.length ? `<br><small class="muted">${parts.join(' · ')}</small>` : '';
}

const PAYMENT_LABELS = {
  paid: 'Pagato', confirmed: 'Pagato', pending: 'Da pagare', failed: 'Non riuscito',
  refunded: 'Rimborsato', refund_requested: 'Rimborso richiesto',
};
const DECK_LABELS = { missing: 'Mancante', submitted: 'Consegnata', valid: 'Valida', invalid: 'Non valida' };

/* Una cella della tabella giocatori: lo stato sopra, le azioni sotto, le note in fondo. */
const cell = (top, bottom = '', note = '') =>
  `<div class="cell"><div class="cell-top">${top}</div><div class="cell-bottom">${bottom}</div></div>${note}`;

/* Come si raggiunge il giocatore: la sua email, quella del genitore per un
   minore, nessuna per un ospite. */
function contactLine(r) {
  if (r.player_kind === 'guest') return `<span class="pill">${esc(tr('ospite'))}</span>`;
  if (r.player_kind === 'profile') {
    return `<small class="muted">${esc(tr('minore · genitore: {nome}', { nome: r.guardian_name || '' }))}${r.guardian_email ? ' · ' + esc(r.guardian_email) : ''}</small>`;
  }
  return `<small class="muted">${esc(r.player_email)}</small>`;
}

function playerRow(r) {
  const name = r.player?.display_name || r.player_email;
  const paid = ['paid', 'confirmed'].includes(r.payment_status);
  const deck = r.decklist_status || 'missing';
  const hasDeck = deck !== 'missing';
  const pen = penaltiesOf(r.id);
  const tags = (r.tags || []).map(x =>
    `<span class="player-tag" style="color:${esc(x.color)}">${esc(x.name)}</span>`).join('');

  // Segmenti di lista mancanti ed errori: note sotto, fuori dai due piani.
  const deckNotes = (() => {
    const notes = [];
    const attesi = activeT()?.decklist_formats || [''];
    if (attesi.length > 1) {
      const avute = new Set(r.decklist_formats || []);
      const mancanti = attesi.filter((f) => !avute.has(f)).map((f) => f || 'Costruito');
      notes.push(mancanti.length
        ? `<div class="cell-note" style="color:var(--warn)">manca: ${esc(mancanti.join(', '))}</div>`
        : '<div class="cell-note" style="color:var(--green)">tutti i segmenti</div>');
    }
    if (r.decklist_errors) notes.push(`<div class="cell-note" style="color:var(--danger)">${esc(r.decklist_errors)}</div>`);
    return notes.join('');
  })();
  const answers = answersLine(r).replace('<br>', '');

  return `<tr data-reg="${r.id}">
    <td>
      ${cell(
        `<strong>${esc(name)}</strong>
         ${r.waitlisted ? '<span class="pill warn">attesa</span>' : ''}${r.dropped ? '<span class="pill">drop</span>' : ''}
         ${r.byes && !_byesEditable ? `<span class="pill ok">${esc(tr('{n} bye', { n: r.byes }))}</span>` : ''}
         ${r.pod ? `<span class="pill">${esc(tr('pod {p} · posto {s}', { p: r.pod, s: r.pod_seat }))}</span>` : ''}
         ${r.fixed_table ? `<span class="pill ok">${esc(tr('tavolo {n}', { n: r.fixed_table }))}</span>` : ''}
         ${r.team_name ? `<span class="pill">${esc(r.team_name)} · ${esc(SEAT_LETTER(r.team_seat))}</span>` : ''}`,
        contactLine(r),
        `${answers ? `<div class="cell-note">${answers}</div>` : ''}${tags ? `<div class="cell-note">${tags}</div>` : ''}`,
      )}
    </td>
    <td>
      ${cell(
        `<span class="pill ${paid ? 'ok' : 'warn'}">${esc(tr(PAYMENT_LABELS[r.payment_status] || r.payment_status))}</span>`,
        paid ? '' : `<button class="mini-button" data-act="pay" type="button">${esc(tr('Segna pagato'))}</button>`,
      )}
    </td>
    <td>
      ${cell(
        r.checked_in ? `<span class="pill ok">${esc(tr('Presente'))}</span>` : '<span class="muted">—</span>',
        `<button class="mini-button" data-act="checkin" data-val="${!r.checked_in}" type="button">${esc(r.checked_in ? tr('Annulla') : tr('Check-in'))}</button>`,
      )}
    </td>
    <td>
      ${cell(
        `<span class="pill ${DECK_BADGE[deck] || 'warn'}">${esc(tr(DECK_LABELS[deck] || deck))}</span>`,
        `${hasDeck ? `<button class="mini-button" data-act="deck-view" type="button">${esc(tr('Vedi'))}</button>` : ''}
         <button class="mini-button" data-act="deck-edit" type="button">${esc(hasDeck ? tr('Modifica') : tr('Carica'))}</button>`,
        deckNotes,
      )}
    </td>
    <td>
      ${cell(
        pen.length ? `<span class="pill warn">${pen.length}</span>` : '<span class="muted">—</span>',
        `<button class="mini-button" data-act="penalty" type="button">${esc(tr('Gestisci'))}</button>`,
      )}
    </td>
    <td>
      ${cell('', `<button class="mini-button" data-act="drop" data-val="${!r.dropped}" type="button">${esc(r.dropped ? tr('Reintegra') : tr('Drop'))}</button>
        ${_byesEditable ? `<select data-byes title="${esc(tr('Bye assegnati: salta i primi turni e li vince'))}">
          ${[0, 1, 2, 3].map((n) => `<option value="${n}"${(r.byes || 0) === n ? ' selected' : ''}>${esc(tr('{n} bye', { n }))}</option>`).join('')}
        </select>` : ''}
        <details class="row-menu"><summary class="mini-button" title="${esc(tr('Altre azioni'))}">⋯</summary>
          <div class="row-menu-list">
            <button class="mini-button" data-act="fixed-table" type="button">${esc(r.fixed_table ? tr('Cambia tavolo fisso') : tr('Tavolo fisso…'))}</button>
            ${_suspendSlug && r.player_id ? `<button class="mini-button" data-act="suspend" type="button">${esc(tr('Sospendi dal negozio'))}</button>` : ''}
          </div>
        </details>`)}
    </td>
  </tr>`;
}

function drawGiocatori(t) {
  _suspendSlug = t.can_manage && _myStores.has(t.organization_slug) ? t.organization_slug : null;
  _byesEditable = t.can_manage && ['draft', 'published'].includes(t.status) && !registrationOnly(t);
  const rows = _players.map(playerRow).join('')
    || '<tr><td colspan="6" class="muted">Nessun iscritto: usa "Iscrivi al banco".</td></tr>';
  const conLista = _players.filter(r => (r.decklist_status || 'missing') !== 'missing').length;
  const pagati = _players.filter(r => ['paid', 'confirmed'].includes(r.payment_status)).length;
  const presenti = _players.filter(r => r.checked_in).length;

  $('#panel').innerHTML = `
    <div class="panel" style="margin-bottom:16px">
      <div class="bo-head" style="margin-bottom:12px">
        <h3 style="margin:0">Giocatori (${_players.length})</h3>
        <div class="row-actions">
          <button class="secondary" id="gCsv" type="button">${esc(tr('Esporta CSV'))}</button>
          <button class="secondary" id="gImport" type="button">${esc(tr('Importa da file'))}</button>
          ${['draft', 'published'].includes(t.status) && t.entry_fee_cents > 0
            ? `<button class="secondary" id="gUnpaid" type="button">${esc(tr('Togli chi non ha pagato'))}</button>` : ''}
          <button class="primary" id="gWalkIn" type="button">+ Iscrivi al banco</button>
        </div>
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
<div class="table-scroll">      <table class="bo players">
        <thead><tr>
          <th>Giocatore</th><th>Pagamento</th><th>Check-in</th><th>Lista</th><th>Penalità</th><th></th>
        </tr></thead>
        <tbody id="gBody">${rows}</tbody>
      </table></div>
    </div>
    <div id="teamsBox"></div>
    <div id="podsBox"></div>`;

  $('#gWalkIn').addEventListener('click', () => openWalkInDialog(t.id));
  renderTeams(t);
  renderPods(t);
  $('#gCsv').addEventListener('click', () => downloadPlayersCsv(t));
  $('#gBody').querySelectorAll('[data-byes]').forEach((sel) => sel.addEventListener('change', async () => {
    const rid = sel.closest('[data-reg]').dataset.reg;
    try {
      const updated = await apiFetch(`/tournaments/${t.id}/registrations/${rid}/byes`, {
        method: 'PUT', body: JSON.stringify({ byes: +sel.value }),
      });
      const reg = _players.find((r) => String(r.id) === String(rid));
      if (reg) reg.byes = updated.byes;
      toast(tr('Bye aggiornati.'));
    } catch (err) { toast('Errore: ' + err.message); }
  }));
  $('#gImport').addEventListener('click', () => openImportDialog(t));
  $('#gUnpaid')?.addEventListener('click', () => dropUnpaid(t));
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
      if (act === 'fixed-table') return setFixedTable(t, reg);
      if (act === 'suspend')    return openSuspendDialog(_suspendSlug, {
        user_id: reg.player_id, name: reg.player?.display_name || reg.player_email,
      }, () => renderWarnings(t));
      return regAction(t.id, act, regId, btn.dataset.val);
    }));
}

/* Prima dell'inizio, chi occupa un posto senza aver pagato lo lascia a chi
   aspetta. Prima si vede chi, poi si conferma. */
async function dropUnpaid(t) {
  try {
    const plan = await apiFetch(`/tournaments/${t.id}/drop-unpaid`, { method: 'POST' });
    if (!plan.dropped.length) { toast(tr('Hanno pagato tutti.')); return; }
    const question = (plan.dropped.length === 1
      ? tr('Togliere 1 iscritto che non ha pagato?')
      : tr('Togliere {n} iscritti che non hanno pagato?', { n: plan.dropped.length }))
      + '\n\n' + plan.dropped.join(', ')
      + '\n\n' + tr("I posti liberati vanno a chi è in lista d'attesa.");
    if (!confirm(question)) return;
    const done = await apiFetch(`/tournaments/${t.id}/drop-unpaid?dry_run=false`, { method: 'POST' });
    toast(tr('Iscrizioni tolte: {n}.', { n: done.dropped.length })
      + (done.promoted ? ' ' + tr("Entrano dalla lista d'attesa: {p}.", { p: done.promoted }) : ''));
    await loadTournaments();
    renderGiocatori();
  } catch (err) { toast('Errore: ' + err.message); }
}

/* Un tavolo fisso per chi ne ha bisogno (sedia a rotelle, vicino all'uscita):
   i suoi match si giocano lì dal turno dopo. Vuoto per toglierlo. */
async function setFixedTable(t, reg) {
  const answer = prompt(tr('Tavolo fisso per {nome} (vuoto per toglierlo):', { nome: reg.player?.display_name || '' }),
    reg.fixed_table || '');
  if (answer === null) return;
  const table = answer.trim() ? +answer : null;
  if (answer.trim() && !(table >= 1)) { toast(tr('Scrivi un numero di tavolo.')); return; }
  try {
    await apiFetch(`/tournaments/${t.id}/registrations/${reg.id}/fixed-table`, { method: 'PUT', body: JSON.stringify({ table }) });
    toast(table ? tr('Tavolo fisso: {n}.', { n: table }) : tr('Tavolo fisso tolto.'));
    renderGiocatori();
  } catch (err) { toast('Errore: ' + err.message); }
}

/* ── Squadre ─────────────────────────────────────────────
   Nei tornei a squadre ogni squadra ha 2 o 3 posti: a ogni turno il posto A
   gioca contro il posto A avversario, e così via. Giocano le squadre complete. */
const SEAT_LETTER = (seat) => 'ABC'[seat - 1] || String(seat || '');

async function renderTeams(t) {
  const box = $('#teamsBox');
  if (!box) return;
  if ((t.team_size || 1) < 2) { box.innerHTML = ''; return; }
  const teams = await apiFetch(`/tournaments/${t.id}/teams`).catch(() => []);
  const editable = t.can_manage && ['draft', 'published'].includes(t.status);
  const seats = Array.from({ length: t.team_size }, (_, i) => i + 1);
  const taken = new Set(teams.flatMap((team) => team.members.map((m) => m.registration_id)));
  const free = _players.filter((r) => !r.dropped && !r.waitlisted && !taken.has(r.id));
  const seatCell = (team, seat) => {
    const member = team.members.find((m) => m.seat === seat);
    if (!editable) return esc(member?.name || '—');
    return `<select data-team="${team.id}" data-seat="${seat}">
      <option value="">—</option>
      ${member ? `<option value="${member.registration_id}" selected>${esc(member.name)}</option>` : ''}
      ${free.map((r) => `<option value="${r.id}">${esc(r.player?.display_name || r.player_email)}</option>`).join('')}
    </select>`;
  };
  box.innerHTML = `<div class="panel" style="margin-top:16px">
    <div class="bo-head" style="margin-bottom:8px">
      <h3 style="margin:0">${esc(tr('Squadre ({n})', { n: teams.length }))}</h3>
      ${editable ? `<form id="teamForm" class="toolbar">
        <input id="teamName" required maxlength="120" placeholder="${esc(tr('Nome della squadra'))}" style="width:220px" />
        <button class="primary" type="submit">${esc(tr('Aggiungi squadra'))}</button>
      </form>` : ''}
    </div>
    <p class="muted" style="margin:0 0 8px;font-size:.85rem">${esc(tr("A ogni turno il posto A gioca contro il posto A della squadra avversaria, e così via: vince l'incontro chi vince più posti. Giocano solo le squadre complete."))}</p>
    <div class="table-scroll"><table class="bo">
      <thead><tr><th>${esc(tr('Squadra'))}</th>${seats.map((s) => `<th>${esc(tr('Posto {x}', { x: SEAT_LETTER(s) }))}</th>`).join('')}<th></th></tr></thead>
      <tbody>${teams.map((team) => `<tr>
        <td><strong>${esc(team.name)}</strong> ${team.complete ? '' : `<span class="pill warn">${esc(tr('incompleta'))}</span>`}</td>
        ${seats.map((s) => `<td>${seatCell(team, s)}</td>`).join('')}
        <td class="row-actions">${editable ? `<button class="mini-button danger" data-drop-team="${team.id}" type="button">${esc(tr('Elimina'))}</button>` : ''}</td>
      </tr>`).join('') || `<tr><td colspan="${seats.length + 2}" class="muted">${esc(tr('Nessuna squadra: aggiungine una.'))}</td></tr>`}</tbody>
    </table></div>
  </div>`;
  $('#teamForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch(`/tournaments/${t.id}/teams`, { method: 'POST', body: JSON.stringify({ name: $('#teamName').value.trim() }) });
      renderGiocatori();
    } catch (err) { toast('Errore: ' + err.message); }
  });
  box.querySelectorAll('[data-seat]').forEach((sel) => sel.addEventListener('change', async () => {
    try {
      await apiFetch(`/tournaments/${t.id}/teams/${sel.dataset.team}/seats/${sel.dataset.seat}`, {
        method: 'PUT', body: JSON.stringify({ registration_id: +sel.value || null }),
      });
      renderGiocatori();
    } catch (err) { toast('Errore: ' + err.message); renderGiocatori(); }
  }));
  box.querySelectorAll('[data-drop-team]').forEach((b) => b.addEventListener('click', async () => {
    if (!confirm(tr('Eliminare la squadra? I suoi giocatori restano iscritti, senza squadra.'))) return;
    try {
      await apiFetch(`/tournaments/${t.id}/teams/${b.dataset.dropTeam}`, { method: 'DELETE' });
      renderGiocatori();
    } catch (err) { toast('Errore: ' + err.message); }
  }));
}

/* ── Pod di draft ────────────────────────────────────────
   Per un draft i giocatori si dividono in pod (di solito da 8) e si siedono
   in ordine: al primo turno si gioca contro chi siede di fronte, dentro il pod. */
async function renderPods(t) {
  const box = $('#podsBox');
  if (!box) return;
  const draftLike = /draft/i.test(t.format || '') || t.pod_size > 0;
  if (!draftLike || registrationOnly(t)) { box.innerHTML = ''; return; }
  const pods = await apiFetch(`/tournaments/${t.id}/pods`).catch(() => []);
  const editable = t.can_manage && ['draft', 'published'].includes(t.status);
  box.innerHTML = `<div class="panel" style="margin-top:16px">
    <div class="bo-head" style="margin-bottom:8px">
      <h3 style="margin:0">${esc(tr('Pod di draft'))}</h3>
      <div class="toolbar">
        ${editable ? `<label>${esc(tr('Giocatori per pod'))} <select id="podSize" style="min-width:72px">
          ${[6, 7, 8, 9, 10, 12].map((n) => `<option value="${n}"${n === (t.pod_size || 8) ? ' selected' : ''}>${n}</option>`).join('')}
        </select></label>
        <button class="primary" id="podMake" type="button">${esc(pods.length ? tr('Rifai i pod') : tr('Crea i pod'))}</button>
        ${pods.length ? `<button class="secondary" id="podClear" type="button">${esc(tr('Togli'))}</button>` : ''}` : ''}
        ${pods.length ? `<button class="secondary" id="podPrint" type="button">${esc(tr('Stampa'))}</button>` : ''}
      </div>
    </div>
    <p class="muted" style="margin:0;font-size:.85rem">${esc(tr('I pod si fanno con chi è pronto a giocare (pagato, presente, con la lista se serve), prima di avviare il torneo. Al primo turno si gioca contro chi siede di fronte, poi svizzera dentro il pod.'))}</p>
    ${pods.length ? `<div class="pod-grid" id="podGrid">${pods.map((p) => `<div class="pod-card">
      <h4>${esc(tr('Pod {n}', { n: p.pod }))}</h4>
      <ol>${p.players.map((s) => `<li value="${s.seat}">${esc(s.name)}</li>`).join('')}</ol>
    </div>`).join('')}</div>` : ''}
  </div>`;
  $('#podMake')?.addEventListener('click', async () => {
    if (pods.length && !confirm(tr('Rifare i pod? Posti e gruppi cambiano.'))) return;
    try {
      await apiFetch(`/tournaments/${t.id}/pods`, { method: 'POST', body: JSON.stringify({ pod_size: +$('#podSize').value }) });
      await loadTournaments();
      renderGiocatori();
    } catch (err) { toast('Errore: ' + err.message); }
  });
  $('#podClear')?.addEventListener('click', async () => {
    try {
      await apiFetch(`/tournaments/${t.id}/pods`, { method: 'DELETE' });
      await loadTournaments();
      renderGiocatori();
    } catch (err) { toast('Errore: ' + err.message); }
  });
  $('#podPrint')?.addEventListener('click', () => {
    const w = window.open('', '_blank');
    if (!w) { toast(tr('Il browser ha bloccato la finestra di stampa.')); return; }
    w.document.write(`<!doctype html><title>${esc(t.name)} — pod</title>
      <style>body{font-family:sans-serif;padding:24px} .pod{break-inside:avoid;margin-bottom:24px}
      h1{font-size:20px} h2{font-size:16px;margin:0 0 6px} ol{margin:0;padding-left:24px;line-height:1.7}</style>
      <h1>${esc(t.name)}</h1>
      ${pods.map((p) => `<div class="pod"><h2>${esc(tr('Pod {n}', { n: p.pod }))}</h2><ol>${p.players.map((s) => `<li value="${s.seat}">${esc(s.name)}</li>`).join('')}</ol></div>`).join('')}`);
    w.document.close();
    w.print();
  });
}

/* ── Import da file ─────────────────────────────────────
   Preiscrizioni raccolte altrove, un torneo spostato da un'altra piattaforma.
   Prima l'anteprima riga per riga, poi l'import: niente sorprese. */
const IMPORT_OUTCOMES = {
  added: { label: 'Iscritto', cls: 'ok' },
  waitlisted: { label: "Lista d'attesa", cls: 'warn' },
  already: { label: 'Già iscritto', cls: '' },
  error: { label: 'Errore', cls: 'danger' },
};

/* Excel in italiano salva i CSV in Windows-1252, non in UTF-8: se il file non
   è UTF-8 valido lo si rilegge così, altrimenti le lettere accentate si rompono. */
async function readTextFile(file) {
  const bytes = await file.arrayBuffer();
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return new TextDecoder('windows-1252').decode(bytes);
  }
}

function openImportDialog(t) {
  const dlg = $('#boDialog');
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">${esc(tr('Iscrizioni'))}</span><h2>${esc(tr('Importa da file'))}</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr("Un CSV da un foglio di calcolo, con virgole o punti e virgola: serve almeno la colonna dell'email; nome, ID editore e pagato si riconoscono dall'intestazione. Chi non ha un account lo riceve, come al banco."))}</p>
      <div class="bo-grid">
        <label style="grid-column:1/-1">${esc(tr('File'))}<input id="imFile" type="file" accept=".csv,.txt,text/csv,text/plain" /></label>
        <label style="grid-column:1/-1">${esc(tr('Oppure incolla qui'))}<textarea id="imText" style="min-height:110px" placeholder="email;nome;id editore&#10;mario@example.com;Mario Rossi;1234567890"></textarea></label>
        <label class="bo-check" style="grid-column:1/-1"><input id="imPaid" type="checkbox" /> ${esc(tr('Segna tutti come pagati al banco'))}</label>
      </div>
      <div id="imPreview" style="margin-top:12px"></div>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>${esc(tr('Annulla'))}</button>
        <button class="secondary" id="imCheck" type="button">${esc(tr('Anteprima'))}</button>
        <button class="primary" id="imGo" type="button" disabled>${esc(tr('Importa'))}</button>
      </menu>
    </form>`;
  dlg.showModal();

  $('#imFile').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (file) $('#imText').value = await readTextFile(file);
    $('#imGo').disabled = true;
  });
  $('#imText').addEventListener('input', () => { $('#imGo').disabled = true; });

  const send = (dryRun) => apiFetch(`/tournaments/${t.id}/import`, {
    method: 'POST',
    body: JSON.stringify({ csv_text: $('#imText').value, mark_paid: $('#imPaid').checked, dry_run: dryRun }),
  });

  $('#imCheck').addEventListener('click', async () => {
    if (!$('#imText').value.trim()) { toast(tr('Scegli un file o incolla la lista.')); return; }
    try {
      const plan = await send(true);
      const rows = plan.rows.map((r) => {
        const o = IMPORT_OUTCOMES[r.outcome];
        return `<tr><td>${r.line}</td><td>${esc(r.name)}<br><small class="muted">${esc(r.email)}</small></td>
          <td><span class="pill ${o.cls}">${esc(tr(o.label))}</span>${r.detail ? `<br><small class="muted">${esc(r.detail)}</small>` : ''}</td></tr>`;
      }).join('');
      $('#imPreview').innerHTML = `
        <p style="margin:0 0 8px">${esc(tr("{n} da iscrivere, {w} in lista d'attesa, {s} saltati.", { n: plan.added, w: plan.waitlisted, s: plan.skipped }))}</p>
        <div style="max-height:280px;overflow:auto"><table class="bo">
          <thead><tr><th>${esc(tr('Riga'))}</th><th>${esc(tr('Giocatore'))}</th><th>${esc(tr('Esito'))}</th></tr></thead>
          <tbody>${rows}</tbody></table></div>`;
      const total = plan.added + plan.waitlisted;
      $('#imGo').disabled = !total;
      $('#imGo').textContent = total ? tr('Importa {n}', { n: total }) : tr('Importa');
    } catch (err) { $('#imPreview').innerHTML = `<p class="field-error">${esc(err.message)}</p>`; }
  });

  $('#imGo').addEventListener('click', async () => {
    $('#imGo').disabled = true;
    try {
      const done = await send(false);
      dlg.close();
      toast(tr("Importati {n} giocatori ({w} in lista d'attesa).", { n: done.added + done.waitlisted, w: done.waitlisted }));
      renderGiocatori();
    } catch (err) {
      toast('Errore: ' + err.message);
      $('#imGo').disabled = false;
    }
  });
}

/* ── Modali ──────────────────────────────────────────── */

function openWalkInDialog(tid) {
  const dlg = $('#boDialog');
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">Iscrizione</span><h2>Iscrivi al banco</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      <div class="bo-grid">
        <label>Email <small class="muted">${esc(tr('(vuota: ospite senza account)'))}</small><input id="wEmail" type="email" placeholder="player@email.com" /></label>
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
      email: $('#wEmail').value.trim() || null,
      display_name: $('#wName').value.trim(),
      wizards_account: $('#wWiz').value.trim(),
      mark_paid: $('#wPaid').checked,
    };
    if (!body.display_name) { toast(tr('Il nome è obbligatorio.')); return; }
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
  let regs = [];
  try {
    [standings, regs] = await Promise.all([
      apiFetch(`/tournaments/${t.id}/standings`).then((s) => s || []),
      // I premi non stanno nella classifica pubblica: vengono dagli iscritti.
      t.can_manage ? fetchAllRegs(t.id).catch(() => []) : [],
    ]);
  } catch (err) { toast('Errore: ' + err.message); }
  const prizeOf = new Map(regs.map((r) => [r.id, r]));
  // Ogni gioco ha i suoi spareggi, nell'ordine in cui contano.
  const columns = tiebreakerColumns((await gameInfo(t.game))?.tiebreakers);
  const rows = standings.map(s => `
    <tr>
      <td>${s.position}</td>
      <td><strong>${esc(s.name)}</strong></td>
      <td>${s.points}</td>
      <td>${esc(s.record)}</td>
      ${columns.map((c) => `<td>${s[c.key] ?? 0}%</td>`).join('')}
      ${t.can_manage ? `<td>${prizeCell(prizeOf.get(s.registration_id))}</td>` : ''}
    </tr>`).join('') || `<tr><td colspan="${5 + columns.length}" class="muted">Nessun dato (genera round e inserisci risultati).</td></tr>`;
  let teamHtml = '';
  if ((t.team_size || 1) > 1) {
    const teamRows = await apiFetch(`/tournaments/${t.id}/team-standings`).catch(() => []);
    teamHtml = `<div class="panel" style="margin-bottom:16px"><h3>${esc(tr('Classifica a squadre'))}</h3>
      <table class="bo"><thead><tr><th>#</th><th>${esc(tr('Squadra'))}</th><th>${esc(tr('Punti'))}</th><th>V/S/P</th><th>OMW%</th><th>${esc(tr('Posti vinti'))}</th></tr></thead>
      <tbody>${teamRows.map((r) => `<tr><td>${r.position}</td><td><strong>${esc(r.name)}</strong></td><td>${r.points}</td><td>${esc(r.record)}</td><td>${r.opponent_match_win_percentage}%</td><td>${r.seat_wins}</td></tr>`).join('')
        || `<tr><td colspan="6" class="muted">${esc(tr('Nessun incontro concluso.'))}</td></tr>`}</tbody></table></div>`;
  }
  const html = `${teamHtml}<div class="panel" style="margin-bottom:16px"><h3>Classifica</h3>
    <table class="bo"><thead><tr><th>#</th><th>Giocatore</th><th>Punti</th><th>V/S/P</th>
      ${columns.map((c) => `<th>${esc(c.label)}</th>`).join('')}${t.can_manage ? `<th>${esc(tr('Premio'))}</th>` : ''}</tr></thead><tbody>${rows}</tbody></table></div>`;
  if (prepend) $('#panel').insertAdjacentHTML('afterbegin', html);
  else $('#panel').innerHTML = html;
  $('#panel').querySelectorAll('[data-prize]').forEach((b) => b.addEventListener('click', () => togglePrize(t, b)));
}

/* Il premio consegnato: cosa e quando. Chi l'ha dato resta nel registro. */
function prizeCell(reg) {
  if (!reg) return '';
  if (reg.prize_given_at) {
    return `<span class="pill ok">✓ ${esc(reg.prize_note || tr('consegnato'))}</span>
      <button class="mini-button" data-prize="${reg.id}" data-given="1" type="button">${esc(tr('Annulla'))}</button>`;
  }
  return `<button class="mini-button" data-prize="${reg.id}" type="button">${esc(tr('Consegna'))}</button>`;
}

async function togglePrize(t, button) {
  const given = button.dataset.given !== '1';
  let note = '';
  if (given) {
    note = prompt(tr('Cosa gli consegni? (es. "3 buste", "20 € di credito")'), '');
    if (note === null) return;
  } else if (!confirm(tr('Annullare la consegna del premio?'))) {
    return;
  }
  try {
    await apiFetch(`/tournaments/${t.id}/registrations/${button.dataset.prize}/prize`, {
      method: 'PUT', body: JSON.stringify({ given, note: note.trim() }),
    });
    toast(given ? tr('Premio segnato come consegnato.') : tr('Consegna annullata.'));
    renderRisultati();
  } catch (err) { toast('Errore: ' + err.message); }
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

/* Una cella CSV. Le risposte le scrivono i giocatori: un testo che comincia
   con = + - @ un foglio di calcolo lo eseguirebbe come formula, quindi si
   apre con un apice e resta testo. */
function csvCell(value) {
  let s = String(value ?? '');
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return `"${s.replace(/"/g, '""')}"`;
}

function downloadCsv(filename, rows) {
  const blob = new Blob(['\ufeff' + rows.map((row) => row.map(csvCell).join(',')).join('\n')],
    { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/* Gli iscritti con le risposte alle domande: per le magliette, i tavoli, la cassa. */
function downloadPlayersCsv(t) {
  const state = (r) => (r.dropped ? 'drop' : r.waitlisted ? 'attesa' : 'iscritto');
  const header = ['Nome', 'Email', 'ID editore', 'Pagamento', 'Check-in', 'Stato', ..._fields.map((f) => f.label)];
  const rows = _players.map((r) => [
    r.player?.display_name || '', r.player_kind === 'account' ? r.player_email : (r.guardian_email || ''),
    r.wizards_account, r.payment_status,
    r.checked_in ? 'sì' : '', state(r), ..._fields.map((f) => r.answers?.[f.id] || ''),
  ]);
  const name = String(t.name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  downloadCsv(`iscritti-${name || t.id}.csv`, [header, ...rows]);
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
  let org = null;
  try {
    org = await myStore();
  } catch (err) {
    if (err.status === 404) return renderNoStore();
    toast('Errore: ' + err.message);
  }
  if (!org) { $('#panel').innerHTML = '<p class="empty">Nessun negozio configurato.</p>'; return; }
  const slug = encodeURIComponent(org.slug);
  const [locations, members, stores] = await Promise.all([
    myLocations().catch(() => []),
    apiFetch(`/organizations/${slug}/members`).catch(() => []),
    apiFetch('/organizations/memberships').catch(() => []),
  ]);

  $('#panel').innerHTML = `${storeSwitcher(stores)}
  <div class="panel">
    <h3>Profilo pubblico — ${esc(org.name)}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">
      Visibile su <a class="secondary-link" href="store.html?s=${esc(org.slug)}" target="_blank" rel="noopener">store.html?s=${esc(org.slug)}</a>
    </p>
    <form id="storeForm" class="bo-grid">
      <label class="span-2">Nome<input id="sName" value="${esc(org.name)}" /></label>
      <label class="span-2">Città<input id="sCity" value="${esc(org.city)}" /></label>
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
  </div>
  ${locationsPanel(locations)}
  ${staffPanel(org, members)}`;
  bindStoreSwitcher();
  bindLocationsPanel(org, locations);
  bindStaffPanel(org, members);

  $('#sGeocode').addEventListener('click', async () => {
    const q = [$('#sAddr').value, $('#sCity').value].filter(Boolean).join(', ');
    if (!q) { toast('Inserisci prima indirizzo o città.'); return; }
    try {
      const hit = await geocode(q);
      if (!hit) { toast('Indirizzo non trovato.'); return; }
      $('#sLat').value = hit.lat;
      $('#sLng').value = hit.lng;
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
      _myStore = null;
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── Negozio e staff ──────────────────────────────────────
   Far parte di un negozio è esplicito: chi non ne ha uno lo apre (e ne è il
   titolare) o si fa aggiungere dal titolare di uno che c'è già. */
const STORE_ROLES = { owner: 'Titolare', organizer: 'Organizzatore' };
const storeRoleLabel = (role) => tr(STORE_ROLES[role] || role);

/** Dopo aver cambiato negozio cambiano i tornei in lista e quello attivo. */
async function storeChanged() {
  _myStore = null;
  await loadTournaments();
  renderNegozio();
}

async function renderNoStore() {
  const stores = await apiFetch('/organizations/memberships').catch(() => []);
  $('#panel').innerHTML = `${storeSwitcher(stores, true)}
  <div class="panel">
    <h3>${esc(tr('Il tuo negozio'))}</h3>
    <p class="muted" style="margin-top:0">${esc(tr('Non fai ancora parte di un negozio: i tuoi tornei per ora escono sotto Mull2Five. Apri il tuo negozio per avere una pagina tua, le tue sedi e uno staff che gestisce i tornei con te. I tornei che hai già creato vengono con te.'))}</p>
    <p class="muted">${esc(tr('Lavori per un negozio che è già qui? Chiedi al titolare di aggiungerti allo staff con la tua email.'))}</p>
    <form id="newStore" class="bo-grid">
      <label class="span-2">${esc(tr('Nome del negozio'))}<input id="nsName" required minlength="2" maxlength="120" /></label>
      <label class="span-2">${esc(tr('Città'))}<input id="nsCity" maxlength="120" /></label>
      <button class="primary" type="submit" style="grid-column:1/-1">${esc(tr('Apri il negozio'))}</button>
    </form>
  </div>`;
  bindStoreSwitcher();
  $('#newStore').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch('/organizations/mine', { method: 'POST', body: JSON.stringify({
        name: $('#nsName').value.trim(), city: $('#nsCity').value.trim(),
      })});
      toast(tr('Negozio aperto: ne sei il titolare.'));
      storeChanged();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/** Chi lavora per più negozi sceglie per quale: i tornei nuovi nascono lì. */
function storeSwitcher(stores, always = false) {
  if (stores.length < (always ? 1 : 2)) return '';
  return `<div class="panel" style="margin-bottom:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <span>${esc(tr('Stai lavorando per'))}</span>
    <select id="storePick">
      ${always && !stores.some((s) => s.current) ? `<option value="">${esc(tr('— nessun negozio —'))}</option>` : ''}
      ${stores.map((s) => `<option value="${esc(s.slug)}"${s.current ? ' selected' : ''}>${esc(s.name)} · ${esc(storeRoleLabel(s.role))}</option>`).join('')}
    </select>
  </div>`;
}

function bindStoreSwitcher() {
  $('#storePick')?.addEventListener('change', async (e) => {
    if (!e.target.value) return;
    try {
      await apiFetch(`/organizations/${encodeURIComponent(e.target.value)}/use`, { method: 'POST' });
      storeChanged();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

function staffPanel(org, members) {
  const owner = org.my_role === 'owner';
  const rows = members.map((m) => {
    const me = String(m.user_id) === String(session.sub);
    const role = owner
      ? `<select data-member-role="${m.user_id}">${Object.keys(STORE_ROLES).map((r) =>
          `<option value="${r}"${r === m.role ? ' selected' : ''}>${esc(storeRoleLabel(r))}</option>`).join('')}</select>`
      : esc(storeRoleLabel(m.role));
    const action = me
      ? `<button class="mini-button" data-member-drop="${m.user_id}" data-self="1" type="button">${esc(tr('Esci dallo staff'))}</button>`
      : owner ? `<button class="mini-button" data-member-drop="${m.user_id}" type="button" style="color:var(--danger,#ef6a5e)">${esc(tr('Togli'))}</button>` : '';
    return `<tr>
      <td>${esc(m.display_name)}${me ? ` <span class="muted">(${esc(tr('tu'))})</span>` : ''}</td>
      <td class="muted">${esc(m.email)}</td>
      <td>${role}</td>
      <td class="row-actions">${action}</td>
    </tr>`;
  }).join('');
  return `<div class="panel" style="margin-top:16px">
    <h3>${esc(tr('Staff del negozio'))}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr("Chi fa parte dello staff crea e gestisce tutti i tornei del negozio; chi ne fa parte lo decide il titolare. Per i judge di un solo torneo c'è la scheda Staff del torneo."))}</p>
    <table class="bo"><thead><tr><th>${esc(tr('Nome'))}</th><th>Email</th><th>${esc(tr('Ruolo'))}</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>
    ${owner ? `<form id="memberForm" class="bo-grid" style="margin-top:12px">
      <label class="span-2">Email<input id="mEmail" type="email" required placeholder="${esc(tr('email del suo account'))}" /></label>
      <label>${esc(tr('Ruolo'))}<select id="mRole">
        ${Object.keys(STORE_ROLES).map((r) => `<option value="${r}"${r === 'organizer' ? ' selected' : ''}>${esc(storeRoleLabel(r))}</option>`).join('')}
      </select></label>
      <button class="primary" type="submit" style="grid-column:1/-1">${esc(tr('Aggiungi allo staff'))}</button>
      <p class="muted" style="grid-column:1/-1;margin:0;font-size:.82rem">${esc(tr('Deve avere già un account. Se era solo giocatore, diventa organizzatore.'))}</p>
    </form>` : ''}
  </div>`;
}

function bindStaffPanel(org, members) {
  const base = `/organizations/${encodeURIComponent(org.slug)}/members`;
  $('#memberForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch(base, { method: 'POST', body: JSON.stringify({
        email: $('#mEmail').value.trim(), role: $('#mRole').value,
      })});
      toast(tr('Aggiunto allo staff.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  });
  $('#panel').querySelectorAll('[data-member-role]').forEach((sel) => sel.addEventListener('change', async () => {
    try {
      await apiFetch(`${base}/${sel.dataset.memberRole}`, { method: 'PATCH', body: JSON.stringify({ role: sel.value }) });
      toast(tr('Ruolo aggiornato.'));
      if (String(sel.dataset.memberRole) === String(session.sub)) _myStore = null;
    } catch (err) {
      toast('Errore: ' + err.message);
    }
    renderNegozio();
  }));
  $('#panel').querySelectorAll('[data-member-drop]').forEach((b) => b.addEventListener('click', async () => {
    const self = b.dataset.self === '1';
    const member = members.find((m) => String(m.user_id) === b.dataset.memberDrop);
    const question = self
      ? tr('Uscire dallo staff di {negozio}? Non gestirai più i suoi tornei.', { negozio: org.name })
      : tr('Togliere {nome} dallo staff? I tornei che ha creato restano al negozio.', { nome: member?.display_name || '' });
    if (!confirm(question)) return;
    try {
      await apiFetch(`${base}/${b.dataset.memberDrop}`, { method: 'DELETE' });
      if (self) { storeChanged(); return; }
      toast(tr('Tolto dallo staff.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  }));
}

function locationsPanel(locations) {
  const rows = locations.map((loc) => `
    <tr>
      <td><strong>${esc(loc.name)}</strong>${loc.notes ? `<div class="muted" style="font-size:.82rem">${esc(loc.notes)}</div>` : ''}</td>
      <td class="muted">${esc([loc.address, loc.city].filter(Boolean).join(', ') || '—')}</td>
      <td>${loc.latitude != null ? esc(tr('Sì')) : `<span class="muted">${esc(tr('No: non esce nella ricerca per distanza'))}</span>`}</td>
      <td class="row-actions">
        <button class="mini-button" data-edit-loc="${loc.id}" type="button">${esc(tr('Modifica'))}</button>
        <button class="mini-button" data-drop-loc="${loc.id}" type="button" style="color:var(--danger,#ef6a5e)">${esc(tr('Elimina'))}</button>
      </td>
    </tr>`).join('')
    || `<tr><td colspan="4" class="muted">${esc(tr("Nessuna sede: i tornei usano l'indirizzo del negozio o il luogo scritto a mano."))}</td></tr>`;
  return `<div class="panel" style="margin-top:16px">
    <h3>${esc(tr('Sedi'))}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr('Dove si gioca: un secondo punto vendita, una sala per gli eventi grandi. Ogni torneo sceglie la sua sede e ne prende indirizzo e posizione sulla mappa.'))}</p>
    <table class="bo"><thead><tr><th>${esc(tr('Sede'))}</th><th>${esc(tr('Indirizzo'))}</th><th>${esc(tr('Coordinate'))}</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>
    <form id="locForm" class="bo-grid" style="margin-top:12px">
      <input type="hidden" id="lId" />
      <label class="span-2">${esc(tr('Nome'))}<input id="lName" required minlength="2" maxlength="120" placeholder="${esc(tr('Sala eventi'))}" /></label>
      <label class="span-2">${esc(tr('Città'))}<input id="lCity" maxlength="120" /></label>
      <label style="grid-column:1/-1">${esc(tr('Indirizzo'))}<input id="lAddr" maxlength="240" /></label>
      <label class="span-2">${esc(tr('Latitudine'))}<input id="lLat" type="number" step="0.0001" /></label>
      <label class="span-2">${esc(tr('Longitudine'))}<input id="lLng" type="number" step="0.0001" /></label>
      <label style="grid-column:1/-1">${esc(tr('Note per chi arriva'))}<input id="lNotes" placeholder="${esc(tr('Piano, parcheggio, accessibilità'))}" /></label>
      <div style="grid-column:1/-1;display:flex;gap:8px;flex-wrap:wrap">
        <button class="secondary" id="lGeocode" type="button">Trova coordinate dall'indirizzo</button>
        <button class="primary" id="lSave" type="submit">${esc(tr('Aggiungi sede'))}</button>
        <button class="secondary" id="lCancel" type="button" style="display:none">${esc(tr('Annulla'))}</button>
      </div>
    </form>
  </div>`;
}

function bindLocationsPanel(org, locations) {
  const base = `/organizations/${encodeURIComponent(org.slug)}/locations`;
  const num = (id) => ($(id).value === '' ? null : +$(id).value);
  const fill = (loc) => {
    $('#lId').value = loc?.id ?? '';
    $('#lName').value = loc?.name ?? '';
    $('#lCity').value = loc?.city ?? '';
    $('#lAddr').value = loc?.address ?? '';
    $('#lLat').value = loc?.latitude ?? '';
    $('#lLng').value = loc?.longitude ?? '';
    $('#lNotes').value = loc?.notes ?? '';
    $('#lSave').textContent = loc ? tr('Salva sede') : tr('Aggiungi sede');
    $('#lCancel').style.display = loc ? '' : 'none';
  };
  $('#panel').querySelectorAll('[data-edit-loc]').forEach((b) => b.addEventListener('click', () => {
    fill(locations.find((loc) => String(loc.id) === b.dataset.editLoc));
    $('#lName').focus();
  }));
  $('#panel').querySelectorAll('[data-drop-loc]').forEach((b) => b.addEventListener('click', async () => {
    const loc = locations.find((l) => String(l.id) === b.dataset.dropLoc);
    if (!confirm(tr('Eliminare la sede "{nome}"? I tornei che la usavano tengono scritto dove si sono giocati.', { nome: loc.name }))) return;
    try {
      await apiFetch(`${base}/${loc.id}`, { method: 'DELETE' });
      toast(tr('Sede eliminata.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  }));
  $('#lCancel').addEventListener('click', () => fill(null));
  $('#lGeocode').addEventListener('click', async () => {
    const q = [$('#lAddr').value, $('#lCity').value].filter(Boolean).join(', ');
    if (!q) { toast('Inserisci prima indirizzo o città.'); return; }
    try {
      const hit = await geocode(q);
      if (!hit) { toast('Indirizzo non trovato.'); return; }
      $('#lLat').value = hit.lat;
      $('#lLng').value = hit.lng;
    } catch { toast('Geocoding non disponibile: inserisci le coordinate a mano.'); }
  });
  $('#locForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = $('#lId').value;
    const body = {
      name: $('#lName').value.trim(), city: $('#lCity').value.trim(),
      address: $('#lAddr').value.trim(), notes: $('#lNotes').value.trim(),
      latitude: num('#lLat'), longitude: num('#lLng'),
    };
    try {
      await apiFetch(id ? `${base}/${id}` : base, { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) });
      toast(id ? tr('Sede salvata.') : tr('Sede aggiunta.'));
      renderNegozio();
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
      <td><label class="bo-check">
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
        <label class="span-2">Nome<input id="tgName" required maxlength="60" placeholder="Habitué" /></label>
        <label>Colore<input id="tgColor" type="color" value="#c6ff3d" /></label>
        <label style="grid-column:1/-1">Descrizione<input id="tgDesc" maxlength="240" placeholder="A cosa serve questo tag" /></label>
        <button class="primary" type="submit" style="grid-column:1/-1">Crea tag</button>
      </form>
    </div>

    <div class="panel">
      <h3>Assegna agli iscritti</h3>
      <div class="toolbar" style="margin-bottom:10px">
        <label>Giocatori di
          <select id="tgEvent">${_tournaments.map(x =>
            `<option value="${x.id}" ${String(x.id) === String(_tagEventId) ? 'selected' : ''}>${esc(x.name)}</option>`).join('')
            || '<option value="">— nessun evento —</option>'}</select>
        </label>
        <label>Tag <select id="tgPick" ${tags.length ? '' : 'disabled'}>${tags.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join('')
          || `<option value="">${esc(tr('— nessun tag —'))}</option>`}</select></label>
        <button class="primary" id="tgAssign" type="button" ${tags.length ? '' : 'disabled'}>Assegna ai selezionati</button>
      </div>
      <table class="bo"><thead><tr>
        <th><label class="bo-check"><input type="checkbox" id="tgAll" title="Seleziona tutti" /> Giocatore</label></th><th>Tag</th>
      </tr></thead><tbody>${regRows}</tbody></table>
    </div>
    <div id="suspBox"></div>`;
  renderSuspensions();

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

  $('#tgAll')?.addEventListener('change', (e) => {
    $('#panel').querySelectorAll('[data-player]').forEach(b => { b.checked = e.target.checked; });
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

/* ── SOSPENSIONI ─────────────────────────────────────────
   Un giocatore tenuto fuori dagli eventi del negozio, con il motivo e fino a
   quando. Lo storico resta: anche le revocate servono a decidere la prossima. */
async function renderSuspensions() {
  const box = $('#suspBox');
  if (!box) return;
  let store;
  try { store = await myStore(); } catch {
    box.innerHTML = `<div class="panel" style="margin-top:16px"><h3>${esc(tr('Sospensioni'))}</h3>
      <p class="muted" style="margin:0">${esc(tr('Le sospensioni valgono per gli eventi di un negozio: apri il tuo dalla sezione Negozio.'))}</p></div>`;
    return;
  }
  const base = `/organizations/${encodeURIComponent(store.slug)}/suspensions`;
  const list = await apiFetch(base).catch(() => []);
  const state = (s) => {
    if (s.active) return `<span class="pill warn">${esc(tr('In corso'))}</span>`;
    if (s.lifted_at) return `<span class="muted">${esc(tr('Revocata il {data}', { data: fmtDate(s.lifted_at) }))}</span>`;
    return `<span class="muted">${esc(tr('Finita'))}</span>`;
  };
  const rows = list.map((s) => `<tr>
      <td>${esc(s.display_name)}<br><small class="muted">${esc(s.email)}</small></td>
      <td>${esc(s.reason)}</td>
      <td>${esc(fmtDate(s.created_at))} → ${s.ends_on ? esc(fmtDate(s.ends_on)) : esc(tr('finché non la revochi'))}
        ${s.created_by_name ? `<br><small class="muted">${esc(tr('da {nome}', { nome: s.created_by_name }))}</small>` : ''}</td>
      <td>${state(s)}</td>
      <td class="row-actions">${s.active ? `<button class="mini-button" data-lift="${s.id}" type="button">${esc(tr('Revoca'))}</button>` : ''}</td>
    </tr>`).join('')
    || `<tr><td colspan="5" class="muted">${esc(tr('Nessuna sospensione.'))}</td></tr>`;
  box.innerHTML = `<div class="panel" style="margin-top:16px">
    <div class="bo-head" style="margin-bottom:8px">
      <h3 style="margin:0">${esc(tr('Sospensioni'))}</h3>
      <button class="secondary" id="suspNew" type="button">${esc(tr('Sospendi un giocatore'))}</button>
    </div>
    <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr('Chi è sospeso non si iscrive agli eventi del negozio. Il motivo lo vede solo lo staff; il giocatore sa fino a quando.'))}</p>
    <table class="bo"><thead><tr><th>${esc(tr('Giocatore'))}</th><th>${esc(tr('Motivo'))}</th><th>${esc(tr('Periodo'))}</th><th></th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>
  </div>`;
  $('#suspNew').addEventListener('click', () => openSuspendDialog(store.slug, null, renderSuspensions));
  box.querySelectorAll('[data-lift]').forEach((b) => b.addEventListener('click', async () => {
    if (!confirm(tr('Revocare la sospensione? Potrà di nuovo iscriversi agli eventi del negozio.'))) return;
    try {
      await apiFetch(`${base}/${b.dataset.lift}/lift`, { method: 'POST' });
      toast(tr('Sospensione revocata.'));
      renderSuspensions();
    } catch (err) { toast('Errore: ' + err.message); }
  }));
}

/** Sospende un giocatore: dalla riga degli iscritti (si sa già chi) o dalla
    Community (si scrive l'email). */
function openSuspendDialog(slug, who, onDone) {
  const dlg = $('#boDialog');
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">${esc(tr('Sospensione'))}</span>
        <h2>${who ? esc(tr('Sospendi {nome}', { nome: who.name })) : esc(tr('Sospendi un giocatore'))}</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      <div class="bo-grid">
        ${who ? '' : `<label style="grid-column:1/-1">Email<input id="spEmail" type="email" required placeholder="${esc(tr('email del suo account'))}" /></label>`}
        <label style="grid-column:1/-1">${esc(tr('Motivo'))}<textarea id="spReason" required minlength="3" maxlength="500" style="min-height:70px" placeholder="${esc(tr('Lo vede solo lo staff del negozio'))}"></textarea></label>
        <label>${esc(tr('Fino al (compreso)'))}<input id="spUntil" type="date" /></label>
        <p class="muted" style="grid-column:1/-1;margin:0;font-size:.82rem">${esc(tr('Senza data vale finché non la revochi. Le iscrizioni che ha già restano: le trovi segnalate negli avvisi dei tornei.'))}</p>
      </div>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>${esc(tr('Annulla'))}</button>
        <button class="primary" id="spSubmit" type="button">${esc(tr('Sospendi'))}</button>
      </menu>
    </form>`;
  dlg.showModal();
  $('#spSubmit').addEventListener('click', async () => {
    const body = {
      reason: $('#spReason').value.trim(),
      ends_on: $('#spUntil').value || null,
      ...(who ? { user_id: who.user_id } : { email: $('#spEmail').value.trim() }),
    };
    if (body.reason.length < 3) { toast(tr('Scrivi il motivo.')); return; }
    if (!who && !body.email) { toast(tr("Scrivi l'email del giocatore.")); return; }
    try {
      await apiFetch(`/organizations/${encodeURIComponent(slug)}/suspensions`, { method: 'POST', body: JSON.stringify(body) });
      dlg.close();
      toast(tr('Giocatore sospeso.'));
      onDone?.();
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
let _editEvent = false;     // aprendo la manifestazione, portare subito al modulo di modifica
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
      <div class="bo-event-actions row-actions">
        <button class="mini-button" data-edit-event="${e.id}" type="button">✏ ${esc(tr('Modifica'))}</button>
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
    c.addEventListener('click', (e) => {
      _editEvent = Boolean(e.target.closest('[data-edit-event]'));
      _openEventId = c.dataset.openEvent;
      render();
    }));
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
        <button class="mini-button" id="evEdit" type="button">✏ ${esc(tr('Modifica'))}</button>
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
  // Il modulo sta in fondo, dopo tappe e staff: "Modifica" ci porta e mette il cursore sul nome.
  const goToEdit = () => {
    $('#evEditForm').scrollIntoView({ behavior: 'smooth', block: 'center' });
    $('#evEName').focus({ preventScroll: true });
  };
  $('#evEdit').addEventListener('click', goToEdit);
  if (_editEvent) { _editEvent = false; goToEdit(); }

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

/* ── IMPOSTAZIONI ────────────────────────────────────────
   Tutto quello che si era deciso alla creazione, modificabile. A torneo avviato
   alcune voci si bloccano (le decide il backend, LOCKED_AFTER_START): qui si
   disattivano con il motivo, così non si prova a cambiarle per niente. */
const LOCKED_AFTER_START = new Set([
  'game', 'format', 'best_of', 'starts_on', 'start_time', 'capacity', 'entry_fee',
  'pay_at_event', 'pay_stripe', 'pay_paypal', 'structure', 'swiss_rounds', 'top_cut_size',
  'decklist_required', 'check_in_required', 'team_size',
]);

async function renderImpostazioni() {
  const t = activeT();
  if (!t) { $('#panel').innerHTML = '<p class="empty">Apri un evento dalla lista.</p>'; return; }
  // Un torneo di un gioco oggi spento lo tiene: tra le scelte c'è anche il suo.
  const enabled = await loadGames();
  const games = enabled.some((g) => g.code === (t.game || 'mtg')) ? enabled
    : [...enabled, { code: t.game, name: gameLabel(t.game), formats: [], default_best_of: t.best_of || 3 }];
  const started = !['draft', 'published'].includes(t.status);
  const following = followingInSeries(t);
  const lock = (name) => (started && LOCKED_AFTER_START.has(name)
    ? `disabled title="${esc(tr('Non si cambia a torneo avviato'))}"` : '');
  const checked = (v) => (v ? 'checked' : '');
  const option = (value, label, current) =>
    `<option value="${esc(value)}"${String(value) === String(current) ? ' selected' : ''}>${esc(label)}</option>`;

  $('#panel').innerHTML = `
    <form id="setForm" class="settings-form">
      ${started ? `<p class="muted" style="margin:0 0 12px">${esc(tr('Il torneo è avviato: gioco, formato, date, capienza, quota, pagamenti e struttura non si cambiano più.'))}</p>` : ''}

      <div class="panel">
        <h3>${esc(tr('Generale'))}</h3>
        <div class="bo-grid">
          <label style="grid-column:1/-1">Nome<input id="sName" required value="${esc(t.name)}" /></label>
          <label ${games.length > 1 ? '' : 'style="display:none"'}>${esc(tr('Gioco'))}<select id="sGame" ${lock('game')}>
            ${games.map((g) => option(g.code, g.name, t.game || 'mtg')).join('')}</select></label>
          <label>Formato<input id="sFormat" list="sFormatList" value="${esc(t.format)}" ${lock('format')} />
            <datalist id="sFormatList"></datalist></label>
          <label>Tipo evento<select id="sType">
            ${EVENT_TYPES.map((x) => option(x.value, x.label, t.event_type)).join('')}</select></label>
          <label>Livello (REL)<select id="sRel">
            ${RELS.map((r) => option(r, r, t.rules_enforcement_level)).join('')}</select></label>
          <label style="grid-column:1/-1">${esc(tr('Descrizione'))}<textarea id="sDesc" style="min-height:70px">${esc(t.description || '')}</textarea></label>
        </div>
      </div>

      <div class="panel">
        <h3>${esc(tr('Quando e dove'))}</h3>
        <div class="bo-grid">
          <label>Data<input id="sDate" type="date" value="${esc(String(t.starts_on).slice(0, 10))}" ${lock('starts_on')} /></label>
          <label>Orario inizio<input id="sTime" type="time" value="${esc(t.start_time || '')}" ${lock('start_time')} /></label>
          <label style="grid-column:1/-1;display:none" id="sLocationWrap">${esc(tr('Sede'))}<select id="sLocation"></select></label>
          <label style="grid-column:1/-1" id="sVenueWrap">Luogo<input id="sVenue" value="${esc(t.venue || '')}" /></label>
        </div>
      </div>

      <div class="panel">
        <h3>${esc(tr('Iscrizioni e pagamento'))}</h3>
        <div class="bo-grid">
          <label>Capienza<input id="sCap" type="number" min="2" value="${t.capacity}" ${lock('capacity')} /></label>
          <label>Entry fee €<input id="sFee" type="number" min="0" step="0.01" value="${((t.entry_fee_cents || 0) / 100).toFixed(2)}" ${lock('entry_fee')} /></label>
          <label class="bo-check"><input id="sAtEvent" type="checkbox" ${checked(t.pay_at_event)} ${lock('pay_at_event')} /> Pagamento al banco</label>
          <label class="bo-check"><input id="sStripe" type="checkbox" ${checked(t.pay_stripe)} ${lock('pay_stripe')} /> Online Stripe</label>
          <label class="bo-check"><input id="sPaypal" type="checkbox" ${checked(t.pay_paypal)} ${lock('pay_paypal')} /> Online PayPal</label>
          <label class="bo-check"><input id="sEmail" type="checkbox" ${checked(t.email_notifications_enabled)} /> ${esc(tr('Notifiche email ai giocatori'))}</label>
          <label style="grid-column:1/-1">${esc(tr('Policy rimborsi'))}<textarea id="sRefund" style="min-height:60px">${esc(t.refund_policy || '')}</textarea></label>
        </div>
      </div>

      <div class="panel">
        <h3>${esc(tr('Svolgimento'))}</h3>
        <div class="bo-grid">
          <label>${esc(tr('Match in svizzera'))}<select id="sBestOf" ${lock('best_of')}>
            ${[1, 2, 3].map((n) => option(n, bestOfLabel(n), t.best_of || 3)).join('')}</select></label>
          <label>${esc(tr('Struttura'))}<select id="sStructure" ${lock('structure')}>
            ${option('swiss', tr('Svizzera'), t.structure)}
            ${option('swiss_topcut', tr('Svizzera + top cut'), t.structure)}
            ${option('single_elimination', tr('Eliminazione diretta'), t.structure)}
            ${option('registration_only', tr('Solo iscrizioni, senza turni'), t.structure)}</select></label>
          <label>${esc(tr('Formula'))}<select id="sTeam" ${lock('team_size')}>${[1, 2, 3].map((n) => `<option value="${n}"${n === (t.team_size || 1) ? ' selected' : ''}>${esc(n === 1 ? tr('Individuale') : tr('Squadre da {n}', { n }))}</option>`).join('')}</select></label>
          <label>${esc(tr('Turni svizzeri (0 = automatico)'))}<input id="sRounds" type="number" min="0" value="${t.swiss_rounds || 0}" ${lock('swiss_rounds')} /></label>
          <label>${esc(tr('Top cut'))}<select id="sCut" ${lock('top_cut_size')}>
            ${[2, 4, 8, 16].map((n) => option(n, `Top ${n}`, t.top_cut_size || 8)).join('')}</select></label>
          <label>${esc(tr('Minuti per turno'))}<input id="sTimer" type="number" min="1" max="120" value="${t.round_timer_minutes || 50}" /></label>
          <label class="bo-check"><input id="sIds" type="checkbox" ${checked(t.allow_intentional_draws !== false)} /> ${esc(tr('Patte intenzionali'))}</label>
          <label class="bo-check"><input id="sDeck" type="checkbox" ${checked(t.decklist_required)} ${lock('decklist_required')} /> Lista obbligatoria</label>
          <label class="bo-check"><input id="sCheckin" type="checkbox" ${checked(t.check_in_required)} ${lock('check_in_required')} /> ${esc(tr('Check-in obbligatorio'))}</label>
        </div>
      </div>

      <div class="settings-actions">
        ${following.length ? `<label class="bo-check" style="margin-right:auto"><input id="sSeries" type="checkbox" />
          ${esc(tr('Applica le modifiche anche ai {n} tornei successivi della serie', { n: following.length }))}</label>` : ''}
        <button class="primary" type="submit" id="sSave">${esc(tr('Salva le modifiche'))}</button>
      </div>
    </form>
    <div id="fieldsBox" style="margin-top:16px"></div>`;
  renderFieldsEditor(t);

  // Cambiando gioco cambiano i formati proposti e, a torneo non avviato, il formato dei match.
  const syncFormats = (fromUser) => {
    const game = games.find((g) => g.code === $('#sGame').value) || games[0];
    if (!game) return;
    $('#sFormatList').innerHTML = game.formats.map((f) => `<option value="${esc(f)}"></option>`).join('');
    if (fromUser) {
      if (!game.formats.includes($('#sFormat').value)) $('#sFormat').value = game.formats[0];
      $('#sBestOf').value = String(game.default_best_of);
    }
  };
  $('#sGame').addEventListener('change', () => syncFormats(true));
  syncFormats(false);
  fillLocationChoices('#sLocation', '#sLocationWrap', '#sVenueWrap', t.location_id ?? undefined);

  $('#setForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    // Si manda tutto: il backend applica solo quello che è davvero cambiato.
    const body = {
      name: $('#sName').value.trim(),
      game: $('#sGame').value,
      format: $('#sFormat').value.trim(),
      event_type: $('#sType').value,
      rules_enforcement_level: $('#sRel').value,
      description: $('#sDesc').value.trim(),
      starts_on: $('#sDate').value,
      start_time: $('#sTime').value || null,
      // 0 toglie la sede; con una sede il luogo scritto si svuota e vale il suo.
      location_id: +$('#sLocation').value || 0,
      venue: $('#sLocation').value ? '' : $('#sVenue').value.trim(),
      capacity: +$('#sCap').value,
      entry_fee_cents: Math.round((+$('#sFee').value || 0) * 100),
      pay_at_event: $('#sAtEvent').checked,
      pay_stripe: $('#sStripe').checked,
      pay_paypal: $('#sPaypal').checked,
      email_notifications_enabled: $('#sEmail').checked,
      refund_policy: $('#sRefund').value.trim(),
      best_of: +$('#sBestOf').value,
      structure: $('#sStructure').value,
      team_size: +$('#sTeam').value || 1,
      swiss_rounds: +$('#sRounds').value || 0,
      top_cut_size: +$('#sCut').value,
      round_timer_minutes: +$('#sTimer').value,
      allow_intentional_draws: $('#sIds').checked,
      decklist_required: $('#sDeck').checked,
      check_in_required: $('#sCheckin').checked,
    };
    const save = $('#sSave');
    save.disabled = true;
    try {
      const series = $('#sSeries')?.checked;
      const saved = await apiFetch(`/tournaments/${t.id}${series ? '?series=true' : ''}`, { method: 'PATCH', body: JSON.stringify(body) });
      if (series && saved.series_updated != null) {
        toast(tr('Salvato, anche su {n} tornei della serie.', { n: saved.series_updated })
          + (saved.series_skipped.length ? ' ' + tr('Non cambiati: {elenco}', { elenco: saved.series_skipped.join('; ') }) : ''));
      } else {
        toast(tr('Impostazioni salvate.'));
      }
      await loadTournaments();
      render();
    } catch (err) {
      toast('Errore: ' + err.message);
      save.disabled = false;
    }
  });
}

/* ── DOMANDE ALL'ISCRIZIONE ──────────────────────────────
   Quello che il torneo chiede in più a chi si iscrive. Si salvano tutte
   insieme: le domande che restano tengono le risposte già date. */
const FIELD_KINDS = [
  { value: 'text', label: 'Testo libero' },
  { value: 'choice', label: 'Scelta tra opzioni' },
  { value: 'checkbox', label: 'Casella da spuntare' },
];

async function renderFieldsEditor(t) {
  const box = $('#fieldsBox');
  if (!box) return;
  const saved = await apiFetch(`/tournaments/${t.id}/fields`).catch(() => []);
  const toDraft = (list) => list.map((f) => ({ id: f.id, label: f.label, kind: f.kind, options: f.options.join('\n'), required: f.required }));
  let draft = toDraft(saved);
  let savedIds = new Set(saved.map((f) => f.id));

  const draw = () => {
    box.innerHTML = `<div class="panel">
      <h3>${esc(tr("Domande all'iscrizione"))}</h3>
      <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr('Le vede chi si iscrive, le risposte le trovi nella scheda Giocatori e nel CSV. Una casella obbligatoria va spuntata per iscriversi: serve per "accetto il regolamento".'))}</p>
      ${draft.map((f, i) => `<div class="field-row" data-i="${i}">
        <input data-k="label" value="${esc(f.label)}" maxlength="160" placeholder="${esc(tr('Domanda'))}" />
        <select data-k="kind">${FIELD_KINDS.map((k) => `<option value="${k.value}"${k.value === f.kind ? ' selected' : ''}>${esc(tr(k.label))}</option>`).join('')}</select>
        <label class="bo-check"><input type="checkbox" data-k="required"${f.required ? ' checked' : ''} /> ${esc(tr('Obbligatoria'))}</label>
        <div class="row-actions">
          <button class="mini-button" data-move="-1" type="button" ${i === 0 ? 'disabled' : ''} aria-label="${esc(tr('Su'))}">↑</button>
          <button class="mini-button" data-move="1" type="button" ${i === draft.length - 1 ? 'disabled' : ''} aria-label="${esc(tr('Giù'))}">↓</button>
          <button class="mini-button" data-remove type="button" style="color:var(--danger)">${esc(tr('Togli'))}</button>
        </div>
        ${f.kind === 'choice' ? `<textarea data-k="options" placeholder="${esc(tr('Una scelta per riga'))}">${esc(f.options)}</textarea>` : ''}
      </div>`).join('') || `<p class="muted">${esc(tr("Nessuna domanda: all'iscrizione si chiede solo l'ID dell'editore."))}</p>`}
      <div class="row-actions" style="margin-top:8px">
        <button class="secondary" id="fAdd" type="button">${esc(tr('+ Aggiungi domanda'))}</button>
        <button class="primary" id="fSave" type="button">${esc(tr('Salva le domande'))}</button>
      </div>
    </div>`;

    box.querySelectorAll('.field-row').forEach((row) => {
      const f = draft[+row.dataset.i];
      row.querySelectorAll('[data-k]').forEach((el) => el.addEventListener(el.type === 'checkbox' || el.tagName === 'SELECT' ? 'change' : 'input', () => {
        f[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value;
        if (el.dataset.k === 'kind') draw();   // le opzioni compaiono solo per le scelte
      }));
      row.querySelectorAll('[data-move]').forEach((b) => b.addEventListener('click', () => {
        const i = +row.dataset.i;
        const j = i + +b.dataset.move;
        [draft[i], draft[j]] = [draft[j], draft[i]];
        draw();
      }));
      row.querySelector('[data-remove]').addEventListener('click', () => { draft.splice(+row.dataset.i, 1); draw(); });
    });
    $('#fAdd').addEventListener('click', () => { draft.push({ id: null, label: '', kind: 'text', options: '', required: false }); draw(); });
    $('#fSave').addEventListener('click', async () => {
      const removed = [...savedIds].filter((id) => !draft.some((f) => f.id === id));
      if (removed.length && !confirm(tr('Le risposte alle domande tolte vanno perse. Continuare?'))) return;
      const body = draft.filter((f) => f.label.trim()).map((f) => ({
        id: f.id, label: f.label.trim(), kind: f.kind, required: f.required,
        options: f.kind === 'choice' ? f.options.split('\n') : [],
      }));
      try {
        const result = await apiFetch(`/tournaments/${t.id}/fields`, { method: 'PUT', body: JSON.stringify(body) });
        draft = toDraft(result);
        savedIds = new Set(result.map((f) => f.id));
        toast(tr('Domande salvate.'));
        draw();
      } catch (err) { toast('Errore: ' + err.message); }
    });
  };
  draw();
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
