/**
 * month-grid.test.js — Il mese a griglia.
 *
 * Due conti sbagliano facile e si vedono solo guardando: il giorno della
 * settimana da cui parte il mese (se sbaglia, tutti gli eventi slittano di una
 * casella) e l'ultimo giorno del mese, che l'API riceve come `date_to` — un
 * giorno in meno e il torneo del 31 non compare.
 */
import { describe, expect, it } from 'vitest';
import { monthKey, monthRange, renderMonth, shiftMonth } from '../js/month-grid.js';

describe('i mesi', () => {
  it('si scrivono con il mese a due cifre', () => {
    expect(monthKey(new Date(2026, 0, 7))).toBe('2026-01');
    expect(monthKey(new Date(2026, 9, 31))).toBe('2026-10');
  });

  it('si spostano anche attraverso il capodanno', () => {
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
    expect(shiftMonth('2026-10', 0)).toBe('2026-10');
  });

  it('finiscono l\'ultimo giorno, febbraio bisestile compreso', () => {
    expect(monthRange('2026-10')).toEqual({ from: '2026-10-01', to: '2026-10-31', days: 31 });
    expect(monthRange('2026-11').to).toBe('2026-11-30');
    expect(monthRange('2026-02').to).toBe('2026-02-28');
    expect(monthRange('2028-02').to).toBe('2028-02-29');
  });
});

describe('la griglia', () => {
  const eventi = [
    { id: 7, name: 'Modern del giovedì', starts_on: '2026-10-08', start_time: '20:00', format: 'Modern' },
    { id: 9, name: 'Prerelease', starts_on: '2026-10-08', format: 'Sealed', venue: 'Il Covo', city: 'Napoli' },
    { id: 11, name: 'Legacy di chiusura', starts_on: '2026-10-31', format: 'Legacy', status: 'completed' },
  ];

  function disegna(month = '2026-10') {
    const host = document.createElement('div');
    renderMonth(host, { month, events: eventi });
    return host;
  }

  it('comincia di lunedì: ottobre 2026 parte di giovedì, quindi tre caselle vuote', () => {
    const host = disegna();
    expect(host.querySelectorAll('.cal-head')).toHaveLength(7);
    expect(host.querySelectorAll('.cal-day.out')).toHaveLength(3);
    expect(host.querySelectorAll('.cal-day:not(.out)')).toHaveLength(31);
  });

  it('mette ogni evento nel suo giorno', () => {
    const giorni = [...disegna().querySelectorAll('.cal-day:not(.out)')];
    const otto = giorni[7];           // l'8 ottobre: ottavo giorno del mese
    const link = [...otto.querySelectorAll('.cal-event')];
    expect(link).toHaveLength(2);
    expect(link[0].getAttribute('href')).toBe('event.html?id=7');
    expect(link[0].textContent).toContain('Modern del giovedì');
    expect(link[0].querySelector('b').textContent).toBe('20:00');
    // Il luogo non occupa spazio nella casella: sta nel titolo al passaggio del mouse.
    expect(link[1].getAttribute('title')).toBe('Sealed · Il Covo, Napoli');
    expect(giorni[6].querySelectorAll('.cal-event')).toHaveLength(0);
    expect(giorni[6].classList.contains('empty')).toBe(true);
  });

  it('un torneo concluso porta allo storico, non alla pagina delle iscrizioni', () => {
    const ultimo = [...disegna().querySelectorAll('.cal-day:not(.out)')][30];
    const link = ultimo.querySelector('.cal-event');
    expect(link.getAttribute('href')).toBe('history.html?t=11');
    expect(link.classList.contains('done')).toBe(true);
  });

  it('un mese senza niente resta una griglia, non una pagina vuota', () => {
    const host = disegna('2027-03');
    expect(host.querySelectorAll('.cal-event')).toHaveLength(0);
    expect(host.querySelectorAll('.cal-day:not(.out)')).toHaveLength(31);
    expect(host.querySelector('.cal-count').textContent).toContain('3');
  });
});
