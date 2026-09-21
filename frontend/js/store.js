/**
 * store.js — Profilo pubblico di un negozio: anagrafica, calendario e albo d'oro.
 */
import { apiGet, esc, eventTile, updateAuthNav } from './catalog.js';

const $ = (s) => document.querySelector(s);

function section(title, items, emptyLabel) {
  return `<section class="rail">
    <div class="rail-head"><h2>${esc(title)}</h2></div>
    ${items.length
      ? `<div class="public-events-grid">${items.map(eventTile).join('')}</div>`
      : `<p class="empty">${esc(emptyLabel)}</p>`}
  </section>`;
}

/* Le sedi del negozio: nome, indirizzo, note per chi arriva e mappa. */
function locationsSection(locations) {
  if (!locations.length) return '';
  const cards = locations.map((loc) => {
    const map = loc.latitude != null && loc.longitude != null
      ? `https://www.openstreetmap.org/?mlat=${loc.latitude}&mlon=${loc.longitude}`
      : null;
    return `<div class="location-card">
      <strong>${esc(loc.name)}</strong>
      ${loc.address || loc.city ? `<span>${esc([loc.address, loc.city].filter(Boolean).join(', '))}</span>` : ''}
      ${loc.notes ? `<span class="muted">${esc(loc.notes)}</span>` : ''}
      ${map ? `<a class="secondary-link" href="${esc(map)}" target="_blank" rel="noopener">Mappa ↗</a>` : ''}
    </div>`;
  }).join('');
  return `<section class="rail">
    <div class="rail-head"><h2>Dove giochiamo</h2></div>
    <div class="location-list">${cards}</div>
  </section>`;
}

async function load() {
  const slug = new URLSearchParams(location.search).get('s');
  const host = $('#storeProfile');
  if (!slug) { host.innerHTML = '<p class="empty">Negozio non indicato.</p>'; return; }

  let data;
  try {
    data = await apiGet(`/organizations/${encodeURIComponent(slug)}/profile`);
  } catch (err) {
    host.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }

  const o = data.organization;
  document.title = `${o.name} — Mull2Five`;
  // Link a OpenStreetMap: nessuna chiave API e nessun tracciamento di terze parti.
  const maps = o.latitude != null && o.longitude != null
    ? `https://www.openstreetmap.org/?mlat=${o.latitude}&mlon=${o.longitude}`
    : null;

  host.innerHTML = `
    <div class="profile-head">
      ${o.logo_url
        ? `<img class="profile-logo" src="${esc(o.logo_url)}" alt="" />`
        : '<div class="profile-logo"></div>'}
      <div style="flex:1;min-width:240px">
        <span class="eyebrow">Negozio${o.is_premium ? ' · Premium' : ''}</span>
        <h1>${esc(o.name)}</h1>
        ${o.description ? `<p style="color:var(--muted);margin:0">${esc(o.description)}</p>` : ''}
        <div class="tile-meta" style="margin-top:8px">
          ${o.city ? `<span>${esc(o.city)}</span>` : ''}
          ${o.address ? `<span>${esc(o.address)}</span>` : ''}
          ${maps ? `<a class="secondary-link" href="${esc(maps)}" target="_blank" rel="noopener">Mappa ↗</a>` : ''}
          ${o.website ? `<a class="secondary-link" href="${esc(o.website)}" target="_blank" rel="noopener">Sito ↗</a>` : ''}
        </div>
        <div class="profile-stats">
          <div class="profile-stat"><strong>${o.upcoming_count}</strong><span>in programma</span></div>
          <div class="profile-stat"><strong>${o.past_count}</strong><span>conclusi</span></div>
        </div>
      </div>
    </div>
    ${locationsSection(data.locations || [])}
    ${section('Prossimi eventi', data.upcoming, 'Nessun evento in calendario.')}
    ${section('Eventi passati', data.past, 'Nessun evento concluso.')}`;
}

document.addEventListener('DOMContentLoaded', () => { updateAuthNav(); load(); });
