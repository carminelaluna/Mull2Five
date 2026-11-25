/**
 * deck-view.test.js — La lista letta dal browser deve contare le stesse carte
 * che conta il server (services/decklists.py, tests/test_decks.py).
 */
import { describe, it, expect } from 'vitest';
import {
  categoryLabel, deckToText, fitGrid, groupByType, manaSymbols, mergeCards, parseDeck, sortByType,
} from '../js/deck-view.js';

const names = (cards) => cards.map((c) => [c.quantity, c.name]);

describe('parseDeck', () => {
  it('legge gli export di Arena e MTGO come il server', () => {
    const deck = parseDeck('Deck\n4 Lightning Bolt (2XM) 141\n4x Ragavan, Nimble Pilferer\n2 Fire//Ice\n\n'
      + 'Sideboard\n2 Pyroblast (ICE) 212 *F*\nSB: 1 Blood Moon');
    expect(names(deck.main)).toEqual([[4, 'Lightning Bolt'], [4, 'Ragavan, Nimble Pilferer'], [2, 'Fire // Ice']]);
    expect(names(deck.side)).toEqual([[2, 'Pyroblast'], [1, 'Blood Moon']]);
  });

  it('la riga vuota dopo il main apre il sideboard, quelle iniziali no', () => {
    const deck = parseDeck('\n\n4 Lightning Bolt\n56 Mountain\n\n3 Blood Moon');
    expect(names(deck.main)).toEqual([[4, 'Lightning Bolt'], [56, 'Mountain']]);
    expect(names(deck.side)).toEqual([[3, 'Blood Moon']]);
  });

  it('il comandante e il "Deck" di Arena restano nel main', () => {
    const deck = parseDeck("Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n99 Forest");
    expect(names(deck.main)).toEqual([[1, "Atraxa, Praetors' Voice"], [99, 'Forest']]);
    expect(deck.side).toEqual([]);
  });
});

describe('costruttore', () => {
  it('somma le righe con lo stesso nome e torna al testo', () => {
    const main = mergeCards(parseDeck('2 Lightning Bolt\n56 Mountain\n2 lightning bolt').main);
    expect(names(main)).toEqual([[4, 'Lightning Bolt'], [56, 'Mountain']]);
    const text = deckToText({ main, side: [{ name: 'Pyroblast', quantity: 2 }] });
    expect(text).toBe('4 Lightning Bolt\n56 Mountain\n\nSideboard\n2 Pyroblast');
    expect(names(parseDeck(text).side)).toEqual([[2, 'Pyroblast']]);
  });

  it('senza sideboard il testo non ha la sezione', () => {
    expect(deckToText({ main: [{ name: 'Island', quantity: 40 }], side: [] })).toBe('40 Island');
  });

  it('ordina per tipo, poi per costo, poi per nome, come le liste stampate', () => {
    const cards = mergeCards(parseDeck('4 Mountain\n4 Lightning Bolt\n2 Murktide Regent\n4 Ragavan, Nimble Pilferer\n4 Expressive Iteration').main);
    const info = new Map([
      ['mountain', { category: 'land', cmc: 0 }],
      ['lightning bolt', { category: 'instant', cmc: 1 }],
      ['murktide regent', { category: 'creature', cmc: 7 }],
      ['ragavan, nimble pilferer', { category: 'creature', cmc: 1 }],
      ['expressive iteration', { category: 'sorcery', cmc: 2 }],
    ]);
    expect(sortByType(cards, info).map((c) => c.name)).toEqual([
      'Ragavan, Nimble Pilferer', 'Murktide Regent', 'Lightning Bolt', 'Expressive Iteration', 'Mountain']);
    expect(groupByType(cards, info).map(([key, list]) => [categoryLabel(key), list.length])).toEqual([
      ['Creature', 2], ['Istantanei', 1], ['Stregonerie', 1], ['Terre', 1]]);
    // Finché le carte non arrivano: com'è scritta, in un gruppo solo.
    expect(groupByType(cards, new Map())).toEqual([['', cards]]);
  });

  it('la grafica sceglie le colonne con le carte più grandi che ci stanno', () => {
    const { cols, cardWidth } = fitGrid(15, 1200, 600, 10);
    const rows = Math.ceil(15 / cols);
    expect(cols * cardWidth + (cols - 1) * 10).toBeLessThanOrEqual(1200 + 1e-6);
    expect(rows * cardWidth * (680 / 488) + (rows - 1) * 10).toBeLessThanOrEqual(600 + 1e-6);
    expect(fitGrid(1, 400, 400, 10)).toEqual({ cols: 1, cardWidth: 400 / (680 / 488) });
  });

  it('i simboli di mana diventano immagini e il resto resta testo', () => {
    const html = manaSymbols('{2}{W/U} // <b>');
    expect(html).toContain('card-symbols/2.svg');
    expect(html).toContain('card-symbols/WU.svg');
    expect(html).toContain('&lt;b&gt;');
  });
});
