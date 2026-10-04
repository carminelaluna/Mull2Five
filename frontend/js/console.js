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


/* `draws` sono le partite finite pari dentro il match, e non ne tracciamo:
   un 1-1 è un match pari con due partite giocate, non una patta di gioco.
   Mandarne una faceva rifiutare il referto dal server. */
function scoreToBody(score) {
  const [a, b] = score.split('-').map(Number);
  return { match_wins_a: a, match_wins_b: b, draws: 0 };
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
    <button class="primary"   data-el="restart"  type="button">${esc(tr('▶ Avvia / Reset'))}</button>
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

  <details class="panel" data-el="standingsBox" style="margin-top:12px">
    <summary>${esc(tr('Classifica'))}</summary>
    <div data-el="standings"><p class="empty">Caricamento…</p></div>
  </details>

  <details class="panel" data-el="bracketBox" style="margin-top:12px;display:none" open>
    <summary>Tabellone</summary>
    <div data-el="bracket"><p class="empty">Caricamento…</p></div>
  </details>

  <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
    <button class="secondary" data-el="genRound" type="button">${esc(tr('Genera round successivo'))}</button>
    <button class="secondary" data-el="closeTournament" type="button" style="display:none">${esc(tr('🏁 Chiudi torneo'))}</button>
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
  let standings = [];
  let bracket = [];
  let repairing = null;   // il tavolo che si sta riabbinando a mano
  let penaltiesFor = null;   // il tavolo di cui è aperto il pannello del judge
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
  /* Il referto di un judge lo conferma chi tiene il tabellone, non chi l'ha scritto. */
  const canConfirm = () => ['organizer', 'head_judge', 'scorekeeper'].includes(myRole);
  /* Warning e game loss li dà chi arbitra: a un giocatore la bandierina non compare. */
  const canJudge = () => ['organizer', 'head_judge', 'scorekeeper', 'judge'].includes(myRole);
  const activeRound = () => rounds.find((r) => String(r.id) === String(activeRoundId));

  /* ── Dati ──────────────────────────────────────────────── */

  async function refresh() {
    if (!alive) return;
    try { rounds = (await apiFetch(`/tournaments/${tid}/rounds`) || []).sort((a, b) => a.number - b.number); }
    catch { rounds = []; }
    try { tournament = await apiFetch(`/tournaments/${tid}`); } catch { tournament = null; }
    try { myRole = (await apiFetch(`/tournaments/${tid}/my-role`))?.role || 'none'; } catch { myRole = 'none'; }
    try { deckChecks = await apiFetch(`/tournaments/${tid}/deck-checks`) || []; } catch { deckChecks = []; }
    // La classifica serve in sala quanto gli abbinamenti: chi chiede "a che punto sono"
    // non deve mandare l'organizzatore in un'altra pagina.
    try { standings = await apiFetch(`/tournaments/${tid}/standings`) || []; } catch { standings = []; }
    try { bracket = await apiFetch(`/tournaments/${tid}/bracket`) || []; } catch { bracket = []; }
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

  /* Gli abbinamenti si correggono a mano solo sull'ultimo turno e prima che
     il tavolo abbia un risultato: il backend rifiuta il resto, ma inutile
     offrire un pulsante che non può funzionare. */
  function canEditPairing(round) {
    return canRunRounds()
      && !judgeView
      && String(round.id) === String(rounds.at(-1)?.id);
  }

  /* Chi si può mettere a questo tavolo: tutti quelli abbinati nel turno, più
     gli eventuali bye. Il doppione lo rifiuta il server, con il suo motivo. */
  function pairingChoices(round) {
    const visti = new Map();
    for (const p of round.pairings) {
      if (p.player_a_registration_id) visti.set(p.player_a_registration_id, p.player_a);
      if (p.player_b_registration_id) visti.set(p.player_b_registration_id, p.player_b);
    }
    return [...visti.entries()];
  }

  function pairingEditor(round, p) {
    const scelte = pairingChoices(round);
    const opts = (selected, vuoto) =>
      (vuoto ? `<option value="">${esc(tr('— nessuno (bye)'))}</option>` : '')
      + scelte.map(([id, nome]) =>
        `<option value="${id}"${String(id) === String(selected) ? ' selected' : ''}>${esc(nome)}</option>`).join('');
    return `<div class="ctl-row repair-row">
      <label>${esc(tr('Tavolo'))}<input type="number" min="1" data-repair="table" value="${p.table_number}" style="width:5rem" /></label>
      <select data-repair="a">${opts(p.player_a_registration_id, false)}</select>
      <span>vs</span>
      <select data-repair="b">${opts(p.player_b_registration_id, true)}</select>
      <button class="mini-button primary" data-action="repair-save" data-pid="${p.id}" type="button">${esc(tr('Salva'))}</button>
      <button class="mini-button" data-action="repair-cancel" type="button">${esc(tr('Annulla'))}</button>
    </div>`;
  }

  /* Il tabellone del taglio finale: una colonna per turno, dai quarti alla
     finale. Compare solo quando c'è, e resta aperto: in sala è quello che
     tutti guardano. */
  function renderBracket() {
    const box = el('bracketBox');
    if (!box) return;
    if (!bracket.length) { box.style.display = 'none'; return; }
    box.style.display = '';

    const perTurno = new Map();
    for (const m of bracket) {
      if (!perTurno.has(m.round_number)) perTurno.set(m.round_number, []);
      perTurno.get(m.round_number).push(m);
    }
    const colonne = [...perTurno.entries()].sort((a, b) => a[0] - b[0]).map(([numero, partite]) => {
      const titolo = { 1: tr('Finale'), 2: tr('Semifinali'), 4: tr('Quarti'), 8: tr('Ottavi') }[partite.length]
        || tr('Turno {n}', { n: numero });
      const righe = partite.sort((a, b) => a.table_number - b.table_number).map((m) => {
        const vinto = (nome) => (m.winner && m.winner === nome ? ' won' : '');
        return `<div class="br-match">
          <div class="br-side${vinto(m.player_a)}">${esc(m.player_a || '—')}<span>${m.match_wins_a}</span></div>
          <div class="br-side${vinto(m.player_b)}">${esc(m.player_b || 'BYE')}<span>${m.match_wins_b}</span></div>
        </div>`;
      }).join('');
      return `<div class="br-col"><h4>${esc(titolo)}</h4>${righe}</div>`;
    }).join('');
    el('bracket').innerHTML = `<div class="br-grid">${colonne}</div>`;
  }

  /* Nel taglio finale "Round 5" non dice niente: quello che serve sapere è a
     che punto del tabellone si è, e lo dicono i tavoli ancora in gioco. */
  function roundName(round) {
    const fase = round.phase || 'swiss';
    if (fase === 'swiss') return tr('Round {n}', { n: round.number });
    const partite = (round.pairings || []).filter((p) => p.player_b).length;
    return { 1: tr('Finale'), 2: tr('Semifinali'), 4: tr('Quarti'), 8: tr('Ottavi') }[partite]
      || tr('Top {n}', { n: partite * 2 });
  }

  function renderRow(round, p) {
    const isBye = !p.player_b;
    const finalScore = p.result && p.result !== '' ? `${p.match_wins_a}-${p.match_wins_b}` : '';

    let control;
    if (isBye) {
      control = '<span class="badge ok">BYE · 2 – 0</span>';
    } else if (p.report_status === 'pending' && !finalScore) {
      // Proposto da un judge: in classifica ci va quando qualcun altro conferma.
      control = `<span class="badge warn">${esc(tr('Proposto'))} ${esc((p.report_score || '').replace('-', ' – '))}</span>
        ${canConfirm()
          ? `<button class="mini-button primary" data-action="confirm-report" data-pid="${p.id}" type="button">${esc(tr('Conferma'))}</button>`
          : `<span class="muted" style="font-size:.78rem">${esc(tr('in attesa del tabellone'))}</span>`}`;
    } else if (finalScore && !editing.has(String(p.id))) {
      control = `<span class="badge ok">${finalScore.replace('-', ' – ')} 🔒</span>
        <button class="mini-button" data-action="edit" data-pid="${p.id}" type="button">${esc(tr('Modifica'))}</button>`;
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

    // Lo stato dedotto batte quello manuale: se il risultato c'e, il tavolo e
    // chiuso qualunque cosa dica table_status.
    const stato = finalScore ? 'done'
      : p.report_status === 'conflict' ? 'disputed'
      : (p.table_status || 'playing');
    const statoLabel = {
      playing: '', called: 'chiamato', attention: 'serve judge',
      disputed: 'contestato', done: '',
    }[stato];
    let judgeTools = '';
    if ((judgeView || String(p.id) === String(penaltiesFor)) && !isBye) {
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
        ${finalScore ? '' : `<button class="mini-button" data-action="cycle-status" data-pid="${p.id}"
          data-next="${stato === 'playing' ? 'called' : stato === 'called' ? 'attention' : 'playing'}"
          type="button">${esc(tr('Stato: {stato}', { stato: statoLabel || tr('in gioco') }))}</button>`}
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

    const mine = String(p.assigned_judge_id || '') === String(myUserId);

    return `<div class="ctl-row status-${esc(stato)}">
      <span class="table-num">T${p.table_number}</span>
      <span class="names"><strong>${esc(p.player_a)}</strong> vs <strong>${esc(p.player_b || 'BYE')}</strong></span>
      ${tableClock}
      ${statoLabel ? `<span class="tbl-state">${esc(statoLabel)}</span>` : ''}
      ${p.assigned_judge_name
        ? `<button class="mini-button judge-chip${mine ? ' mine' : ''}" data-action="unassign" data-pid="${p.id}" type="button" title="Libera il tavolo">👤 ${esc(p.assigned_judge_name)}</button>`
        : (finalScore ? '' : `<button class="mini-button" data-action="assign" data-pid="${p.id}" type="button">Prendo io</button>`)}
      ${canJudge() && !isBye ? `<button class="mini-button${String(p.id) === String(penaltiesFor) ? ' active' : ''}"
        data-action="toggle-penalties" data-pid="${p.id}" type="button"
        title="${esc(tr('Warning, game loss, deck check e stato del tavolo'))}">⚑</button>` : ''}
      ${finalScore || isBye || !canEditPairing(round) ? '' : `<button class="mini-button" data-action="repair" data-pid="${p.id}" type="button" title="${esc(tr('Cambia gli avversari di questo tavolo'))}">✎</button>`}
      ${judgeTools}
      <span>${control}</span>
    </div>`;
  }

  /* Un referto per volta, e in fretta.

     Prima ogni risultato rileggeva sei endpoint e ridisegnava tutto: con
     quaranta tavoli da riportare sembrava che la pagina si ricaricasse a ogni
     clic. La rotta restituisce già il turno aggiornato, quindi si sostituisce
     quello e si ridisegna; classifica e tabellone si aggiornano dopo, senza
     far aspettare chi sta inserendo. */
  async function submitResult(pairingId, score, isCorrection) {
    if (!score) return;
    editing.delete(String(pairingId));
    const path = isCorrection ? `/pairings/${pairingId}/correct` : `/pairings/${pairingId}/result`;
    try {
      const aggiornato = await apiFetch(`/tournaments/${tid}${path}`, {
        method: 'PATCH', body: JSON.stringify(scoreToBody(score)),
      });
      const i = rounds.findIndex((r) => String(r.id) === String(aggiornato.id));
      if (i >= 0) rounds[i] = aggiornato;
      render();
      toast(isCorrection ? tr('Risultato corretto.') : tr('Risultato registrato.'));
      refreshDerived();
    } catch (e) {
      toast('Errore: ' + e.message);
      await refresh();   // non si sa più com'è messo il tavolo: si rilegge
    }
  }

  /* Classifica e tabellone cambiano a ogni risultato, ma non servono subito:
     si aggiornano per conto loro e la schermata si ridisegna quando arrivano. */
  let derivedPending = null;
  function refreshDerived() {
    clearTimeout(derivedPending);
    derivedPending = setTimeout(async () => {
      const [s, b] = await Promise.all([
        apiFetch(`/tournaments/${tid}/standings`).catch(() => null),
        apiFetch(`/tournaments/${tid}/bracket`).catch(() => null),
      ]);
      if (s) standings = s;
      if (b) bracket = b;
      render();
    }, 600);
  }

  function render() {
    const round = activeRound();
    const tabs = el('tabs');
    tabs.innerHTML = rounds.map((r) =>
      `<button class="ctl-tab${String(r.id) === String(activeRoundId) ? ' active' : ''}" data-round="${r.id}" type="button">${esc(roundName(r))}</button>`
    ).join('') + `<button class="ctl-tab judge${judgeView ? ' active' : ''}" data-el="judgeToggle" type="button">⚖ Judge</button>`;

    tabs.querySelectorAll('[data-round]').forEach((b) =>
      b.addEventListener('click', () => { activeRoundId = b.dataset.round; render(); }));
    el('judgeToggle').addEventListener('click', () => { judgeView = !judgeView; render(); });

    const box = el('standings');
    if (box) {
      box.innerHTML = standings.length
        ? `<div class="table-scroll"><table class="bo">
             <thead><tr><th>#</th><th>${esc(tr('Giocatore'))}</th><th>${esc(tr('Punti'))}</th><th>${esc(tr('Record'))}</th></tr></thead>
             <tbody>${standings.map((s) => `<tr>
               <td>${s.position ?? '—'}</td><td>${esc(s.name || '')}${s.dropped ? ` <span class="muted">${esc(tr('ritirato'))}</span>` : ''}</td>
               <td>${s.points ?? 0}</td><td>${esc(s.record || '')}</td></tr>`).join('')}</tbody>
           </table></div>`
        : `<p class="empty">${esc(tr('Ancora nessun risultato.'))}</p>`;
    }

    renderBracket();

    const tables = el('tables');
    if (!round) {
      tables.innerHTML = '<p class="empty">Nessun round. Avvia il torneo e genera il primo round.</p>';
      el('roundLabel').textContent = '';
      return;
    }
    el('roundLabel').textContent = roundName(round);

    const pairings = round.pairings
      .filter((p) => !judgeView || (p.player_b && !p.result))
      .sort((a, b) => a.table_number - b.table_number);


    tables.innerHTML = (pairings.length
      ? pairings.map((p) => (String(p.id) === String(repairing) ? pairingEditor(round, p) : renderRow(round, p))).join('')
      : '<p class="empty" style="margin:0">Tutti i tavoli hanno un risultato. ✓</p>');

    tables.querySelectorAll('[data-action="toggle-penalties"]').forEach((btn) =>
      btn.addEventListener('click', () => {
        penaltiesFor = String(penaltiesFor) === btn.dataset.pid ? null : btn.dataset.pid;
        render();
      }));
    tables.querySelectorAll('[data-action="confirm-report"]').forEach((btn) =>
      btn.addEventListener('click', () => call(
        () => apiFetch(`/tournaments/${tid}/pairings/${btn.dataset.pid}/confirm-report`, { method: 'POST' }),
        tr('Referto confermato.'))));
    tables.querySelectorAll('[data-action="repair"]').forEach((btn) =>
      btn.addEventListener('click', () => { repairing = btn.dataset.pid; render(); }));
    tables.querySelector('[data-action="repair-cancel"]')?.addEventListener('click', () => {
      repairing = null;
      render();
    });
    tables.querySelector('[data-action="repair-save"]')?.addEventListener('click', (e) => {
      const riga = e.target.closest('.repair-row');
      const valore = (nome) => riga.querySelector(`[data-repair="${nome}"]`).value;
      repairing = null;
      call(() => apiFetch(`/tournaments/${tid}/pairings/${e.target.dataset.pid}`, {
        method: 'PATCH',
        body: JSON.stringify({
          table_number: Number(valore('table')) || 1,
          player_a_registration_id: Number(valore('a')),
          player_b_registration_id: Number(valore('b')) || null,
        }),
      }), tr('Abbinamento aggiornato.'));
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
          <button class="secondary" value="cancel" formnovalidate>${esc(tr('Annulla'))}</button>
          <button class="primary" data-el="dcSave" type="button">${esc(tr('Registra'))}</button>
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
