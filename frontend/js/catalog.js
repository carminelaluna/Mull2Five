/**
 * catalog.js — Vocabolario e pezzi condivisi fra Discover, ricerca, negozi e circuiti.
 *
 * Tiene in un posto solo le etichette dei tipi evento, i preset di distanza e
 * periodo e il rendering delle schede, così le quattro pagine pubbliche parlano
 * la stessa lingua senza duplicare markup.
 */
import { esc } from './escape.js';
import { gameLabel } from './games.js';
import { t as tr } from './i18n.js';
export const API = '/api';
export const TOKEN_KEY = 'mull2five-jwt-v1';

export const EVENT_TYPES = [
  { value: 'locals',             label: 'Serate di gioco' },
  { value: 'prerelease',         label: 'Prerelease' },
  { value: 'rcq',                label: 'RCQ' },
  { value: 'store_championship', label: 'Store Championship' },
  { value: 'premier',            label: 'Eventi premier' },
  { value: 'other',              label: 'Altro' },
];

export const FORMATS = [
  'Modern', 'Standard', 'Pioneer', 'Legacy', 'Vintage',
  'Commander', 'Pauper', 'Sealed', 'Draft',
];

export const RELS = ['Regular', 'Competitive', 'Professional'];

/** Raggi in km: quelli che un giocatore considera davvero per spostarsi. */
export const DISTANCES = [
  { value: 10,   label: '10 km' },
  { value: 25,   label: '25 km' },
  { value: 50,   label: '50 km' },
  { value: 100,  label: '100 km' },
  { value: 250,  label: '250 km' },
  { value: 1000, label: 'Tutta Italia' },
];

export const DATE_RANGES = [
  { value: 1,   label: 'Oggi' },
  { value: 7,   label: 'Una settimana' },
  { value: 14,  label: 'Due settimane' },
  { value: 30,  label: 'Un mese' },
  { value: 180, label: 'Sei mesi' },
  { value: 365, label: 'Un anno' },
];

const TYPE_LABEL = Object.fromEntries(EVENT_TYPES.map((t) => [t.value, t.label]));
export const typeLabel = (value) => TYPE_LABEL[value] || 'Evento';

// Riesportato: le pagine pubbliche lo importano da qui.
export { esc };

export function fmtDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = String(iso).substring(0, 10).split('-');
  return `${d}/${m}/${y}`;
}

export function fmtMoney(cents) {
  return ((+cents || 0) / 100).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' });
}

export async function apiGet(path) {
  const token = localStorage.getItem(TOKEN_KEY);
  const r = await fetch(API + path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

/* ── Sessione e barra di navigazione ───────────────────────── */

export function getSession() {
  const t = localStorage.getItem(TOKEN_KEY);
  if (!t) return null;
  try {
    const claims = JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return claims.exp > Date.now() / 1000 ? claims : null;
  } catch { return null; }
}

export function updateAuthNav() {
  const el = document.querySelector('#publicAuth');
  if (!el) return;
  const s = getSession();
  el.innerHTML = s
    ? `<a class="secondary-link" href="my-registrations.html">Le mie iscrizioni</a>
       <a class="secondary-link" href="decks.html">Le mie liste</a>
       <span style="color:var(--muted);font-size:.85rem">${esc(s.email)}</span>
       <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`
    : `<a class="secondary-link" href="login.html">Accedi</a>
       <a class="primary-btn" href="login.html">Registrati</a>`;
  el.querySelector('#logoutBtn')?.addEventListener('click', () => {
    localStorage.removeItem(TOKEN_KEY);
    location.reload();
  });
}

/* ── Schede ────────────────────────────────────────────────── */

export function eventTile(t) {
  const seats = Math.max((t.capacity || 0) - (t.registered_players || 0), 0);
  return `<a class="tile" href="event.html?id=${t.id}">
    <div class="tile-meta">
      <span class="type-badge type-${esc(t.event_type || 'other')}">${esc(typeLabel(t.event_type))}</span>
      <span class="game-badge game-${esc(t.game || 'mtg')}">${esc(gameLabel(t.game))}</span>
      ${t.distance_km != null ? `<span class="dist-badge">${t.distance_km} km</span>` : ''}
    </div>
    <div class="tile-title">${esc(t.name)}</div>
    <div class="tile-meta">
      <span>${fmtDate(t.starts_on)}${t.start_time ? ` · ${esc(t.start_time)}` : ''}</span>
      <span>${esc(t.format)}</span>
    </div>
    <div class="tile-meta">${t.is_online ? '<span class="online-badge">Online</span>' : esc(t.venue || t.organization_name || '')}</div>
    <div class="tile-foot">
      <span>${t.entry_fee_cents ? fmtMoney(t.entry_fee_cents) : esc(tr('Gratis'))}</span>
      <span style="color:var(--muted)">${esc(t.source === 'wizards' ? tr('Iscrizione in negozio') : tr('{n} posti', { n: seats }))}</span>
    </div>
  </a>`;
}

export function storeTile(o) {
  return `<a class="tile" href="store.html?s=${encodeURIComponent(o.slug)}">
    <div class="tile-meta">
      ${o.is_premium ? '<span class="type-badge type-rcq">Premium</span>' : ''}
      ${o.distance_km != null ? `<span class="dist-badge">${o.distance_km} km</span>` : ''}
    </div>
    <div class="tile-title">${esc(o.name)}</div>
    <div class="tile-meta">${esc(o.city || o.address || '')}</div>
    <div class="tile-foot">
      <span>${o.upcoming_count} in programma</span>
      <span style="color:var(--muted)">${o.past_count} conclusi</span>
    </div>
  </a>`;
}

export function seriesTile(s) {
  const period = s.starts_on || s.ends_on
    ? `${fmtDate(s.starts_on)} → ${fmtDate(s.ends_on)}`
    : 'Periodo non definito';
  return `<a class="tile" href="series.html?c=${encodeURIComponent(s.slug)}">
    <div class="tile-meta">
      <span class="type-badge ${s.is_active ? 'type-locals' : 'type-other'}">
        ${s.is_active ? 'In corso' : 'Concluso'}
      </span>
    </div>
    <div class="tile-title">${esc(s.name)}</div>
    <div class="tile-meta">${esc(period)}</div>
    <div class="tile-foot">
      <span>${s.tournament_count} tappe</span>
      ${s.qualification_threshold ? `<span style="color:var(--muted)">Qualificazione a ${s.qualification_threshold} pt</span>` : ''}
    </div>
  </a>`;
}

/** Messaggio di stato dentro un contenitore, con lo stesso tono ovunque. */
export function placeholder(el, message) {
  el.innerHTML = `<p class="empty">${esc(message)}</p>`;
}

/* ── Posizione del giocatore ───────────────────────────────── */

const GEO_KEY = 'mull2five-geo-v1';

/** Ultima posizione concessa. Resta in locale: non la mandiamo a nessuno
    se non come parametro di ricerca al nostro backend. */
export function savedPosition() {
  try {
    const raw = JSON.parse(localStorage.getItem(GEO_KEY) || 'null');
    return raw && Number.isFinite(raw.lat) && Number.isFinite(raw.lng) ? raw : null;
  } catch { return null; }
}

export function askPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error('Geolocalizzazione non disponibile')); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const at = { lat: +pos.coords.latitude.toFixed(4), lng: +pos.coords.longitude.toFixed(4) };
        try { localStorage.setItem(GEO_KEY, JSON.stringify(at)); } catch { /* modalità privata */ }
        resolve(at);
      },
      () => reject(new Error('Permesso negato: cerca per città')),
      { timeout: 8000, maximumAge: 600000 },
    );
  });
}

export function forgetPosition() {
  try { localStorage.removeItem(GEO_KEY); } catch { /* niente da dimenticare */ }
}
