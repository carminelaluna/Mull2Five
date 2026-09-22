import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { apiGet, toast, updateAuthNav } from './catalog.js';
import { esc } from './escape.js';

const params    = new URLSearchParams(location.search);
const PUBLIC_ID = params.get('p');   // URL: /player.html?p=abc123 (mai l'email)

function fmtDate(d) { if (!d) return '—'; const [y,m,dd]=d.split('-'); return `${dd}/${m}/${y}`; }
/* ── Load profile ─────────────────────────────────────── */
async function loadProfile() {
  const container = document.querySelector('#playerProfile');
  if (!PUBLIC_ID) { container.innerHTML = '<p class="empty">Profilo non trovato: il link potrebbe essere vecchio.</p>'; return; }

  try {
    /* Profilo pubblico calcolato dal backend (solo tornei con classifica pubblica) */
    const profile = await apiGet(`/tournaments/players/${encodeURIComponent(PUBLIC_ID)}/public-history`);
    const playerName = profile.display_name || 'Giocatore';
    const totalW = profile.wins, totalD = profile.draws, totalL = profile.losses;
    const totalPts = profile.total_points, totalTournaments = profile.tournaments_played;

    // Inviti dei programmi ufficiali (un RCQ vinto, per esempio).
    const invites = (profile.rows || []).filter((r) => r.invited).length;
    const winPct = (totalW+totalD+totalL) > 0 ? Math.round(totalW/(totalW+totalD+totalL)*100) : 0;
    const initials = playerName.split(' ').map(w=>w[0]).slice(0,2).join('').toUpperCase();
    const isOrganizer = profile.role === 'organizer' || profile.role === 'admin';
    const organized = profile.organized || [];

    const tableRows = (profile.rows || []).map(r => `
      <tr>
        <td><strong>${esc(r.tournament_name)}</strong></td>
        <td>${esc(r.format)}</td>
        <td>${fmtDate(r.starts_on)}</td>
        <td><strong>${r.placement ? '#' + r.placement : '—'}</strong>${r.invited ? ' <span class="badge ok">🎟 Invito</span>' : ''}</td>
        <td><strong>${r.points}</strong></td>
        <td>${esc(r.record || '—')}</td>
      </tr>`).join('');

    const statusLabel = { published: 'Aperto', running: 'In corso', completed: 'Concluso' };
    const orgRows = organized.map(o => {
      const href = o.status === 'completed' ? `history.html` : `event.html?id=${o.tournament_id}`;
      return `<tr>
        <td><a href="${href}"><strong>${esc(o.name)}</strong></a></td>
        <td>${esc(o.format)}</td>
        <td>${fmtDate(typeof o.starts_on === 'string' ? o.starts_on : '')}</td>
        <td><span class="badge ${o.status === 'completed' ? '' : 'ok'}">${statusLabel[o.status] || o.status}</span></td>
        <td>${o.registered_players}</td>
      </tr>`;
    }).join('');

    /* Sezione "score" mostrata se ha giocato; sezione "tornei organizzati" se è organizzatore. */
    const scoreSection = (profile.rows || []).length ? `
      <h2 style="margin:24px 0 8px">📊 Risultati da giocatore</h2>
      <div class="stats-grid" style="margin-bottom:16px">
        <article class="metric"><span>Punti totali</span><strong>${totalPts}</strong></article>
        <article class="metric"><span>Record totale</span><strong>${totalW}V ${totalD}P ${totalL}S</strong></article>
        <article class="metric"><span>% vittorie</span><strong>${winPct}%</strong></article>
        <article class="metric"><span>Tornei giocati</span><strong>${totalTournaments}</strong></article>
        ${invites ? `<article class="metric"><span>Inviti ottenuti</span><strong>${invites}</strong></article>` : ''}
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Torneo</th><th>Formato</th><th>Data</th><th>Piazzamento</th><th>Punti</th><th>Record</th></tr></thead>
        <tbody>${tableRows}</tbody></table></div>` : '';

    const orgSection = organized.length ? `
      <h2 style="margin:24px 0 8px">🏟️ Tornei organizzati</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Torneo</th><th>Formato</th><th>Data</th><th>Stato</th><th>Iscritti</th></tr></thead>
        <tbody>${orgRows}</tbody></table></div>` : '';

    container.innerHTML = `
      <div style="display:flex;gap:20px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
        <div class="user-avatar" style="width:72px;height:72px;font-size:1.6rem;flex-shrink:0">${initials}</div>
        <div>
          <h1 style="margin:0 0 4px">${esc(playerName)}</h1>
          <p class="muted-text"><span class="badge">${isOrganizer ? 'Organizzatore' : 'Giocatore'}</span></p>
        </div>
      </div>

      ${scoreSection}
      ${orgSection}
      ${!scoreSection && !orgSection ? '<p class="empty">Nessun dato pubblico disponibile per questo profilo.</p>' : ''}

      <p style="margin-top:16px">
        <button class="secondary" onclick="navigator.clipboard.writeText(location.href).then(()=>toast('Link copiato!'))" type="button">
          🔗 Copia link profilo
        </button>
      </p>`;

  } catch (err) {
    container.innerHTML = `<p class="empty">Impossibile caricare il profilo: ${esc(err.message)}</p>`;
  }
}

onReady(() => { updateAuthNav(); loadProfile(); });
