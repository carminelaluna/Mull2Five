/**
 * organizer-circuits.js — La sezione Circuiti del back-office: le leghe del negozio.
 *
 * Un circuito somma i punti di più tornei in una classifica sola. I tornei si
 * scelgono dall'elenco dei propri, già giocati o in calendario, e si aggiungono
 * anche uno alla volta man mano che si giocano. Un torneo sta in un circuito
 * solo: scegliendolo qui, lascia quello in cui era.
 */
import { toast } from './catalog.js';
import { esc } from './escape.js';
import { t as tr } from './i18n.js';
import { $, apiFetch, fmtDate } from './organizer-common.js';

let _circuits = [];
let _openId = null;
let _filter = 'tutti';        // tutti | giocati | in_programma
// I tornei e come ricaricarli li conosce organizer.js.
let _tournaments = () => [];
let _reloadTournaments = async () => {};

export function setCircuitSource(getTournaments, reloadTournaments) {
  _tournaments = getTournaments;
  _reloadTournaments = reloadTournaments;
}

/** Uscendo dalla sezione si torna all'elenco, come per le manifestazioni. */
export function leaveCircuits() { _openId = null; }

const STATUS = {
  draft: 'Bozza', published: 'Aperto', running: 'In corso', completed: 'Concluso', cancelled: 'Annullato',
};
const played = (t) => ['running', 'completed'].includes(t.status);
const day = (d) => (d ? String(d).slice(0, 10) : '');

function pointsSummary(c) {
  const parts = [tr('{n} a vittoria', { n: c.points_win }), tr('{n} a pareggio', { n: c.points_draw })];
  if (c.points_participation) parts.push(tr('{n} a tappa giocata', { n: c.points_participation }));
  if (c.points_champion_bonus) parts.push(tr('+{n} a chi vince un torneo', { n: c.points_champion_bonus }));
  return parts.join(' · ');
}

function pills(c) {
  return `<span class="pill ${c.is_active ? 'ok' : ''}">${esc(c.is_active ? tr('in corso') : tr('chiuso'))}</span>
    <span class="pill ${c.is_public ? 'ok' : 'warn'}">${esc(c.is_public ? tr('pubblico') : tr('privato'))}</span>`;
}

async function loadCircuits() {
  _circuits = await apiFetch('/seasons/mine') || [];
}

export async function renderCircuiti() {
  if (_openId) return renderCircuito(_openId);
  $('#panel').innerHTML = `<p class="empty">${esc(tr('Caricamento…'))}</p>`;
  try { await loadCircuits(); }
  catch (err) { $('#panel').innerHTML = `<p class="empty">${esc(tr('Errore'))}: ${esc(err.message)}</p>`; return; }

  const card = (c) => `
    <article class="bo-event" data-open-circuit="${c.id}">
      <div class="bo-event-main">
        <div class="tile-meta">${pills(c)}</div>
        <div class="bo-event-name">${esc(c.name)}</div>
        <div class="tile-meta">
          ${c.starts_on || c.ends_on ? `<span>${fmtDate(c.starts_on)} → ${fmtDate(c.ends_on)}</span>` : ''}
          <span>${esc(tr('{n} tornei', { n: c.tournament_count }))}</span>
          <span>${esc(pointsSummary(c))}</span>
        </div>
      </div>
    </article>`;

  $('#panel').innerHTML = `
    <div class="bo-head">
      <h2>${esc(tr('Circuiti'))}</h2>
      <button class="primary" id="ciNew" type="button">${esc(tr('+ Nuovo circuito'))}</button>
    </div>
    <p class="muted" style="margin:-8px 0 16px;max-width:64ch">${esc(tr(
      'Una lega: i tornei che scegli sommano i punti in una classifica sola. Puoi metterci tornei già giocati e quelli in calendario, anche uno alla volta man mano che si giocano.'))}</p>
    ${_circuits.length
      ? `<div class="bo-event-list">${_circuits.map(card).join('')}</div>`
      : `<p class="empty">${esc(tr('Nessun circuito. Creane uno per tenere la classifica di una lega.'))}</p>`}`;

  $('#ciNew').addEventListener('click', openNewDialog);
  $('#panel').querySelectorAll('[data-open-circuit]').forEach((el) =>
    el.addEventListener('click', () => { _openId = el.dataset.openCircuit; renderCircuiti(); }));
}

/* I campi dei punti, uguali nel modulo di creazione e in quello di modifica. */
function pointsFields(c, prefix) {
  const num = (id, label, value, extra = '') => `
    <label>${esc(label)}<input id="${prefix}${id}" type="number" min="0" max="100" step="1" value="${value ?? ''}" ${extra} /></label>`;
  return `
    ${num('Win', tr('Punti a vittoria'), c.points_win ?? 3, 'required')}
    ${num('Draw', tr('Punti a pareggio'), c.points_draw ?? 1, 'required')}
    ${num('Part', tr('Punti a tappa giocata'), c.points_participation ?? 0)}
    ${num('Bonus', tr('Bonus torneo vinto'), c.points_champion_bonus ?? 0)}
    <label>${esc(tr('Soglia di qualificazione'))}
      <input id="${prefix}Threshold" type="number" min="0" step="1" value="${c.qualification_threshold ?? ''}" placeholder="${esc(tr('nessuna'))}" /></label>`;
}

function readPoints(prefix) {
  const int = (id) => Math.min(100, Math.max(0, parseInt($(`#${prefix}${id}`).value, 10) || 0));
  const threshold = $(`#${prefix}Threshold`).value.trim();
  return {
    points_win: int('Win'),
    points_draw: int('Draw'),
    points_participation: int('Part'),
    points_champion_bonus: int('Bonus'),
    qualification_threshold: threshold === '' ? null : Math.max(0, parseInt(threshold, 10) || 0),
  };
}

function openNewDialog() {
  const dlg = $('#boDialog');
  dlg.innerHTML = `
    <form method="dialog" class="modal">
      <header><div><span class="eyebrow">${esc(tr('Circuito'))}</span><h2>${esc(tr('Nuovo circuito'))}</h2></div>
        <button class="icon-button" value="cancel" formnovalidate>&times;</button></header>
      <div class="bo-grid">
        <label style="grid-column:1/-1">${esc(tr('Nome'))}<input id="ciName" required minlength="3" maxlength="120" placeholder="${esc(tr('Lega del venerdì'))}" /></label>
        ${pointsFields({}, 'ciN')}
        <label class="bo-check" style="grid-column:1/-1"><input id="ciPub" type="checkbox" checked /> ${esc(tr('Pagina pubblica con la classifica'))}</label>
      </div>
      <menu>
        <button class="secondary" value="cancel" formnovalidate>${esc(tr('Annulla'))}</button>
        <button class="primary" id="ciCreate" type="button">${esc(tr('Crea'))}</button>
      </menu>
    </form>`;
  dlg.showModal();
  $('#ciName').focus();
  $('#ciCreate').addEventListener('click', async () => {
    const name = $('#ciName').value.trim();
    if (name.length < 3) { toast(tr('Il nome deve avere almeno 3 caratteri.')); return; }
    try {
      const created = await apiFetch('/seasons', { method: 'POST', body: JSON.stringify({
        name, is_public: $('#ciPub').checked, ...readPoints('ciN'),
      })});
      dlg.close();
      toast(tr('Circuito creato: ora scegli i tornei.'));
      _openId = String(created.id);     // si entra subito: il passo dopo è scegliere i tornei
      renderCircuiti();
    } catch (err) { toast(`${tr('Errore')}: ${err.message}`); }
  });
}

/* ── Dentro un circuito ───────────────────────────────── */

function leaderboardTable(rows, threshold) {
  if (!rows.length) {
    return `<p class="muted" style="margin:0">${esc(tr('Ancora nessun punto: la classifica nasce dai turni giocati nei tornei del circuito.'))}</p>`;
  }
  const body = rows.slice(0, 20).map((r) => `
    <tr>
      <td>${r.position}</td>
      <td><strong>${esc(r.player_name)}</strong>
        ${threshold != null && r.points >= threshold ? `<span class="pill ok">${esc(tr('qualificato'))}</span>` : ''}</td>
      <td><strong>${r.points}</strong></td>
      <td>${r.wins}/${r.draws}/${r.losses}</td>
      <td>${r.tournaments_played}</td>
      <td>${r.titles || ''}</td>
    </tr>`).join('');
  return `<div class="table-scroll"><table class="bo">
    <thead><tr><th>#</th><th>${esc(tr('Giocatore'))}</th><th>${esc(tr('Punti'))}</th><th>V/P/S</th>
      <th>${esc(tr('Tappe'))}</th><th>${esc(tr('Vinti'))}</th></tr></thead>
    <tbody>${body}</tbody></table></div>
    ${rows.length > 20 ? `<p class="muted" style="margin:8px 0 0">${esc(tr('I primi 20 di {n}: la classifica intera è sulla pagina pubblica.', { n: rows.length }))}</p>` : ''}`;
}

async function renderCircuito(id) {
  $('#panel').innerHTML = `<p class="empty">${esc(tr('Caricamento…'))}</p>`;
  let board = [];
  try {
    [, board] = await Promise.all([loadCircuits(), apiFetch(`/seasons/${id}/leaderboard`).catch(() => [])]);
  } catch (err) { toast(`${tr('Errore')}: ${err.message}`); }
  const c = _circuits.find((x) => String(x.id) === String(id));
  if (!c) { _openId = null; return renderCircuiti(); }

  const mine = _tournaments().filter((t) => t.can_manage && t.status !== 'cancelled');
  const inside = mine.filter((t) => t.season_id === c.id)
    .sort((a, b) => String(a.starts_on).localeCompare(String(b.starts_on)));
  const names = Object.fromEntries(_circuits.map((x) => [x.id, x.name]));
  const candidates = mine.filter((t) => t.season_id !== c.id)
    .filter((t) => _filter === 'tutti' || (_filter === 'giocati' ? played(t) : !played(t)))
    .sort((a, b) => String(b.starts_on).localeCompare(String(a.starts_on)));

  const stage = (t) => `
    <tr>
      <td><strong>${esc(t.name)}</strong><br><small class="muted">${esc(t.format)} · ${fmtDate(t.starts_on)}</small></td>
      <td><span class="pill ${t.status === 'completed' ? 'ok' : t.status === 'running' ? 'warn' : ''}">${esc(tr(STATUS[t.status] || t.status))}</span></td>
      <td class="row-actions"><button class="mini-button" data-remove="${t.id}" type="button">${esc(tr('Togli'))}</button></td>
    </tr>`;

  const candidate = (t) => `
    <tr>
      <td style="width:32px"><input type="checkbox" data-pick="${t.id}" aria-label="${esc(t.name)}" /></td>
      <td><strong>${esc(t.name)}</strong><br><small class="muted">${esc(t.format)} · ${fmtDate(t.starts_on)}</small>
        ${t.season_id ? `<br><small class="muted">${esc(tr('ora in «{name}»: passa a questo circuito', { name: names[t.season_id] || '—' }))}</small>` : ''}</td>
      <td><span class="pill ${t.status === 'completed' ? 'ok' : ''}">${esc(tr(STATUS[t.status] || t.status))}</span></td>
    </tr>`;

  const filterButton = (value, label) =>
    `<button class="mini-button${_filter === value ? ' active' : ''}" data-filter="${value}" type="button" aria-pressed="${_filter === value}">${esc(label)}</button>`;

  $('#panel').innerHTML = `
    <div class="bo-crumb">
      <button class="bo-back" id="ciBack" type="button">${esc(tr('← Circuiti'))}</button>
      <div class="bo-crumb-title">
        <strong>${esc(c.name)}</strong>
        <span class="muted">${pills(c)} ${esc(tr('{n} tornei', { n: c.tournament_count }))} · ${esc(pointsSummary(c))}</span>
      </div>
      <div class="bo-crumb-actions">
        ${c.is_public && c.slug ? `<a class="mini-button" href="series.html?c=${encodeURIComponent(c.slug)}" target="_blank" rel="noopener">↗ ${esc(tr('Pagina pubblica'))}</a>` : ''}
        <button class="mini-button" id="ciToggle" type="button">${esc(c.is_active ? tr('Chiudi circuito') : tr('Riapri circuito'))}</button>
      </div>
    </div>

    <div class="panel" style="margin-bottom:16px">
      <h3>${esc(tr('Tornei del circuito'))} (${inside.length})</h3>
      <table class="bo"><thead><tr><th>${esc(tr('Torneo'))}</th><th>${esc(tr('Stato'))}</th><th></th></tr></thead>
        <tbody>${inside.map(stage).join('')
          || `<tr><td colspan="3" class="muted">${esc(tr('Nessun torneo: sceglili qui sotto.'))}</td></tr>`}</tbody></table>
    </div>

    <div class="panel" style="margin-bottom:16px">
      <div class="bo-head" style="margin-bottom:8px">
        <h3 style="margin:0">${esc(tr('Aggiungi tornei'))}</h3>
        <div class="row-actions">
          ${filterButton('tutti', tr('Tutti'))}
          ${filterButton('giocati', tr('Già giocati'))}
          ${filterButton('in_programma', tr('In programma'))}
        </div>
      </div>
      ${c.is_active ? `
        <p class="muted" style="margin:0 0 8px;font-size:.85rem">${esc(tr(
          'Spunta i tornei e aggiungili insieme. Quelli già giocati portano subito i loro risultati in classifica; quelli in programma contano appena si giocano.'))}</p>
        ${candidates.length ? `
          <div class="table-scroll"><table class="bo"><tbody>${candidates.map(candidate).join('')}</tbody></table></div>
          <div class="row-actions" style="margin-top:12px">
            <button class="mini-button" id="ciPickAll" type="button">${esc(tr('Seleziona tutti'))}</button>
            <button class="primary" id="ciAdd" type="button" disabled>${esc(tr('Aggiungi selezionati'))}</button>
          </div>`
        : `<p class="muted" style="margin:0">${esc(tr('Nessun altro torneo da aggiungere.'))}</p>`}`
      : `<p class="muted" style="margin:0">${esc(tr('Il circuito è chiuso: riaprilo per aggiungere tornei.'))}</p>`}
    </div>

    <div class="panel" style="margin-bottom:16px">
      <h3>${esc(tr('Classifica'))}</h3>
      ${leaderboardTable(board, c.qualification_threshold)}
    </div>

    <div class="panel">
      <h3>${esc(tr('Regole e anagrafica'))}</h3>
      <form id="ciEditForm" class="bo-grid">
        <label style="grid-column:1/-1">${esc(tr('Nome'))}<input id="ciEName" required minlength="3" maxlength="120" value="${esc(c.name)}" /></label>
        <label>${esc(tr('Dal'))}<input id="ciEFrom" type="date" value="${esc(day(c.starts_on))}" /></label>
        <label>${esc(tr('Al'))}<input id="ciETo" type="date" value="${esc(day(c.ends_on))}" /></label>
        ${pointsFields(c, 'ciE')}
        <label style="grid-column:1/-1">${esc(tr('Descrizione'))}<textarea id="ciEDesc" maxlength="2000" style="min-height:70px">${esc(c.description || '')}</textarea></label>
        <label class="bo-check" style="grid-column:1/-1"><input id="ciEPub" type="checkbox" ${c.is_public ? 'checked' : ''} /> ${esc(tr('Pagina pubblica con la classifica'))}</label>
        <div class="row-actions" style="grid-column:1/-1;justify-content:space-between">
          <button class="primary" type="submit">${esc(tr('Salva'))}</button>
          <button class="mini-button" id="ciDelete" type="button" style="color:var(--danger)">${esc(tr('Elimina circuito'))}</button>
        </div>
      </form>
    </div>`;

  const refresh = async () => { await _reloadTournaments(); renderCircuiti(); };

  $('#ciBack').addEventListener('click', () => { _openId = null; renderCircuiti(); });

  $('#ciToggle').addEventListener('click', async () => {
    try {
      await apiFetch(`/seasons/${c.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !c.is_active }) });
      toast(c.is_active ? tr('Circuito chiuso.') : tr('Circuito riaperto.'));
      renderCircuiti();
    } catch (err) { toast(`${tr('Errore')}: ${err.message}`); }
  });

  $('#panel').querySelectorAll('[data-filter]').forEach((b) =>
    b.addEventListener('click', () => { _filter = b.dataset.filter; renderCircuiti(); }));

  $('#panel').querySelectorAll('[data-remove]').forEach((b) =>
    b.addEventListener('click', async () => {
      try {
        await apiFetch(`/seasons/${c.id}/tournaments/${b.dataset.remove}`, { method: 'DELETE' });
        toast(tr('Torneo tolto dal circuito: i suoi punti escono dalla classifica.'));
        await refresh();
      } catch (err) { toast(`${tr('Errore')}: ${err.message}`); }
    }));

  const picks = () => [...$('#panel').querySelectorAll('[data-pick]:checked')].map((x) => Number(x.dataset.pick));
  const addButton = $('#ciAdd');
  const syncAdd = () => {
    if (!addButton) return;
    const n = picks().length;
    addButton.disabled = n === 0;
    addButton.textContent = n ? tr('Aggiungi selezionati ({n})', { n }) : tr('Aggiungi selezionati');
  };
  $('#panel').querySelectorAll('[data-pick]').forEach((x) => x.addEventListener('change', syncAdd));
  $('#ciPickAll')?.addEventListener('click', () => {
    const boxes = [...$('#panel').querySelectorAll('[data-pick]')];
    const all = boxes.every((x) => x.checked);
    boxes.forEach((x) => { x.checked = !all; });
    syncAdd();
  });
  addButton?.addEventListener('click', async () => {
    const ids = picks();
    if (!ids.length) return;
    const moving = candidates.filter((t) => ids.includes(t.id) && t.season_id);
    if (moving.length && !window.confirm(tr('{n} tornei sono già in un altro circuito: passano a questo e lasciano quello. Continuare?', { n: moving.length }))) return;
    try {
      await apiFetch(`/seasons/${c.id}/tournaments`, { method: 'POST', body: JSON.stringify({ tournament_ids: ids }) });
      toast(tr('{n} tornei aggiunti al circuito.', { n: ids.length }));
      await refresh();
    } catch (err) { toast(`${tr('Errore')}: ${err.message}`); }
  });

  $('#ciEditForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('#ciEName').value.trim();
    if (name.length < 3) { toast(tr('Il nome deve avere almeno 3 caratteri.')); return; }
    try {
      await apiFetch(`/seasons/${c.id}`, { method: 'PATCH', body: JSON.stringify({
        name,
        description: $('#ciEDesc').value.trim(),
        starts_on: $('#ciEFrom').value || null,
        ends_on: $('#ciETo').value || null,
        is_public: $('#ciEPub').checked,
        ...readPoints('ciE'),
      })});
      toast(tr('Salvato: la classifica usa le regole nuove.'));
      renderCircuiti();
    } catch (err) { toast(`${tr('Errore')}: ${err.message}`); }
  });

  $('#ciDelete').addEventListener('click', async () => {
    if (!window.confirm(tr('Eliminare il circuito «{name}»? I tornei restano, si perde la classifica.', { name: c.name }))) return;
    try {
      await apiFetch(`/seasons/${c.id}`, { method: 'DELETE' });
      toast(tr('Circuito eliminato.'));
      _openId = null;
      await refresh();
    } catch (err) { toast(`${tr('Errore')}: ${err.message}`); }
  });
}
