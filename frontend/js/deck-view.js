/**
 * deck-view.js — Vista grafica di una decklist con le immagini Scryfall.
 *
 * Viveva nel vecchio tool offline ed è sparita con la migrazione a V2. Qui è un
 * modulo condiviso: la usano "Le mie iscrizioni" (lista propria) e lo Storico
 * (liste pubbliche dei tornei conclusi).
 *
 * Le carte compaiono subito come segnaposto col nome e vengono sostituite dalle
 * immagini quando Scryfall risponde: se l'API è lenta o irraggiungibile la lista
 * resta comunque leggibile.
 */
import { esc } from './escape.js';

const SCRYFALL_COLLECTION = 'https://api.scryfall.com/cards/collection';
const SCRYFALL_BATCH = 75;   // limite dell'endpoint collection


const normalize = (name) => String(name).trim().toLowerCase();

/** Separa main e sideboard da una lista in formato "4 Nome Carta". */
export function parseDeck(rawText) {
  const deck = { main: [], side: [] };
  let section = 'main';
  for (const rawLine of String(rawText || '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (/^(sideboard|side|sb)\b/i.test(line)) { section = 'side'; continue; }
    const match = line.match(/^(\d+)\s*x?\s+(.+)$/i);
    if (!match) continue;
    // Via il set fra parentesi e il numero di collezione: Scryfall cerca per nome.
    const name = match[2].replace(/\s+\(.+?\)\s*\d*$/, '').replace(/\s+\d+$/, '').trim();
    if (!name) continue;
    deck[section].push({ quantity: Number(match[1]), name, section, index: deck[section].length });
  }
  return deck;
}

const cardKey = (card) =>
  `${card.section}-${card.index}-${card.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;

function tile(card) {
  return `<article class="card-tile fallback-card" data-card-key="${esc(cardKey(card))}">
    <span class="card-qty">${card.quantity}</span>
    <div class="card-name-fallback">${esc(card.name)}</div>
  </article>`;
}

function section(title, cards, emptyLabel) {
  return `<section class="deck-section">
    <h3>${esc(title)} <span class="muted">(${cards.reduce((n, c) => n + c.quantity, 0)})</span></h3>
    <div class="card-image-grid">${
      cards.length ? cards.map(tile).join('') : `<p class="muted">${esc(emptyLabel)}</p>`
    }</div>
  </section>`;
}

/** Carta Scryfall corrispondente al nome scritto in lista, incluse le doppia faccia. */
function matchCard(scryfallCards, deckName) {
  const wanted = normalize(deckName);
  return scryfallCards.find((card) => {
    if (normalize(card.name) === wanted) return true;
    if (card.card_faces?.some((face) => normalize(face.name) === wanted)) return true;
    return normalize(card.name).split(' // ').includes(wanted);
  });
}

/** URL immagine, scegliendo la faccia giusta per le MDFC/trasformanti. */
function imageFor(scryfallCard, deckName) {
  if (!scryfallCard) return '';
  const direct = scryfallCard.image_uris?.normal || scryfallCard.image_uris?.small;
  if (direct) return direct;
  const wanted = normalize(deckName);
  const face = scryfallCard.card_faces?.find((f) => normalize(f.name) === wanted)
    || scryfallCard.card_faces?.[0];
  return face?.image_uris?.normal || face?.image_uris?.small || '';
}

async function hydrate(cards, root) {
  const found = [];
  for (let i = 0; i < cards.length; i += SCRYFALL_BATCH) {
    const batch = cards.slice(i, i + SCRYFALL_BATCH);
    const response = await fetch(SCRYFALL_COLLECTION, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identifiers: batch.map((c) => ({ name: c.name })) }),
    });
    if (!response.ok) throw new Error('Scryfall non raggiungibile');
    found.push(...((await response.json()).data || []));
  }
  for (const card of cards) {
    const image = imageFor(matchCard(found, card.name), card.name);
    if (!image) continue;
    const el = root.querySelector(`[data-card-key="${CSS.escape(cardKey(card))}"]`);
    if (!el) continue;
    el.classList.remove('fallback-card');
    el.innerHTML = `<span class="card-qty">${card.quantity}</span>
      <img alt="${esc(card.name)}" src="${esc(image)}" loading="lazy" />`;
  }
}

/**
 * Disegna la lista dentro `root` e poi carica le immagini.
 * Ritorna una promise che si risolve quando le immagini sono a posto (o fallite):
 * chi chiama può ignorarla, il testo è già leggibile.
 */
export async function renderDeck(root, rawText, { title = '' } = {}) {
  const deck = parseDeck(rawText);
  const all = [...deck.main, ...deck.side];
  if (!all.length) {
    root.innerHTML = '<p class="empty">Nessuna lista da mostrare.</p>';
    return;
  }
  root.innerHTML = `${title ? `<h2 class="deck-title">${esc(title)}</h2>` : ''}
    <div class="deck-sections">
      ${section('Main Deck', deck.main, 'Main deck vuoto.')}
      ${section('Sideboard', deck.side, 'Sideboard non presente.')}
    </div>
    <p class="muted deck-hint">Immagini da Scryfall…</p>`;
  const hint = root.querySelector('.deck-hint');
  try {
    await hydrate(all, root);
    hint?.remove();
  } catch {
    if (hint) hint.textContent = 'Immagini Scryfall non disponibili: resta il testo della lista.';
  }
}
