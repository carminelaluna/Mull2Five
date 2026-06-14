/**
 * SPA pubblica giocatori — entry point.
 * Usa direttamente l'API backend (non localStorage).
 */

const API = '/api';
let _page = 1;
const PER_PAGE = 12;

/* ── Helpers ─────────────────────────────────────────── */

async function apiFetch(path, opts = {}) {
  const token = localStorage.getItem('arcana-events-jwt-v1');
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(API + path, { ...opts, headers });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.status === 204 ? null : r.json();
}

function esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmtDate(d) { if (!d) return '—'; const [y,m,dd]=d.split('-'); return `${dd}/${m}/${y}`; }
function fmtMoney(v) { return (+v||0).toLocaleString('it-IT',{style:'currency',currency:'EUR'}); }

/* ── Sessione ─────────────────────────────────────────── */

function getSession() {
  const t = localStorage.getItem('arcana-events-jwt-v1');
  if (!t) return null;
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
  catch { return null; }
}

function updateAuthNav() {
  const session = getSession();
  const el = document.querySelector('#publicAuth');
  if (!el) return;
  if (session) {
    el.innerHTML = `<span style="color:var(--muted);font-size:.88rem">${esc(session.email)}</span>
      <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
    el.querySelector('#logoutBtn').addEventListener('click', () => {
      localStorage.removeItem('arcana-events-jwt-v1');
      location.reload();
    });
  } else {
    el.innerHTML = `<a class="secondary-link" href="login.html">Accedi</a>
                    <a class="primary-btn"    href="login.html">Registrati</a>`;
  }
}

/* ── Tornei ──────────────────────────────────────────── */

async function loadTournaments() {
  const name   = document.querySelector('#searchName')?.value.trim() || '';
  const format = document.querySelector('#searchFormat')?.value || '';
  const date   = document.querySelector('#searchDate')?.value || '';
  const city   = document.querySelector('#searchCity')?.value.trim() || '';

  const params = new URLSearchParams();
  if (name)   params.set('name',   name);
  if (format) params.set('format', format);
  if (date)   params.set('date_from', date);
  if (city)   params.set('venue',  city);
  params.set('status', 'published');

  const listEl  = document.querySelector('#eventsList');
  const emptyEl = document.querySelector('#eventsEmpty');
  listEl.innerHTML = '<p class="empty">Caricamento…</p>';

  try {
    const tournaments = await apiFetch('/tournaments?' + params.toString());
    const data = Array.isArray(tournaments) ? tournaments : (tournaments?.items ?? []);

    /* Paginazione client-side */
    const total   = data.length;
    const start   = (_page - 1) * PER_PAGE;
    const page    = data.slice(start, start + PER_PAGE);

    if (!page.length) {
      listEl.innerHTML = '';
      emptyEl.style.display = '';
      return;
    }
    emptyEl.style.display = 'none';

    listEl.innerHTML = page.map(t => `
      <article class="event-card">
        <div class="event-card-head">
          <div>
            <strong>${esc(t.name)}</strong>
            ${t.venue ? `<small>${esc(t.venue)}</small>` : ''}
          </div>
          <span class="badge">${esc(t.format)}</span>
        </div>
        <div class="event-card-meta">
          <span>${fmtDate(t.starts_on?.substring(0,10))}</span>
          <span>${fmtMoney((t.entry_fee_cents||0)/100)} entry</span>
          <span>${Math.max(t.capacity - (t.registered_players||0), 0)} posti</span>
          <span class="badge">${esc(t.rules_enforcement_level || 'Regular')}</span>
        </div>
        <a class="primary" href="event.html?id=${t.id}" style="text-align:center;text-decoration:none;display:block;padding:10px;border-radius:8px">
          Dettagli e iscrizione →
        </a>
      </article>`).join('');

    /* Controlli pagina */
    const totalPages = Math.ceil(total / PER_PAGE);
    const pagEl = document.querySelector('#eventsPagination');
    pagEl.innerHTML = totalPages <= 1 ? '' : `
      <button class="secondary" ${_page <= 1 ? 'disabled' : ''} id="prevPage">← Prec</button>
      <span class="page-info">${_page} / ${totalPages}</span>
      <button class="secondary" ${_page >= totalPages ? 'disabled' : ''} id="nextPage">Succ →</button>`;
    pagEl.querySelector('#prevPage')?.addEventListener('click', () => { _page--; loadTournaments(); });
    pagEl.querySelector('#nextPage')?.addEventListener('click', () => { _page++; loadTournaments(); });

  } catch (err) {
    listEl.innerHTML = `<p class="empty">Impossibile caricare i tornei: ${esc(err.message)}</p>`;
  }
}

/* ── Init ────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const i18n = await import('./i18n.js');
    i18n.initI18n();
  } catch { /* i18n opzionale */ }
  updateAuthNav();
  loadTournaments();

  document.querySelector('#searchForm')?.addEventListener('submit', e => {
    e.preventDefault(); _page = 1; loadTournaments();
  });

  /* Real-time search */
  ['#searchName','#searchFormat','#searchDate','#searchCity'].forEach(id => {
    document.querySelector(id)?.addEventListener('input', () => { _page = 1; loadTournaments(); });
  });
});
