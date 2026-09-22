import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { esc } from './escape.js';
import { bestOfLabel, gameInfo, gameLabel } from './games.js';
import { t as tr } from './i18n.js';
import { actingAs, actingBanner, actingHeaders, bindActingBanner, setActing } from './acting.js';

const API = '/api';
const params = new URLSearchParams(location.search);
const TOURNAMENT_ID = params.get('id');

async function apiFetch(path, opts = {}) {
  const token = localStorage.getItem('mull2five-jwt-v1');
  const headers = { 'Content-Type': 'application/json', ...(token ? actingHeaders() : {}), ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(API + path, { ...opts, headers });
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

function getSession() {
  const t = localStorage.getItem('mull2five-jwt-v1'); if (!t) return null;
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
    const game = await gameInfo(t.game);
    const platform = t.is_online ? (game?.online_platforms || []).find((p) => p.code === t.online_platform) : null;
    // Tornei vetrina dal Wizards Event Locator: ci si iscrive presso il negozio.
    const imported = t.source === 'wizards';
    // Chi organizza, come persona e come negozio: è a lui che il giocatore si rivolge.
    const storeLink = t.organization_name
      ? (t.organization_slug
        ? `<a class="secondary-link" href="store.html?s=${esc(t.organization_slug)}">${esc(t.organization_name)}</a>`
        : esc(t.organization_name))
      : '';
    const organizer = imported ? t.organization_name : t.organizer_name;
    const organizerLine = imported
      ? (storeLink ? `<p class="muted-text" style="margin:0">${esc(tr('Organizzato da'))} ${storeLink}</p>` : '')
      : t.organizer_name
        ? `<p class="muted-text" style="margin:0">${esc(tr('Organizzato da'))} <strong>${esc(t.organizer_name)}</strong>${storeLink ? ` · ${storeLink}` : ''}</p>`
        : '';

    document.title = `${t.name} — Mull2Five`;
    document.querySelector('#eventDetail').innerHTML = `${actingBanner()}
      <div class="event-detail-header">
        <div>
          <span class="game-badge game-${esc(t.game || 'mtg')}">${esc(gameLabel(t.game))}</span>
          <span class="badge">${esc(t.format)}</span>
          <h1 style="margin:8px 0">${esc(t.name)}</h1>
          ${organizerLine}
          ${t.is_online
            ? `<p class="muted-text">${esc(tr('Online · {dove}', { dove: platform?.name || '' }))}</p>`
            : t.venue ? `<p class="muted-text">${esc(t.venue)}</p>` : ''}
          ${imported ? `<p class="muted-text locator-note">${esc(tr('Dal Wizards Event Locator: iscrizione e pagamento si fanno presso il negozio.'))}</p>` : ''}
        </div>
        <div style="display:grid;gap:8px;text-align:right">
          ${imported
            ? `<a class="primary" href="${esc(t.external_url)}" target="_blank" rel="noopener" style="text-align:center;text-decoration:none;padding:10px 18px;border-radius:8px">${esc(tr('Iscriviti presso il negozio ↗'))}</a>`
            : isReg
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
            <dt>Data</dt>       <dd>${fmtDate(t.starts_on?.substring(0,10))}${t.start_time ? ' · ' + esc(t.start_time) : ''}</dd>
            <dt class="game-detail">${esc(tr('Gioco'))}</dt> <dd class="game-detail">${esc(game?.name || gameLabel(t.game))}</dd>
            <dt>Formato</dt>    <dd>${esc(t.format)}</dd>
            ${t.is_online ? `<dt>${esc(tr('Dove'))}</dt> <dd>${esc(tr('Online · {dove}', { dove: platform?.name || '' }))}</dd>` : ''}
            ${t.structure === 'registration_only'
              ? `<dt>${esc(tr('Formula'))}</dt> <dd>${esc(tr('Solo iscrizioni, senza turni'))}</dd>`
              : `<dt>${esc(tr('Match'))}</dt> <dd>${esc(bestOfLabel(t.best_of))}</dd>`}
            ${(t.team_size || 1) > 1 ? `<dt>${esc(tr('Formula'))}</dt> <dd>${esc(tr('Squadre da {n}', { n: t.team_size }))}</dd>` : ''}
            ${organizer ? `<dt>${esc(tr('Organizzatore'))}</dt> <dd>${esc(organizer)}</dd>` : ''}
            <dt>REL</dt>        <dd>${esc(t.rules_enforcement_level || 'Regular')}</dd>
            <dt>Entry fee</dt>  <dd>${fmtMoney((t.entry_fee_cents||0)/100)}</dd>
            ${imported
              ? (t.capacity ? `<dt>Posti</dt> <dd>${t.capacity}</dd>` : '')
              : `<dt>Posti</dt> <dd>${spots} / ${t.capacity}</dd>`}
          </dl>
        </div>
        ${t.description ? `<div class="panel"><h3>Descrizione</h3><p>${esc(t.description)}</p></div>` : ''}
        ${t.refund_policy ? `<div class="panel"><h3>Policy rimborsi</h3><p>${esc(t.refund_policy)}</p></div>` : ''}
      </div>`;

    document.querySelector('#registerBtn')?.addEventListener('click', async () => {
      document.querySelector('#registerTitle').textContent = t.name;
      // Si vede a chi ci si iscrive prima di confermare, non solo dopo.
      document.querySelector('#registerOrganizer').textContent = t.organizer_name
        ? tr('Organizzato da {nome}', { nome: t.organizer_name + (t.organization_name ? ` · ${t.organization_name}` : '') })
        : '';
      // L'identificativo richiesto è quello dell'editore del gioco.
      document.querySelector('#regIdLabel').textContent = game?.publisher_id_label || 'Wizards Account';
      // Negli eventi ufficiali l'ID serve: risultati e inviti arrivano lì. Si ripropone l'ultimo usato.
      const official = ['rcq', 'store_championship', 'premier'].includes(t.event_type) || t.invites > 0;
      document.querySelector('#regIdNote').textContent = official ? tr('(serve per risultati e inviti)') : tr('(opzionale)');
      const knownIds = await apiFetch('/auth/me/publisher-ids').catch(() => ({}));
      if (!document.querySelector('#regWizards').value) document.querySelector('#regWizards').value = knownIds[t.game || 'mtg'] || '';
      // Online serve il nome in gioco: si ripropone l'ultimo usato su quella piattaforma.
      document.querySelector('#regHandleWrap').style.display = t.is_online ? '' : 'none';
      if (t.is_online && platform) {
        document.querySelector('#regHandleLabel').textContent = platform.handle_label;
        document.querySelector('#regHandle').placeholder = platform.handle_hint || '';
        const handles = await apiFetch('/auth/me/handles').catch(() => ({}));
        document.querySelector('#regHandle').value = handles[platform.code] || '';
      }
      // Chi gestisce i profili dei figli sceglie chi iscrive (X-Act-As vuota: l'account).
      const profiles = await apiFetch('/auth/me/profiles', { headers: { 'X-Act-As': '' } }).catch(() => []);
      const acting = actingAs();
      document.querySelector('#regWhoWrap').style.display = profiles.length ? '' : 'none';
      document.querySelector('#regWho').innerHTML = `<option value="">${esc(tr('Me stesso'))}</option>`
        + profiles.map((p) => `<option value="${p.id}"${acting?.id === p.id ? ' selected' : ''}>${esc(p.display_name)}</option>`).join('');
      // Le domande in più che l'organizzatore ha messo al torneo.
      const fields = await apiFetch(`/tournaments/${t.id}/fields`).catch(() => []);
      document.querySelector('#regFields').innerHTML = fields.map(fieldInput).join('');
      document.querySelector('#registerDialog').showModal();
    });
    document.querySelector('#confirmRegister')?.addEventListener('click', () => doRegister(t));
    bindActingBanner(document.querySelector('#eventDetail'));

  } catch (err) {
    document.querySelector('#eventDetail').innerHTML = `<p class="empty">Errore: ${esc(err.message)}</p>`;
  }
}

function fieldInput(f) {
  const optional = f.required ? '' : ` <span class="muted-text">(${esc(tr('opzionale'))})</span>`;
  if (f.kind === 'checkbox') {
    return `<label class="reg-check"><input type="checkbox" data-field="${f.id}" /> ${esc(f.label)}${optional}</label>`;
  }
  if (f.kind === 'choice') {
    return `<label><span>${esc(f.label)}${optional}</span><select data-field="${f.id}">
      <option value="">—</option>${f.options.map((o) => `<option>${esc(o)}</option>`).join('')}</select></label>`;
  }
  return `<label><span>${esc(f.label)}${optional}</span><input data-field="${f.id}" maxlength="1000" /></label>`;
}

function collectAnswers() {
  const answers = {};
  document.querySelectorAll('#regFields [data-field]').forEach((el) => {
    answers[el.dataset.field] = el.type === 'checkbox' ? el.checked : el.value.trim();
  });
  return answers;
}

async function doRegister(t) {
  const btn = document.querySelector('#confirmRegister');
  btn.disabled = true; btn.textContent = 'Iscrizione in corso…';
  try {
    const who = document.querySelector('#regWho')?.value || '';
    const reg = await apiFetch(`/tournaments/${t.id}/registrations`, {
      method: 'POST',
      headers: { 'X-Act-As': who },
      body: JSON.stringify({
        player_display_name: getSession()?.email || '',
        wizards_account:     document.querySelector('#regWizards').value.trim(),
        game_handle:         document.querySelector('#regHandle').value.trim(),
        payment_provider:    document.querySelector('#regPayment').value,
        answers:             collectAnswers(),
      }),
    });
    document.querySelector('#registerDialog').close();
    // Si prosegue come chi è stato iscritto: il pagamento è dalle sue iscrizioni.
    setActing(who ? { id: who, name: document.querySelector('#regWho').selectedOptions[0].textContent } : null);
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
    el.querySelector('#logoutBtn').addEventListener('click', () => { localStorage.removeItem('mull2five-jwt-v1'); location.reload(); });
  } else {
    el.innerHTML = `<a class="secondary-link" href="login.html">Accedi</a>
                    <a class="primary-btn" href="login.html">Registrati</a>`;
  }
}

onReady(() => { updateAuthNav(); loadEvent(); });
