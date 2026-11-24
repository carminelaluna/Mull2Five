/**
 * saved-decks.test.js — Quali liste salvate si offrono a un torneo, e in che ordine.
 *
 * Il menu sta nella pagina del torneo e in "Le mie iscrizioni": chi apre la
 * tendina deve trovare in cima le liste del formato del torneo, e non vedere
 * quelle di un altro gioco né quelle vuote, che il torneo rifiuterebbe.
 */
import { describe, expect, it } from 'vitest';

import { deckOptions, deckSegments, decksFor } from '../js/saved-decks.js';

const lista = (id, name, format, extra = {}) => ({
  id, name, format, game: 'mtg', raw_text: '4 Lightning Bolt\n56 Mountain', main_count: 60, side_count: 0, ...extra,
});

describe('le liste salvate per un torneo', () => {
  const liste = [
    lista(1, 'Tron', 'Pioneer'),
    lista(2, 'Burn', 'Modern'),
    lista(3, 'Vuota', 'Modern', { raw_text: '  ', main_count: 0 }),
    lista(4, 'Pokémon', 'Standard', { game: 'pokemon' }),
    lista(5, 'Murktide', 'modern'),
  ];

  it('mette prima quelle del formato del torneo, senza badare alle maiuscole', () => {
    expect(decksFor(liste, { game: 'mtg', format: 'Modern' }).map((d) => d.name))
      .toEqual(['Burn', 'Murktide', 'Tron']);
  });

  it('lascia fuori le liste vuote e quelle di un altro gioco', () => {
    const nomi = decksFor(liste, { game: 'mtg', format: 'Pioneer' }).map((d) => d.name);
    expect(nomi).not.toContain('Vuota');
    expect(nomi).not.toContain('Pokémon');
  });

  it('senza gioco non ne scarta nessuna piena', () => {
    expect(decksFor(liste, { format: 'Standard' })[0].name).toBe('Pokémon');
  });
});

describe('il menu', () => {
  it('ha in cima la voce che non manda niente, poi le liste riconoscibili', () => {
    document.body.innerHTML = `<select>${deckOptions([lista(2, 'Burn <rosso>', 'Modern')], 'Nessuna, la carico dopo')}</select>`;
    const options = [...document.querySelectorAll('option')];
    expect(options.map((o) => o.value)).toEqual(['', '2']);
    expect(options[0].textContent).toBe('Nessuna, la carico dopo');
    expect(options[1].textContent).toBe('Burn <rosso> · Modern (60/0)');
  });

  it('chiede una lista per ogni porzione di un evento misto, una sola altrimenti', () => {
    expect(deckSegments({ decklist_formats: ['', 'Draft'] })).toEqual(['', 'Draft']);
    expect(deckSegments({ decklist_formats: [] })).toEqual(['']);
    expect(deckSegments({})).toEqual(['']);
  });
});
