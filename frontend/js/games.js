/**
 * games.js — I giochi supportati, per le pagine.
 *
 * Formati, formato dei match e spareggi arrivano dal backend (GET /api/games,
 * backend/app/games.py): qui c'è solo come mostrarli, non una seconda copia
 * delle regole.
 */
import { t } from './i18n.js';

let catalog = null;

/** L'elenco dei giochi, chiesto una volta per pagina. */
export function loadGames() {
  catalog ??= fetch('/api/games')
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  return catalog;
}

/** Il gioco con quel codice; un codice mancante (tornei vecchi) vale come Magic. */
export async function gameInfo(code) {
  const games = await loadGames();
  return games.find((g) => g.code === (code || 'mtg')) || games.find((g) => g.code === 'mtg') || null;
}

// Nomi brevi per badge e filtri: quello completo ("Magic: The Gathering") non ci sta.
const SHORT = { mtg: 'Magic', lorcana: 'Lorcana', swu: 'Star Wars', onepiece: 'One Piece', pokemon: 'Pokémon' };
export const gameLabel = (code) => SHORT[code] || SHORT.mtg;

/** "Al meglio di 3", per le schede del torneo. */
export const bestOfLabel = (bestOf) => t('Al meglio di {n}', { n: bestOf || 3 });

const SCORES = {
  1: ['1-0', '0-1', '0-0'],
  2: ['2-0', '1-0', '1-1', '0-1', '0-2', '0-0'],
  3: ['2-0', '2-1', '1-0', '1-1', '0-1', '1-2', '0-2', '0-0'],
};

/**
 * I punteggi che si possono inserire per un match: dipendono dal formato del
 * torneo, e nei playoff si gioca sempre al meglio di 3, senza patta. È la stessa
 * regola che il backend applica; qui serve a non proporre punteggi che rifiuterebbe.
 */
export function scoresFor(bestOf = 3, { playoff = false, intentionalDraws = true } = {}) {
  let list = playoff ? SCORES[3].filter((s) => s[0] !== s[2]) : (SCORES[bestOf] || SCORES[3]);
  // Senza patte intenzionali sparisce lo 0-0; la patta a tempo (1-1) resta.
  if (!intentionalDraws) list = list.filter((s) => s !== '0-0');
  return [...list];   // una copia: chi la riceve può aggiungerci un punteggio già salvato
}

/** Come mostrare un punteggio nel menu: "2 – 1", e lo 0-0 detto per quello che è. */
export function scoreLabel(score) {
  return score === '0-0' ? t('0 – 0 (patta)') : score.replace('-', ' – ');
}

/**
 * Le colonne degli spareggi in classifica, nell'ordine in cui contano: ogni gioco
 * ha le sue (vedi backend/app/services/standings.py).
 */
export function tiebreakerColumns(system) {
  if (system === 'onepiece') {
    return [
      { key: 'match_win_percentage', label: t('Win rate') },
      { key: 'opponent_match_win_percentage', label: t('Win rate avversari') },
    ];
  }
  if (system === 'pokemon') {
    return [
      { key: 'opponent_match_win_percentage', label: 'Op Win %' },
      { key: 'opponent_opponent_win_percentage', label: 'Op Op Win %' },
    ];
  }
  return [
    { key: 'opponent_match_win_percentage', label: 'OMW%' },
    { key: 'game_win_percentage', label: 'GW%' },
    { key: 'opponent_game_win_percentage', label: 'OGW%' },
  ];
}
