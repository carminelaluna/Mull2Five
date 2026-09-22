/**
 * deck-view.test.js — La lista letta dal browser deve contare le stesse carte
 * che conta il server (services/decklists.py, tests/test_decks.py).
 */
import { describe, it, expect } from 'vitest';
import { deckToText, manaSymbols, mergeCards, parseDeck } from '../js/deck-view.js';

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

  it('i simboli di mana diventano immagini e il resto resta testo', () => {
    const html = manaSymbols('{2}{W/U} // <b>');
    expect(html).toContain('card-symbols/2.svg');
    expect(html).toContain('card-symbols/WU.svg');
    expect(html).toContain('&lt;b&gt;');
  });
});
