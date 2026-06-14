const API       = '/api';
const TOKEN_KEY = 'manabind-jwt-v1';
const params    = new URLSearchParams(location.search);
const EMAIL     = params.get('email');   // URL: /player.html?email=xxx@xxx.com

function esc(s) { return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmtDate(d) { if (!d) return '—'; const [y,m,dd]=d.split('-'); return `${dd}/${m}/${y}`; }
function toast(msg) {
  const el = document.querySelector('#toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(()=>el.classList.remove('show'), 3200);
}

function getSession() {
  const t = localStorage.getItem(TOKEN_KEY); if (!t) return null;
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
  catch { return null; }
}

async function apiFetch(path) {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(API + path, { headers });
  if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || r.statusText);
  return r.json();
}

/* ── Auth nav ─────────────────────────────────────────── */
function updateAuthNav() {
  const s = getSession(); const el = document.querySelector('#publicAuth'); if (!el) return;
  if (s) {
    el.innerHTML = `<span style="color:var(--muted);font-size:.85rem">${esc(s.email)}</span>
      <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
    el.querySelector('#logoutBtn').addEventListener('click', () => { localStorage.removeItem(TOKEN_KEY); location.reload(); });
  } else {
    el.innerHTML = `<a class="secondary-link" href="login.html">Accedi</a>
                    <a class="primary-btn"    href="login.html">Registrati</a>`;
  }
}

/* ── Load profile ─────────────────────────────────────── */
async function loadProfile() {
  const container = document.querySelector('#playerProfile');
  if (!EMAIL) { container.innerHTML = '<p class="empty">Email giocatore mancante nell\'URL.</p>'; return; }

  try {
    /* Profilo pubblico calcolato dal backend (solo tornei con classifica pubblica) */
    const profile = await apiFetch(`/tournaments/players/${encodeURIComponent(EMAIL)}/public-history`);
    const playerName = profile.display_name || EMAIL.split('@')[0];
    const totalW = profile.wins, totalD = profile.draws, totalL = profile.losses;
    const totalPts = profile.total_points, totalTournaments = profile.tournaments_played;

    const winPct = (totalW+totalD+totalL) > 0 ? Math.round(totalW/(totalW+totalD+totalL)*100) : 0;
    const initials = playerName.split(' ').map(w=>w[0]).slice(0,2).join('').toUpperCase();
    const tableRows = (profile.rows || []).map(r => `
      <tr>
        <td><strong>${esc(r.tournament_name)}</strong></td>
        <td>${esc(r.format)}</td>
        <td>${fmtDate(r.starts_on)}</td>
        <td><strong>${r.placement ? '#' + r.placement : '—'}</strong></td>
        <td><strong>${r.points}</strong></td>
        <td>${esc(r.record || '—')}</td>
      </tr>`).join('');

    container.innerHTML = `
      <div style="display:flex;gap:20px;align-items:center;margin-bottom:28px;flex-wrap:wrap">
        <div class="user-avatar" style="width:72px;height:72px;font-size:1.6rem;flex-shrink:0">${initials}</div>
        <div>
          <h1 style="margin:0 0 4px">${esc(playerName)}</h1>
          <p class="muted-text">${esc(EMAIL)}</p>
        </div>
      </div>

      <div class="stats-grid" style="margin-bottom:24px">
        <article class="metric"><span>Punti totali</span><strong>${totalPts}</strong></article>
        <article class="metric"><span>Record totale</span><strong>${totalW}V ${totalD}P ${totalL}S</strong></article>
        <article class="metric"><span>% vittorie</span><strong>${winPct}%</strong></article>
        <article class="metric"><span>Tornei</span><strong>${totalTournaments}</strong></article>
      </div>

      ${tableRows ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Torneo</th><th>Formato</th><th>Data</th><th>Piazzamento</th><th>Punti</th><th>Record</th></tr></thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>` : '<p class="empty">Nessun dato di classifica disponibile.</p>'}

      <p style="margin-top:16px">
        <button class="secondary" onclick="navigator.clipboard.writeText(location.href).then(()=>toast('Link copiato!'))" type="button">
          🔗 Copia link profilo
        </button>
      </p>`;

  } catch (err) {
    container.innerHTML = `<p class="empty">Impossibile caricare il profilo: ${esc(err.message)}</p>`;
  }
}

document.addEventListener('DOMContentLoaded', () => { updateAuthNav(); loadProfile(); });
