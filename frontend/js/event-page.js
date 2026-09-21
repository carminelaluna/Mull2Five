/**
 * event-page.js — Pagina pubblica di una manifestazione.
 *
 * Il programma di un weekend in un posto solo: main event e side event con le
 * loro date, invece di far cercare al giocatore sette tornei sparsi nel
 * calendario. Nel modello si chiama Event; "manifestazione" e il nome in
 * interfaccia, perche "evento" da noi e gia il singolo torneo.
 */
import { apiGet, esc, eventTile, fmtDate, updateAuthNav } from './catalog.js';

const $ = (s) => document.querySelector(s);

/** Le tappe si leggono per giornata: a un weekend la domanda e "oggi cosa c'e?". */
function byDay(tournaments) {
  const days = new Map();
  for (const t of tournaments) {
    const key = String(t.starts_on).slice(0, 10);
    if (!days.has(key)) days.set(key, []);
    days.get(key).push(t);
  }
  return [...days.entries()].sort(([a], [b]) => a.localeCompare(b));
}

async function load() {
  const slug = new URLSearchParams(location.search).get('e');
  const host = $('#eventPage');
  if (!slug) { host.innerHTML = '<p class="empty">Manifestazione non indicata.</p>'; return; }

  let data;
  try {
    data = await apiGet(`/events/by-slug/${encodeURIComponent(slug)}`);
  } catch (err) {
    host.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }

  const ev = data.event;
  document.title = `${ev.name} — Mull2Five`;
  const periodo = ev.ends_on && ev.ends_on !== ev.starts_on
    ? `${fmtDate(ev.starts_on)} → ${fmtDate(ev.ends_on)}`
    : fmtDate(ev.starts_on);

  const giornate = byDay(data.tournaments);
  const programma = giornate.length
    ? giornate.map(([day, tornei]) => `
        <section class="rail">
          <div class="rail-head"><h2>${esc(fmtDate(day))}</h2></div>
          <div class="public-events-grid">${tornei.map(eventTile).join('')}</div>
        </section>`).join('')
    : '<p class="empty">Il programma non è ancora stato pubblicato.</p>';

  host.innerHTML = `
    <div class="profile-head">
      <div style="flex:1;min-width:240px">
        <span class="eyebrow">Manifestazione</span>
        <h1>${esc(ev.name)}</h1>
        ${ev.description ? `<p style="color:var(--muted);margin:0">${esc(ev.description)}</p>` : ''}
        <div class="tile-meta" style="margin-top:8px">
          <span>${esc(periodo)}</span>
          ${ev.venue ? `<span>${esc(ev.venue)}</span>` : ''}
          ${ev.organization_slug
            ? `<a class="secondary-link" href="store.html?s=${esc(ev.organization_slug)}">Il negozio ↗</a>`
            : ''}
        </div>
        <div class="profile-stats">
          <div class="profile-stat"><strong>${ev.tournament_count}</strong><span>tappe</span></div>
          <div class="profile-stat"><strong>${giornate.length}</strong><span>giornate</span></div>
        </div>
      </div>
    </div>
    ${programma}`;
}

document.addEventListener('DOMContentLoaded', () => { updateAuthNav(); load(); });
