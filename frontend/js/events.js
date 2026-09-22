/**
 * events.js — Ricerca eventi con facet a sinistra e risultati a tabella.
 *
 * Lo stato dei filtri vive nella querystring: ogni ricerca è un link
 * condivisibile e il tasto indietro del browser funziona. "Salva ricerca"
 * memorizza quella querystring in locale.
 */
import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { gameLabel, loadGames } from './games.js';
import { t as tr } from './i18n.js';
import {
  DATE_RANGES, DISTANCES, EVENT_TYPES, FORMATS, RELS,
  apiGet, askPosition, esc, fmtDate, fmtMoney, savedPosition, typeLabel, updateAuthNav,
} from './catalog.js';

const $ = (s) => document.querySelector(s);
const SAVED_KEY = 'mull2five-saved-searches-v1';
const PER_PAGE = 25;

let _page = 1;
let _position = savedPosition();

/* ── Stato = querystring ───────────────────────────────────── */

function readState() {
  const q = new URLSearchParams(location.search);
  const list = (key) => (q.get(key) || '').split(',').filter(Boolean);
  return {
    games: list('games'),
    formats: list('formats'),
    event_types: list('event_types'),
    rel: list('rel'),
    days: +q.get('days') || 14,
    radius_km: q.get('radius_km') ? +q.get('radius_km') : null,
    name: q.get('name') || '',
    // "Storico" non e una pagina a parte: e questa ricerca sui tornei conclusi.
    stato: q.get('stato') === 'conclusi' ? 'conclusi' : 'programma',
    luogo: ['online', 'negozio'].includes(q.get('luogo')) ? q.get('luogo') : '',
  };
}

const LUOGHI = [
  { value: '', label: 'Ovunque' },
  { value: 'negozio', label: 'Nei negozi' },
  { value: 'online', label: 'Online' },
];

const STATI = [
  { value: 'programma', label: 'In programma' },
  { value: 'conclusi',  label: 'Conclusi' },
];

function writeState(state, { replace = false } = {}) {
  const q = new URLSearchParams();
  for (const key of ['games', 'formats', 'event_types', 'rel']) {
    if (state[key].length) q.set(key, state[key].join(','));
  }
  q.set('days', state.days);
  if (state.radius_km) q.set('radius_km', state.radius_km);
  if (state.name) q.set('name', state.name);
  if (state.stato === 'conclusi') q.set('stato', 'conclusi');
  if (state.luogo) q.set('luogo', state.luogo);
  const url = `${location.pathname}?${q}`;
  if (replace) history.replaceState(null, '', url);
  else history.pushState(null, '', url);
  return q;
}

// I giochi arrivano dal backend all'avvio: formati e filtro dipendono da loro.
let _games = [];

/** I formati da proporre: quelli dei giochi scelti, o di tutti se non se ne è scelto nessuno. */
function formatChoices(state) {
  const games = state.games.length ? _games.filter((g) => state.games.includes(g.code)) : _games;
  const formats = [...new Set(games.flatMap((g) => g.formats))];
  // Senza catalogo (backend irraggiungibile) restano i formati di Magic di sempre.
  return formats.length ? formats : FORMATS;
}

function toggle(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/* ── Facet ─────────────────────────────────────────────────── */

function checkboxes(title, key, options, state, { limit = 6 } = {}) {
  const shown = state[`_more_${key}`] ? options : options.slice(0, limit);
  const rows = shown.map(({ value, label }) => `
    <label>
      <input type="checkbox" data-facet="${key}" value="${esc(value)}"
             ${state[key].includes(value) ? 'checked' : ''} />
      ${esc(label)}
    </label>`).join('');
  const more = options.length > limit
    ? `<button class="facet-more" type="button" data-more="${key}">
         ${state[`_more_${key}`] ? 'Mostra meno' : `Mostra altri ${options.length - limit}`}
       </button>`
    : '';
  return `<div class="facet"><h3>${esc(title)}</h3>${rows}${more}</div>`;
}

function radios(title, key, options, current) {
  const rows = options.map(({ value, label }) => `
    <label>
      <input type="radio" name="${key}" data-facet="${key}" value="${value}"
             ${String(current) === String(value) ? 'checked' : ''} />
      ${esc(label)}
    </label>`).join('');
  return `<div class="facet"><h3>${esc(title)}</h3>${rows}</div>`;
}

function renderFacets(state) {
  const geo = _position
    ? radios('Distanza', 'radius_km', DISTANCES, state.radius_km || '')
    : `<div class="facet"><h3>Distanza</h3>
         <button class="chip" id="askGeo" type="button">📍 Usa la mia posizione</button>
         <p style="color:var(--muted);font-size:.78rem;margin:8px 0 0">
           Serve la posizione per filtrare per distanza.</p>
       </div>`;

  $('#facets').innerHTML = `
    <div class="facet">
      <h3>Nome</h3>
      <input id="facetName" placeholder="Cerca…" value="${esc(state.name)}" style="width:100%" />
    </div>
    ${radios('Stato', 'stato', STATI, state.stato)}
    ${radios('Dove si gioca', 'luogo', LUOGHI, state.luogo)}
    ${_games.length > 1 ? checkboxes('Gioco', 'games', _games.map((g) => ({ value: g.code, label: gameLabel(g.code) })), state) : ''}
    ${checkboxes('Tipo di evento', 'event_types', EVENT_TYPES, state)}
    ${checkboxes('Formato', 'formats', formatChoices(state).map((f) => ({ value: f, label: f })), state)}
    ${checkboxes('Livello (REL)', 'rel', RELS.map((r) => ({ value: r, label: r })), state, { limit: 3 })}
    ${state.stato === 'conclusi' ? '' : radios('Periodo', 'days', DATE_RANGES, state.days)}
    ${geo}
    <div class="facet">
      <button class="secondary" id="resetFilters" type="button" style="width:100%">Azzera filtri</button>
      <button class="primary" id="saveSearch" type="button" style="width:100%;margin-top:6px">
        ☆ Salva ricerca
      </button>
    </div>`;

  $('#facets').querySelectorAll('[data-facet]').forEach((input) =>
    input.addEventListener('change', () => {
      const key = input.dataset.facet;
      const next = { ...state };
      if (input.type === 'checkbox') next[key] = toggle(state[key], input.value);
      else if (key === 'stato' || key === 'luogo') next[key] = input.value;
      else next[key] = key === 'days' ? +input.value : +input.value || null;
      _page = 1;
      writeState(next);
      run();
    }));

  $('#facets').querySelectorAll('[data-more]').forEach((btn) =>
    btn.addEventListener('click', () => {
      state[`_more_${btn.dataset.more}`] = !state[`_more_${btn.dataset.more}`];
      renderFacets(state);
    }));

  let typing;
  $('#facetName').addEventListener('input', (e) => {
    clearTimeout(typing);
    typing = setTimeout(() => {
      _page = 1;
      writeState({ ...state, name: e.target.value.trim() }, { replace: true });
      run({ keepFocus: true });
    }, 300);
  });

  $('#resetFilters').addEventListener('click', () => {
    _page = 1;
    history.pushState(null, '', location.pathname);
    run();
  });
  $('#saveSearch').addEventListener('click', saveCurrentSearch);
  $('#askGeo')?.addEventListener('click', async () => {
    try {
      _position = await askPosition();
      run();
    } catch (err) {
      $('#askGeo').insertAdjacentHTML('afterend',
        `<p style="color:var(--danger);font-size:.78rem">${esc(err.message)}</p>`);
    }
  });
}

/* ── Riassunto in linguaggio naturale ──────────────────────── */

function summarize(state, total) {
  const kinds = state.event_types.length
    ? state.event_types.map(typeLabel).join(', ')
    : 'eventi di ogni tipo';
  const formats = state.formats.length ? ` in ${state.formats.join(', ')}` : '';
  const rel = state.rel.length ? ` a livello ${state.rel.join('/')}` : '';
  const near = state.radius_km && _position ? `entro <b>${state.radius_km} km</b> da te` : 'ovunque';
  const where = state.luogo === 'online' ? '<b>online</b>' : near + (state.luogo === 'negozio' ? ' nei negozi' : '');
  if (state.stato === 'conclusi') {
    $('#filterSummary').innerHTML =
      `<b>${esc(total)}</b> tornei <b>conclusi</b>: <b>${esc(kinds)}${esc(formats)}${esc(rel)}</b> ${where}.`;
    return;
  }
  const when = DATE_RANGES.find((d) => d.value === state.days)?.label.toLowerCase() || `${state.days} giorni`;
  $('#filterSummary').innerHTML =
    `<b>${esc(total)}</b> risultati: <b>${esc(kinds)}${esc(formats)}${esc(rel)}</b> ${where}, nei prossimi <b>${esc(when)}</b>.`;
}

/* ── Risultati ─────────────────────────────────────────────── */

function renderRows(events) {
  const body = $('#resultsBody');
  if (!events.length) {
    body.innerHTML = '<tr><td colspan="5" class="muted">Nessun evento con questi filtri.</td></tr>';
    $('#resultsPagination').innerHTML = '';
    return;
  }
  const start = (_page - 1) * PER_PAGE;
  const page = events.slice(start, start + PER_PAGE);
  body.innerHTML = page.map((t) => `
    <tr data-id="${t.id}" data-done="${t.status === 'completed' ? '1' : ''}">
      <td class="col-name">
        ${esc(t.name)}
        <span class="col-sub">
          <span class="game-badge game-${esc(t.game || 'mtg')}">${esc(gameLabel(t.game))}</span>
          <span class="type-badge type-${esc(t.event_type || 'other')}">${esc(typeLabel(t.event_type))}</span>
          ${esc(t.rules_enforcement_level || '')}
        </span>
      </td>
      <td>${fmtDate(t.starts_on)}<span class="col-sub">${esc(t.start_time || '')}</span></td>
      <td>${esc(t.format)}</td>
      <td>${t.is_online ? '<span class="online-badge">Online</span>' : esc(t.venue || t.organization_name || '—')}
        ${t.distance_km != null ? `<span class="col-sub dist-badge">${t.distance_km} km</span>` : ''}</td>
      <td>${t.entry_fee_cents ? fmtMoney(t.entry_fee_cents) : 'Gratis'}
        <span class="col-sub">${t.source === 'wizards' ? esc(tr('Iscrizione in negozio'))
          : `${Math.max((t.capacity || 0) - (t.registered_players || 0), 0)} posti`}</span></td>
    </tr>`).join('');
  body.querySelectorAll('[data-id]').forEach((tr) =>
    tr.addEventListener('click', () => {
      location.href = tr.dataset.done === '1'
        ? `history.html?t=${tr.dataset.id}`
        : `event.html?id=${tr.dataset.id}`;
    }));

  const pages = Math.ceil(events.length / PER_PAGE);
  $('#resultsPagination').innerHTML = pages <= 1 ? '' : `
    <button class="secondary" ${_page <= 1 ? 'disabled' : ''} id="prevPage">← Prec</button>
    <span class="page-info">${_page} / ${pages}</span>
    <button class="secondary" ${_page >= pages ? 'disabled' : ''} id="nextPage">Succ →</button>`;
  $('#prevPage')?.addEventListener('click', () => { _page--; run(); });
  $('#nextPage')?.addEventListener('click', () => { _page++; run(); });
}

async function run({ keepFocus = false } = {}) {
  const state = readState();
  if (!keepFocus) renderFacets(state);
  renderSaved();

  const q = new URLSearchParams(location.search);
  q.delete('stato');
  q.delete('luogo');
  if (state.luogo) q.set('online', state.luogo === 'online' ? 'true' : 'false');
  const finished = state.stato === 'conclusi';
  q.set('status', finished ? 'completed' : 'published,running');
  // Una finestra "nei prossimi N giorni" non ha senso guardando indietro.
  if (finished) q.delete('days');
  if (state.radius_km && _position) {
    q.set('near_lat', _position.lat);
    q.set('near_lng', _position.lng);
  } else {
    q.delete('radius_km');
  }

  const body = $('#resultsBody');
  // Righe finte finché arrivano i risultati: la tabella non cambia altezza di colpo.
  body.innerHTML = Array.from({ length: 4 }, () => `<tr class="skeleton" aria-hidden="true"><td colspan="5">
    <span class="skeleton-line wide"></span><span class="skeleton-line short"></span></td></tr>`).join('');
  try {
    const events = await apiGet('/tournaments?' + q.toString());
    summarize(state, events.length);
    renderRows(events);
  } catch (err) {
    body.innerHTML = `<tr><td colspan="5" class="muted">Errore: ${esc(err.message)}</td></tr>`;
  }
}

/* ── Ricerche salvate ──────────────────────────────────────── */

function readSaved() {
  try { return JSON.parse(localStorage.getItem(SAVED_KEY) || '[]'); } catch { return []; }
}

function writeSaved(list) {
  try { localStorage.setItem(SAVED_KEY, JSON.stringify(list.slice(0, 8))); } catch { /* modalità privata */ }
}

function describe(state) {
  const parts = [];
  if (state.event_types.length) parts.push(state.event_types.map(typeLabel).join('/'));
  if (state.formats.length) parts.push(state.formats.join('/'));
  if (state.radius_km) parts.push(`${state.radius_km} km`);
  parts.push(DATE_RANGES.find((d) => d.value === state.days)?.label || `${state.days} gg`);
  return parts.join(' · ');
}

function saveCurrentSearch() {
  const search = location.search || '?days=14';
  const list = readSaved().filter((s) => s.search !== search);
  list.unshift({ search, label: describe(readState()) });
  writeSaved(list);
  renderSaved();
}

function renderSaved() {
  const list = readSaved();
  const host = $('#savedFilters');
  if (!list.length) { host.innerHTML = ''; return; }
  host.innerHTML = '<span style="color:var(--muted);font-size:.82rem">Ricerche salvate:</span>' +
    list.map((s, i) => `
      <span class="chip saved-chip">
        <a href="${esc(s.search)}" style="color:inherit;text-decoration:none">${esc(s.label)}</a>
        <button type="button" data-drop="${i}" title="Rimuovi">×</button>
      </span>`).join('');
  host.querySelectorAll('[data-drop]').forEach((btn) =>
    btn.addEventListener('click', () => {
      const list2 = readSaved();
      list2.splice(+btn.dataset.drop, 1);
      writeSaved(list2);
      renderSaved();
    }));
}

window.addEventListener('popstate', () => { _page = 1; run(); });

onReady(async () => {
  updateAuthNav();
  _games = await loadGames();
  run();
});
