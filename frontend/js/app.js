/**
 * app.js — Home "Scopri": rail per tipo di contenuto invece di una lista piatta.
 *
 * Ogni rail ha i suoi chip di filtro rapido e un "tutti →" che porta alla ricerca
 * completa con i filtri già impostati. Chi sa cosa cerca va dritto su events.html;
 * chi non lo sa, scorre.
 */
import {
  apiGet, askPosition, esc, eventTile, forgetPosition, placeholder,
  savedPosition, seriesTile, storeTile, updateAuthNav,
} from './catalog.js';

const $ = (s) => document.querySelector(s);

/* Ogni voce è un chip: etichetta + parametri di ricerca. Il primo è il default. */
const EVENT_RAILS = [
  { label: 'Tutti',        params: { days: 30 } },
  { label: 'Questa settimana', params: { days: 7 } },
  { label: 'RCQ',          params: { event_types: 'rcq', days: 180 } },
  { label: 'Prerelease',   params: { event_types: 'prerelease', days: 60 } },
  { label: 'Competitivi',  params: { rel: 'Competitive,Professional', days: 90 } },
];

const STORE_RAILS = [
  { label: 'Tutti',      params: {} },
  { label: 'Vicino a me', params: { near: true } },
  { label: 'Premium',    params: { premium_only: true } },
];

let _position = savedPosition();

function query(params) {
  const q = new URLSearchParams({ status: 'published', ...params });
  if (params.near) {
    q.delete('near');
    if (_position) { q.set('near_lat', _position.lat); q.set('near_lng', _position.lng); q.set('radius_km', 100); }
  }
  return q.toString();
}

/** Chip di una rail: aria-pressed segna l'attivo, il click ricarica solo quella rail. */
function renderChips(host, rails, active, onPick) {
  host.innerHTML = rails.map((r, i) => `
    <button class="chip" type="button" data-i="${i}" aria-pressed="${i === active}">${esc(r.label)}</button>
  `).join('');
  host.querySelectorAll('[data-i]').forEach((btn) =>
    btn.addEventListener('click', () => onPick(+btn.dataset.i)));
}

async function loadEvents(index = 0) {
  const host = $('#eventsRail');
  renderChips($('#eventsChips'), EVENT_RAILS, index, loadEvents);
  placeholder(host, 'Caricamento…');
  const rail = EVENT_RAILS[index];
  try {
    const events = await apiGet('/tournaments?' + query(rail.params));
    if (!events.length) { placeholder(host, 'Nessun evento in questa selezione.'); return; }
    host.innerHTML = events.slice(0, 12).map(eventTile).join('');
  } catch (err) {
    placeholder(host, `Impossibile caricare gli eventi: ${err.message}`);
  }
  const q = new URLSearchParams(rail.params);
  $('#eventsAll').href = 'events.html?' + q.toString();
}

async function loadStores(index = 0) {
  const host = $('#storesRail');
  renderChips($('#storesChips'), STORE_RAILS, index, loadStores);
  placeholder(host, 'Caricamento…');
  const params = { ...STORE_RAILS[index].params };
  const q = new URLSearchParams();
  if (params.premium_only) q.set('premium_only', 'true');
  if (params.near && _position) {
    q.set('near_lat', _position.lat); q.set('near_lng', _position.lng); q.set('radius_km', 100);
  }
  try {
    const stores = await apiGet('/organizations?' + q.toString());
    if (!stores.length) {
      placeholder(host, params.near && !_position
        ? 'Concedi la posizione per vedere i negozi vicini.'
        : 'Nessun negozio in questa selezione.');
      return;
    }
    host.innerHTML = stores.slice(0, 12).map(storeTile).join('');
  } catch (err) {
    placeholder(host, `Impossibile caricare i negozi: ${err.message}`);
  }
}

async function loadSeries() {
  const host = $('#seriesRail');
  placeholder(host, 'Caricamento…');
  try {
    const series = await apiGet('/seasons/public');
    if (!series.length) {
      // Senza circuiti la rail sparisce: meglio niente che una sezione vuota.
      $('#seriesSection').style.display = 'none';
      return;
    }
    host.innerHTML = series.slice(0, 12).map(seriesTile).join('');
  } catch {
    $('#seriesSection').style.display = 'none';
  }
}

/* ── Posizione ─────────────────────────────────────────────── */

function renderGeo() {
  const el = $('#geoBar');
  el.innerHTML = _position
    ? `<span class="dist-badge">📍 Posizione attiva</span>
       <button class="chip" id="geoForget" type="button">Dimentica</button>`
    : `<button class="chip" id="geoAsk" type="button">📍 Usa la mia posizione</button>
       <span style="color:var(--muted);font-size:.82rem">per ordinare eventi e negozi per distanza</span>`;
  $('#geoAsk')?.addEventListener('click', async () => {
    try {
      _position = await askPosition();
      renderGeo();
      loadEvents(0);
      loadStores(1);
    } catch (err) {
      el.insertAdjacentHTML('beforeend', `<span style="color:var(--danger);font-size:.82rem">${esc(err.message)}</span>`);
    }
  });
  $('#geoForget')?.addEventListener('click', () => {
    forgetPosition();
    _position = null;
    renderGeo();
    loadEvents(0);
    loadStores(0);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  updateAuthNav();
  renderGeo();
  loadEvents(0);
  loadStores(_position ? 1 : 0);
  loadSeries();
});
