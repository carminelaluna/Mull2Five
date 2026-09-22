/**
 * decklists.js — L'archivio pubblico delle liste.
 *
 * Le liste dei tornei conclusi che le hanno rese pubbliche: si filtrano per
 * formato, archetipo, carta, periodo e posizione, e sopra c'è il metagame delle
 * stesse liste. Lo stato dei filtri vive nella querystring, come nella ricerca
 * eventi: ogni ricerca è un link da condividere.
 */
import './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { TOKEN_KEY, apiGet, esc, fmtDate, getSession, updateAuthNav } from './catalog.js';
import { renderDeck } from './deck-view.js';
import { loadGames } from './games.js';
import { t as tr } from './i18n.js';

const $ = (selector) => document.querySelector(selector);
const PER_PAGE = 25;
const DEFAULT_DAYS = 90;
const PERIODS = [
  { value: 30, label: 'Ultimi 30 giorni' },
  { value: 90, label: 'Ultimi 3 mesi' },
  { value: 365, label: 'Ultimo anno' },
  { value: 0, label: 'Da sempre' },
];
const TOPS = [
  { value: 0, label: 'Tutte' },
  { value: 8, label: 'Top 8' },
  { value: 1, label: 'Solo i vincitori' },
];

let _formats = [];
let _open = null;   // la lista aperta nella finestra

function toast(msg) {
  const el = $('#toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove('show'), 3200);
}

/* ── Stato = querystring ───────────────────────────────────── */

function readState() {
  const q = new URLSearchParams(location.search);
  return {
    format: q.get('format') || '',
    archetype: q.get('archetype') || '',
    card: q.get('card') || '',
    days: q.has('days') ? +q.get('days') || 0 : DEFAULT_DAYS,
    top: +q.get('top') || 0,
    page: Math.max(1, +q.get('page') || 1),
  };
}

function writeState(state, { replace = false } = {}) {
  const q = new URLSearchParams();
  if (state.format) q.set('format', state.format);
  if (state.archetype) q.set('archetype', state.archetype);
  if (state.card) q.set('card', state.card);
  if (state.days !== DEFAULT_DAYS) q.set('days', state.days);
  if (state.top) q.set('top', state.top);
  if (state.page > 1) q.set('page', state.page);
  const url = q.toString() ? `${location.pathname}?${q}` : location.pathname;
  if (replace) history.replaceState(null, '', url);
  else history.pushState(null, '', url);
}

function update(changes, options = {}) {
  writeState({ ...readState(), page: 1, ...changes }, options);
  run(options);
}

/* ── Filtri ────────────────────────────────────────────────── */

function radios(title, key, options, current) {
  const rows = options.map(({ value, label }) => `
    <label>
      <input type="radio" name="${key}" data-facet="${key}" value="${esc(value)}"
             ${String(current) === String(value) ? 'checked' : ''} />
      ${esc(tr(label))}
    </label>`).join('');
  return `<div class="facet"><h3>${esc(tr(title))}</h3>${rows}</div>`;
}

function textFacet(title, key, value, placeholder) {
  return `<div class="facet">
    <h3>${esc(tr(title))}</h3>
    <input data-text="${key}" placeholder="${esc(tr(placeholder))}" value="${esc(value)}" style="width:100%" />
  </div>`;
}

function renderFacets(state) {
  const formats = [{ value: '', label: 'Tutti' }, ..._formats.map((f) => ({ value: f, label: f }))];
  $('#facets').innerHTML = `
    ${radios('Formato', 'format', formats, state.format)}
    ${textFacet('Archetipo', 'archetype', state.archetype, 'Es. Burn')}
    ${textFacet('Carta', 'card', state.card, 'Es. Lightning Bolt')}
    ${radios('Periodo', 'days', PERIODS, state.days)}
    ${radios('Posizione', 'top', TOPS, state.top)}
    <div class="facet">
      <button class="secondary" id="resetFilters" type="button" style="width:100%">${esc(tr('Azzera filtri'))}</button>
    </div>`;
  $('#facets').querySelectorAll('[data-facet]').forEach((input) => input.addEventListener('change', () => {
    const key = input.dataset.facet;
    update({ [key]: key === 'format' ? input.value : +input.value });
  }));
  $('#facets').querySelectorAll('[data-text]').forEach((input) => {
    let typing;
    input.addEventListener('input', () => {
      clearTimeout(typing);
      typing = setTimeout(() => update({ [input.dataset.text]: input.value.trim() }, { replace: true, keepFacets: true }), 350);
    });
  });
  $('#resetFilters').addEventListener('click', () => {
    history.pushState(null, '', location.pathname);
    run();
  });
}

/* ── Metagame ──────────────────────────────────────────────── */

async function renderMeta(state) {
  const panel = $('#metaPanel');
  const q = new URLSearchParams({ days: state.days });
  if (state.format) q.set('format', state.format);
  let meta;
  try { meta = await apiGet(`/decklists/meta?${q}`); } catch { panel.hidden = true; return; }
  if (!meta.total_lists) { panel.hidden = true; return; }
  const maxShare = Math.max(...meta.archetypes.map((a) => a.share), 1);
  const archetypes = meta.archetypes.slice(0, 10).map((a) => `
    <tr>
      <td>
        <button class="link-button" data-archetype="${esc(a.archetype === 'Non indicato' ? '' : a.archetype)}" type="button">${esc(a.archetype)}</button>
        <div class="meta-bar" style="width:${Math.round(a.share / maxShare * 100)}%"></div>
      </td>
      <td class="num">${a.share}%</td>
      <td class="num">${a.lists}</td>
      <td class="num">${a.top8}</td>
    </tr>`).join('');
  const cards = meta.top_cards.slice(0, 10).map((c) => `
    <tr>
      <td><button class="link-button" data-card="${esc(c.name)}" type="button">${esc(c.name)}</button></td>
      <td class="num">${c.share}%</td>
      <td class="num">${c.copies}</td>
    </tr>`).join('');
  panel.innerHTML = `
    <div class="archive-meta-head">
      <h3>${esc(tr('Metagame'))}</h3>
      <span class="muted">${esc(tr('{n} liste', { n: meta.total_lists }))}${state.format ? ` · ${esc(state.format)}` : ''}</span>
    </div>
    <div class="archive-meta-grid">
      <table class="meta-table">
        <thead><tr><th>${esc(tr('Archetipo'))}</th><th class="num">${esc(tr('% liste'))}</th><th class="num">${esc(tr('Liste'))}</th><th class="num">Top 8</th></tr></thead>
        <tbody>${archetypes}</tbody>
      </table>
      <table class="meta-table">
        <thead><tr><th>${esc(tr('Carte più giocate'))}</th><th class="num">${esc(tr('Nelle liste'))}</th><th class="num">${esc(tr('Copie'))}</th></tr></thead>
        <tbody>${cards}</tbody>
      </table>
    </div>`;
  panel.hidden = false;
  panel.querySelectorAll('[data-archetype]').forEach((b) => b.addEventListener('click', () => update({ archetype: b.dataset.archetype })));
  panel.querySelectorAll('[data-card]').forEach((b) => b.addEventListener('click', () => update({ card: b.dataset.card })));
}

/* ── Risultati ─────────────────────────────────────────────── */

function summarize(state, total) {
  const parts = [`<b>${esc(total)}</b> ${esc(total === 1 ? tr('lista') : tr('liste'))}`];
  if (state.format) parts.push(`${esc(tr('di'))} <b>${esc(state.format)}</b>`);
  if (state.archetype) parts.push(`${esc(tr('archetipo'))} <b>${esc(state.archetype)}</b>`);
  if (state.card) parts.push(`${esc(tr('con'))} <b>${esc(state.card)}</b>`);
  if (state.top) parts.push(`<b>${esc(state.top === 1 ? tr('vincitrici') : tr('nella top {n}', { n: state.top }))}</b>`);
  const period = PERIODS.find((p) => p.value === state.days)?.label || '';
  $('#filterSummary').innerHTML = `${parts.join(' ')} · ${esc(tr(period).toLowerCase())}.`;
}

function renderRows(data, state) {
  const body = $('#resultsBody');
  if (!data.items.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">${esc(tr('Nessuna lista con questi filtri. In archivio finiscono le liste dei tornei conclusi con classifica e liste pubbliche.'))}</td></tr>`;
    $('#resultsPagination').innerHTML = '';
    return;
  }
  body.innerHTML = data.items.map((d) => `
    <tr data-deck="${d.decklist_id}">
      <td><span class="pos-badge${d.position === 1 ? ' first' : ''}">${d.position}°</span></td>
      <td class="col-name">${esc(d.player_name)}</td>
      <td>${esc(d.archetype || '—')}<span class="col-sub">${d.main_count}/${d.side_count}</span></td>
      <td>${esc(d.tournament_name)}
        <span class="col-sub">${esc(d.format)} · ${fmtDate(d.starts_on)}${d.store_name ? ` · ${esc(d.store_name)}` : ''} · ${esc(tr('{n} giocatori', { n: d.players }))}</span></td>
      <td>${esc(d.record)}<span class="col-sub">${esc(tr('{n} punti', { n: d.points }))}</span></td>
    </tr>`).join('');
  body.querySelectorAll('[data-deck]').forEach((row) => row.addEventListener('click', () => openDeck(+row.dataset.deck)));

  const pages = Math.ceil(data.total / PER_PAGE);
  $('#resultsPagination').innerHTML = pages <= 1 ? '' : `
    <button class="secondary" ${state.page <= 1 ? 'disabled' : ''} id="prevPage">← ${esc(tr('Prec'))}</button>
    <span class="page-info">${state.page} / ${pages}</span>
    <button class="secondary" ${state.page >= pages ? 'disabled' : ''} id="nextPage">${esc(tr('Succ'))} →</button>`;
  $('#prevPage')?.addEventListener('click', () => { writeState({ ...state, page: state.page - 1 }); run(); });
  $('#nextPage')?.addEventListener('click', () => { writeState({ ...state, page: state.page + 1 }); run(); });
}

async function run({ keepFacets = false } = {}) {
  const state = readState();
  if (!keepFacets) renderFacets(state);
  renderMeta(state);
  const q = new URLSearchParams({ days: state.days, page: state.page, per_page: PER_PAGE });
  for (const key of ['format', 'archetype', 'card']) if (state[key]) q.set(key, state[key]);
  if (state.top) q.set('top', state.top);
  $('#resultsBody').innerHTML = `<tr><td colspan="5" class="muted">${esc(tr('Caricamento…'))}</td></tr>`;
  try {
    const data = await apiGet(`/decklists?${q}`);
    summarize(state, data.total);
    renderRows(data, state);
  } catch (err) {
    $('#resultsBody').innerHTML = `<tr><td colspan="5" class="muted">${esc(err.message)}</td></tr>`;
  }
}

/* ── La lista aperta ───────────────────────────────────────── */

async function openDeck(id) {
  const dialog = $('#deckViewDialog');
  const body = $('#deckViewBody');
  body.innerHTML = `<p class="empty">${esc(tr('Caricamento lista…'))}</p>`;
  $('#deckSave').hidden = !getSession();
  dialog.showModal();
  try {
    _open = await apiGet(`/decklists/${id}`);
  } catch (err) {
    body.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  $('#deckViewEyebrow').textContent = `${_open.position}° · ${_open.tournament_name}`;
  $('#deckViewTitle').textContent = `${_open.archetype || tr('Lista')} — ${_open.player_name}`;
  await renderDeck(body, _open.raw_text);
}

async function saveOpenDeck() {
  if (!_open) return;
  const token = localStorage.getItem(TOKEN_KEY);
  const r = await fetch('/api/decks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      name: `${_open.archetype || tr('Lista')} — ${_open.player_name}`.slice(0, 120),
      format: _open.format, archetype: _open.archetype, raw_text: _open.raw_text,
    }),
  });
  if (r.ok) toast(tr('Salvata tra le tue liste ✓'));
  else toast((await r.json().catch(() => ({}))).detail || tr('Salvataggio non riuscito'));
}

/* ── Init ──────────────────────────────────────────────────── */

async function init() {
  updateAuthNav();
  const games = await loadGames();
  _formats = games.find((g) => g.code === 'mtg')?.formats || [];
  $('#deckCopy').addEventListener('click', () => {
    if (!_open) return;
    navigator.clipboard.writeText(_open.raw_text)
      .then(() => toast(tr('Lista copiata')))
      .catch(() => toast(tr('Copia non riuscita')));
  });
  $('#deckSave').addEventListener('click', saveOpenDeck);
  window.addEventListener('popstate', () => run());
  run();
}

init();
