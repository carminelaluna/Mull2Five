/**
 * console.js — Regia del torneo, montabile ovunque.
 *
 * Stessa console in due posti: dentro la pagina dell'evento in back-office
 * (l'organizzatore non deve cambiare scheda per far scorrere un round) e come
 * pagina a sé su control.html, che resta indispensabile in sala — su un secondo
 * schermo e per i judge, che nel back-office non entrano.
 *
 * Tutto lo stato vive nella chiusura di `mountConsole`: due montaggi non si
 * pestano i piedi e `destroy()` ferma i timer, altrimenti il ciclo di refresh
 * continuerebbe a riscrivere un pannello che non esiste più.
 */
import { toast } from './catalog.js';
import { esc } from './escape.js';
import { scoreLabel, scoresFor } from './games.js';
import { t as tr } from './i18n.js';
import { apiRequest, decodeToken, getToken } from './session.js';


function scoreToBody(score) {
  const [a, b] = score.split('-').map(Number);
  return { match_wins_a: a, match_wins_b: b, draws: a === 1 && b === 1 ? 1 : 0 };
}

function fmt(sec) {
  const over = sec < 0;
  const s = Math.abs(Math.floor(sec));
  return `${over ? '-' : ''}${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

const SHELL = `
  <div class="ctl-screens" data-el="screens"></div>

  <div class="ctl-timer">
    <span class="ctl-clock" data-el="clock">--:--</span>
    <label>min <input data-el="minutes" type="number" min="1" max="180" value="50" style="width:64px" /></label>
    <button class="primary"   data-el="restart"  type="button">▶ Avvia / Reset</button>
    <button class="secondary" data-el="stop"     type="button">⏹ Stop</button>
    <button class="secondary" data-el="extend5"  type="button">+5′ round</button>
    <button class="secondary" data-el="extend10" type="button">+10′ round</button>
    <span data-el="roundLabel" style="color:var(--muted)"></span>
  </div>

  <div class="badge warn" data-el="closedBanner" style="display:none;margin-bottom:12px">
    Torneo chiuso: risultati e classifica restano consultabili, ma non si generano altri turni.
  </div>

  <div class="ctl-tabs" data-el="tabs"></div>
  <div class="panel" data-el="tables"><p class="empty">Caricamento…</p></div>

  <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
    <button class="secondary" data-el="genRound" type="button">Genera round successivo</button>
    <button class="secondary" data-el="closeTournament" type="button" style="display:none">🏁 Chiudi torneo</button>
  </div>`;

/**
 * Disegna la console dentro `host` e la tiene viva.
 * @returns {{destroy: () => void, tournamentId: string}}
 */
export function mountConsole(host, tournamentId, { screenLinks = true, onClosed = null } = {}) {
  const tid = String(tournamentId);

  let rounds = [];
  let activeRoundId = null;
  let judgeView = false;
  let tournament = null;
  let myRole = 'none';
  let deckChecks = [];
  let alive = true;
  // Dal token: serve per sapere quale tavolo e il mio.
  const myUserId = +(decodeToken(getToken())?.sub) || null;
  const editing = new Set();   // pairing in correzione

  host.innerHTML = `<div class="ctl-console">${SHELL}</div>`;
  const el = (name) => host.querySelector(`[data-el="${name}"]`);

  const apiFetch = (path, opts = {}) => apiRequest(path, { requireLogin: true, ...opts });

  async function call(fn, okMsg) {
    try { await fn(); toast(okMsg); await refresh(); }
    catch (e) { toast('Errore: ' + e.message); }
  }

  const isClosed = () => ['completed', 'cancelled'].includes(tournament?.status);
  /* Chi fa scorrere i round: organizzatore e capojudge. Il judge arbitra i tavoli. */
  const canRunRounds = () => ['organizer', 'head_judge'].includes(myRole);
  const activeRound = () => rounds.find((r) => String(r.id) === String(activeRoundId));

  /* ── Dati ──────────────────────────────────────────────── */

  async function refresh() {
    if (!alive) return;
    try { rounds = (await apiFetch(`/tournaments/${tid}/rounds`) || []).sort((a, b) => a.number - b.number); }
    catch { rounds = []; }
    try { tournament = await apiFetch(`/tournaments/${tid}`); } catch { tournament = null; }
    try { myRole = (await apiFetch(`/tournaments/${tid}/my-role`))?.role || 'none'; } catch { myRole = 'none'; }
    try { deckChecks = await apiFetch(`/tournaments/${tid}/deck-checks`) || []; } catch { deckChecks = []; }
    if (!alive) return;   // il pannello può essere stato smontato durante le fetch
    if (!rounds.some((r) => String(r.id) === String(activeRoundId))) activeRoundId = rounds.at(-1)?.id ?? null;
    render();
    renderScreens();
    renderLifecycle();
  }

  /* ── Comandi che dipendono dallo stato del torneo ──────── */

  function renderLifecycle() {
    const closed = isClosed();
    el('closedBanner').style.display = closed ? 'block' : 'none';
    for (const name of ['restart', 'stop', 'extend5', 'extend10', 'genRound']) {
      el(name).disabled = closed;
    }
    // Chiudere il torneo spetta all'organizzatore, non ai judge.
    el('closeTournament').style.display = (myRole === 'organizer' && !closed) ? '' : 'none';
    el('genRound').style.display = canRunRounds() ? '' : 'none';
  }

  function renderScreens() {
    if (!screenLinks) { el('screens').innerHTML = ''; return; }
    el('screens').innerHTML = `
      <a class="secondary-link" href="timer.html?t=${tid}" target="_blank" rel="noopener">🖥 Timer schermo</a> ·
      <a class="secondary-link" href="display.html?t=${tid}" target="_blank" rel="noopener">📺 Display abbinamenti</a>
      <small style="color:var(--muted);margin-left:8px">${location.origin}/display.html?t=${tid}</small>`;
  }

  /* ── Round ─────────────────────────────────────────────── */

  async function genRound(force = false) {
    try {
      const rnd = await apiFetch(`/tournaments/${tid}/rounds${force ? '?force=true' : ''}`, { method: 'POST' });
      if (rnd?.id) activeRoundId = rnd.id;   // si passa subito al round nuovo
      toast('Round generato.');
      await refresh();
    } catch (e) {
      // Oltre i turni svizzeri previsti il backend chiede conferma: 409 EXTRA_SWISS_ROUND.
      if (!force && String(e.message).includes('EXTRA_SWISS_ROUND')) {
        const msg = e.message.replace(/^EXTRA_SWISS_ROUND:\s*/, '');
        if (window.confirm(`⚠️ ${msg}\n\nVuoi comunque generare un turno aggiuntivo?`)) return genRound(true);
        return;
      }
      toast('Errore: ' + e.message);
    }
  }

  async function closeTournament() {
    const pending = rounds.at(-1)?.pairings?.filter((p) => p.player_b && !p.result).length || 0;
    const warning = pending
      ? `\n\nAttenzione: ${pending} tavol${pending === 1 ? 'o' : 'i'} dell'ultimo round non ha ancora un risultato.`
      : '';
    const name = tournament?.name || 'il torneo';
    if (!window.confirm(`Chiudere "${name}"?${warning}\n\nLa classifica resta consultabile, ma non potrai generare altri turni.`)) return;
    try {
      await apiFetch(`/tournaments/${tid}/close`, { method: 'POST' });
      toast('Torneo chiuso.');
      await refresh();
      onClosed?.();
    } catch (e) { toast('Errore: ' + e.message); }
  }

  /* ── Tavoli ────────────────────────────────────────────── */

  /* Chi non si presenta al tavolo perde a tavolino: l'avversario vince con il
     punteggio pieno e la penalità resta scritta. */
  function noShow(p, rid, name) {
    return `<button class="mini-button danger" data-action="no-show" data-pid="${p.id}" data-rid="${rid}"
      data-name="${esc(name)}" type="button" title="${esc(tr('Non si è presentato: sconfitta a tavolino'))}">🚫 ${esc(name)}</button>`;
  }

  function renderRow(round, p, allowNoShow) {
    const isBye = !p.player_b;
    const absentBox = (id) => (allowNoShow
      ? `<label class="absent-chk"><input type="checkbox" data-absent="${id}"> ass.</label>` : '');
    const finalScore = p.result && p.result !== '' ? `${p.match_wins_a}-${p.match_wins_b}` : '';

    let control;
    if (isBye) {
      control = '<span class="badge ok">BYE · 2 – 0</span>';
    } else if (finalScore && !editing.has(String(p.id))) {
      control = `<span class="badge ok">${finalScore.replace('-', ' – ')} 🔒</span>
        <button class="mini-button" data-action="edit" data-pid="${p.id}" type="button">Modifica</button>`;
    } else {
      // Correggere un risultato già bloccato passa da /correct (audit log);
      // l'inserimento normale resta su /result.
      const correct = finalScore ? ' data-correct="1"' : '';
      // I punteggi possibili dipendono dal formato del torneo; nei playoff al meglio di 3.
      const scores = scoresFor(tournament?.best_of, {
        playoff: (round.phase || 'swiss') !== 'swiss',
        intentionalDraws: tournament?.allow_intentional_draws !== false,
      });
      if (finalScore && !scores.includes(finalScore)) scores.push(finalScore);   // uno già salvato si vede comunque
      const opts = ['<option value="">— in corso</option>'].concat(
        scores.map((s) => `<option value="${s}"${finalScore === s ? ' selected' : ''}>${scoreLabel(s)}</option>`));
      control = `<select data-action="result" data-pid="${p.id}"${correct}>${opts.join('')}</select>`;
    }

    let judgeTools = '';
    if (judgeView && !isBye) {
      const btn = (rid, kind, cls, label) =>
        `<button class="mini-button ${cls}" data-action="penalty" data-rid="${rid}" data-kind="${kind}" type="button">${label}</button>`;
      // Il segno di spunta dice che quella lista e gia stata controllata: senza,
      // due judge rifanno lo stesso deck check e si perde tempo di round.
      const dc = (rid, name) => {
        const done = deckChecks.some((c) => String(c.registration_id) === String(rid));
        return `<button class="mini-button${done ? ' checked' : ''}" data-action="deck-check"
          data-rid="${rid}" data-name="${esc(name)}" type="button"
          title="${done ? 'Gia controllato' : 'Registra deck check'}">${done ? '✓' : '🔍'} ${esc(name)}</button>`;
      };
      judgeTools = `<span class="judge-tools">
        ${btn(p.player_a_registration_id, 'warning', 'warn', `⚠ ${esc(p.player_a)}`)}
        ${btn(p.player_b_registration_id, 'warning', 'warn', `⚠ ${esc(p.player_b)}`)}
        ${btn(p.player_a_registration_id, 'game_loss', 'danger', `GL ${esc(p.player_a)}`)}
        ${btn(p.player_b_registration_id, 'game_loss', 'danger', `GL ${esc(p.player_b)}`)}
        ${dc(p.player_a_registration_id, p.player_a)}
        ${dc(p.player_b_registration_id, p.player_b)}
        ${finalScore ? '' : noShow(p, p.player_a_registration_id, p.player_a) + noShow(p, p.player_b_registration_id, p.player_b)}
      </span>`;
    }

    let tableClock = '';
    if (!isBye && !finalScore) {
      const extra = p.extra_seconds || 0;
      const clockSpan = round.ends_at
        ? `<span class="tbl-clock" data-ends="${round.ends_at}" data-extra="${extra}"></span>` : '';
      const extraLbl = extra ? `<span class="tbl-extra">+${Math.round(extra / 60)}′</span>` : '';
      tableClock = `${clockSpan}${extraLbl}
        <button class="mini-button" data-action="extend-table" data-pid="${p.id}" data-min="2" type="button">+2′</button>
        <button class="mini-button" data-action="extend-table" data-pid="${p.id}" data-min="5" type="button">+5′</button>`;
    }

    // Lo stato dedotto batte quello manuale: se il risultato c'e, il tavolo e
    // chiuso qualunque cosa dica table_status.
    const stato = finalScore ? 'done'
      : p.report_status === 'conflict' ? 'disputed'
      : (p.table_status || 'playing');
    const statoLabel = {
      playing: '', called: 'chiamato', attention: 'serve judge',
      disputed: 'contestato', done: '',
    }[stato];
    const mine = String(p.assigned_judge_id || '') === String(myUserId);

    return `<div class="ctl-row status-${esc(stato)}">
      <span class="table-num">T${p.table_number}</span>
      <span class="names"><strong>${esc(p.player_a)}</strong>${absentBox(p.player_a_registration_id)} vs <strong>${esc(p.player_b || 'BYE')}</strong>${p.player_b ? absentBox(p.player_b_registration_id) : ''}</span>
      ${tableClock}
      ${statoLabel ? `<span class="tbl-state">${esc(statoLabel)}</span>` : ''}
      ${p.assigned_judge_name
        ? `<button class="mini-button judge-chip${mine ? ' mine' : ''}" data-action="unassign" data-pid="${p.id}" type="button" title="Libera il tavolo">👤 ${esc(p.assigned_judge_name)}</button>`
        : (finalScore ? '' : `<button class="mini-button" data-action="assign" data-pid="${p.id}" type="button">Prendo io</button>`)}
      ${finalScore ? '' : `<button class="mini-button" data-action="cycle-status" data-pid="${p.id}" data-next="${stato === 'playing' ? 'called' : stato === 'called' ? 'attention' : 'playing'}" type="button" title="Cambia stato">⚑</button>`}
      ${judgeTools}
      <span>${control}</span>
    </div>`;
  }

  async function submitResult(pairingId, score, isCorrection) {
    if (!score) return;
    editing.delete(String(pairingId));
    const path = isCorrection ? `/pairings/${pairingId}/correct` : `/pairings/${pairingId}/result`;
    await call(
      () => apiFetch(`/tournaments/${tid}${path}`, { method: 'PATCH', body: JSON.stringify(scoreToBody(score)) }),
      isCorrection ? 'Risultato corretto.' : 'Risultato registrato.');
  }

  function render() {
    const round = activeRound();
    const tabs = el('tabs');
    tabs.innerHTML = rounds.map((r) =>
      `<button class="ctl-tab${String(r.id) === String(activeRoundId) ? ' active' : ''}" data-round="${r.id}" type="button">Round ${r.number}</button>`
    ).join('') + `<button class="ctl-tab judge${judgeView ? ' active' : ''}" data-el="judgeToggle" type="button">⚖ Judge</button>`;

    tabs.querySelectorAll('[data-round]').forEach((b) =>
      b.addEventListener('click', () => { activeRoundId = b.dataset.round; render(); }));
    el('judgeToggle').addEventListener('click', () => { judgeView = !judgeView; render(); });

    const tables = el('tables');
    if (!round) {
      tables.innerHTML = '<p class="empty">Nessun round. Avvia il torneo e genera il primo round.</p>';
      el('roundLabel').textContent = '';
      return;
    }
    el('roundLabel').textContent = `Round ${round.number}`;

    const pairings = round.pairings
      .filter((p) => !judgeView || (p.player_b && !p.result))
      .sort((a, b) => a.table_number - b.table_number);

    // L'ultimo round senza risultati si può rigenerare segnando gli assenti.
    const isLatest = String(round.id) === String(rounds.at(-1)?.id);
    const noResults = !round.pairings.some((p) => p.result && p.player_b);
    const canRegen = !judgeView && canRunRounds() && isLatest && noResults;
    const noShowBar = canRegen
      ? `<div class="noshow-bar">
           <button class="mini-button" data-el="regen" type="button">♻ Segna assenti &amp; rigenera</button>
           <small style="color:var(--muted)">Spunta gli assenti, poi rigenera gli abbinamenti.</small>
         </div>` : '';

    tables.innerHTML = noShowBar + (pairings.length
      ? pairings.map((p) => renderRow(round, p, canRegen)).join('')
      : '<p class="empty" style="margin:0">Tutti i tavoli hanno un risultato. ✓</p>');

    el('regen')?.addEventListener('click', () => {
      const ids = [...tables.querySelectorAll('input[data-absent]:checked')].map((c) => +c.dataset.absent);
      if (!ids.length && !window.confirm('Nessun assente selezionato: rigenerare comunque gli abbinamenti?')) return;
      call(() => apiFetch(`/tournaments/${tid}/rounds/regenerate`, {
        method: 'POST', body: JSON.stringify({ drop_registration_ids: ids }),
      }), 'Round rigenerato.');
    });

    tables.querySelectorAll('[data-action="result"]').forEach((sel) =>
      sel.addEventListener('change', () => submitResult(sel.dataset.pid, sel.value, sel.dataset.correct === '1')));
    tables.querySelectorAll('[data-action="edit"]').forEach((btn) =>
      btn.addEventListener('click', () => { editing.add(btn.dataset.pid); render(); }));
    tables.querySelectorAll('[data-action="extend-table"]').forEach((btn) =>
      btn.addEventListener('click', () => call(
        () => apiFetch(`/tournaments/${tid}/pairings/${btn.dataset.pid}/extend`,
          { method: 'PATCH', body: JSON.stringify({ minutes: +btn.dataset.min }) }),
        `+${btn.dataset.min} minuti al tavolo.`)));
    tables.querySelectorAll('[data-action="assign"]').forEach((btn) =>
      btn.addEventListener('click', () => call(
        () => apiFetch(`/tournaments/${tid}/pairings/${btn.dataset.pid}/assign`,
          { method: 'PATCH', body: JSON.stringify({ user_id: myUserId }) }), 'Tavolo preso.')));
    tables.querySelectorAll('[data-action="unassign"]').forEach((btn) =>
      btn.addEventListener('click', () => call(
        () => apiFetch(`/tournaments/${tid}/pairings/${btn.dataset.pid}/assign`,
          { method: 'PATCH', body: JSON.stringify({ user_id: null }) }), 'Tavolo liberato.')));
    tables.querySelectorAll('[data-action="cycle-status"]').forEach((btn) =>
      btn.addEventListener('click', () => call(
        () => apiFetch(`/tournaments/${tid}/pairings/${btn.dataset.pid}/status`,
          { method: 'PATCH', body: JSON.stringify({ status: btn.dataset.next }) }), 'Stato aggiornato.')));
    tables.querySelectorAll('[data-action="deck-check"]').forEach((btn) =>
      btn.addEventListener('click', () => openDeckCheck(+btn.dataset.rid, btn.dataset.name)));
    tables.querySelectorAll('[data-action="no-show"]').forEach((btn) =>
      btn.addEventListener('click', () => {
        const name = btn.dataset.name;
        if (!confirm(tr('{nome} non si è presentato: sconfitta a tavolino?', { nome: name }))) return;
        const drop = confirm(tr('Ritirare {nome} dal torneo? Se resta, al prossimo turno viene abbinato di nuovo.', { nome: name }));
        call(() => apiFetch(`/tournaments/${tid}/pairings/${btn.dataset.pid}/tardiness`, {
          method: 'POST',
          body: JSON.stringify({ registration_id: +btn.dataset.rid, penalty: 'match_loss', drop }),
        }), drop ? tr('Sconfitta a tavolino, giocatore ritirato.') : tr('Sconfitta a tavolino assegnata.'));
      }));
    tables.querySelectorAll('[data-action="penalty"]').forEach((btn) =>
      btn.addEventListener('click', () => {
        const label = btn.dataset.kind === 'game_loss' ? 'Game Loss' : 'Warning';
        call(() => apiFetch(`/tournaments/${tid}/penalties`, {
          method: 'POST',
          body: JSON.stringify({
            registration_id: +btn.dataset.rid,
            round_id: activeRound()?.id || null,
            kind: btn.dataset.kind,
          }),
        }), `${label} assegnato.`);
      }));
  }

  /* ── Deck check ────────────────────────────────────────── */

  const DC_RESULTS = [
    { value: 'ok',        label: 'Regolare' },
    { value: 'minor',     label: 'Discrepanza lieve' },
    { value: 'major',     label: 'Errore grave' },
    { value: 'not_found', label: 'Lista assente' },
  ];

  /* La dialog la crea il modulo: la console si monta in due pagine diverse e
     non puo contare sul markup di nessuna delle due. */
  function openDeckCheck(registrationId, playerName) {
    let dlg = host.querySelector('.dc-dialog');
    if (!dlg) {
      dlg = document.createElement('dialog');
      dlg.className = 'dc-dialog bo-dialog';
      host.appendChild(dlg);
    }
    const storico = deckChecks
      .filter((c) => String(c.registration_id) === String(registrationId))
      .map((c) => `<li>${esc(DC_RESULTS.find((r) => r.value === c.result)?.label || c.result)}
        ${c.round_number ? `· round ${c.round_number}` : ''}
        ${c.note ? `· ${esc(c.note)}` : ''}
        <small style="color:var(--muted)">— ${esc(c.judge_name)}</small></li>`).join('');

    dlg.innerHTML = `
      <form method="dialog" class="modal">
        <header>
          <div><span class="eyebrow">Deck check</span><h2>${esc(playerName)}</h2></div>
          <button class="icon-button" value="cancel" formnovalidate>&times;</button>
        </header>
        <label>Esito<select data-el="dcResult">
          ${DC_RESULTS.map((r) => `<option value="${r.value}">${esc(r.label)}</option>`).join('')}
        </select></label>
        <label>Nota<input data-el="dcNote" maxlength="500" placeholder="Carta mancante, lista illeggibile…" /></label>
        ${storico ? `<h3 style="margin:16px 0 6px;font-size:.9rem">Controlli precedenti</h3>
          <ul style="margin:0;padding-left:18px;font-size:.85rem;line-height:1.7">${storico}</ul>` : ''}
        <menu>
          <button class="secondary" value="cancel" formnovalidate>Annulla</button>
          <button class="primary" data-el="dcSave" type="button">Registra</button>
        </menu>
      </form>`;
    dlg.showModal();
    dlg.querySelector('[data-el="dcSave"]').addEventListener('click', async () => {
      try {
        await apiFetch(`/tournaments/${tid}/deck-checks`, {
          method: 'POST',
          body: JSON.stringify({
            registration_id: registrationId,
            result: dlg.querySelector('[data-el="dcResult"]').value,
            note: dlg.querySelector('[data-el="dcNote"]').value.trim(),
          }),
        });
        dlg.close();
        toast('Deck check registrato.');
        await refresh();
      } catch (e) { toast('Errore: ' + e.message); }
    });
  }

  /* ── Countdown ─────────────────────────────────────────── */

  function tick() {
    const round = activeRound();
    const clock = el('clock');
    if (round?.ends_at) {
      const rem = (new Date(round.ends_at) - Date.now()) / 1000;
      clock.textContent = fmt(rem);
      clock.className = 'ctl-clock ' + (rem <= 0 ? 'over' : rem <= 300 ? 'warning' : '');
    } else {
      clock.textContent = '--:--';
      clock.className = 'ctl-clock';
    }
    host.querySelectorAll('.tbl-clock[data-ends]').forEach((span) => {
      const end = new Date(span.dataset.ends).getTime() + (+span.dataset.extra) * 1000;
      const rem = (end - Date.now()) / 1000;
      span.textContent = fmt(rem);
      span.classList.toggle('over', rem <= 0);
    });
  }

  /* ── Avvio ─────────────────────────────────────────────── */

  const extend = (min) => apiFetch(`/tournaments/${tid}/timer/extend`,
    { method: 'POST', body: JSON.stringify({ minutes: min }) });

  el('restart').addEventListener('click', () => call(
    () => apiFetch(`/tournaments/${tid}/timer/restart`,
      { method: 'POST', body: JSON.stringify({ minutes: +el('minutes').value || 50 }) }), 'Timer avviato.'));
  el('stop').addEventListener('click', () => call(
    () => apiFetch(`/tournaments/${tid}/timer/stop`, { method: 'POST' }), 'Timer fermato.'));
  el('extend5').addEventListener('click', () => call(() => extend(5), '+5 minuti al round.'));
  el('extend10').addEventListener('click', () => call(() => extend(10), '+10 minuti al round.'));
  el('genRound').addEventListener('click', () => genRound());
  el('closeTournament').addEventListener('click', closeTournament);

  refresh();
  const poll = setInterval(refresh, 4000);   // riallinea con chi lavora da altri dispositivi
  const beat = setInterval(tick, 250);       // countdown fluido, senza chiamate

  return {
    tournamentId: tid,
    destroy() {
      alive = false;
      host.querySelector('.dc-dialog')?.close();
      clearInterval(poll);
      clearInterval(beat);
      host.innerHTML = '';
    },
  };
}
