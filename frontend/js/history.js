/**
 * history.js — Storico tornei pubblico.
 * Elenca i tornei conclusi; cliccando un torneo mostra vincitore, classifica e
 * decklist (solo se rese pubbliche dall'organizzatore). Endpoint pubblici.
 */
import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { apiGet, fmtDate, updateAuthNav } from './catalog.js';
import { renderDeck } from './deck-view.js';
import { esc } from './escape.js';

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
    <p style="margin:12px 0 0"><a class="secondary-link" href="coverage.html?t=${tid}">🖼 Scheda da pubblicare ↗</a></p>
  </div>`;
  box.querySelectorAll('[data-deck]').forEach(b => b.addEventListener('click', () => {
    const s = r.standings.find(x => String(x.registration_id) === b.dataset.deck);
    showDeck(s);
  }));

  // #46 Bracket Top 8 (se gli abbinamenti sono pubblici)
  loadBracket(tid, box);
  loadMeta(tid, box);
}

/* Metagame del torneo: quanti hanno giocato cosa e come e andata. */
async function loadMeta(tid, box) {
  let rows = [];
  try { rows = (await apiGet(`/tournaments/${tid}/public-meta`)) || []; } catch { return; }
  if (!rows.length) return;
  const max = Math.max(...rows.map(r => r.players));
  const body = rows.map(r => `
    <tr>
      <td style="min-width:160px">
        <strong>${esc(r.archetype)}</strong>
        <div class="meta-bar" style="width:${Math.round(r.players / max * 100)}%"></div>
      </td>
      <td>${r.players}</td>
      <td>${r.wins}/${r.losses}/${r.draws}</td>
      <td>${r.win_rate}%</td>
    </tr>`).join('');
  const panel = document.createElement('div');
  panel.className = 'panel';
  panel.style.marginTop = '12px';
  panel.innerHTML = `<h3 style="margin-top:0">Metagame</h3>
    <table class="data-table" style="width:100%">
      <thead><tr><th>Archetipo</th><th>Giocatori</th><th>V/S/P</th><th>Win rate</th></tr></thead>
      <tbody>${body}</tbody>
    </table>`;
  box.appendChild(panel);
}

/* Lista di un piazzato, con le immagini delle carte. */
async function showDeck(standing) {
  const body = document.querySelector('#deckViewBody');
  document.querySelector('#deckViewTitle').textContent =
    `${standing.name}${standing.archetype ? ' — ' + standing.archetype : ''}`;
  body.innerHTML = '<p class="empty">Caricamento lista…</p>';
  document.querySelector('#deckViewDialog').showModal();
  await renderDeck(body, standing.decklist || '');
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

onReady(async () => {
  updateAuthNav();
  await loadHistory();
  document.querySelector('#histSearch').addEventListener('input', draw);
  // history.html?t=ID apre subito quel torneo: ci si arriva da "Le mie iscrizioni".
  const wanted = new URLSearchParams(location.search).get('t');
  if (wanted) showResults(wanted);
});
