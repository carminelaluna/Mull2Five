/**
 * decks.js — "Le mie liste": le liste salvate del giocatore e il costruttore.
 *
 * Le carte si cercano tramite il server (/api/cards/search: per Magic chiede a
 * Scryfall) e le regole del formato le controlla il server (/api/decks/validate):
 * qui c'è solo la lista in costruzione. Per un gioco senza ricerca carte resta la
 * modalità testo.
 */
import './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { actingAs, actingBanner, bindActingBanner } from './acting.js';
import { deckToText, manaSymbols, mergeCards, parseDeck, renderDeck } from './deck-view.js';
import { esc } from './escape.js';
import { loadGames } from './games.js';
import { t as tr } from './i18n.js';
import { toast } from './catalog.js';
import { apiRequest, logout, requireSession } from './session.js';

/* ── Auth guard ──────────────────────────────────────── */
const session = requireSession();

/* ── Helpers ─────────────────────────────────────────── */
const $ = (selector, root = document) => root.querySelector(selector);

// Chi gestisce il profilo di un figlio salva le liste per lui (X-Act-As).
const apiFetch = (path, opts = {}) => apiRequest(path, { acting: true, requireLogin: true, ...opts });

function updateAuthNav() {
  const el = $('#publicAuth'); if (!el) return;
  el.innerHTML = `<a class="secondary-link" href="my-registrations.html">${esc(tr('Le mie iscrizioni'))}</a>
    <span style="color:var(--muted);font-size:.85rem">${esc(session.email)}</span>
    <button class="secondary-link" id="logoutBtn" type="button">${esc(tr('Esci'))}</button>`;
  $('#logoutBtn').addEventListener('click', () => logout('index.html'));
}

/* ── Stato ───────────────────────────────────────────── */
// L'ordine dei gruppi, come nelle liste stampate (le categorie vengono dal server).
const CATEGORIES = [
  ['creature', 'Creature'], ['planeswalker', 'Planeswalker'], ['battle', 'Battaglie'],
  ['instant', 'Istantanei'], ['sorcery', 'Stregonerie'], ['artifact', 'Artefatti'],
  ['enchantment', 'Incantesimi'], ['land', 'Terre'], ['other', 'Altre carte'],
];

let games = [];
let decks = [];
let current = null;          // la lista aperta: { id, name, game, format, archetype, main, side }
let dirty = false;           // modifiche non salvate
let mode = 'builder';        // 'builder' o 'text'
let validation = null;       // l'ultima risposta di /decks/validate
let validateTimer = null;
const cardInfo = new Map();  // nome minuscolo → { name, mana_cost, type_line, category, image, found }
const asked = new Set();     // nomi già chiesti a /cards/lookup, anche se senza risposta

const gameOf = (code) => games.find((g) => g.code === code) || games[0] || { code: 'mtg', formats: [], deck_tools: false };
const hasTools = () => Boolean(gameOf(current.game).deck_tools);
const count = (cards) => cards.reduce((n, card) => n + card.quantity, 0);

function blankDeck() {
  const game = gameOf('mtg');
  const format = game.formats.includes('Modern') ? 'Modern' : (game.formats[0] || '');
  return { id: null, name: '', game: game.code, format, archetype: '', main: [], side: [] };
}

function fromSaved(saved) {
  const parsed = parseDeck(saved.raw_text);
  return {
    id: saved.id, name: saved.name, game: saved.game, format: saved.format, archetype: saved.archetype,
    main: mergeCards(parsed.main), side: mergeCards(parsed.side),
  };
}

function markDirty() {
  dirty = true;
  scheduleValidate();
}

function confirmDiscard() {
  return !dirty || confirm(tr('Hai modifiche non salvate: vuoi lasciarle?'));
}

/* ── Elenco delle liste ──────────────────────────────── */
function renderList() {
  const box = $('#decksList');
  const badge = (deck) => {
    if (!deck.main_count && !deck.side_count) return `<span class="badge">${esc(tr('vuota'))}</span>`;
    return deck.errors.length
      ? `<span class="badge warn">${esc(tr('da sistemare'))}</span>`
      : `<span class="badge ok">${esc(tr('valida'))}</span>`;
  };
  box.innerHTML = `<h3 class="decks-list-title">${esc(tr('Liste salvate ({n})', { n: decks.length }))}</h3>
    ${decks.length
      ? `<div class="deck-items">${decks.map((deck) => `
        <button class="deck-item${current?.id === deck.id ? ' active' : ''}" data-deck="${deck.id}" type="button">
          <strong>${esc(deck.name)}</strong>
          <span class="deck-item-meta">
            <span>${esc(deck.format || '—')} · ${deck.main_count}/${deck.side_count}</span>
            ${badge(deck)}
          </span>
        </button>`).join('')}</div>`
      : `<p class="muted" style="margin:0">${esc(tr('Nessuna lista salvata: costruiscine una qui accanto.'))}</p>`}`;
  box.querySelectorAll('[data-deck]').forEach((b) => b.addEventListener('click', () => openDeck(+b.dataset.deck)));
}

function openDeck(id) {
  if (current?.id === id || !confirmDiscard()) return;
  const saved = decks.find((deck) => deck.id === id);
  current = saved ? fromSaved(saved) : blankDeck();
  dirty = false;
  history.replaceState(null, '', saved ? `?deck=${saved.id}` : location.pathname);
  renderList();
  renderEditor();
}

function newDeck() {
  if (!confirmDiscard()) return;
  current = blankDeck();
  dirty = false;
  history.replaceState(null, '', location.pathname);
  renderList();
  renderEditor();
  $('#dName')?.focus();
}

/* ── Editor ──────────────────────────────────────────── */
function formatOptions() {
  const formats = [...gameOf(current.game).formats];
  if (current.format && !formats.includes(current.format)) formats.unshift(current.format);
  return formats.map((f) => `<option value="${esc(f)}"${f === current.format ? ' selected' : ''}>${esc(f)}</option>`).join('');
}

function renderEditor() {
  if (!hasTools()) mode = 'text';
  $('#deckEditor').innerHTML = `
    <div class="deck-fields">
      <label>${esc(tr('Nome'))}<input id="dName" maxlength="120" placeholder="${esc(tr('Es. Burn del giovedì'))}" value="${esc(current.name)}" /></label>
      <label>${esc(tr('Formato'))}<select id="dFormat">${formatOptions()}</select></label>
      <label>${esc(tr('Archetipo'))}<input id="dArchetype" maxlength="120" placeholder="Burn, Domain Ramp…" value="${esc(current.archetype)}" /></label>
    </div>
    <div class="deck-toolbar">
      <div class="deck-mode" role="tablist">
        <button class="deck-mode-btn${mode === 'builder' ? ' active' : ''}" data-mode="builder" type="button" role="tab" ${hasTools() ? '' : 'disabled'}>${esc(tr('Costruttore'))}</button>
        <button class="deck-mode-btn${mode === 'text' ? ' active' : ''}" data-mode="text" type="button" role="tab">${esc(tr('Testo'))}</button>
      </div>
      <span class="muted deck-totals" id="dTotals"></span>
    </div>
    <div id="dBody"></div>
    <div class="deck-status" id="dStatus"></div>
    <div class="deck-actions">
      <div class="deck-actions-left">
        <button class="secondary" id="dPreview" type="button">${esc(tr('Anteprima'))}</button>
        <button class="secondary" id="dCopy" type="button">${esc(tr('Copia testo'))}</button>
        <button class="secondary" id="dDownload" type="button">${esc(tr('Scarica .txt'))}</button>
        <button class="secondary" id="dSend" type="button">${esc(tr('Invia a un torneo'))}</button>
        ${current.id ? `<button class="secondary danger-outline" id="dDelete" type="button">${esc(tr('Elimina'))}</button>` : ''}
      </div>
      <button class="primary" id="dSave" type="button">${esc(tr('Salva lista'))}</button>
    </div>`;

  $('#dName').addEventListener('input', (e) => { current.name = e.target.value; dirty = true; });
  $('#dArchetype').addEventListener('input', (e) => { current.archetype = e.target.value; dirty = true; });
  $('#dFormat').addEventListener('change', (e) => { current.format = e.target.value; markDirty(); });
  $('#deckEditor').querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => {
    if (b.disabled || mode === b.dataset.mode) return;
    mode = b.dataset.mode;
    $('#deckEditor').querySelectorAll('[data-mode]').forEach((x) => x.classList.toggle('active', x === b));
    renderBody();
  }));
  $('#dBody').addEventListener('click', onCardAction);
  $('#dSave').addEventListener('click', save);
  $('#dPreview').addEventListener('click', preview);
  $('#dCopy').addEventListener('click', copyText);
  $('#dDownload').addEventListener('click', download);
  $('#dSend').addEventListener('click', openSendDialog);
  $('#dDelete')?.addEventListener('click', removeDeck);
  renderBody();
  validation = null;
  scheduleValidate(0);
}

function renderBody() {
  const body = $('#dBody');
  if (mode === 'text') {
    body.innerHTML = `
      <label>${esc(tr('La lista, una carta per riga'))}
        <textarea id="dText" class="deck-text" spellcheck="false" placeholder="4 Lightning Bolt&#10;4 Ragavan, Nimble Pilferer&#10;…&#10;&#10;Sideboard&#10;2 Blood Moon">${esc(deckToText(current))}</textarea>
      </label>
      <label class="deck-file">${esc(tr('Oppure carica un file (.txt, .dec)'))}
        <input id="dFile" type="file" accept=".txt,.dec,.csv,text/plain" />
      </label>
      ${hasTools() ? '' : `<p class="muted">${esc(tr("La ricerca carte per questo gioco non c'è ancora: scrivi la lista a mano."))}</p>`}`;
    const area = $('#dText');
    const read = (text) => {
      const parsed = parseDeck(text);
      current.main = mergeCards(parsed.main);
      current.side = mergeCards(parsed.side);
      markDirty();
      updateTotals();
    };
    area.addEventListener('input', () => read(area.value));
    $('#dFile').addEventListener('change', async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      area.value = await file.text();
      read(area.value);
    });
    updateTotals();
    return;
  }
  body.innerHTML = `
    <div class="card-search">
      <input id="cardSearch" autocomplete="off" spellcheck="false" placeholder="${esc(tr('Cerca una carta e premi Invio…'))}" aria-label="${esc(tr('Cerca una carta'))}" />
      <select id="addTo" aria-label="${esc(tr('Dove aggiungerla'))}">
        <option value="main">${esc(tr('nel main'))}</option>
        <option value="side">${esc(tr('nel sideboard'))}</option>
      </select>
      <ul class="card-suggest" id="cardSuggest" role="listbox" hidden></ul>
    </div>
    <div class="deck-columns">
      <section class="deck-col" id="colMain"></section>
      <section class="deck-col" id="colSide"></section>
    </div>`;
  bindSearch();
  renderCards();
  lookupMissing();
}

function updateTotals() {
  const el = $('#dTotals');
  if (el) el.textContent = tr('Main {m} · Sideboard {s}', { m: count(current.main), s: count(current.side) });
}

/* ── Carte ───────────────────────────────────────────── */
function cardRow(section, card) {
  const toSide = section === 'main';
  const missing = card.info && !card.info.found;
  return `<div class="deck-row" data-section="${section}" data-index="${card.index}" data-name="${esc(card.name.toLowerCase())}">
    <span class="deck-qty">
      <button class="mini-button" data-act="dec" type="button" aria-label="${esc(tr('Una copia in meno'))}">−</button>
      <strong>${card.quantity}</strong>
      <button class="mini-button" data-act="inc" type="button" aria-label="${esc(tr('Una copia in più'))}">+</button>
    </span>
    <span class="deck-card-name" data-image="${esc(card.info?.image || '')}" title="${esc(card.info?.type_line || '')}">${esc(card.name)}${missing ? ` <span class="badge warn">${esc(tr('non trovata'))}</span>` : ''}</span>
    <span class="deck-mana">${manaSymbols(card.info?.mana_cost)}</span>
    <button class="mini-button" data-act="move" type="button" title="${esc(toSide ? tr('Sposta una copia nel sideboard') : tr('Sposta una copia nel main'))}">${toSide ? '→ SB' : '→ Main'}</button>
    <button class="mini-button" data-act="remove" type="button" title="${esc(tr('Togli dalla lista'))}" aria-label="${esc(tr('Togli dalla lista'))}">×</button>
  </div>`;
}

function renderCards(flash = '') {
  for (const section of ['main', 'side']) {
    const box = $(section === 'main' ? '#colMain' : '#colSide');
    if (!box) continue;
    const cards = current[section].map((card, index) => ({ ...card, index, info: cardInfo.get(card.name.toLowerCase()) }));
    const title = `<h3 class="deck-col-title">${esc(section === 'main' ? tr('Main') : tr('Sideboard'))} <span class="muted">(${count(current[section])})</span></h3>`;
    if (!cards.length) {
      box.innerHTML = `${title}<p class="muted deck-empty">${esc(section === 'main' ? tr('Nessuna carta: cercala qui sopra.') : tr('Sideboard vuoto.'))}</p>`;
      continue;
    }
    // Finché Scryfall non ha risposto le carte restano in un gruppo solo, senza titoli.
    const groups = cards.some((card) => card.info)
      ? CATEGORIES.map(([key, label]) => [label, cards.filter((card) => (card.info?.category || 'other') === key)])
        .filter(([, list]) => list.length)
      : [['', cards]];
    box.innerHTML = title + groups.map(([label, list]) => `<div class="deck-group">
        ${label ? `<h4>${esc(tr(label))} <span class="muted">(${count(list)})</span></h4>` : ''}
        ${list.map((card) => cardRow(section, card)).join('')}
      </div>`).join('');
  }
  updateTotals();
  if (flash) $(`.deck-row[data-name="${CSS.escape(flash.toLowerCase())}"]`)?.classList.add('flash');
}

function addCard(section, name, quantity = 1) {
  const list = current[section];
  const seen = list.find((card) => card.name.toLowerCase() === name.toLowerCase());
  if (seen) seen.quantity += quantity;
  else list.push({ name, quantity });
}

function onCardAction(e) {
  const btn = e.target.closest('[data-act]');
  const row = btn?.closest('.deck-row');
  if (!row) return;
  const section = row.dataset.section;
  const list = current[section];
  const index = +row.dataset.index;
  const card = list[index];
  if (!card) return;
  const act = btn.dataset.act;
  if (act === 'inc') card.quantity += 1;
  if (act === 'dec' || act === 'move') card.quantity -= 1;
  if (act === 'remove' || card.quantity <= 0) list.splice(index, 1);
  if (act === 'move') addCard(section === 'main' ? 'side' : 'main', card.name);
  markDirty();
  renderCards(act === 'move' ? card.name : '');
}

/** Costo, tipo e immagine delle carte nuove: servono per i gruppi e l'anteprima. */
async function lookupMissing() {
  if (!hasTools()) return;
  const names = [...current.main, ...current.side].map((card) => card.name)
    .filter((name) => !cardInfo.has(name.toLowerCase()) && !asked.has(name.toLowerCase()))
    .slice(0, 250);
  if (!names.length) return;
  names.forEach((name) => asked.add(name.toLowerCase()));
  try {
    const cards = await apiFetch('/cards/lookup', { method: 'POST', body: JSON.stringify({ game: current.game, names }) });
    cards.forEach((card) => cardInfo.set(card.query.toLowerCase(), card));
  } catch {
    return;   // senza Scryfall la lista resta leggibile, solo senza gruppi né costi
  }
  if (mode === 'builder') renderCards();
  lookupMissing();   // le carte aggiunte mentre la risposta era in viaggio
}

/* ── Ricerca con autocompletamento ───────────────────── */
function bindSearch() {
  const input = $('#cardSearch');
  const list = $('#cardSuggest');
  let suggestions = [];
  let highlighted = 0;
  let timer = null;
  let sequence = 0;

  const close = () => { list.hidden = true; suggestions = []; };
  const show = () => {
    list.innerHTML = suggestions.map((name, i) =>
      `<li role="option" data-i="${i}" class="${i === highlighted ? 'active' : ''}" aria-selected="${i === highlighted}">${esc(name)}</li>`).join('');
    list.hidden = !suggestions.length;
  };
  const pick = (name) => {
    const section = $('#addTo').value;
    addCard(section, name);
    markDirty();
    renderCards(name);
    lookupMissing();
    input.value = '';
    close();
    input.focus();
  };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 2) { close(); return; }
    timer = setTimeout(async () => {
      const mine = ++sequence;
      try {
        const { names } = await apiFetch(`/cards/search?game=${encodeURIComponent(current.game)}&q=${encodeURIComponent(query)}`);
        if (mine !== sequence) return;   // nel frattempo è partita una ricerca più recente
        suggestions = names.slice(0, 8);
        highlighted = 0;
        show();
      } catch (err) { toast(err.message); }
    }, 180);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' && suggestions.length) {
      e.preventDefault(); highlighted = (highlighted + 1) % suggestions.length; show();
    } else if (e.key === 'ArrowUp' && suggestions.length) {
      e.preventDefault(); highlighted = (highlighted - 1 + suggestions.length) % suggestions.length; show();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (suggestions[highlighted]) pick(suggestions[highlighted]);
    } else if (e.key === 'Escape') {
      close();
    }
  });
  // mousedown e non click: il click arriverebbe dopo il blur, a tendina già chiusa.
  list.addEventListener('mousedown', (e) => {
    const item = e.target.closest('li');
    if (!item) return;
    e.preventDefault();
    pick(suggestions[+item.dataset.i]);
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
}

/* ── Controllo della lista ───────────────────────────── */
function scheduleValidate(delay = 350) {
  clearTimeout(validateTimer);
  validateTimer = setTimeout(() => validateNow(false), delay);
}

async function validateNow(legality) {
  const raw = deckToText(current);
  if (!raw.trim()) { validation = null; renderStatus(); return; }
  const button = $('#dLegal');
  if (button) { button.disabled = true; button.textContent = tr('Controllo in corso…'); }
  try {
    const result = await apiFetch('/decks/validate', {
      method: 'POST',
      body: JSON.stringify({ raw_text: raw, game: current.game, format: current.format, legality }),
    });
    validation = { ...result, legality };
  } catch (err) {
    validation = { errors: [err.message], legality };
  }
  renderStatus();
}

function renderStatus() {
  const box = $('#dStatus');
  if (!box) return;
  if (!validation) {
    box.innerHTML = `<p class="muted deck-status-note">${esc(tr('Aggiungi le carte: qui vedi subito se la lista rispetta il formato.'))}</p>`;
    return;
  }
  const ok = !validation.errors.length;
  const label = ok
    ? (validation.legality ? tr('Valida e legale') : tr('Rispetta il formato'))
    : tr('{n} da sistemare', { n: validation.errors.length });
  box.innerHTML = `<div class="deck-status-head">
      <span class="badge ${ok ? 'ok' : 'bad'}">${esc(label)}</span>
      <span class="muted">${esc(current.format || '')}</span>
      ${hasTools() ? `<button class="secondary" id="dLegal" type="button">${esc(tr('Controlla legalità'))}</button>` : ''}
    </div>
    ${ok ? '' : `<ul class="deck-errors">${validation.errors.map((error) => `<li>${esc(error)}</li>`).join('')}</ul>`}
    <p class="muted deck-status-note">${esc(validation.legality
      ? tr('Legalità controllata adesso con Scryfall.')
      : tr('Numero di carte e copie si controllano mentre scrivi; carte bandite e ristrette con «Controlla legalità».'))}</p>`;
  $('#dLegal')?.addEventListener('click', () => validateNow(true));
}

/* ── Azioni ──────────────────────────────────────────── */
async function save() {
  current.name = current.name.trim();
  if (!current.name) { toast(tr('Dai un nome alla lista.')); $('#dName').focus(); return; }
  const button = $('#dSave');
  button.disabled = true;
  const body = JSON.stringify({
    name: current.name, game: current.game, format: current.format,
    archetype: current.archetype.trim(), raw_text: deckToText(current),
  });
  try {
    const saved = current.id
      ? await apiFetch(`/decks/${current.id}`, { method: 'PUT', body })
      : await apiFetch('/decks', { method: 'POST', body });
    decks = await apiFetch('/decks');
    current.id = saved.id;
    dirty = false;
    history.replaceState(null, '', `?deck=${saved.id}`);
    renderList();
    renderEditor();
    toast(tr('Lista salvata ✓'));
  } catch (err) {
    toast(err.message);
    button.disabled = false;
  }
}

async function removeDeck() {
  if (!current.id || !confirm(tr('Eliminare la lista «{name}»?', { name: current.name }))) return;
  try {
    await apiFetch(`/decks/${current.id}`, { method: 'DELETE' });
  } catch (err) { toast(err.message); return; }
  decks = decks.filter((deck) => deck.id !== current.id);
  dirty = false;
  current = decks[0] ? fromSaved(decks[0]) : blankDeck();
  history.replaceState(null, '', current.id ? `?deck=${current.id}` : location.pathname);
  renderList();
  renderEditor();
  toast(tr('Lista eliminata'));
}

async function preview() {
  const dialog = $('#deckViewDialog');
  $('#deckViewTitle').textContent = current.name || tr('Lista senza nome');
  dialog.showModal();
  await renderDeck($('#deckViewBody'), deckToText(current));
}

/* ── Invia a un torneo ───────────────────────────────────
   Le liste salvate servono a questo: ritrovarle e mandarle. Prima si doveva
   copiare il testo e incollarlo in "Le mie iscrizioni"; da qui si scelgono il
   torneo e il segmento e si manda. */
let _open = [];

/** Le iscrizioni che accettano ancora una lista, quelle che ne aspettano una per prime. */
function sendableRegistrations(rows) {
  const wanted = (row) => row.tournament.decklist_required
    && (row.registration.decklist_formats || []).length < (row.tournament.decklist_formats || ['']).length;
  return rows
    .filter((row) => !row.tournament.decklist_locked && !row.registration.dropped)
    .sort((a, b) => (wanted(b) - wanted(a)) || String(a.tournament.starts_on).localeCompare(String(b.tournament.starts_on)));
}

/** I segmenti di quel torneo: con uno solo non si chiede niente. */
function fillSegments(row) {
  const segments = row?.tournament.decklist_formats?.length ? row.tournament.decklist_formats : [''];
  const done = new Set(row?.registration.decklist_formats || []);
  $('#sendSegmentRow').style.display = segments.length < 2 ? 'none' : '';
  $('#sendSegment').innerHTML = segments.map((seg) =>
    `<option value="${esc(seg)}">${esc(seg || tr('Lista principale'))}${done.has(seg) ? ` — ${esc(tr('già inviata'))}` : ''}</option>`).join('');
}

async function openSendDialog() {
  if (!deckToText(current).trim()) { toast(tr('La lista è vuota.')); return; }
  $('#sendError').textContent = '';
  $('#sendHint').textContent = tr('Mandi «{name}» come sta adesso, anche se non è ancora salvata.', { name: current.name || tr('questa lista') });
  $('#sendTournament').innerHTML = `<option value="">${esc(tr('Caricamento…'))}</option>`;
  $('#sendSegmentRow').style.display = 'none';
  $('#sendDialog').showModal();
  try {
    _open = sendableRegistrations(await apiFetch('/tournaments/me/registrations'));
  } catch (err) {
    _open = [];
    $('#sendError').textContent = err.message;
  }
  const select = $('#sendTournament');
  select.disabled = !_open.length;
  $('#sendSubmit').disabled = !_open.length;
  select.innerHTML = _open.length
    ? _open.map((row) => `<option value="${row.tournament.id}">${esc(row.tournament.name)} · ${esc(row.tournament.format)} · ${esc(fmtDay(row.tournament.starts_on))}</option>`).join('')
    : `<option value="">${esc(tr('Nessun torneo che aspetta una lista'))}</option>`;
  fillSegments(_open[0]);
  select.onchange = () => fillSegments(_open.find((row) => String(row.tournament.id) === select.value));
}

const fmtDay = (iso) => (iso ? iso.substring(0, 10).split('-').reverse().join('/') : '');

async function sendDeck() {
  const row = _open.find((r) => String(r.tournament.id) === $('#sendTournament').value);
  if (!row) return;
  const button = $('#sendSubmit');
  button.disabled = true;
  try {
    await apiFetch(`/tournaments/${row.tournament.id}/decklist`, {
      method: 'POST',
      body: JSON.stringify({
        raw_text: deckToText(current),
        archetype: current.archetype || '',
        format: $('#sendSegmentRow').style.display === 'none' ? '' : $('#sendSegment').value,
      }),
    });
    $('#sendDialog').close();
    toast(tr('Lista inviata a {name} ✓', { name: row.tournament.name }));
  } catch (err) {
    $('#sendError').textContent = err.message;
  }
  button.disabled = false;
}

function copyText() {
  navigator.clipboard.writeText(deckToText(current))
    .then(() => toast(tr('Lista copiata')))
    .catch(() => toast(tr('Copia non riuscita: usa la modalità Testo.')));
}

function download() {
  const file = new Blob([deckToText(current) + '\n'], { type: 'text/plain' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(file);
  link.download = `${(current.name || 'lista').replace(/[^\w\- ]+/g, '').trim() || 'lista'}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
}

/* ── Anteprima della carta sotto il puntatore ────────── */
function bindPreview() {
  const box = $('#cardPreview');
  const img = box.querySelector('img');
  document.addEventListener('mouseover', (e) => {
    const name = e.target.closest?.('.deck-card-name');
    if (!name?.dataset.image) { box.hidden = true; return; }
    img.src = name.dataset.image;
    img.alt = name.textContent.trim();
    box.hidden = false;
  });
  document.addEventListener('mousemove', (e) => {
    if (box.hidden) return;
    const width = 244, height = 340, gap = 24;
    const x = e.clientX + gap + width > innerWidth ? e.clientX - width - gap : e.clientX + gap;
    const y = Math.min(Math.max(8, e.clientY - height / 2), innerHeight - height - 8);
    box.style.left = `${x}px`;
    box.style.top = `${y}px`;
  });
}

/* ── Init ────────────────────────────────────────────── */
async function init() {
  updateAuthNav();
  const who = actingAs();
  if (who) {
    $('h1').textContent = tr('Le liste di {nome}', { nome: who.name });
    $('#actingBar').innerHTML = actingBanner();
    bindActingBanner($('#actingBar'));
  }
  $('#newDeck').addEventListener('click', newDeck);
  $('#sendSubmit').addEventListener('click', sendDeck);
  bindPreview();
  window.addEventListener('beforeunload', (e) => {
    if (!dirty) return;
    e.preventDefault();
    e.returnValue = '';
  });
  games = await loadGames();
  try {
    decks = await apiFetch('/decks');
  } catch (err) {
    toast(err.message);
    decks = [];
  }
  const wanted = +new URLSearchParams(location.search).get('deck');
  const start = decks.find((deck) => deck.id === wanted) || decks[0];
  current = start ? fromSaved(start) : blankDeck();
  renderList();
  renderEditor();
}

init();
