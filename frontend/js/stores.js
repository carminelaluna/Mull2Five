/**
 * stores.js — Elenco negozi, con filtro rapido e ricerca per nome o città.
 */
import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import {
  apiGet, askPosition, esc, placeholder, savedPosition, storeTile, updateAuthNav,
} from './catalog.js';

const $ = (s) => document.querySelector(s);

const RAILS = [
  { label: 'Tutti',       params: {} },
  { label: 'Vicino a me', params: { near: true } },
  { label: 'Premium',     params: { premium_only: 'true' } },
];

let _position = savedPosition();
let _active = _position ? 1 : 0;
let _all = [];

function renderChips() {
  $('#storeChips').innerHTML = RAILS.map((r, i) =>
    `<button class="chip" type="button" data-i="${i}" aria-pressed="${i === _active}">${esc(r.label)}</button>`,
  ).join('');
  $('#storeChips').querySelectorAll('[data-i]').forEach((btn) =>
    btn.addEventListener('click', async () => {
      const index = +btn.dataset.i;
      if (RAILS[index].params.near && !_position) {
        try { _position = await askPosition(); }
        catch (err) { placeholder($('#storeGrid'), err.message); return; }
      }
      _active = index;
      load();
    }));
}

/* Il filtro testuale lavora su quanto già scaricato: la lista dei negozi di un
   tenant è corta, non vale un giro sul server a ogni tasto. */
function draw() {
  const q = ($('#storeSearch').value || '').toLowerCase();
  const items = _all.filter((o) => `${o.name} ${o.city} ${o.address}`.toLowerCase().includes(q));
  const grid = $('#storeGrid');
  if (!items.length) { placeholder(grid, 'Nessun negozio trovato.'); return; }
  grid.innerHTML = items.map(storeTile).join('');
}

async function load() {
  renderChips();
  placeholder($('#storeGrid'), 'Caricamento…');
  const params = RAILS[_active].params;
  const q = new URLSearchParams();
  if (params.premium_only) q.set('premium_only', 'true');
  if (params.near && _position) {
    q.set('near_lat', _position.lat);
    q.set('near_lng', _position.lng);
    q.set('radius_km', 250);
  }
  try {
    _all = await apiGet('/organizations?' + q.toString());
    draw();
  } catch (err) {
    placeholder($('#storeGrid'), `Impossibile caricare i negozi: ${err.message}`);
  }
}

onReady(() => {
  updateAuthNav();
  $('#storeSearch').addEventListener('input', draw);
  load();
});
