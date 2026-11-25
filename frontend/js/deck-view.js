/**
 * deck-view.js — La lista vista come la mostra Melee: le carte, il testo e la grafica.
 *
 * Un modulo condiviso: lo usano l'archivio delle liste, lo Storico, "Le mie
 * iscrizioni", le mie liste e il back-office. Tre viste:
 *   - Immagini: il main a griglia per tipo e costo, il sideboard in colonna con
 *     le carte sovrapposte, il numero di copie su ognuna;
 *   - Testo: i gruppi per tipo, con il costo di mana;
 *   - Grafica: la stessa cosa in un'immagine sola, 16:9 o quadrata, da scaricare
 *     e condividere (25/11/2026).
 *
 * Le carte le chiede al sito (/api/cards/lookup), che le prende da Scryfall e le
 * tiene in cache. Prima le chiedeva a Scryfall dal browser, e la CSP del sito lo
 * vietava: in produzione le immagini non arrivavano mai. Finché il sito non
 * risponde, ogni carta è un segnaposto col nome: la lista è già leggibile.
 */
import { esc } from './escape.js';
import { t as tr } from './i18n.js';
import { apiRequest } from './session.js';

const LOOKUP_BATCH = 250;          // il massimo di /cards/lookup (CardLookupIn)
const CARD_RATIO = 680 / 488;      // altezza su larghezza di una carta Magic

// Come legge le liste il server (services/decklists.py): le due letture devono
// contare le stesse carte, o il giocatore vedrebbe numeri diversi da quelli controllati.
const CARD_LINE = /^(?:(sb)\s*:\s*)?(\d+)\s*x?\s+(.+)$/i;           // "4 Bolt", "4x Bolt", "SB: 2 Pyroblast"
const SIDE_HEADER = /^(?:\/\/\s*)?(sideboard|side|sb|companion|compagno)\b/i;
// "Deck" di Arena, "Commander" e i gruppi per tipo riportano al main, anche dopo la riga vuota.
const MAIN_HEADER = /^(?:\/\/\s*)?(deck|main|maindeck|mazzo|commander|comandante|creatures?|lands?|terre|instants?|istantanei|sorcery|sorceries|stregonerie|artifacts?|artefatti|enchantments?|incantesimi|planeswalkers?|battles?|battaglie|other|altro)\b/i;

/** Il nome come lo cerca Scryfall: senza segno della foil, set e numero di collezione. */
export function cleanCardName(raw) {
  let name = String(raw).trim().replace(/\s*\*[A-Za-z]+\*$/, '').replace(/\s+\([A-Za-z0-9]{2,6}\)(?:\s+\S+)?$/, '');
  if (name.includes('//')) name = name.split('//').map((part) => part.trim()).join(' // ');
  return name.replace(/\s+/g, ' ').trim();
}

/** Separa main e sideboard da una lista in formato "4 Nome Carta". */
export function parseDeck(rawText) {
  const deck = { main: [], side: [] };
  let section = 'main';
  for (const rawLine of String(rawText || '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      // Una riga vuota dopo il main: il resto è sideboard (formato MTGO/Arena).
      if (section === 'main' && deck.main.length) section = 'side';
      continue;
    }
    const card = line.match(CARD_LINE);
    if (card) {
      const name = cleanCardName(card[3]);
      const quantity = Number(card[2]);
      const where = card[1] ? 'side' : section;
      if (name && quantity > 0) deck[where].push({ quantity, name, section: where, index: deck[where].length });
      continue;
    }
    if (SIDE_HEADER.test(line)) section = 'side';
    else if (MAIN_HEADER.test(line)) section = 'main';
  }
  return deck;
}

/** Le righe con lo stesso nome diventano una sola, con le copie sommate. */
export function mergeCards(cards) {
  const byName = new Map();
  for (const card of cards) {
    const key = card.name.toLowerCase();
    const seen = byName.get(key);
    if (seen) seen.quantity += card.quantity;
    else byName.set(key, { name: card.name, quantity: card.quantity });
  }
  return [...byName.values()];
}

/** Il testo di una lista: il main, una riga vuota, "Sideboard" e il sideboard. */
export function deckToText(deck) {
  const lines = (cards) => (cards || []).map((card) => `${card.quantity} ${card.name}`);
  const side = lines(deck.side);
  return [...lines(deck.main), ...(side.length ? ['', 'Sideboard', ...side] : [])].join('\n');
}

/** "{2}{U}{U}" con i simboli di mana di Scryfall. */
export function manaSymbols(cost) {
  return esc(cost || '').replace(/\{([^}]+)\}/g, (_, symbol) =>
    `<img class="mana" alt="{${symbol}}" src="https://svgs.scryfall.io/card-symbols/${symbol.replace('/', '')}.svg" loading="lazy" />`);
}

/* ── Tipi di carta ─────────────────────────────────────────── */

// L'ordine dei gruppi, come nelle liste stampate. Le categorie le decide il
// server (MTG_CATEGORIES in services/decklists.py): qui solo l'ordine e i nomi.
export const CATEGORY_ORDER = [
  'creature', 'planeswalker', 'battle', 'instant', 'sorcery', 'artifact', 'enchantment', 'land', 'other',
];

export function categoryLabel(key) {
  switch (key) {
    case 'creature': return tr('Creature');
    case 'planeswalker': return tr('Planeswalker');
    case 'battle': return tr('Battaglie');
    case 'instant': return tr('Istantanei');
    case 'sorcery': return tr('Stregonerie');
    case 'artifact': return tr('Artefatti');
    case 'enchantment': return tr('Incantesimi');
    case 'land': return tr('Terre');
    default: return tr('Altre carte');
  }
}

const count = (cards) => cards.reduce((n, card) => n + card.quantity, 0);
const infoOf = (info, card) => info.get(card.name.toLowerCase());

/** Per tipo, poi per costo, poi per nome. Senza le informazioni delle carte, com'è scritta. */
export function sortByType(cards, info) {
  if (!info.size) return [...cards];
  const rank = (card) => {
    const found = infoOf(info, card);
    return [CATEGORY_ORDER.indexOf(found?.category || 'other'), found?.cmc ?? 99, card.name.toLowerCase()];
  };
  return [...cards].sort((a, b) => {
    const [ta, ca, na] = rank(a);
    const [tb, cb, nb] = rank(b);
    return ta - tb || ca - cb || na.localeCompare(nb);
  });
}

/** I gruppi per tipo che hanno almeno una carta. Senza informazioni, un gruppo solo. */
export function groupByType(cards, info) {
  if (!info.size) return [['', [...cards]]];
  return CATEGORY_ORDER
    .map((key) => [key, sortByType(cards.filter((card) => (infoOf(info, card)?.category || 'other') === key), info)])
    .filter(([, list]) => list.length);
}

/** Le colonne con cui `n` carte stanno in largo×alto con la misura più grande. */
export function fitGrid(n, width, height, gap) {
  let best = { cols: 1, cardWidth: 0 };
  for (let cols = 1; cols <= Math.max(n, 1); cols += 1) {
    const rows = Math.ceil(n / cols);
    const byWidth = (width - gap * (cols - 1)) / cols;
    const byHeight = (height - gap * (rows - 1)) / rows / CARD_RATIO;
    const cardWidth = Math.min(byWidth, byHeight);
    if (cardWidth > best.cardWidth) best = { cols, cardWidth };
  }
  return best;
}

async function lookup(cards, game) {
  const names = [...new Set(cards.map((card) => card.name))];
  const info = new Map();
  for (let i = 0; i < names.length; i += LOOKUP_BATCH) {
    const found = await apiRequest('/cards/lookup', {
      method: 'POST', body: JSON.stringify({ game, names: names.slice(i, i + LOOKUP_BATCH) }),
    });
    for (const card of found || []) info.set(card.query.toLowerCase(), card);
  }
  return info;
}

/* ── Immagini e testo ──────────────────────────────────────── */

function tile(card, info) {
  const found = infoOf(info, card);
  const image = found?.found ? found.image : '';
  // crossorigin: la grafica ridisegna le stesse immagini in un canvas, e una
  // copia presa senza CORS dalla cache lo renderebbe impossibile da salvare.
  return `<figure class="card-tile${image ? '' : ' fallback-card'}" title="${esc(`${card.quantity} ${card.name}`)}">
    <span class="card-qty">${card.quantity}</span>
    ${image
    ? `<img alt="${esc(card.name)}" src="${esc(image)}" loading="lazy" crossorigin="anonymous" />`
    : `<figcaption class="card-name-fallback">${esc(card.name)}</figcaption>`}
  </figure>`;
}

function imagesView(view) {
  const main = sortByType(view.main, view.info);
  const side = sortByType(view.side, view.info);
  return `<div class="deck-visual${side.length ? '' : ' no-side'}">
    <div class="card-image-grid">${main.length
    ? main.map((card) => tile(card, view.info)).join('')
    : `<p class="muted">${esc(tr('Main deck vuoto.'))}</p>`}</div>
    ${side.length ? `<aside class="deck-side-stack">
      <h4>${esc(tr('Sideboard'))} <span class="muted">(${count(side)})</span></h4>
      <div class="side-cards">${side.map((card) => tile(card, view.info)).join('')}</div>
    </aside>` : ''}
  </div>`;
}

function textView(view) {
  const block = (label, cards) => `<section class="deck-text-group">
    <h4>${esc(label)} <span class="muted">(${count(cards)})</span></h4>
    <ul>${cards.map((card) => `<li>
      <span class="qty">${card.quantity}</span>
      <span class="name">${esc(card.name)}</span>
      <span class="cost">${manaSymbols(infoOf(view.info, card)?.mana_cost || '')}</span>
    </li>`).join('')}</ul>
  </section>`;
  const groups = groupByType(view.main, view.info)
    .map(([key, cards]) => block(key ? categoryLabel(key) : tr('Main deck'), cards));
  if (view.side.length) groups.push(block(tr('Sideboard'), sortByType(view.side, view.info)));
  return `<div class="deck-text">${groups.join('')}</div>`;
}

/* ── La grafica ────────────────────────────────────────────── */

const SHAPES = { wide: [1600, 900], square: [1600, 1600] };
const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';
const LIME = '#c6ff3d';

function loadImage(src) {
  return new Promise((resolve) => {
    if (!src) { resolve(null); return; }
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

/** Il testo accorciato con "…" finché sta nella larghezza. */
function fitText(ctx, text, width) {
  let out = String(text);
  if (ctx.measureText(out).width <= width) return out;
  while (out && ctx.measureText(`${out}…`).width > width) out = out.slice(0, -1);
  return `${out.trimEnd()}…`;
}

function drawCard(ctx, card, img, x, y, w, h) {
  ctx.save();
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, w * 0.045);
  ctx.clip();
  if (img) {
    ctx.drawImage(img, x, y, w, h);
  } else {
    // Senza immagine la carta resta una carta: un riquadro col nome.
    ctx.fillStyle = '#22222a';
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = '#ffffff';
    ctx.font = `600 ${Math.max(11, w * 0.09)}px ${FONT}`;
    ctx.textBaseline = 'top';
    let line = '';
    let lineY = y + w * 0.12;
    for (const word of card.name.split(' ')) {
      const next = line ? `${line} ${word}` : word;
      if (line && ctx.measureText(next).width > w * 0.84) {
        ctx.fillText(line, x + w * 0.08, lineY);
        line = word;
        lineY += w * 0.12;
      } else {
        line = next;
      }
    }
    ctx.fillText(line, x + w * 0.08, lineY);
  }
  ctx.restore();
  // Le copie, in alto a destra: si leggono anche sulle carte sovrapposte del sideboard.
  const radius = Math.max(11, w * 0.085);
  const cx = x + w - radius * 1.05;
  const cy = y + radius * 1.05;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(13, 13, 15, .9)';
  ctx.fill();
  ctx.lineWidth = Math.max(1.5, radius * 0.12);
  ctx.strokeStyle = LIME;
  ctx.stroke();
  ctx.fillStyle = '#ffffff';
  ctx.font = `700 ${radius * 1.15}px ${FONT}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(String(card.quantity), cx, cy + radius * 0.06);
  ctx.textAlign = 'left';
}

/** La lista in un'immagine sola, come la "Visualizzazione visiva" di Melee. */
export async function deckCanvas(view, shape = 'wide') {
  const [W, H] = SHAPES[shape] || SHAPES.wide;
  const pad = 48;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');
  const main = sortByType(view.main, view.info);
  const side = sortByType(view.side, view.info);
  const images = new Map(await Promise.all([...main, ...side].map(async (card) => {
    const found = infoOf(view.info, card);
    return [card.name.toLowerCase(), await loadImage(found?.found ? found.image : '')];
  })));

  const background = ctx.createLinearGradient(0, 0, W, H);
  background.addColorStop(0, '#1b1b21');
  background.addColorStop(1, '#0d0d0f');
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, W, H);

  // Intestazione: titolo, chi l'ha giocata, dove e quante carte. Il marchio a destra.
  ctx.textBaseline = 'top';
  ctx.font = `800 30px ${FONT}`;
  ctx.fillStyle = LIME;
  ctx.textAlign = 'right';
  ctx.fillText('Mull2Five', W - pad, pad + 6);
  ctx.textAlign = 'left';
  ctx.fillStyle = '#ffffff';
  ctx.font = `800 44px ${FONT}`;
  ctx.fillText(fitText(ctx, view.meta.title || tr('Lista'), W - pad * 2 - 240), pad, pad);
  let y = pad + 58;
  if (view.meta.by) {
    ctx.font = `600 24px ${FONT}`;
    ctx.fillStyle = LIME;
    ctx.fillText(fitText(ctx, tr('di {nome}', { nome: view.meta.by }), W - pad * 2), pad, y);
    y += 34;
  }
  const details = [
    ...(view.meta.details || []).filter(Boolean),
    `${tr('Main deck')}: ${count(main)}`,
    side.length ? `${tr('Sideboard')}: ${count(side)}` : '',
  ].filter(Boolean).join('  •  ');
  ctx.font = `20px ${FONT}`;
  ctx.fillStyle = '#9a9aa5';
  ctx.fillText(fitText(ctx, details, W - pad * 2), pad, y);
  const top = y + 44;
  const bottom = H - pad - 24;

  // Il sideboard in colonna a destra, con le carte sovrapposte: si leggono i titoli.
  const sideWidth = side.length ? 220 : 0;
  if (side.length) {
    const x = W - pad - sideWidth;
    ctx.font = `600 18px ${FONT}`;
    ctx.fillStyle = '#9a9aa5';
    ctx.fillText(`${tr('Sideboard')} (${count(side)})`, x, top);
    const stackTop = top + 30;
    const room = bottom - stackTop;
    const cardHeight = Math.min(sideWidth * CARD_RATIO, room / (1 + (side.length - 1) * 0.13));
    const cardWidth = cardHeight / CARD_RATIO;
    const step = side.length > 1 ? Math.min(cardHeight * 0.17, (room - cardHeight) / (side.length - 1)) : 0;
    side.forEach((card, i) => drawCard(ctx, card, images.get(card.name.toLowerCase()), x, stackTop + i * step,
      cardWidth, cardHeight));
    ctx.strokeStyle = '#2a2a31';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x - 18, top);
    ctx.lineTo(x - 18, bottom);
    ctx.stroke();
  }

  // Il main: la griglia più grande che ci sta, al centro dello spazio che resta.
  const gap = 12;
  const areaWidth = W - pad * 2 - (sideWidth ? sideWidth + 36 : 0);
  const { cols, cardWidth } = fitGrid(main.length, areaWidth, bottom - top, gap);
  const cardHeight = cardWidth * CARD_RATIO;
  const rows = Math.ceil(main.length / cols);
  const left = pad + (areaWidth - (cols * cardWidth + (cols - 1) * gap)) / 2;
  const gridTop = top + Math.max(0, (bottom - top - (rows * cardHeight + (rows - 1) * gap)) / 2);
  main.forEach((card, i) => drawCard(ctx, card, images.get(card.name.toLowerCase()),
    left + (i % cols) * (cardWidth + gap), gridTop + Math.floor(i / cols) * (cardHeight + gap), cardWidth, cardHeight));

  ctx.font = `16px ${FONT}`;
  ctx.fillStyle = '#6a6a75';
  ctx.textBaseline = 'bottom';
  ctx.fillText('mull2five.it', pad, H - pad + 8);
  return canvas;
}

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('blob vuoto'))), 'image/png');
    } catch (err) {
      reject(err);   // SecurityError: un'immagine arrivata senza CORS
    }
  });
}

const slugify = (text) => String(text || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'lista';

function graphicUrl(view) {
  const shape = view.shape;
  view.graphics[shape] ??= deckCanvas(view, shape).then(canvasBlob).then((blob) => URL.createObjectURL(blob));
  return view.graphics[shape];
}

function graphicView(view) {
  const file = `${slugify(view.meta.title)}-${view.shape === 'square' ? '1x1' : '16x9'}.png`;
  return `<div class="deck-graphic-tools">
      <div class="deck-modes" role="group" aria-label="${esc(tr('Formato della grafica'))}">
        <button type="button" class="chip" data-shape="wide" aria-pressed="${view.shape === 'wide'}">16:9</button>
        <button type="button" class="chip" data-shape="square" aria-pressed="${view.shape === 'square'}">1:1</button>
      </div>
      <a class="primary deck-download" hidden download="${esc(file)}">${esc(tr('Scarica l\'immagine'))}</a>
    </div>
    <div class="deck-graphic-frame" data-graphic><p class="muted">${esc(tr('Preparo la grafica…'))}</p></div>`;
}

async function showGraphic(root, view) {
  const frame = root.querySelector('[data-graphic]');
  const link = root.querySelector('.deck-download');
  try {
    const url = await graphicUrl(view);
    if (!frame.isConnected) return;
    frame.innerHTML = `<img class="deck-graphic" alt="${esc(view.meta.title || tr('Lista'))}" src="${esc(url)}" />`;
    link.href = url;
    link.hidden = false;
  } catch {
    view.graphics[view.shape] = null;
    if (frame.isConnected) {
      frame.innerHTML = `<p class="muted">${esc(tr('La grafica non si è potuta preparare: riprova tra poco.'))}</p>`;
    }
  }
}

/* ── La vista ──────────────────────────────────────────────── */

// La vista mostrata in ogni contenitore: aprire un'altra lista mentre la prima
// aspetta le carte non deve far tornare la prima.
const shown = new WeakMap();

function draw(root, view) {
  const body = view.mode === 'text' ? textView(view) : view.mode === 'graphic' ? graphicView(view) : imagesView(view);
  root.innerHTML = `<div class="deck-view">
    ${view.title ? `<h2 class="deck-title">${esc(view.title)}</h2>` : ''}
    <div class="deck-toolbar">
      <span class="deck-counts">${esc(tr('Main deck'))} ${count(view.main)}${view.side.length
    ? ` · ${esc(tr('Sideboard'))} ${count(view.side)}` : ''}</span>
      <div class="deck-modes" role="group" aria-label="${esc(tr('Come mostrare la lista'))}">
        <button type="button" class="chip" data-mode="images" aria-pressed="${view.mode === 'images'}">${esc(tr('Immagini'))}</button>
        <button type="button" class="chip" data-mode="text" aria-pressed="${view.mode === 'text'}">${esc(tr('Testo'))}</button>
        <button type="button" class="chip" data-mode="graphic" aria-pressed="${view.mode === 'graphic'}"
          ${view.loading ? 'disabled' : ''}>${esc(tr('Grafica'))}</button>
      </div>
    </div>
    ${body}
    ${view.hint ? `<p class="muted deck-hint">${esc(view.hint)}</p>` : ''}
  </div>`;
  if (view.mode === 'graphic') showGraphic(root, view);
}

/**
 * Disegna la lista dentro `root` e poi carica le carte. `meta` va nell'intestazione
 * della grafica: { title, by, details: [torneo, data, formato…] }. `title`, se
 * c'è, compare anche sopra la vista. Ritorna quando le carte sono arrivate (o
 * non sono arrivate): chi chiama può non aspettarla, il testo è già leggibile.
 */
export async function renderDeck(root, rawText, { title = '', meta = {}, game = 'mtg' } = {}) {
  const deck = parseDeck(rawText);
  const view = {
    title, meta: { ...meta, title: meta.title || title },
    main: mergeCards(deck.main), side: mergeCards(deck.side),
    info: new Map(), mode: 'images', shape: 'wide', graphics: {}, loading: true,
    hint: tr('Immagini da Scryfall…'),
  };
  shown.set(root, view);
  if (!view.main.length && !view.side.length) {
    root.innerHTML = `<p class="empty">${esc(tr('Nessuna lista da mostrare.'))}</p>`;
    return;
  }
  // Un clic solo per tutta la vista: i bottoni si ridisegnano a ogni cambio.
  root.onclick = (event) => {
    const mode = event.target.closest('[data-mode]')?.dataset.mode;
    const shape = event.target.closest('[data-shape]')?.dataset.shape;
    if (mode && mode !== view.mode) { view.mode = mode; draw(root, view); }
    if (shape && shape !== view.shape) { view.shape = shape; draw(root, view); }
  };
  draw(root, view);
  try {
    view.info = await lookup([...view.main, ...view.side], game);
    view.hint = '';
  } catch {
    view.hint = tr('Immagini Scryfall non disponibili: resta il testo della lista.');
  }
  view.loading = false;
  if (shown.get(root) === view) draw(root, view);
}
