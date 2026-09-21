/**
 * series.js — Pagina pubblica di un circuito: classifica cumulativa e tappe.
 */
import { apiGet, esc, eventTile, fmtDate, updateAuthNav } from './catalog.js';

const $ = (s) => document.querySelector(s);

function leaderboardTable(rows, threshold) {
  if (!rows.length) return '<p class="empty">Ancora nessun punto assegnato.</p>';
  const body = rows.map((r) => {
    const qualified = threshold != null && r.points >= threshold;
    return `<tr>
      <td>${r.position <= 3 ? ['🥇', '🥈', '🥉'][r.position - 1] : r.position}</td>
      <td class="col-name">${esc(r.player_name)}
        ${qualified ? '<span class="col-sub dist-badge">Qualificato</span>' : ''}</td>
      <td><strong>${r.points}</strong></td>
      <td>${r.wins}/${r.draws}/${r.losses}</td>
      <td>${r.tournaments_played}</td>
    </tr>`;
  }).join('');
  return `<table class="results-table">
    <thead><tr><th>#</th><th>Giocatore</th><th>Punti</th><th>V/P/S</th><th>Tappe</th></tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

async function load() {
  const slug = new URLSearchParams(location.search).get('c');
  const host = $('#seriesProfile');
  if (!slug) { host.innerHTML = '<p class="empty">Circuito non indicato.</p>'; return; }

  let data;
  try {
    data = await apiGet(`/seasons/by-slug/${encodeURIComponent(slug)}`);
  } catch (err) {
    host.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }

  const s = data.season;
  document.title = `${s.name} — Mull2Five`;
  const period = s.starts_on || s.ends_on ? `${fmtDate(s.starts_on)} → ${fmtDate(s.ends_on)}` : '';

  host.innerHTML = `
    <div class="profile-head">
      <div style="flex:1;min-width:240px">
        <span class="eyebrow">Circuito${s.is_active ? ' · in corso' : ' · concluso'}</span>
        <h1>${esc(s.name)}</h1>
        ${s.description ? `<p style="color:var(--muted);margin:0">${esc(s.description)}</p>` : ''}
        ${period ? `<div class="tile-meta" style="margin-top:8px"><span>${esc(period)}</span></div>` : ''}
        <div class="profile-stats">
          <div class="profile-stat"><strong>${s.tournament_count}</strong><span>tappe</span></div>
          <div class="profile-stat"><strong>${s.points_win}</strong><span>punti vittoria</span></div>
          <div class="profile-stat"><strong>${s.points_draw}</strong><span>punti pareggio</span></div>
          ${s.points_champion_bonus
            ? `<div class="profile-stat"><strong>+${s.points_champion_bonus}</strong><span>bonus vincitore</span></div>`
            : ''}
          ${s.qualification_threshold != null
            ? `<div class="profile-stat"><strong>${s.qualification_threshold}</strong><span>soglia qualificazione</span></div>`
            : ''}
        </div>
      </div>
    </div>

    <section class="rail">
      <div class="rail-head"><h2>Classifica</h2></div>
      <div class="panel" style="padding:4px 8px">
        ${leaderboardTable(data.leaderboard, s.qualification_threshold)}
      </div>
    </section>

    <section class="rail">
      <div class="rail-head"><h2>Tappe</h2></div>
      ${data.tournaments.length
        ? `<div class="public-events-grid">${data.tournaments.map(eventTile).join('')}</div>`
        : '<p class="empty">Nessuna tappa collegata.</p>'}
    </section>`;
}

document.addEventListener('DOMContentLoaded', () => { updateAuthNav(); load(); });
