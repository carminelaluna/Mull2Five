/**
 * month-grid.js — Il mese a griglia, per il lato pubblico.
 *
 * "Cosa c'è giovedì?" è la domanda che si fa davanti al calendario appeso in
 * negozio, e un elenco ordinato per data non la risponde: bisogna scorrere e
 * contare. Qui il mese è una griglia di sette colonne, lunedì a sinistra, e
 * ogni giorno mostra quel che si gioca.
 *
 * Non sa niente di filtri né di API: riceve gli eventi già filtrati e il mese da
 * disegnare, e avvisa chi l'ha chiamata quando l'utente ne chiede un altro. I
 * nomi di mesi e giorni li scrive Intl nella lingua scelta, così non servono
 * dizionari per dodici parole che il browser conosce già.
 */
import { esc, placeLabel } from './catalog.js';
import { getLang, t as tr } from './i18n.js';

/** 'YYYY-MM' di una data (quella di oggi, se non si passa niente). */
export function monthKey(when = new Date()) {
  return `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, '0')}`;
}

/** Il mese spostato di `delta`: shiftMonth('2026-01', -1) → '2025-12'. */
export function shiftMonth(key, delta) {
  const [year, month] = key.split('-').map(Number);
  return monthKey(new Date(year, month - 1 + delta, 1));
}

/** Primo e ultimo giorno del mese, come li vuole l'API ('YYYY-MM-DD'). */
export function monthRange(key) {
  const [year, month] = key.split('-').map(Number);
  const giorni = new Date(year, month, 0).getDate();
  const iso = (day) => `${key}-${String(day).padStart(2, '0')}`;
  return { from: iso(1), to: iso(giorni), days: giorni };
}

function monthLabel(key) {
  const [year, month] = key.split('-').map(Number);
  const testo = new Date(year, month - 1, 1)
    .toLocaleDateString(getLang(), { month: 'long', year: 'numeric' });
  return testo.charAt(0).toUpperCase() + testo.slice(1);
}

/** Le iniziali dei giorni, da lunedì: il 5 gennaio 2026 è un lunedì. */
function weekdayNames() {
  return Array.from({ length: 7 }, (_, i) =>
    new Date(2026, 0, 5 + i).toLocaleDateString(getLang(), { weekday: 'short' }));
}

function dayCell(key, day, events, today) {
  const iso = `${key}-${String(day).padStart(2, '0')}`;
  const [year, month] = key.split('-').map(Number);
  // Sul telefono le sette colonne diventano un elenco, e lì il solo numero del
  // giorno non dice niente: serve "gio 8". Lo stampa il CSS da questo attributo.
  const etichetta = new Date(year, month - 1, day)
    .toLocaleDateString(getLang(), { weekday: 'short', day: 'numeric' });
  const ofDay = events.filter((e) => String(e.starts_on).substring(0, 10) === iso);
  const voci = ofDay.map((e) => {
    const done = e.status === 'completed';
    const dove = e.is_online ? tr('Online') : (placeLabel(e) || e.organization_name || '');
    const titolo = [e.format, dove].filter(Boolean).join(' · ');
    return `<a class="cal-event${done ? ' done' : ''}"
               href="${done ? 'history.html?t=' : 'event.html?id='}${e.id}"
               title="${esc(titolo)}">
              ${e.start_time ? `<b>${esc(e.start_time)}</b> ` : ''}${esc(e.name)}
            </a>`;
  }).join('');
  return `<div class="cal-day${iso === today ? ' today' : ''}${ofDay.length ? '' : ' empty'}"
               data-label="${esc(etichetta)}">
            <span class="cal-num">${day}</span>${voci}
          </div>`;
}

/**
 * Disegna il mese dentro `host`.
 * `onMonth(key)` viene chiamata quando si cambia mese (frecce o "Oggi").
 */
export function renderMonth(host, { month, events = [], onMonth }) {
  const { days } = monthRange(month);
  const [year, mese] = month.split('-').map(Number);
  // getDay() mette la domenica a 0; qui la settimana comincia di lunedì.
  const offset = (new Date(year, mese - 1, 1).getDay() + 6) % 7;
  const today = monthKey() === month
    ? `${month}-${String(new Date().getDate()).padStart(2, '0')}`
    : '';

  const celle = [
    ...Array.from({ length: offset }, () => '<div class="cal-day out" aria-hidden="true"></div>'),
    ...Array.from({ length: days }, (_, i) => dayCell(month, i + 1, events, today)),
  ].join('');

  host.innerHTML = `
    <div class="cal-bar">
      <button class="secondary" type="button" data-month="prev"
              aria-label="${esc(tr('Mese precedente'))}">←</button>
      <strong class="cal-title">${esc(monthLabel(month))}</strong>
      <button class="secondary" type="button" data-month="next"
              aria-label="${esc(tr('Mese successivo'))}">→</button>
      <button class="chip" type="button" data-month="today">${esc(tr('Oggi'))}</button>
      <span class="cal-count">${esc(events.length === 1 ? tr('1 evento') : tr('{n} eventi', { n: events.length }))}</span>
    </div>
    <div class="cal-grid" role="grid">
      ${weekdayNames().map((n) => `<div class="cal-head">${esc(n)}</div>`).join('')}
      ${celle}
    </div>`;

  host.querySelectorAll('[data-month]').forEach((btn) =>
    btn.addEventListener('click', () => {
      const dove = btn.dataset.month;
      onMonth?.(dove === 'today' ? monthKey() : shiftMonth(month, dove === 'prev' ? -1 : 1));
    }));
}
