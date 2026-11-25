/**
 * inbox.test.js — La campanella scrive la frase dal tipo: il server manda solo
 * il tipo e i pezzi (services/inbox.py). Un tipo nuovo senza frase si vede qui.
 */
import { describe, it, expect } from 'vitest';
import { phrase, timeAgo } from '../js/inbox.js';

describe('campanella', () => {
  it('ogni tipo del server ha la sua frase', () => {
    const kinds = ['registered', 'waitlisted', 'waitlist_in', 'paid', 'reminder', 'started',
      'pairings', 'announcement', 'cancelled', 'ticket_new', 'ticket_reply'];
    for (const kind of kinds) expect(phrase({ kind, detail: '' })).not.toBe('Notifica');
    expect(phrase({ kind: 'pairings', detail: '3' })).toBe('Turno 3: abbinamenti pronti');
    expect(phrase({ kind: 'reminder', detail: '20:30' })).toBe('Si gioca domani alle 20:30');
    expect(phrase({ kind: 'waitlist_in', detail: '24' })).toBe('Si è liberato un posto: paga entro 24 ore');
    expect(phrase({ kind: 'cancelled', detail: 'refunded' })).toBe('Torneo annullato: il rimborso è partito');
    expect(phrase({ kind: 'paid', detail: '10.00 EUR' })).toMatch(/^Pagamento ricevuto: 10,00\s€$/);
  });

  it('dice quando, come lo si dice', () => {
    const now = Date.parse('2026-11-25T12:00:00Z');
    expect(timeAgo('2026-11-25T11:59:40Z', now)).toBe('adesso');
    expect(timeAgo('2026-11-25T11:55:00Z', now)).toBe('5 min fa');
    expect(timeAgo('2026-11-25T09:00:00Z', now)).toBe('3 ore fa');
    expect(timeAgo('2026-11-24T08:00:00Z', now)).toBe('ieri');
  });
});
