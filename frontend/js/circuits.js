/**
 * circuits.js — Elenco dei circuiti pubblici, punto d'ingresso alle classifiche.
 *
 * Sostituisce la vecchia "Classifica stagionale": li si sceglieva la stagione da
 * un menu a tendina senza sapere cosa fossero. Qui i circuiti sono schede.
 */
import { apiGet, placeholder, seriesTile, updateAuthNav } from './catalog.js';

const $ = (s) => document.querySelector(s);

async function load() {
  const grid = $('#circuitGrid');
  placeholder(grid, 'Caricamento…');
  try {
    const series = await apiGet('/seasons/public');
    if (!series.length) {
      placeholder(grid, 'Nessun circuito pubblicato: chiedi al tuo negozio di crearne uno.');
      return;
    }
    const attivi = series.filter((s) => s.is_active);
    const chiusi = series.filter((s) => !s.is_active);
    grid.innerHTML = [
      attivi.length ? `<h2 class="rail-sub">In corso</h2>
        <div class="public-events-grid">${attivi.map(seriesTile).join('')}</div>` : '',
      chiusi.length ? `<h2 class="rail-sub">Conclusi</h2>
        <div class="public-events-grid">${chiusi.map(seriesTile).join('')}</div>` : '',
    ].join('');
  } catch (err) {
    placeholder(grid, `Impossibile caricare i circuiti: ${err.message}`);
  }
}

document.addEventListener('DOMContentLoaded', () => { updateAuthNav(); load(); });
