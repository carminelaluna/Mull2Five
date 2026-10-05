/**
 * console-timer.test.js — Il tempo del round come si legge in sala.
 *
 * Il segno meno conta: a un judge serve sapere di quanto si è sforato. Ma oltre
 * l'ora i minuti da soli diventano illeggibili, ed è quello che si vedeva in
 * Regia su un round lasciato aperto.
 */
import { describe, expect, it } from 'vitest';
import { fmt } from '../js/console.js';

describe('il tempo del round', () => {
  it('sono minuti e secondi, con lo zero davanti', () => {
    expect(fmt(0)).toBe('00:00');
    expect(fmt(59)).toBe('00:59');
    expect(fmt(50 * 60)).toBe('50:00');
    expect(fmt(9 * 60 + 5)).toBe('09:05');
  });

  it('sforato, porta il meno', () => {
    expect(fmt(-1)).toBe('-00:01');
    expect(fmt(-12 * 60 - 34)).toBe('-12:34');
  });

  it("passata l'ora mostra le ore", () => {
    // Senza, un round aperto da una notte diceva "-18008:27": dodici giorni e
    // mezzo contati in minuti, che nessuno legge a colpo d'occhio.
    expect(fmt(3600)).toBe('1:00:00');
    expect(fmt(-(3600 + 5 * 60 + 7))).toBe('-1:05:07');
    expect(fmt(-(12 * 3600 + 3 * 60))).toBe('-12:03:00');
  });

  it('i secondi a metà si troncano, non si arrotondano', () => {
    // Il conto alla rovescia non deve mostrare un secondo che non è passato.
    expect(fmt(61.9)).toBe('01:01');
  });
});
