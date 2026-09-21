import { renderDeck } from './deck-view.js';
import { esc } from './escape.js';

const API       = '/api';
const TOKEN_KEY = 'mull2five-jwt-v1';

/* ── Auth guard ──────────────────────────────────────── */
const token = localStorage.getItem(TOKEN_KEY);
if (!token) location.replace('login.html?next=my-registrations.html');

function decodeJwt(t) {
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
  catch { return null; }
}
const session = decodeJwt(token);
if (!session || session.exp < Date.now() / 1000) {
  localStorage.removeItem(TOKEN_KEY);
  location.replace('login.html?next=my-registrations.html');
}

/* ── Helpers ─────────────────────────────────────────── */
async function apiFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, ...(opts.headers||{}) };
  const r = await fetch(API + path, { ...opts, headers });
  if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); location.replace('login.html'); return; }
  if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || r.statusText);
  return r.status === 204 ? null : r.json();
}

function fmtDate(d) { if (!d) return '—'; const [y,m,dd]=d.split('-'); return `${dd}/${m}/${y}`; }
function fmtMoney(v) { return (+v||0).toLocaleString('it-IT',{style:'currency',currency:'EUR'}); }
function toast(msg) {
  const el = document.querySelector('#toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(()=>el.classList.remove('show'), 3200);
}

let _activeFormat = '';   // segmento della lista in modifica
let _activeTournamentId = null;
let _activePairingId    = null;
let _activeIsA          = true;   // sono il giocatore A del pairing?

/* ── Auth nav ────────────────────────────────────────── */
function updateAuthNav() {
  const el = document.querySelector('#publicAuth'); if (!el) return;
  el.innerHTML = `<a class="secondary-link" href="player.html?email=${encodeURIComponent(session.email)}">Profilo</a>
    <span style="color:var(--muted);font-size:.85rem">${esc(session.email)}</span>
    <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
  el.querySelector('#logoutBtn').addEventListener('click', () => {
    localStorage.removeItem(TOKEN_KEY); location.replace('index.html');
  });
}

/* ── Load registrations ──────────────────────────────── */
async function loadRegistrations() {
  const container = document.querySelector('#registrationsList');
  try {
    /* Cerca tutti i tornei e poi la mia iscrizione */
    const tournaments = await apiFetch('/tournaments?status=published,running,completed');
    const data = Array.isArray(tournaments) ? tournaments : (tournaments?.items ?? []);

    /* Recupera le mie iscrizioni per ogni torneo */
    const myRegs = (await Promise.allSettled(
      data.map(t => apiFetch(`/tournaments/${t.id}/my-registration`)
        .then(reg => ({ tournament: t, reg }))
        .catch(() => null))
    )).filter(r => r.status === 'fulfilled' && r.value).map(r => r.value);

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
      btn.addEventListener('click', () => openDeckDialog(btn.dataset.tournamentId, btn.dataset.regId, btn.dataset.edit === '1', btn.dataset.format || ''));
    });
    container.querySelectorAll('[data-action="view-deck"]').forEach(btn => {
      btn.addEventListener('click', () => showMyDeck(btn.dataset.tournamentId, btn.dataset.name, btn.dataset.format || ''));
    });
    container.querySelectorAll('[data-action="submit-result"]').forEach(btn => {
      btn.addEventListener('click', () => openResultDialog(
        btn.dataset.tournamentId, btn.dataset.pairingId, btn.dataset.opponent, btn.dataset.isA === '1'
      ));
    });
    container.querySelectorAll('[data-action="confirm-result"]').forEach(btn => {
      btn.addEventListener('click', () => confirmResult(btn.dataset.tournamentId, btn.dataset.pairingId));
    });
    container.querySelectorAll('[data-action="reject-result"]').forEach(btn => {
      btn.addEventListener('click', () => rejectResult(btn.dataset.tournamentId, btn.dataset.pairingId));
    });
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
    payActions = `<div class="pay-actions" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">${buttons.join('')}</div>`;
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
      parti.push(`<button class="ghost" data-action="view-deck" data-tournament-id="${t.id}" data-name="${esc(t.name)}" data-format="${esc(fmt)}" type="button">Vedi</button>`);
    }
    if (deckOpen) {
      parti.push(`<button class="ghost" data-action="upload-deck" data-tournament-id="${t.id}" data-reg-id="${reg.id}" data-format="${esc(fmt)}" data-edit="${ok ? '1' : ''}" type="button">${ok ? 'Modifica' : 'Carica'}</button>`);
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
  } catch {}

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
    } catch {}
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
    ? `<button class="ghost" data-action="self-drop" data-tournament-id="${t.id}" data-name="${esc(t.name)}" type="button" style="color:var(--danger,#ef6a5e)">Ritirati</button>`
    : '';
  // #43 Annulla iscrizione self-service: solo prima dell'inizio (torneo pubblicato).
  const canCancel = !reg.dropped && t.status === 'published';
  const cancelBtn = canCancel
    ? `<button class="ghost" data-action="self-cancel" data-tournament-id="${t.id}" data-name="${esc(t.name)}" type="button" style="color:var(--danger,#ef6a5e)">Annulla iscrizione</button>`
    : '';

  return `<article class="panel reg-card">
    <div class="reg-card-head">
      <div>
        <strong>${esc(t.name)}</strong>
        ${t.venue ? `<small>${esc(t.venue)}</small>` : ''}
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="badge">${esc(t.format)}</span>
        <span class="badge ${statusCls}">${statusLabel}</span>
        ${waitlistBadge} ${droppedBadge}
      </div>
    </div>
    <div class="reg-card-meta">
      <span>${fmtDate(t.starts_on?.substring(0,10))}</span>
      <span>Entry: ${fmtMoney((t.entry_fee_cents || 0) / 100)}</span>
      ${payBadge} ${deckBadge} ${dropBtn} ${cancelBtn}
      ${t.status === 'completed'
        ? `<a class="secondary-link" href="history.html?t=${t.id}">📊 Risultati e liste</a>`
        : `<a class="secondary-link" href="/api/tournaments/${t.id}/ical">📅 Aggiungi al calendario</a>`}
    </div>
    ${payActions}
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
           type="button">Invia risultato</button>`;
  }

  return `<div class="my-pairing">
    <span class="eyebrow">Round ${round.number} — Tavolo ${mine.table_number || '—'}</span>
    <div class="pairing-row">
      <span class="table-num">vs</span>
      <span><strong>${esc(myName)}</strong> vs <strong>${esc(opponent)}</strong></span>
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

async function openDeckDialog(tournamentId, regId, isEdit = false, fmt = '') {
  _activeFormat = fmt;
  _activeTournamentId = tournamentId;
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
function openResultDialog(tournamentId, pairingId, opponent, isA) {
  _activeTournamentId = tournamentId;
  _activePairingId    = pairingId;
  _activeIsA          = !!isA;
  document.querySelector('#resultDescription').textContent = `vs ${opponent}`;
  document.querySelector('#resultSelect').value            = '';
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
      } catch {}
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
  } catch {}
}

/* ── Init ────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  updateAuthNav();
  loadRegistrations();
  loadHistory();
  setupPushToggle();
  document.querySelector('#submitDeck').addEventListener('click', submitDeck);
  document.querySelector('#submitResult').addEventListener('click', submitResult);
  // Carica la lista da file nel textarea
  document.querySelector('#deckFile')?.addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (f) document.querySelector('#deckText').value = await f.text();
  });
});

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
    _history = await apiFetch('/tournaments/me/history') || [];
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
