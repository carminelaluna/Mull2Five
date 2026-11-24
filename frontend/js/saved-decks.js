/**
 * saved-decks.js — Le liste di "Le mie liste" offerte a un torneo.
 *
 * Si sceglie una lista già fatta in tre posti: la pagina del torneo (nel
 * modulo d'iscrizione e da iscritto), la finestra "Carica lista" di "Le mie
 * iscrizioni" e "Invia a un torneo" in "Le mie liste". Qui c'è solo quali
 * offrire e in che ordine; la si manda con POST /tournaments/{id}/decklist.
 */
import { esc } from './escape.js';

/** Solo le liste del gioco del torneo, prima quelle del suo formato: sono quelle che servono.
    Una lista salvata vuota non si offre: il torneo la rifiuterebbe. */
export function decksFor(decks, { game = '', format = '' } = {}) {
  const wanted = format.toLowerCase();
  const sameFormat = (d) => (d.format || '').toLowerCase() === wanted;
  const ofGame = decks.filter((d) => (d.raw_text || '').trim() && (!game || !d.game || d.game === game));
  return [...ofGame.filter(sameFormat), ...ofGame.filter((d) => !sameFormat(d))];
}

/** "Burn · Modern (60/15)": nome, formato e carte, per riconoscerla nel menu. */
export const deckLabel = (d) => `${d.name} · ${d.format || '—'} (${d.main_count}/${d.side_count})`;

/** Le voci di un menu: la prima, vuota, non manda niente. */
export function deckOptions(decks, first) {
  return `<option value="">${esc(first)}</option>`
    + decks.map((d) => `<option value="${d.id}">${esc(deckLabel(d))}</option>`).join('');
}

/** Le liste che il torneo vuole: una sola, o una per porzione in un evento misto. */
export const deckSegments = (t) => (t.decklist_formats?.length ? t.decklist_formats : ['']);
