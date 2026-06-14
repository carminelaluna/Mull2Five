const API = '/api';
const params = new URLSearchParams(location.search);
const TOURNAMENT_ID = params.get('id');

async function apiFetch(path, opts = {}) {
  const token = localStorage.getItem('arcana-events-jwt-v1');
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(API + path, { ...opts, headers });
  if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || r.statusText);
  return r.status === 204 ? null : r.json();
}

function esc(s) { return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmtDate(d) { if (!d) return '—'; const [y,m,dd]=d.split('-'); return `${dd}/${m}/${y}`; }
function fmtMoney(v) { return (+v||0).toLocaleString('it-IT',{style:'currency',currency:'EUR'}); }
function toast(msg) {
  const el = document.querySelector('#toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(()=>el.classList.remove('show'), 3200);
}

function getSession() {
  const t = localStorage.getItem('arcana-events-jwt-v1'); if (!t) return null;
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
  catch { return null; }
}

async function loadEvent() {
  if (!TOURNAMENT_ID) { document.querySelector('#eventDetail').innerHTML = '<p class="empty">ID torneo mancante.</p>'; return; }
  try {
    const session = getSession();
    const t = await apiFetch(`/tournaments/${TOURNAMENT_ID}`);
    // La lista completa iscritti è riservata all'organizzatore: per il giocatore
    // usiamo il conteggio pubblico (registered_players) e la sua iscrizione.
    const myReg = session
      ? await apiFetch(`/tournaments/${TOURNAMENT_ID}/my-registration`).catch(() => null)
      : null;
    const spots  = Math.max(t.capacity - (t.registered_players || 0), 0);
    const isReg  = !!myReg;
    const canReg = session && !isReg && spots > 0 && t.registration_mode === 'open';

    document.title = `${t.name} — Arcana Events`;
    document.querySelector('#eventDetail').innerHTML = `
      <div class="event-detail-header">
        <div>
          <span class="badge">${esc(t.format)}</span>
          <h1 style="margin:8px 0">${esc(t.name)}</h1>
          ${t.venue ? `<p class="muted-text">${esc(t.venue)}</p>` : ''}
        </div>
        <div style="display:grid;gap:8px;text-align:right">
          ${isReg
            ? '<span class="badge ok" style="font-size:1rem">✓ Iscritto</span>'
            : canReg
              ? `<button class="primary" id="registerBtn" type="button">Iscriviti — ${fmtMoney((t.entry_fee_cents||0)/100)}</button>`
              : !session
                ? `<a class="primary" href="login.html" style="text-align:center;text-decoration:none;padding:10px 18px;border-radius:8px">Accedi per iscriverti</a>`
                : `<span class="badge warn">${spots === 0 ? 'Torneo pieno' : 'Iscrizioni chiuse'}</span>`}
        </div>
      </div>

      <div class="event-info-grid">
        <div class="panel">
          <h3>Dettagli</h3>
          <dl class="info-dl">
            <dt>Data</dt>       <dd>${fmtDate(t.starts_on?.substring(0,10))}</dd>
            <dt>Formato</dt>    <dd>${esc(t.format)}</dd>
            <dt>REL</dt>        <dd>${esc(t.rules_enforcement_level || 'Regular')}</dd>
            <dt>Entry fee</dt>  <dd>${fmtMoney((t.entry_fee_cents||0)/100)}</dd>
            <dt>Posti</dt>      <dd>${spots} / ${t.capacity}</dd>
          </dl>
        </div>
        ${t.description ? `<div class="panel"><h3>Descrizione</h3><p>${esc(t.description)}</p></div>` : ''}
        ${t.refund_policy ? `<div class="panel"><h3>Policy rimborsi</h3><p>${esc(t.refund_policy)}</p></div>` : ''}
      </div>`;

    document.querySelector('#registerBtn')?.addEventListener('click', () => {
      document.querySelector('#registerTitle').textContent = t.name;
      document.querySelector('#registerDialog').showModal();
    });
    document.querySelector('#confirmRegister')?.addEventListener('click', () => doRegister(t));

  } catch (err) {
    document.querySelector('#eventDetail').innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`;
  }
}

async function doRegister(t) {
  const btn = document.querySelector('#confirmRegister');
  btn.disabled = true; btn.textContent = 'Iscrizione in corso…';
  try {
    const reg = await apiFetch(`/tournaments/${t.id}/registrations`, {
      method: 'POST',
      body: JSON.stringify({
        player_display_name: getSession()?.email || '',
        wizards_account:     document.querySelector('#regWizards').value.trim(),
        payment_provider:    document.querySelector('#regPayment').value,
      }),
    });
    document.querySelector('#registerDialog').close();
    // La registrazione crea l'iscrizione in stato "pending": il pagamento
    // avviene da "Le mie iscrizioni", dove sono mostrati i metodi abilitati.
    toast('Iscrizione effettuata! Completa il pagamento dalle tue iscrizioni.');
    setTimeout(() => { location.href = 'my-registrations.html'; }, 1200);
  } catch (err) {
    document.querySelector('#regError').textContent = err.message;
    btn.disabled = false; btn.textContent = 'Iscriviti e paga';
  }
}

/* Auth nav */
function updateAuthNav() {
  const s = getSession();
  const el = document.querySelector('#publicAuth'); if (!el) return;
  if (s) {
    el.innerHTML = `<span style="color:var(--muted);font-size:.85rem">${esc(s.email)}</span>
      <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
    el.querySelector('#logoutBtn').addEventListener('click', () => { localStorage.removeItem('arcana-events-jwt-v1'); location.reload(); });
  } else {
    el.innerHTML = `<a class="secondary-link" href="login.html">Accedi</a>
                    <a class="primary-btn" href="login.html">Registrati</a>`;
  }
}

document.addEventListener('DOMContentLoaded', () => { updateAuthNav(); loadEvent(); });
