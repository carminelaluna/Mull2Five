import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { busy } from './form-state.js';
import { renderDeck } from './deck-view.js';
import { esc } from './escape.js';
import { gameInfo, gameLabel, scoresFor } from './games.js';
import { t as tr } from './i18n.js';
import { actingAs, actingBanner, bindActingBanner, setActing } from './acting.js';
import { toast } from './catalog.js';
import { apiRequest, clearToken, logout, requireSession } from './session.js';


/* ── Auth guard ──────────────────────────────────────── */
const session = requireSession();

/* ── Helpers ─────────────────────────────────────────── */
// Chi gestisce il profilo di un figlio vede e fa le cose per lui (X-Act-As).
const apiFetch = (path, opts = {}) => apiRequest(path, { acting: true, requireLogin: true, ...opts });

function fmtDate(d) { if (!d) return '—'; const [y,m,dd]=d.split('-'); return `${dd}/${m}/${y}`; }
function fmtMoney(v) { return (+v||0).toLocaleString('it-IT',{style:'currency',currency:'EUR'}); }
let _activeFormat = '';   // segmento della lista in modifica
let _activeTournament = { format: '', name: '' };   // per salvare la lista anche tra le mie
let _savedDecks = [];
let _activeTournamentId = null;
let _activePairingId    = null;
let _activeIsA          = true;   // sono il giocatore A del pairing?

/* ── Auth nav ────────────────────────────────────────── */
function updateAuthNav() {
  const el = document.querySelector('#publicAuth'); if (!el) return;
  el.innerHTML = `<a class="secondary-link" href="player.html?p=${encodeURIComponent(session.pid || '')}">Profilo</a>
    <a class="secondary-link" href="decks.html">${esc(tr('Le mie liste'))}</a>
    <span style="color:var(--muted);font-size:.85rem">${esc(session.email)}</span>
    <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
  el.querySelector('#logoutBtn').addEventListener('click', () => logout('index.html'));
}

/* ── Load registrations ──────────────────────────────── */
async function loadRegistrations() {
  const container = document.querySelector('#registrationsList');
  try {
    /* Iscrizioni e tornei in una richiesta sola (prima ne partiva una per torneo). */
    const rows = await apiFetch('/tournaments/me/registrations');
    const myRegs = (rows || []).map(({ tournament, registration }) => ({ tournament, reg: registration }));

    if (!myRegs.length) {
      container.innerHTML = `<p class="empty">Non sei iscritto a nessun torneo.
        <a href="index.html" style="color:var(--teal)">Sfoglia i tornei →</a></p>`;
      return;
    }

    /* Per ogni iscrizione carica pairings e standings */
    const cards = await Promise.all(myRegs.map(({ tournament: t, reg }) =>
      buildCard(t, reg)
    ));
    container.innerHTML = cards.join('');

    /* Event handlers */
    container.querySelectorAll('[data-action="upload-deck"]').forEach(btn => {
      btn.addEventListener('click', () => openDeckDialog(btn.dataset.tournamentId, btn.dataset.regId, btn.dataset.edit === '1', btn.dataset.format || '',
        { format: btn.dataset.tformat || '', name: btn.dataset.tname || '' }));
    });
    container.querySelectorAll('[data-action="view-deck"]').forEach(btn => {
      btn.addEventListener('click', () => showMyDeck(btn.dataset.tournamentId, btn.dataset.name, btn.dataset.format || ''));
    });
    container.querySelectorAll('[data-action="submit-result"]').forEach(btn => {
      btn.addEventListener('click', () => openResultDialog(
        btn.dataset.tournamentId, btn.dataset.pairingId, btn.dataset.opponent, btn.dataset.isA === '1',
        { bestOf: +btn.dataset.bestOf || 3, playoff: btn.dataset.playoff === '1', intentionalDraws: btn.dataset.ids === '1' },
      ));
    });
    container.querySelectorAll('[data-action="confirm-result"]').forEach(btn => {
      btn.addEventListener('click', () => confirmResult(btn.dataset.tournamentId, btn.dataset.pairingId));
    });
    container.querySelectorAll('[data-action="reject-result"]').forEach(btn => {
      btn.addEventListener('click', () => rejectResult(btn.dataset.tournamentId, btn.dataset.pairingId));
    });
    container.querySelectorAll('[data-action="edit-publisher-id"]').forEach((btn) => btn.addEventListener('click', async () => {
      const value = prompt(btn.dataset.label, btn.dataset.value);
      if (value === null || value.trim() === btn.dataset.value) return;
      try {
        await apiFetch(`/tournaments/${btn.dataset.tournamentId}/my-publisher-id`, {
          method: 'PUT', body: JSON.stringify({ publisher_id: value.trim() }),
        });
        toast(tr('Aggiornato ✓'));
        loadRegistrations();
      } catch (err) { toast(err.message); }
    }));
    container.querySelectorAll('[data-action="edit-handle"]').forEach((btn) => btn.addEventListener('click', async () => {
      const hint = btn.dataset.hint ? ` (${tr('es. {x}', { x: btn.dataset.hint })})` : '';
      const handle = prompt(`${btn.dataset.label}${hint}`, btn.dataset.handle);
      if (handle === null || handle.trim() === btn.dataset.handle) return;
      try {
        await apiFetch(`/tournaments/${btn.dataset.tournamentId}/my-handle`, {
          method: 'PUT', body: JSON.stringify({ game_handle: handle.trim() }),
        });
        toast(tr('Aggiornato ✓'));
        loadRegistrations();
      } catch (err) { toast(err.message); }
    }));
    container.querySelectorAll('[data-copy]').forEach((btn) => btn.addEventListener('click', () => {
      navigator.clipboard.writeText(btn.dataset.copy).then(() => toast(tr('Copiato: {x}', { x: btn.dataset.copy })));
    }));
    container.querySelectorAll('[data-action="self-drop"]').forEach(btn => {
      btn.addEventListener('click', () => selfDrop(btn.dataset.tournamentId, btn.dataset.name));
    });
    container.querySelectorAll('[data-action="self-cancel"]').forEach(btn => {
      btn.addEventListener('click', () => selfCancel(btn.dataset.tournamentId, btn.dataset.name));
    });
    container.querySelectorAll('[data-action="pay"]').forEach(btn => {
      btn.addEventListener('click', () => payNow(btn, btn.dataset.tournamentId, btn.dataset.provider));
    });

    /* Avvia il watcher "nuovo round" sui tornei in corso */
    startRoundWatcher(myRegs.filter(({ tournament: t }) => t.status === 'running')
                            .map(({ tournament: t }) => t.id));

  } catch (err) {
    container.innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`;
  }
}

async function buildCard(t, reg) {
  /* Torneo online: dove si gioca e con che nome ti trova l'avversario. */
  const platform = t.is_online
    ? ((await gameInfo(t.game))?.online_platforms || []).find((p) => p.code === t.online_platform) : null;
  const onlineRow = t.is_online ? `<div class="reg-row"><span class="reg-label">${esc(tr('Online'))}</span>
      <span class="reg-row-body">${esc(platform?.name || '')} · <span class="handle">${esc(reg.game_handle || '—')}</span>
        ${t.status !== 'completed' ? `<button class="mini-button" data-action="edit-handle" data-tournament-id="${t.id}"
          data-label="${esc(platform?.handle_label || '')}" data-hint="${esc(platform?.handle_hint || '')}"
          data-handle="${esc(reg.game_handle || '')}" type="button">${esc(tr('Cambia'))}</button>` : ''}
        ${reg.online_link ? `<a class="secondary-link" href="${esc(reg.online_link)}" target="_blank" rel="noopener noreferrer">${esc(tr('Apri la stanza ↗'))}</a>` : ''}</span></div>` : '';

  /* Eventi ufficiali: l'ID presso l'editore, che si può aggiungere anche dopo. */
  const official = ['rcq', 'store_championship', 'premier'].includes(t.event_type) || t.invites > 0;
  const idLabel = (await gameInfo(t.game))?.publisher_id_label || 'Wizards Account';
  const publisherRow = official ? `<div class="reg-row"><span class="reg-label">${esc(idLabel)}</span>
      <span class="reg-row-body">${reg.wizards_account
        ? `<span class="handle">${esc(reg.wizards_account)}</span>`
        : `<span class="badge warn">${esc(tr('manca: serve per risultati e inviti'))}</span>`}
        <button class="mini-button" data-action="edit-publisher-id" data-tournament-id="${t.id}"
          data-label="${esc(idLabel)}" data-value="${esc(reg.wizards_account || '')}" type="button">${esc(reg.wizards_account ? tr('Cambia') : tr('Aggiungi'))}</button></span></div>` : '';

  /* Stato pagamento */
  const isPaid = ['paid', 'confirmed'].includes(reg.payment_status);
  const payBadge = {
    paid:      '<span class="badge ok">Pagato ✓</span>',
    pending:   '<span class="badge warn">In attesa di pagamento</span>',
    confirmed: '<span class="badge ok">Confermato ✓</span>',
  }[reg.payment_status] || '<span class="badge warn">Non pagato</span>';

  /* Pulsanti di pagamento: mostrati solo se non ha ancora pagato.
     Online (Stripe/PayPal) solo se l'organizzatore li ha abilitati per il torneo. */
  let payActions = '';
  if (!isPaid) {
    const buttons = [];
    if (t.pay_stripe) buttons.push(
      `<button class="primary" data-action="pay" data-tournament-id="${t.id}" data-provider="stripe" type="button">Paga con Stripe</button>`);
    if (t.pay_paypal) buttons.push(
      `<button class="primary" data-action="pay" data-tournament-id="${t.id}" data-provider="paypal" type="button">Paga con PayPal</button>`);
    if (t.pay_at_event) buttons.push(
      '<span class="badge">Puoi pagare anche all\'evento</span>');
    if (!t.pay_stripe && !t.pay_paypal && !t.pay_at_event) buttons.push(
      '<span class="badge warn">Nessun metodo di pagamento configurato — contatta l\'organizzatore</span>');
    payActions = buttons.join('');
  }

  /* Decklist — decklist_status: missing | submitted | valid | invalid.
     Caricamento consentito solo prima dell'inizio (le liste si bloccano a torneo
     avviato e, di default, 30 min prima dell'orario di inizio). */
  const hasDeck = reg.decklist_status && reg.decklist_status !== 'missing';
  // decklist_locked arriva dal backend: tiene conto della deadline esplicita, del
  // default (30' prima dell'inizio) e dello stato del torneo.
  const deckOpen = !t.decklist_locked;
  // Un torneo a formato unico ha un solo segmento (""). In un evento misto ne
  // ha uno per porzione, e ognuna vuole la sua lista.
  const segmenti = (t.decklist_formats?.length ? t.decklist_formats : ['']);
  const misto = segmenti.length > 1;
  const inviate = new Set(reg.decklist_formats || (hasDeck ? [''] : []));

  const rigaSegmento = (fmt) => {
    const etichetta = fmt || (misto ? 'Costruito' : '');
    const ok = inviate.has(fmt);
    const parti = [];
    if (etichetta) parti.push(`<strong style="font-size:.82rem">${esc(etichetta)}</strong>`);
    if (ok) {
      parti.push('<span class="badge ok">Inviata ✓</span>');
      parti.push(`<button class="mini-button" data-action="view-deck" data-tournament-id="${t.id}" data-name="${esc(t.name)}" data-format="${esc(fmt)}" type="button">Vedi</button>`);
    }
    if (deckOpen) {
      parti.push(`<button class="mini-button" data-action="upload-deck" data-tournament-id="${t.id}" data-reg-id="${reg.id}" data-format="${esc(fmt)}" data-tformat="${esc(t.format)}" data-tname="${esc(t.name)}" data-edit="${ok ? '1' : ''}" type="button">${ok ? 'Modifica' : 'Carica'}</button>`);
    } else if (!ok) {
      parti.push('<span class="badge warn">Liste chiuse</span>');
    }
    return `<span class="deck-segment">${parti.join(' ')}</span>`;
  };

  const deckParts = segmenti.map(rigaSegmento);
  if (deckOpen && t.decklist_locks_at) {
    deckParts.push(`<span class="badge">Modificabile fino al ${fmtDeadline(t.decklist_locks_at)}</span>`);
  } else if (!deckOpen && inviate.size) {
    deckParts.push('<span class="badge warn">Liste chiuse: non più modificabili</span>');
  }
  const deckBadge = deckParts.join(' ');

  /* Pairings round corrente */
  let pairingsHtml = '';
  try {
    const rounds = await apiFetch(`/tournaments/${t.id}/my-pairings`);
    const lastRound = Array.isArray(rounds) ? rounds.at(-1) : null;
    if (lastRound) pairingsHtml = renderMyPairing(t, lastRound, reg);
  } catch { /* pezzo in piu: senza, la pagina resta quella che e */ }

  /* Standings */
  let standingsHtml = '';
  if (t.status === 'running' || t.status === 'completed') {
    try {
      const standings = await apiFetch(`/tournaments/${t.id}/standings`);
      const me = standings?.find(s => s.registration_id === reg.id);
      if (me) {
        standingsHtml = `<div class="my-standing">
          Classifica: <strong>#${me.position ?? '—'}</strong>
          · ${me.points ?? 0} punti
          · ${esc(me.record ?? '')}</div>`;
      }
    } catch { /* pezzo in piu: senza, la pagina resta quella che e */ }
  }

  const statusLabel = { published:'Aperto', running:'In corso', completed:'Concluso', cancelled:'Annullato' }[t.status] || t.status;
  const statusCls   = { running:'ok', completed:'', published:'warn' }[t.status] || '';

  /* Waitlist e drop */
  const waitlistBadge = reg.waitlisted
    ? '<span class="badge warn">In lista d\'attesa</span>' : '';
  const droppedBadge = reg.dropped
    ? '<span class="badge">Ritirato</span>' : '';
  const canDrop = !reg.dropped && (t.status === 'published' || t.status === 'running');
  const dropBtn = canDrop
    ? `<button class="mini-button danger" data-action="self-drop" data-tournament-id="${t.id}" data-name="${esc(t.name)}" type="button">Ritirati</button>`
    : '';
  // #43 Annulla iscrizione self-service: solo prima dell'inizio (torneo pubblicato).
  const canCancel = !reg.dropped && t.status === 'published';
  const cancelBtn = canCancel
    ? `<button class="mini-button danger" data-action="self-cancel" data-tournament-id="${t.id}" data-name="${esc(t.name)}" type="button">Annulla iscrizione</button>`
    : '';

  return `<article class="panel reg-card">
    <div class="reg-card-head">
      <div>
        <strong>${esc(t.name)}</strong>
        ${t.organizer_name ? `<small>${esc(tr('Organizzato da {nome}', { nome: t.organizer_name }))}</small>` : ''}
        ${t.is_online ? `<small>${esc(tr('Online · {dove}', { dove: platform?.name || '' }))}</small>`
          : t.venue ? `<small>${esc(t.venue)}</small>` : ''}
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="game-badge game-${esc(t.game || 'mtg')}">${esc(gameLabel(t.game))}</span>
        <span class="badge">${esc(t.format)}</span>
        <span class="badge ${statusCls}">${statusLabel}</span>
        ${waitlistBadge} ${droppedBadge}
      </div>
    </div>
    <!-- Una riga per argomento, con l'etichetta a sinistra: ogni cosa ha il suo posto. -->
    <div class="reg-card-rows">
      <div class="reg-row"><span class="reg-label">${esc(tr('Quando'))}</span>
        <span class="reg-row-body">${fmtDate(t.starts_on?.substring(0,10))}${t.start_time ? ' · ' + esc(t.start_time) : ''}
          · ${esc(tr('Quota'))} ${fmtMoney((t.entry_fee_cents || 0) / 100)}</span></div>
      <div class="reg-row"><span class="reg-label">${esc(tr('Pagamento'))}</span>
        <span class="reg-row-body">${payBadge}${payActions}</span></div>
      <div class="reg-row"><span class="reg-label">${esc(tr('Lista'))}</span>
        <span class="reg-row-body">${deckBadge}</span></div>
      ${onlineRow}
      ${publisherRow}
      ${reg.pod || reg.fixed_table ? `<div class="reg-row"><span class="reg-label">${esc(tr('Posto'))}</span>
        <span class="reg-row-body">${reg.pod ? `<span class="badge">${esc(tr('Pod {p} · posto {s}', { p: reg.pod, s: reg.pod_seat }))}</span>` : ''}
          ${reg.fixed_table ? `<span class="badge ok">${esc(tr('Tavolo fisso {n}', { n: reg.fixed_table }))}</span>` : ''}</span></div>` : ''}
      ${reg.team_name ? `<div class="reg-row"><span class="reg-label">${esc(tr('Squadra'))}</span>
        <span class="reg-row-body">${esc(reg.team_name)} · ${esc(tr('posto {x}', { x: 'ABC'[reg.team_seat - 1] || reg.team_seat }))}</span></div>` : ''}
    </div>
    <div class="reg-card-actions">
      ${t.status === 'completed'
        ? `<a class="secondary-link" href="history.html?t=${t.id}">📊 Risultati e liste</a>`
        : `<a class="secondary-link" href="/api/tournaments/${t.id}/ical">📅 Aggiungi al calendario</a>`}
      <span class="reg-actions-right">${dropBtn}${cancelBtn}</span>
    </div>
    ${standingsHtml}
    ${pairingsHtml}
  </article>`;
}

function renderMyPairing(t, round, reg) {
  const pairings = round.pairings || [];
  // Match robusto per ID registrazione (i nomi possono coincidere/cambiare).
  const mine = pairings.find(p =>
    p.player_a_registration_id === reg.id || p.player_b_registration_id === reg.id);
  if (!mine) return '';

  const isA      = mine.player_a_registration_id === reg.id;
  const myName   = isA ? mine.player_a : mine.player_b;
  const opponent = (isA ? mine.player_b : mine.player_a) || 'BYE';
  // Online l'avversario si cerca col suo nome in gioco: lo si copia e lo si incolla.
  const oppHandle = isA ? mine.player_b_handle : mine.player_a_handle;
  const handleChip = oppHandle ? ` <span class="handle">${esc(oppHandle)}</span>
    <button class="mini-button" data-copy="${esc(oppHandle)}" type="button">${esc(tr('Copia'))}</button>` : '';

  const reporter    = mine.report_reporter_registration_id;   // chi ha refertato
  const status      = mine.report_status;                     // '' | pending | confirmed | conflict
  const confirmed   = !!mine.result;                          // risultato applicato
  const iReported   = reporter === reg.id;
  const oppReported = reporter != null && reporter !== reg.id;
  // report_score è in formato A-B: orientalo dal mio punto di vista.
  const score   = mine.report_score || '';
  const myScore = isA ? score : invertResult(score);

  let resultCell;
  if (opponent === 'BYE') {
    resultCell = '<span class="badge ok">BYE</span>';
  } else if (confirmed) {
    resultCell = `<span class="badge ok">Risultato confermato${myScore ? ': ' + esc(myScore) : ''}</span>`;
  } else if (status === 'conflict') {
    resultCell = '<span class="badge warn">⚠️ Risultato in conflitto — chiama un Judge</span>';
  } else if (oppReported && status === 'pending') {
    // L'avversario ha refertato per primo: devo confermare o contestare.
    resultCell = `<div class="result-confirm" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        <span class="badge warn">L'avversario ha inserito: ${esc(myScore || score)}</span>
        <button class="primary" data-action="confirm-result" data-tournament-id="${t.id}" data-pairing-id="${mine.id}" type="button">Conferma</button>
        <button class="ghost" data-action="reject-result" data-tournament-id="${t.id}" data-pairing-id="${mine.id}" type="button" style="color:var(--danger,#ef6a5e)">Contesta / Chiama Judge</button>
      </div>`;
  } else if (iReported && status === 'pending') {
    resultCell = `<span class="badge warn">Risultato inviato${myScore ? ': ' + esc(myScore) : ''} — in attesa di conferma dell'avversario</span>`;
  } else {
    resultCell = `<button class="ghost" data-action="submit-result"
           data-tournament-id="${t.id}"
           data-pairing-id="${mine.id}"
           data-is-a="${isA ? '1' : ''}"
           data-opponent="${esc(opponent)}"
           data-best-of="${t.best_of || 3}"
           data-playoff="${round.phase && round.phase !== 'swiss' ? '1' : ''}"
           data-ids="${t.allow_intentional_draws === false ? '' : '1'}"
           type="button">Invia risultato</button>`;
  }

  return `<div class="my-pairing">
    <span class="eyebrow">Round ${round.number} — Tavolo ${mine.table_number || '—'}</span>
    <div class="pairing-row">
      <span class="table-num">vs</span>
      <span><strong>${esc(myName)}</strong> vs <strong>${esc(opponent)}</strong>${handleChip}</span>
      ${resultCell}
    </div>
  </div>`;
}

function invertResult(r) {
  const m = {'2-0':'0-2','0-2':'2-0','2-1':'1-2','1-2':'2-1','1-0':'0-1','0-1':'1-0','1-1':'1-1','0-0':'0-0'};
  return m[r] || r;
}

/* ── Decklist upload ─────────────────────────────────── */
function fmtDeadline(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

async function openDeckDialog(tournamentId, regId, isEdit = false, fmt = '', tournament = {}) {
  _activeFormat = fmt;
  _activeTournamentId = tournamentId;
  _activeTournament = { format: fmt || tournament.format || '', name: tournament.name || '' };
  document.querySelector('#deckSaveCopy').checked = false;
  fillSavedDecks();
  document.querySelector('#deckDialogTitle').textContent =
    `${isEdit ? 'Modifica lista' : 'Carica lista'}${fmt ? ' — ' + fmt : ''}`;
  document.querySelector('#deckText').value              = '';
  document.querySelector('#deckArchetype').value         = '';
  document.querySelector('#deckError').textContent       = '';
  const file = document.querySelector('#deckFile');
  if (file) file.value = '';
  document.querySelector('#deckDialog').showModal();
  if (!isEdit) return;
  // In modifica si riparte dalla lista gia inviata, non da un foglio bianco.
  try {
    const deck = await apiFetch(`/tournaments/${tournamentId}/decklist?format=${encodeURIComponent(fmt)}`);
    document.querySelector('#deckText').value = deck?.raw_text || '';
  } catch {
    document.querySelector('#deckError').textContent =
      'Non sono riuscito a rileggere la lista attuale: reincollala per intero.';
  }
}

/** Le liste salvate in "Le mie liste": una si sceglie e riempie il modulo. */
async function fillSavedDecks() {
  const select = document.querySelector('#deckSaved');
  select.innerHTML = `<option value="">${esc(tr('Caricamento…'))}</option>`;
  try {
    _savedDecks = await apiFetch('/decks');
  } catch {
    _savedDecks = [];
  }
  // Prima quelle del formato del torneo: sono quelle che servono.
  const sameFormat = (d) => d.format.toLowerCase() === _activeTournament.format.toLowerCase();
  const ordered = [..._savedDecks.filter(sameFormat), ..._savedDecks.filter((d) => !sameFormat(d))];
  select.innerHTML = ordered.length
    ? `<option value="">${esc(tr('— Scegli una lista —'))}</option>` + ordered.map((d) =>
      `<option value="${d.id}">${esc(d.name)} · ${esc(d.format || '—')} (${d.main_count}/${d.side_count})</option>`).join('')
    : `<option value="">${esc(tr('Nessuna lista salvata'))}</option>`;
  select.disabled = !ordered.length;
}

async function showMyDeck(tournamentId, tournamentName, fmt = '') {
  const dialog = document.querySelector('#deckViewDialog');
  const body   = document.querySelector('#deckViewBody');
  document.querySelector('#deckViewTitle').textContent =
    `${tournamentName || 'La mia lista'}${fmt ? ' — ' + fmt : ''}`;
  body.innerHTML = '<p class="empty">Caricamento lista…</p>';
  dialog.showModal();
  try {
    const deck = await apiFetch(`/tournaments/${tournamentId}/decklist?format=${encodeURIComponent(fmt)}`);
    await renderDeck(body, deck?.raw_text || '');
  } catch (err) {
    body.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
  }
}

async function submitDeck() {
  const raw       = document.querySelector('#deckText').value.trim();
  const archetype = document.querySelector('#deckArchetype').value.trim();
  const errEl     = document.querySelector('#deckError');
  if (!raw) { errEl.textContent = 'Incolla la tua lista prima di inviare.'; return; }
  const btn = document.querySelector('#submitDeck');
  btn.disabled = true; btn.textContent = 'Invio in corso…';
  try {
    await apiFetch(`/tournaments/${_activeTournamentId}/decklist`, {
      method: 'POST',
      body: JSON.stringify({ raw_text: raw, archetype, format: _activeFormat }),
    });
    if (document.querySelector('#deckSaveCopy').checked) {
      // Anche tra le mie liste: la ritrova per il prossimo torneo.
      await apiFetch('/decks', {
        method: 'POST',
        body: JSON.stringify({
          name: archetype || _activeTournament.name || tr('Lista'), format: _activeTournament.format,
          archetype, raw_text: raw,
        }),
      }).catch((err) => toast(tr('Lista inviata, ma non salvata tra le tue: {err}', { err: err.message })));
    }
    document.querySelector('#deckDialog').close();
    toast('Lista salvata ✓');
    await loadRegistrations();
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    btn.disabled = false; btn.textContent = 'Invia lista';
  }
}

/* ── Risultato ───────────────────────────────────────── */
/** Un punteggio visto dal giocatore che lo inserisce: "2 – 1 (ho vinto)". */
function myResultLabel(score) {
  const [mine, theirs] = score.split('-').map(Number);
  const punteggio = score.replace('-', ' – ');
  if (mine > theirs) return tr('{punteggio} (ho vinto)', { punteggio });
  if (mine < theirs) return tr('{punteggio} (ho perso)', { punteggio });
  return tr('{punteggio} (patta)', { punteggio });
}

function openResultDialog(tournamentId, pairingId, opponent, isA, format = {}) {
  _activeTournamentId = tournamentId;
  _activePairingId    = pairingId;
  _activeIsA          = !!isA;
  document.querySelector('#resultDescription').textContent = `vs ${opponent}`;
  // Solo i punteggi possibili nel formato del match: al meglio di 1 niente 2-1.
  const select = document.querySelector('#resultSelect');
  select.innerHTML = `<option value="">${esc(tr('— Seleziona'))}</option>`
    + scoresFor(format.bestOf, format).map((s) => `<option value="${s}">${esc(myResultLabel(s))}</option>`).join('');
  select.value = '';
  document.querySelector('#resultError').textContent       = '';
  document.querySelector('#resultDialog').showModal();
}

async function submitResult() {
  const result = document.querySelector('#resultSelect').value;   // "X-Y" dal mio punto di vista
  const errEl  = document.querySelector('#resultError');
  if (!result) { errEl.textContent = 'Seleziona un risultato.'; return; }
  const [myWins, oppWins] = result.split('-').map(Number);
  // Il backend vuole i game vinti dal punto di vista di A e B del pairing.
  const body = _activeIsA
    ? { match_wins_a: myWins, match_wins_b: oppWins, draws: 0 }
    : { match_wins_a: oppWins, match_wins_b: myWins, draws: 0 };
  const btn = document.querySelector('#submitResult');
  btn.disabled = true; btn.textContent = 'Invio…';
  try {
    await apiFetch(`/tournaments/${_activeTournamentId}/pairings/${_activePairingId}/player-result`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
    document.querySelector('#resultDialog').close();
    toast('Risultato inviato. Non potrà essere modificato.');
    await loadRegistrations();
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    btn.disabled = false; btn.textContent = 'Invia risultato';
  }
}

/* Conferma il risultato inserito dall'avversario. */
async function confirmResult(tournamentId, pairingId) {
  try {
    await apiFetch(`/tournaments/${tournamentId}/pairings/${pairingId}/player-result/confirm`, { method: 'POST' });
    toast('Risultato confermato ✓');
    await loadRegistrations();
  } catch (err) {
    toast('Errore: ' + err.message);
  }
}

/* Contesta il risultato dell'avversario → conflitto, da risolvere col Judge. */
async function rejectResult(tournamentId, pairingId) {
  const note = window.prompt('Contesti il risultato inserito dall\'avversario.\nDescrivi il problema (un Judge interverrà):', '');
  if (note === null) return;   // annullato
  try {
    await apiFetch(`/tournaments/${tournamentId}/pairings/${pairingId}/player-result/reject`, {
      method: 'POST',
      body: JSON.stringify({ note: note.trim() }),
    });
    toast('Risultato contestato. Chiama un Judge per la risoluzione.');
    await loadRegistrations();
  } catch (err) {
    toast('Errore: ' + err.message);
  }
}

/* ── Pagamento ───────────────────────────────────────── */
async function payNow(btn, tournamentId, provider) {
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = 'Reindirizzamento…';
  try {
    const payment = await apiFetch(`/tournaments/${tournamentId}/checkout`, {
      method: 'POST',
      body: JSON.stringify({ provider }),
    });
    if (payment?.checkout_url) {
      location.href = payment.checkout_url;   // sandbox o vero PSP
    } else {
      toast('Checkout non disponibile. Riprova.');
      btn.disabled = false; btn.textContent = original;
    }
  } catch (err) {
    toast('Errore: ' + err.message);
    btn.disabled = false; btn.textContent = original;
  }
}

/* ── Drop self-service ───────────────────────────────── */
async function selfDrop(tournamentId, name) {
  if (!window.confirm(`Ritirarti da "${name}"? Non parteciperai ai prossimi round. L'operazione non è reversibile.`)) return;
  try {
    await apiFetch(`/tournaments/${tournamentId}/my-registration/drop`, { method: 'POST' });
    toast('Ritiro registrato. Buona giornata!');
    await loadRegistrations();
  } catch (err) {
    toast('Errore: ' + err.message);
  }
}

/* ── #43 Annulla iscrizione self-service (pre-torneo) ──── */
async function selfCancel(tournamentId, name) {
  if (!window.confirm(`Annullare l'iscrizione a "${name}"?\nSe avevi pagato e mancano più di 24h all'inizio, riceverai il rimborso automaticamente.`)) return;
  try {
    const res = await apiFetch(`/tournaments/${tournamentId}/my-registration/cancel`, { method: 'POST' });
    toast(res?.refunded ? 'Iscrizione annullata e rimborso avviato.' : 'Iscrizione annullata.');
    await loadRegistrations();
  } catch (err) {
    toast('Errore: ' + err.message);
  }
}

/* ── Watcher "pairing pronti" ────────────────────────────
   Polla i tornei in corso ogni 30s: quando appare un nuovo round
   suona un beep e mostra una notifica di sistema (se autorizzata). */
const _lastRoundSeen = {};   // tournamentId → ultimo numero round visto

function startRoundWatcher(tournamentIds) {
  if (!tournamentIds.length || startRoundWatcher._started) return;
  startRoundWatcher._started = true;

  /* Chiedi il permesso notifiche al primo gesto utente (policy browser) */
  if ('Notification' in window && Notification.permission === 'default') {
    document.addEventListener('click', () => Notification.requestPermission(), { once: true });
  }

  setInterval(async () => {
    for (const tid of tournamentIds) {
      try {
        const rounds = await apiFetch(`/tournaments/${tid}/my-pairings`);
        const last = Array.isArray(rounds) ? rounds.at(-1) : null;
        if (!last) continue;
        const prev = _lastRoundSeen[tid];
        _lastRoundSeen[tid] = last.number;
        if (prev !== undefined && last.number > prev) {
          notifyNewRound(last);
          await loadRegistrations();   // aggiorna le card con il nuovo pairing
        }
      } catch { /* pezzo in piu: senza, la pagina resta quella che e */ }
    }
  }, 30_000);
}

function notifyNewRound(round) {
  const mine = (round.pairings || [])[0];
  const table = mine?.table_number ? ` — Tavolo ${mine.table_number}` : '';
  const body  = `Round ${round.number}${table}. Vai al tuo posto!`;
  playBeep();
  if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('Pairing pronti!', { body, icon: '/icons/icon.svg' });
  }
  toast('🔔 ' + body);
}

function playBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator(), gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.frequency.value = 880; gain.gain.value = 0.15;
    osc.start(); osc.stop(ctx.currentTime + 0.4);
  } catch { /* pezzo in piu: senza, la pagina resta quella che e */ }
}

/* ── Init ────────────────────────────────────────────── */
/* I diritti sui dati (GDPR): scaricarli ed eliminare l'account, qui dove si
   gestisce il resto. L'eliminazione anonimizza: le classifiche restano giuste. */
function setupAccount() {
  const exportBtn = document.querySelector('#exportData');
  exportBtn?.addEventListener('click', async () => {
    busy(exportBtn, true);
    try {
      const data = await apiFetch('/auth/me/export');
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const link = Object.assign(document.createElement('a'), { href: url, download: 'mull2five-i-miei-dati.json' });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      toast(err.message);
    } finally {
      busy(exportBtn, false);
    }
  });
  const allBtn = document.querySelector('#logoutAll');
  allBtn?.addEventListener('click', async () => {
    busy(allBtn, true);
    try {
      await apiFetch('/auth/logout-all', { method: 'POST' });
      toast(tr('Sei uscito da tutti i dispositivi.'));
      setTimeout(() => logout('login.html'), 1200);
    } catch (err) {
      toast(err.message);
      busy(allBtn, false);
    }
  });
  document.querySelector('#deleteAccount')?.addEventListener('click', async () => {
    if (!confirm(tr("Eliminare l'account? Email, nome e ID vengono cancellati e non si può tornare indietro."))) return;
    try {
      await apiFetch('/auth/me', { method: 'DELETE' });
      clearToken();
      location.replace('index.html');
    } catch (err) { toast(err.message); }
  });
}

onReady(() => {
  updateAuthNav();
  showActing();
  setupAccount();
  // Di ritorno da Stripe o PayPal senza aver pagato: l'iscrizione resta, si riprova da qui.
  if (new URLSearchParams(location.search).get('pagamento') === 'annullato') {
    toast(tr('Pagamento annullato: puoi riprovare quando vuoi da qui.'));
    history.replaceState(null, '', location.pathname);
  }
  loadProfiles();
  loadRegistrations();
  loadHistory();
  setupPushToggle();
  document.querySelector('#submitDeck').addEventListener('click', submitDeck);
  document.querySelector('#deckSaved').addEventListener('change', (e) => {
    const deck = _savedDecks.find((d) => d.id === +e.target.value);
    if (!deck) return;
    document.querySelector('#deckText').value = deck.raw_text;
    document.querySelector('#deckArchetype').value = deck.archetype || '';
  });
  document.querySelector('#submitResult').addEventListener('click', submitResult);
  // Carica la lista da file nel textarea
  document.querySelector('#deckFile')?.addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (f) document.querySelector('#deckText').value = await f.text();
  });
});

/* ── Profili dei minori ──────────────────────────────────
   Sotto l'età minima non si apre un account: il genitore aggiunge il figlio
   come profilo, lo iscrive e lo paga lui; al tavolo gioca con il suo nome. */
function showActing() {
  const who = actingAs();
  if (!who) return;
  document.querySelector('h1').textContent = tr('Le iscrizioni di {nome}', { nome: who.name });
  document.querySelector('#actingBar').innerHTML = actingBanner();
  bindActingBanner(document.querySelector('#actingBar'));
}

async function loadProfiles() {
  const box = document.querySelector('#profilesBox');
  if (!box) return;
  // Un profilo gestito non ne gestisce altri: la sezione è del genitore.
  if (actingAs()) { document.querySelector('#profilesSection').hidden = true; return; }
  let profiles = [];
  let minAge = 14;
  try {
    [profiles, minAge] = await Promise.all([
      apiFetch('/auth/me/profiles'),
      fetch('/api/auth/rules').then((r) => r.json()).then((r) => r.min_account_age).catch(() => 14),
    ]);
  } catch (err) {
    box.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  box.innerHTML = `
    <p class="muted-text" style="margin-top:0">${esc(tr('Sotto i {anni} anni non si apre un account da soli: aggiungi qui i tuoi figli. Li iscrivi e paghi tu, e al tavolo giocano con il loro nome.', { anni: minAge }))}</p>
    ${profiles.map((p) => `
      <div class="profile-row">
        <strong>${esc(p.display_name)}</strong>
        <span class="muted-text">${esc(tr('{n} tornei', { n: p.registrations }))}</span>
        <span class="profile-actions">
          <button class="primary" data-act-as="${p.id}" data-name="${esc(p.display_name)}" type="button">${esc(tr('Gestisci le sue iscrizioni'))}</button>
          ${p.registrations ? '' : `<button class="secondary" data-drop-profile="${p.id}" type="button">${esc(tr('Elimina'))}</button>`}
        </span>
      </div>`).join('')}
    <form id="profileForm" class="profile-form">
      <input id="profileName" required minlength="2" maxlength="160" placeholder="${esc(tr('Nome e cognome del ragazzo'))}" />
      <button class="secondary" type="submit">${esc(tr('Aggiungi profilo'))}</button>
    </form>`;
  box.querySelectorAll('[data-act-as]').forEach((b) => b.addEventListener('click', () => {
    setActing({ id: b.dataset.actAs, name: b.dataset.name });
    location.reload();
  }));
  box.querySelectorAll('[data-drop-profile]').forEach((b) => b.addEventListener('click', async () => {
    if (!confirm(tr('Eliminare il profilo?'))) return;
    try {
      await apiFetch(`/auth/me/profiles/${b.dataset.dropProfile}`, { method: 'DELETE' });
      loadProfiles();
    } catch (err) { toast(err.message); }
  }));
  box.querySelector('#profileForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch('/auth/me/profiles', { method: 'POST', body: JSON.stringify({ display_name: box.querySelector('#profileName').value.trim() }) });
      toast(tr('Profilo aggiunto.'));
      loadProfiles();
    } catch (err) { toast(err.message); }
  });
}

/* ── Notifiche Web Push ──────────────────────────────── */
async function setupPushToggle() {
  const btn = document.querySelector('#pushToggle');
  if (!btn) return;
  let push;
  try { push = await import('./push.js'); } catch { return; }
  const status = await push.pushStatus();
  if (status === 'unsupported' || status === 'disabled') return;  // niente bottone

  const paint = (s) => {
    if (s === 'subscribed') { btn.textContent = '🔕 Disattiva notifiche'; btn.dataset.on = '1'; }
    else if (s === 'denied') { btn.textContent = '🔔 Notifiche bloccate'; btn.disabled = true; }
    else { btn.textContent = '🔔 Attiva notifiche'; btn.dataset.on = ''; }
    btn.hidden = false;
  };
  paint(status);

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      if (btn.dataset.on) { await push.disablePush(); toast('Notifiche disattivate.'); paint('default'); }
      else {
        const ok = await push.enablePush();
        if (ok) { toast('Notifiche attivate! Riceverai annunci e nuovi round.'); paint('subscribed'); }
        else { toast('Permesso negato o non disponibile.'); paint(await push.pushStatus()); }
      }
    } catch (err) { toast('Errore notifiche: ' + err.message); }
    finally { btn.disabled = false; }
  });
}

/* ── Storico tornei (tornei conclusi a cui ho partecipato) ──
   La tabella e un indice: piazzamento e record stanno li, il resto — i round
   giocati, con avversario e punteggio — si apre cliccando la riga. */
let _history = [];

async function loadHistory() {
  const box = document.querySelector('#historyList');
  if (!box) return;
  try {
    _history = ((await apiFetch('/tournaments/me/history')) || []).filter((r) => r.status === 'completed');
    if (!_history.length) { box.innerHTML = '<p class="empty">Nessun torneo concluso ancora.</p>'; return; }
    box.innerHTML = `<table class="data-table history-table" style="width:100%">
      <thead><tr><th>Torneo</th><th>Data</th><th>Formato</th><th>Piazzamento</th><th>Record</th><th>Punti</th></tr></thead>
      <tbody>${_history.map(r => `<tr data-tid="${r.tournament_id}" tabindex="0" role="button">
        <td><strong>${esc(r.tournament_name)}</strong></td>
        <td>${fmtDate(typeof r.starts_on === 'string' ? r.starts_on : '')}</td>
        <td>${esc(r.format)}</td>
        <td>${r.placement ? `${r.placement}º` : '—'}</td>
        <td>${esc(r.record || '—')}</td>
        <td><strong>${r.points}</strong></td>
      </tr>`).join('')}</tbody></table>`;

    box.querySelectorAll('[data-tid]').forEach(tr => {
      const open = () => showTournamentDetail(+tr.dataset.tid);
      tr.addEventListener('click', open);
      // Con tabindex la riga e raggiungibile da tastiera: deve anche attivarsi.
      tr.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
    });
  } catch (err) {
    box.innerHTML = `<p class="empty">Errore storico: ${esc(err.message)}</p>`;
  }
}

function matchRow(round, pairing, myRegId) {
  const isA = pairing.player_a_registration_id === myRegId;
  const opponent = (isA ? pairing.player_b : pairing.player_a) || null;
  if (!opponent) {
    return `<tr><td>${round.number}</td><td>—</td><td class="muted">BYE</td>
      <td><span class="badge ok">Vittoria</span></td></tr>`;
  }
  const mine = isA ? pairing.match_wins_a : pairing.match_wins_b;
  const theirs = isA ? pairing.match_wins_b : pairing.match_wins_a;
  let esito = '<span class="muted">—</span>';
  if (pairing.result) {
    const cls = mine > theirs ? 'ok' : mine < theirs ? 'warn' : '';
    const label = mine > theirs ? 'Vittoria' : mine < theirs ? 'Sconfitta' : 'Pareggio';
    esito = `<span class="badge ${cls}">${label} ${mine} – ${theirs}</span>`;
  }
  return `<tr>
    <td>${round.number}</td>
    <td>T${pairing.table_number}</td>
    <td><strong>${esc(opponent)}</strong></td>
    <td>${esito}</td>
  </tr>`;
}

async function showTournamentDetail(tid) {
  const row = _history.find(r => r.tournament_id === tid);
  const body = document.querySelector('#historyBody');
  document.querySelector('#historyTitle').textContent = row?.tournament_name || 'Torneo';
  document.querySelector('#historyFull').href = `history.html?t=${tid}`;
  body.innerHTML = '<p class="empty">Caricamento…</p>';
  document.querySelector('#historyDialog').showModal();

  const stats = `<div class="profile-stats" style="margin-bottom:18px">
    <div class="profile-stat"><strong>${row?.placement ? row.placement + 'º' : '—'}</strong><span>piazzamento</span></div>
    <div class="profile-stat"><strong>${esc(row?.record || '—')}</strong><span>V / S / P</span></div>
    <div class="profile-stat"><strong>${row?.points ?? 0}</strong><span>punti</span></div>
    <div class="profile-stat"><strong>${esc(row?.format || '—')}</strong><span>formato</span></div>
  </div>`;

  let rounds = [];
  let reg = null;
  try {
    [rounds, reg] = await Promise.all([
      apiFetch(`/tournaments/${tid}/my-pairings`),
      apiFetch(`/tournaments/${tid}/my-registration`),
    ]);
  } catch (err) {
    body.innerHTML = stats + `<p class="empty">Non riesco a caricare i round: ${esc(err.message)}</p>`;
    return;
  }

  const rows = (rounds || [])
    .sort((a, b) => a.number - b.number)
    .flatMap(round => (round.pairings || [])
      .filter(p => p.player_a_registration_id === reg.id || p.player_b_registration_id === reg.id)
      .map(p => matchRow(round, p, reg.id)))
    .join('');

  body.innerHTML = stats + (rows
    ? `<h3 style="margin:0 0 8px">I tuoi match</h3>
       <table class="data-table" style="width:100%">
         <thead><tr><th>Round</th><th>Tavolo</th><th>Avversario</th><th>Esito</th></tr></thead>
         <tbody>${rows}</tbody>
       </table>`
    : '<p class="empty">Nessun match registrato per questo torneo.</p>');
}
