/**
 * history.js — Storico tornei pubblico.
 * Elenca i tornei conclusi; cliccando un torneo mostra vincitore, classifica e
 * decklist (solo se rese pubbliche dall'organizzatore). Endpoint pubblici.
 */
const API = '/api';
const TOKEN_KEY = 'manabind-jwt-v1';

const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const fmtDate = (d) => { if (!d) return '—'; const [y, m, dd] = d.split('-'); return `${dd}/${m}/${y}`; };
function toast(msg) {
  const el = document.querySelector('#toast'); if (!el) return;
  el.textContent = msg; el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove('show'), 3000);
}

async function apiGet(path) {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await fetch(API + path, { headers });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function getSession() {
  const t = localStorage.getItem(TOKEN_KEY); if (!t) return null;
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); } catch { return null; }
}
function updateAuthNav() {
  const s = getSession(); const el = document.querySelector('#publicAuth'); if (!el) return;
  el.innerHTML = s
    ? `<a class="secondary-link" href="player.html?email=${encodeURIComponent(s.email)}">Profilo</a>
       <span style="color:var(--muted);font-size:.85rem">${esc(s.email)}</span>
       <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`
    : `<a class="secondary-link" href="login.html">Accedi</a><a class="primary-btn" href="login.html">Registrati</a>`;
  el.querySelector('#logoutBtn')?.addEventListener('click', () => { localStorage.removeItem(TOKEN_KEY); location.reload(); });
}

let _all = [];

async function loadHistory() {
  const list = document.querySelector('#histList');
  try {
    // I tornei conclusi (status=completed). list_tournaments è pubblico.
    _all = (await apiGet('/tournaments?status=completed')) || [];
    _all.sort((a, b) => String(b.starts_on).localeCompare(String(a.starts_on)));
  } catch (err) { list.innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`; return; }
  draw();
}

function draw() {
  const q = (document.querySelector('#histSearch').value || '').toLowerCase();
  const items = _all.filter(t => t.name.toLowerCase().includes(q));
  const list = document.querySelector('#histList');
  if (!items.length) { list.innerHTML = '<p class="empty">Nessun torneo concluso.</p>'; return; }
  list.innerHTML = items.map(t => `
    <article class="event-card" data-id="${t.id}" style="cursor:pointer">
      <div class="event-card-head">
        <div><strong>${esc(t.name)}</strong>${t.venue ? `<small>${esc(t.venue)}</small>` : ''}</div>
        <span class="badge">${esc(t.format)}</span>
      </div>
      <div class="event-card-meta">
        <span>${fmtDate(t.starts_on?.substring(0, 10))}${t.start_time ? ' · ' + esc(t.start_time) : ''}</span>
        <span>${t.registered_players} partecipanti</span>
      </div>
      <span class="primary" style="display:block;text-align:center;padding:8px;border-radius:8px">Vedi risultati →</span>
    </article>`).join('');
  list.querySelectorAll('[data-id]').forEach(c =>
    c.addEventListener('click', () => showResults(c.dataset.id)));
}

async function showResults(tid) {
  const box = document.querySelector('#histResults');
  box.style.display = 'block';
  box.innerHTML = '<p class="empty">Caricamento risultati…</p>';
  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  let r;
  try { r = await apiGet(`/tournaments/${tid}/public-results`); }
  catch (err) { box.innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`; return; }

  if (!r.standings_public) {
    box.innerHTML = `<div class="panel"><h2>${esc(r.name)}</h2>
      <p class="empty">La classifica di questo torneo non è pubblica.</p></div>`;
    return;
  }
  const winner = r.standings[0];
  const rows = r.standings.map(s => `
    <tr ${s.position === 1 ? 'style="font-weight:bold"' : ''}>
      <td>${s.position <= 3 ? ['🥇', '🥈', '🥉'][s.position - 1] : s.position}</td>
      <td>${esc(s.name)}</td>
      <td>${esc(s.archetype || '—')}</td>
      <td><strong>${s.points}</strong></td>
      <td>${esc(s.record)}</td>
      <td>${r.decklists_public && s.decklist ? `<button class="mini-button" data-deck="${s.registration_id}" type="button">Lista</button>` : '—'}</td>
    </tr>`).join('') || '<tr><td colspan="6" class="muted">Nessun risultato.</td></tr>';

  box.innerHTML = `<div class="panel">
    <h2 style="margin-top:0">${esc(r.name)} — ${esc(r.format)}</h2>
    <p class="muted">${fmtDate(String(r.starts_on))}${r.start_time ? ' · ' + esc(r.start_time) : ''}</p>
    ${winner ? `<div class="my-standing" style="margin-bottom:12px">🏆 Vincitore: <strong>${esc(winner.name)}</strong>${winner.archetype ? ` — ${esc(winner.archetype)}` : ''}</div>` : ''}
    <table class="data-table" style="width:100%">
      <thead><tr><th>#</th><th>Giocatore</th><th>Archetipo</th><th>Punti</th><th>Record</th><th>Lista</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${r.decklists_public ? '' : '<p class="muted" style="margin-top:8px;font-size:.85rem">Le decklist di questo torneo non sono pubbliche.</p>'}
    <pre id="histDeck" style="display:none;white-space:pre-wrap;background:rgba(0,0,0,.25);padding:12px;border-radius:8px;margin-top:12px;max-height:340px;overflow:auto"></pre>
  </div>`;
  box.querySelectorAll('[data-deck]').forEach(b => b.addEventListener('click', () => {
    const s = r.standings.find(x => String(x.registration_id) === b.dataset.deck);
    const pre = document.querySelector('#histDeck');
    pre.style.display = 'block';
    pre.textContent = `${s.name}${s.archetype ? ' — ' + s.archetype : ''}\n\n${s.decklist}`;
    pre.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }));

  // #46 Bracket Top 8 (se gli abbinamenti sono pubblici)
  loadBracket(tid, box);
}

/* #46 Bracket pubblico Top 8: mostrato sotto la classifica se pairings_public. */
async function loadBracket(tid, box) {
  let matches = [];
  try { matches = (await apiGet(`/tournaments/${tid}/public-bracket`)) || []; }
  catch { return; }
  if (!matches.length) return;
  const byRound = {};
  for (const m of matches) (byRound[m.round_number] ||= []).push(m);
  const cols = Object.keys(byRound).sort((a, b) => a - b).map(rn => {
    const cells = byRound[rn].sort((a, b) => a.table_number - b.table_number).map(m => {
      const aw = m.winner && m.winner === m.player_a, bw = m.winner && m.winner === m.player_b;
      return `<div class="bracket-match">
        <div class="${aw ? 'bw' : ''}">${esc(m.player_a)} <span class="muted">${m.match_wins_a}</span></div>
        <div class="${bw ? 'bw' : ''}">${esc(m.player_b || 'BYE')} <span class="muted">${m.match_wins_b}</span></div>
      </div>`;
    }).join('');
    return `<div class="bracket-col"><h4>Turno ${rn}</h4>${cells}</div>`;
  }).join('');
  const panel = document.createElement('div');
  panel.className = 'panel';
  panel.style.marginTop = '12px';
  panel.innerHTML = `<h3 style="margin-top:0">🏆 Bracket Top 8</h3>
    <div class="bracket-grid" style="display:flex;gap:16px;overflow-x:auto">${cols}</div>`;
  box.appendChild(panel);
}

document.addEventListener('DOMContentLoaded', () => {
  updateAuthNav();
  loadHistory();
  document.querySelector('#histSearch').addEventListener('input', draw);
});
