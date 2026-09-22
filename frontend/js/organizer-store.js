/**
 * organizer-store.js — La sezione Negozio del back-office.
 *
 * Il profilo pubblico che i giocatori vedono su store.html, le sedi dove si
 * gioca, lo staff, gli incassi online, le chiavi dell'API e i due pannelli da
 * amministratore (Locator e visite al sito). Sta fuori da organizer.js perche
 * e una sezione intera e non tocca i tornei: parla solo con /organizations.
 */
import { toast } from './catalog.js';
import { esc } from './escape.js';
import { t as tr } from './i18n.js';
import { $, apiFetch, fmtDate, session } from './organizer-common.js';

/* Dopo aver cambiato o modificato il negozio i tornei in lista cambiano: chi
   ci porta qui dice come ricaricarli. */
let _reload = async () => {};
export function setStoreReload(fn) { _reload = fn; }

/* ── Sedi ─────────────────────────────────────────────────
   Il negozio di chi è collegato e i posti dove gioca. Il torneo sceglie una
   sede e ne eredita indirizzo e coordinate; "Altro luogo" lascia scrivere a mano. */
let _myStore = null;
export function myStore() {
  _myStore ??= apiFetch('/organizations/mine').catch((err) => { _myStore = null; throw err; });
  return _myStore;
}

export async function myLocations() {
  const store = await myStore();
  return apiFetch(`/organizations/${encodeURIComponent(store.slug)}/locations`);
}

/* Coordinate da un indirizzo. Nominatim: servizio pubblico OSM, nessuna chiave;
   una richiesta per clic, come chiedono le sue regole d'uso. */
async function geocode(query) {
  const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(query)}`);
  const [hit] = await r.json();
  return hit ? { lat: (+hit.lat).toFixed(4), lng: (+hit.lon).toFixed(4) } : null;
}

/* ── NEGOZIO ─────────────────────────────────────────────
   Il profilo che i giocatori vedono su store.html. Le coordinate servono alla
   ricerca per distanza: senza, il negozio non compare in "vicino a me". */
export async function renderNegozio() {
  $('#panel').innerHTML = '<p class="empty">Caricamento profilo…</p>';
  let org = null;
  try {
    org = await myStore();
  } catch (err) {
    if (err.status === 404) return renderNoStore();
    toast('Errore: ' + err.message);
  }
  if (!org) { $('#panel').innerHTML = '<p class="empty">Nessun negozio configurato.</p>'; return; }
  const slug = encodeURIComponent(org.slug);
  const owner = org.my_role === 'owner';
  const [locations, members, stores, apiKeys, payments] = await Promise.all([
    myLocations().catch(() => []),
    apiFetch(`/organizations/${slug}/members`).catch(() => []),
    apiFetch('/organizations/memberships').catch(() => []),
    owner ? apiFetch(`/organizations/${slug}/api-keys`).catch(() => []) : [],
    owner ? apiFetch(`/organizations/${slug}/payments`).catch(() => null) : null,
  ]);

  $('#panel').innerHTML = `${storeSwitcher(stores)}
  <div class="panel">
    <h3>Profilo pubblico — ${esc(org.name)}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">
      Visibile su <a class="secondary-link" href="store.html?s=${esc(org.slug)}" target="_blank" rel="noopener">store.html?s=${esc(org.slug)}</a>
    </p>
    <form id="storeForm" class="bo-grid">
      <label class="span-2">Nome<input id="sName" value="${esc(org.name)}" /></label>
      <label class="span-2">Città<input id="sCity" value="${esc(org.city)}" /></label>
      <label style="grid-column:1/-1">Indirizzo<input id="sAddr" value="${esc(org.address)}" /></label>
      <label style="grid-column:1/-1">Descrizione
        <textarea id="sDesc" style="min-height:90px">${esc(org.description)}</textarea></label>
      <label>Sito web<input id="sSite" value="${esc(org.website)}" placeholder="https://…" /></label>
      <label>Logo (URL)<input id="sLogo" value="${esc(org.logo_url)}" placeholder="https://…" /></label>
      <label>Latitudine<input id="sLat" type="number" step="0.0001" value="${org.latitude ?? ''}" /></label>
      <label>Longitudine<input id="sLng" type="number" step="0.0001" value="${org.longitude ?? ''}" /></label>
      <div style="grid-column:1/-1;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="secondary" id="sGeocode" type="button">Trova coordinate dall'indirizzo</button>
        <span class="muted" style="font-size:.82rem">Senza coordinate il negozio non esce nella ricerca per distanza.</span>
      </div>
      <button class="primary" type="submit" style="grid-column:1/-1">Salva profilo</button>
    </form>
  </div>
  ${locationsPanel(locations)}
  ${paymentsPanel(org, payments)}
  ${staffPanel(org, members)}
  ${apiPanel(org, apiKeys)}
  ${locatorPanel()}
  ${analyticsPanel()}`;
  bindStoreSwitcher();
  bindLocatorPanel();
  bindAnalyticsPanel();
  bindLocationsPanel(org, locations);
  bindStaffPanel(org, members);
  bindApiPanel(org);
  bindPaymentsPanel(org);

  $('#sGeocode').addEventListener('click', async () => {
    const q = [$('#sAddr').value, $('#sCity').value].filter(Boolean).join(', ');
    if (!q) { toast('Inserisci prima indirizzo o città.'); return; }
    try {
      const hit = await geocode(q);
      if (!hit) { toast('Indirizzo non trovato.'); return; }
      $('#sLat').value = hit.lat;
      $('#sLng').value = hit.lng;
      toast('Coordinate trovate: controlla e salva.');
    } catch { toast('Geocoding non disponibile: inserisci le coordinate a mano.'); }
  });

  $('#storeForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const num = (id) => ($(id).value === '' ? null : +$(id).value);
    try {
      await apiFetch(`/organizations/${encodeURIComponent(org.slug)}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: $('#sName').value.trim(), city: $('#sCity').value.trim(),
          address: $('#sAddr').value.trim(), description: $('#sDesc').value.trim(),
          website: $('#sSite').value.trim(), logo_url: $('#sLogo').value.trim(),
          latitude: num('#sLat'), longitude: num('#sLng'),
        }),
      });
      toast('Profilo salvato.');
      _myStore = null;
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/* ── Negozio e staff ──────────────────────────────────────
   Far parte di un negozio è esplicito: chi non ne ha uno lo apre (e ne è il
   titolare) o si fa aggiungere dal titolare di uno che c'è già. */
const STORE_ROLES = { owner: 'Titolare', organizer: 'Organizzatore' };
const storeRoleLabel = (role) => tr(STORE_ROLES[role] || role);

/** Dopo aver cambiato negozio cambiano i tornei in lista e quello attivo. */
async function storeChanged() {
  _myStore = null;
  await _reload();
  renderNegozio();
}

async function renderNoStore() {
  const stores = await apiFetch('/organizations/memberships').catch(() => []);
  $('#panel').innerHTML = `${storeSwitcher(stores, true)}
  <div class="panel">
    <h3>${esc(tr('Il tuo negozio'))}</h3>
    <p class="muted" style="margin-top:0">${esc(tr('Non fai ancora parte di un negozio: i tuoi tornei per ora escono sotto Mull2Five. Apri il tuo negozio per avere una pagina tua, le tue sedi e uno staff che gestisce i tornei con te. I tornei che hai già creato vengono con te.'))}</p>
    <p class="muted">${esc(tr('Lavori per un negozio che è già qui? Chiedi al titolare di aggiungerti allo staff con la tua email.'))}</p>
    <form id="newStore" class="bo-grid">
      <label class="span-2">${esc(tr('Nome del negozio'))}<input id="nsName" required minlength="2" maxlength="120" /></label>
      <label class="span-2">${esc(tr('Città'))}<input id="nsCity" maxlength="120" /></label>
      <button class="primary" type="submit" style="grid-column:1/-1">${esc(tr('Apri il negozio'))}</button>
    </form>
  </div>
  ${locatorPanel()}
  ${analyticsPanel()}`;
  bindStoreSwitcher();
  bindLocatorPanel();
  bindAnalyticsPanel();
  $('#newStore').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch('/organizations/mine', { method: 'POST', body: JSON.stringify({
        name: $('#nsName').value.trim(), city: $('#nsCity').value.trim(),
      })});
      toast(tr('Negozio aperto: ne sei il titolare.'));
      storeChanged();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

/** Chi lavora per più negozi sceglie per quale: i tornei nuovi nascono lì. */
function storeSwitcher(stores, always = false) {
  if (stores.length < (always ? 1 : 2)) return '';
  return `<div class="panel" style="margin-bottom:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <span>${esc(tr('Stai lavorando per'))}</span>
    <select id="storePick">
      ${always && !stores.some((s) => s.current) ? `<option value="">${esc(tr('— nessun negozio —'))}</option>` : ''}
      ${stores.map((s) => `<option value="${esc(s.slug)}"${s.current ? ' selected' : ''}>${esc(s.name)} · ${esc(storeRoleLabel(s.role))}</option>`).join('')}
    </select>
  </div>`;
}

function bindStoreSwitcher() {
  $('#storePick')?.addEventListener('change', async (e) => {
    if (!e.target.value) return;
    try {
      await apiFetch(`/organizations/${encodeURIComponent(e.target.value)}/use`, { method: 'POST' });
      storeChanged();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}

function staffPanel(org, members) {
  const owner = org.my_role === 'owner';
  const rows = members.map((m) => {
    const me = String(m.user_id) === String(session.sub);
    const role = owner
      ? `<select data-member-role="${m.user_id}">${Object.keys(STORE_ROLES).map((r) =>
          `<option value="${r}"${r === m.role ? ' selected' : ''}>${esc(storeRoleLabel(r))}</option>`).join('')}</select>`
      : esc(storeRoleLabel(m.role));
    const action = me
      ? `<button class="mini-button" data-member-drop="${m.user_id}" data-self="1" type="button">${esc(tr('Esci dallo staff'))}</button>`
      : owner ? `<button class="mini-button" data-member-drop="${m.user_id}" type="button" style="color:var(--danger,#ef6a5e)">${esc(tr('Togli'))}</button>` : '';
    return `<tr>
      <td>${esc(m.display_name)}${me ? ` <span class="muted">(${esc(tr('tu'))})</span>` : ''}</td>
      <td class="muted">${esc(m.email)}</td>
      <td>${role}</td>
      <td class="row-actions">${action}</td>
    </tr>`;
  }).join('');
  return `<div class="panel" style="margin-top:16px">
    <h3>${esc(tr('Staff del negozio'))}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr("Chi fa parte dello staff crea e gestisce tutti i tornei del negozio; chi ne fa parte lo decide il titolare. Per i judge di un solo torneo c'è la scheda Staff del torneo."))}</p>
    <table class="bo"><thead><tr><th>${esc(tr('Nome'))}</th><th>Email</th><th>${esc(tr('Ruolo'))}</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>
    ${owner ? `<form id="memberForm" class="bo-grid" style="margin-top:12px">
      <label class="span-2">Email<input id="mEmail" type="email" required placeholder="${esc(tr('email del suo account'))}" /></label>
      <label>${esc(tr('Ruolo'))}<select id="mRole">
        ${Object.keys(STORE_ROLES).map((r) => `<option value="${r}"${r === 'organizer' ? ' selected' : ''}>${esc(storeRoleLabel(r))}</option>`).join('')}
      </select></label>
      <button class="primary" type="submit" style="grid-column:1/-1">${esc(tr('Aggiungi allo staff'))}</button>
      <p class="muted" style="grid-column:1/-1;margin:0;font-size:.82rem">${esc(tr('Deve avere già un account. Se era solo giocatore, diventa organizzatore.'))}</p>
    </form>` : ''}
  </div>`;
}

/* ── Wizards Event Locator (solo admin) ──────────────────
   Importa i tournaments di Magic di una zona come tournaments "vetrina": si trovano qui,
   ci si iscrive presso il negozio. Spenta sul server finché non si imposta
   WIZARDS_LOCATOR_ENABLED (vedi backend/app/services/wizards_locator.py). */
function locatorPanel() {
  if (session.role !== 'admin') return '';
  return `<div class="panel" style="margin-top:16px">
    <h3>${esc(tr('Tornei dal Wizards Event Locator'))}</h3>
    <p class="muted" id="locatorState" style="margin-top:0;font-size:.85rem">${esc(tr('Caricamento…'))}</p>
    <form id="locatorForm" class="bo-grid">
      <label class="span-2">${esc(tr('Città'))}<input id="locCity" required minlength="2" maxlength="80" placeholder="Milano" /></label>
      <label>${esc(tr('Raggio (km)'))}<input id="locDistance" type="number" min="5" max="200" value="50" /></label>
      <label title="${esc(tr('100 eventi per pagina'))}">${esc(tr('Pagine'))}<input id="locPages" type="number" min="1" max="10" value="3" /></label>
      <button class="primary" id="locSubmit" type="submit" style="grid-column:1/-1">${esc(tr('Importa i tornei'))}</button>
    </form>
    <p class="muted" id="locatorResult" style="margin:10px 0 0;font-size:.85rem" hidden></p>
  </div>`;
}

function bindLocatorPanel() {
  const form = $('#locatorForm');
  if (!form) return;
  const showStatus = (st) => {
    $('#locatorState').textContent = st.enabled
      ? tr('Importati finora: {tornei} tornei di {negozi} negozi. Chi li apre trova il link per iscriversi presso il negozio.', { tournaments: st.imported_tournaments, stores: st.imported_stores })
      : tr("Spenta sul server: si accende con WIZARDS_LOCATOR_ENABLED=true. Le condizioni d'uso di Wizards vietano la raccolta automatica dei dati: prima di accenderla chiedi il permesso a Wizards (WPN).");
    $('#locSubmit').disabled = !st.enabled;
  };
  apiFetch('/admin/wizards-locator').then(showStatus).catch((err) => { $('#locatorState').textContent = 'Errore: ' + err.message; });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const button = $('#locSubmit');
    button.disabled = true;
    button.textContent = tr('Importazione in corso…');
    try {
      const r = await apiFetch('/admin/wizards-locator/import', { method: 'POST', body: JSON.stringify({
        city: $('#locCity').value.trim(),
        distance_km: Number($('#locDistance').value) || 50,
        max_pages: Number($('#locPages').value) || 3,
      }) });
      const result = $('#locatorResult');
      result.hidden = false;
      result.textContent = tr('{letti} eventi letti: {nuovi} nuovi, {aggiornati} aggiornati, {annullati} annullati, {saltati} saltati. Negozi nuovi: {negozi}.', {
        letti: r.fetched, nuovi: r.created, aggiornati: r.updated, annullati: r.cancelled, saltati: r.skipped, stores: r.stores_created,
      });
      showStatus(await apiFetch('/admin/wizards-locator'));
    } catch (err) {
      toast('Errore: ' + err.message);
    } finally {
      button.disabled = false;
      button.textContent = tr('Importa i tornei');
    }
  });
}

/* ── Visite al sito (solo admin) ─────────────────────────
   Statistiche anonime senza cookie (backend/app/routers/site.py): pagine viste,
   visite (gli ingressi nel sito), da dove arrivano e su che schermi. */
function analyticsPanel() {
  if (session.role !== 'admin') return '';
  return `<div class="panel" style="margin-top:16px">
    <div class="bo-head" style="margin-bottom:8px">
      <h3 style="margin:0">${esc(tr('Visite al sito'))}</h3>
      <div class="row-actions"><select id="anDays" aria-label="${esc(tr('Periodo'))}">
        <option value="7">${esc(tr('Ultimi 7 giorni'))}</option>
        <option value="30" selected>${esc(tr('Ultimi 30 giorni'))}</option>
        <option value="90">${esc(tr('Ultimi 90 giorni'))}</option>
      </select></div>
    </div>
    <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr('Statistiche anonime, senza cookie: pagine viste e visite, cioè gli ingressi nel sito.'))}</p>
    <div id="anBody"><p class="empty">${esc(tr('Caricamento…'))}</p></div>
  </div>`;
}

function bindAnalyticsPanel() {
  const select = $('#anDays');
  if (!select) return;
  const list = (rows, label = (x) => x) => (rows.length
    ? `<ol class="an-list">${rows.map((r) => `<li><span>${esc(label(r.label))}</span><strong>${r.count}</strong></li>`).join('')}</ol>`
    : `<p class="muted" style="margin:0">${esc(tr('Ancora niente.'))}</p>`);
  const screens = { mobile: tr('Telefono'), tablet: tr('Tablet'), desktop: tr('Computer') };
  const load = async () => {
    try {
      const a = await apiFetch(`/admin/analytics?days=${select.value}`);
      const max = Math.max(1, ...a.days.map((d) => d.views));
      const bars = a.days.map((d) => `<div class="an-bar" title="${esc(fmtDate(d.day))}: ${d.views}" style="--h:${Math.round((d.views / max) * 100)}%"></div>`).join('');
      $('#anBody').innerHTML = `
        <div class="an-totals">
          <div><strong>${a.total_visitors}</strong><span>${esc(tr('persone'))}</span></div>
          <div><strong>${a.total_entries}</strong><span>${esc(tr('visite'))}</span></div>
          <div><strong>${a.total_views}</strong><span>${esc(tr('pagine viste'))}</span></div>
        </div>
        <div class="an-chart" role="img" aria-label="${esc(tr('Pagine viste per giorno'))}">${bars}</div>
        <div class="an-cols">
          <div><h4>${esc(tr('Pagine'))}</h4>${list(a.pages)}</div>
          <div><h4>${esc(tr('Da dove arrivano'))}</h4>${list(a.referrers, (x) => x || tr('Diretto'))}</div>
          <div><h4>${esc(tr('Schermi'))}</h4>${list(a.devices, (x) => screens[x] || x)}</div>
        </div>`;
    } catch (err) {
      $('#anBody').innerHTML = `<p class="field-error">${esc(err.message)}</p>`;
    }
  };
  select.addEventListener('change', load);
  load();
}

/* ── Incassi online ──────────────────────────────────────
   Dove arrivano le quote pagate online: il conto Stripe del negozio (carta,
   con Stripe Connect) e la sua email PayPal. Li gestisce il titolare. */
function paymentsPanel(org, pay) {
  if (org.my_role !== 'owner' || !pay) return '';
  const [stateLabel, stateClass] = {
    none: [tr('Non collegato'), ''], pending: [tr('Da completare'), 'warn'], active: [tr('Attivo'), 'ok'],
  }[pay.stripe_status] || ['', ''];
  let stripeActions;
  if (!pay.stripe_available) {
    stripeActions = `<span class="muted">${esc(tr('Stripe non è configurato sul server.'))}</span>`;
  } else if (pay.stripe_status === 'none') {
    stripeActions = `<button class="primary" id="stripeConnect" type="button">${esc(tr('Collega Stripe'))}</button>`;
  } else {
    stripeActions = `${pay.stripe_status === 'pending' ? `<button class="primary" id="stripeConnect" type="button">${esc(tr('Completa la configurazione'))}</button>` : ''}
      <button class="secondary" id="stripeDashboard" type="button">${esc(tr('Dashboard Stripe ↗'))}</button>
      <button class="secondary danger-outline" id="stripeDisconnect" type="button">${esc(tr('Scollega'))}</button>`;
  }
  const fee = pay.platform_fee_percent ? ` ${tr('Commissione della piattaforma: {n}%.', { n: pay.platform_fee_percent })}` : '';
  return `<div class="panel" style="margin-top:16px">
    <h3>${esc(tr('Incassi online'))}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr('Collega i conti del negozio e le quote pagate online arrivano a te. Senza, arrivano al conto della piattaforma.') + fee)}</p>
    <div class="pay-rows">
      <div class="pay-row">
        <span class="pay-label">Stripe</span>
        ${pay.stripe_available
          ? `<span><span class="pill ${stateClass}">${esc(stateLabel)}</span></span><span class="pay-actions">${stripeActions}</span>`
          : `<span style="grid-column:2/-1">${stripeActions}</span>`}
      </div>
      <form class="pay-row pay-row-form" id="paypalForm">
        <span class="pay-label">PayPal</span>
        <input id="paypalEmail" type="email" maxlength="254" placeholder="${esc(tr('email del conto PayPal del negozio'))}" value="${esc(pay.paypal_email || '')}" />
        <button class="secondary" type="submit">${esc(tr('Salva'))}</button>
      </form>
    </div>
    <p class="muted" style="margin:10px 0 0;font-size:.82rem">${esc(tr('I rimborsi con carta partono da qui e riprendono il bonifico al negozio; quelli PayPal li fai dal conto PayPal del negozio.'))}</p>
  </div>`;
}

function bindPaymentsPanel(org) {
  const base = `/organizations/${encodeURIComponent(org.slug)}`;
  $('#stripeConnect')?.addEventListener('click', async () => {
    try {
      const { url } = await apiFetch(`${base}/stripe/connect`, { method: 'POST' });
      location.href = url;
    } catch (err) { toast('Errore: ' + err.message); }
  });
  $('#stripeDashboard')?.addEventListener('click', async () => {
    try {
      const { url } = await apiFetch(`${base}/stripe/dashboard`, { method: 'POST' });
      window.open(url, '_blank', 'noopener');
    } catch (err) { toast('Errore: ' + err.message); }
  });
  $('#stripeDisconnect')?.addEventListener('click', async () => {
    if (!confirm(tr('Scollegare Stripe? I nuovi pagamenti con carta andranno al conto della piattaforma.'))) return;
    try {
      await apiFetch(`${base}/stripe`, { method: 'DELETE' });
      toast(tr('Stripe scollegato.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  });
  $('#paypalForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch(`${base}/paypal`, { method: 'PUT', body: JSON.stringify({ paypal_email: $('#paypalEmail').value.trim() }) });
      toast(tr('Salvato.'));
    } catch (err) { toast('Errore: ' + err.message); }
  });
  // Di ritorno da Stripe: si chiede subito se l'account può incassare.
  const back = new URLSearchParams(location.search).get('stripe');
  if (back) {
    history.replaceState(null, '', location.pathname);
    apiFetch(`${base}/stripe/refresh`, { method: 'POST' })
      .then((pay) => {
        toast(pay.stripe_status === 'active' ? tr('Stripe collegato: i pagamenti con carta arrivano al negozio.')
          : tr('Stripe non ha ancora finito le verifiche: riprova tra poco.'));
        renderNegozio();
      })
      .catch((err) => toast('Errore: ' + err.message));
  }
}

/* ── API pubblica ────────────────────────────────────────
   Le chiavi con cui il sito del negozio, un bot o un overlay di streaming leggono
   i suoi tournaments. Le gestisce il titolare; una chiave si vede solo appena creata. */
function apiPanel(org, keys) {
  if (org.my_role !== 'owner') return '';
  const when = (iso) => new Date(iso).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  const rows = keys.map((k) => `<tr>
      <td><strong>${esc(k.name)}</strong></td>
      <td><span class="handle">${esc(k.prefix)}…</span></td>
      <td class="muted">${esc(when(k.created_at))}${k.created_by ? ` · ${esc(k.created_by)}` : ''}</td>
      <td class="muted">${k.last_used_at ? esc(when(k.last_used_at)) : esc(tr('mai'))}</td>
      <td class="row-actions"><button class="mini-button" data-revoke-key="${k.id}" type="button" style="color:var(--danger,#ef6a5e)">${esc(tr('Revoca'))}</button></td>
    </tr>`).join('') || `<tr><td colspan="5" class="muted">${esc(tr('Nessuna chiave.'))}</td></tr>`;
  const base = `${location.origin}/api/v1`;
  return `<div class="panel" style="margin-top:16px">
    <h3>${esc(tr('API per il sito del negozio'))}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr('Con una chiave il tuo sito, un bot o un overlay di streaming leggono tornei, iscritti, abbinamenti e classifiche del negozio. Sola lettura, senza email né dati di pagamento.'))}</p>
    <div class="table-scroll"><table class="bo"><thead><tr><th>${esc(tr('Nome'))}</th><th>${esc(tr('Chiave'))}</th>
      <th>${esc(tr('Creata'))}</th><th>${esc(tr('Ultimo uso'))}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <form id="apiKeyForm" class="toolbar" style="margin-top:12px">
      <input id="apiKeyName" required maxlength="80" placeholder="${esc(tr('A cosa serve, es. Sito del negozio'))}" style="width:280px" />
      <button class="primary" type="submit">${esc(tr('Crea chiave'))}</button>
    </form>
    <div id="apiKeyNew"></div>
    <details class="bo-more" style="margin-top:12px"><summary>${esc(tr('Come si usa'))}</summary>
      <pre class="code-block">curl -H "X-API-Key: m2f_…" ${esc(base)}/tournaments
${esc(base)}/tournaments/{id}
${esc(base)}/tournaments/{id}/players
${esc(base)}/tournaments/{id}/pairings?round=2
${esc(base)}/tournaments/{id}/standings</pre>
    </details>
  </div>`;
}

function bindApiPanel(org) {
  const base = `/organizations/${encodeURIComponent(org.slug)}/api-keys`;
  $('#apiKeyForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const created = await apiFetch(base, { method: 'POST', body: JSON.stringify({ name: $('#apiKeyName').value.trim() }) });
      await renderNegozio();
      $('#apiKeyNew').innerHTML = `<div class="bo-warning warn" style="margin-top:12px">
        <span class="bo-warning-icon" aria-hidden="true">🔑</span>
        <span class="bo-warning-text">${esc(tr('Copiala adesso: poi non la vedrai più.'))} <span class="handle">${esc(created.key)}</span></span>
        <button class="mini-button" id="apiKeyCopy" type="button">${esc(tr('Copia'))}</button></div>`;
      $('#apiKeyCopy').addEventListener('click', () => navigator.clipboard.writeText(created.key).then(() => toast(tr('Chiave copiata'))));
      $('#apiKeyNew').scrollIntoView({ block: 'nearest' });
    } catch (err) { toast('Errore: ' + err.message); }
  });
  $('#panel').querySelectorAll('[data-revoke-key]').forEach((b) => b.addEventListener('click', async () => {
    if (!confirm(tr('Revocare la chiave? Chi la usa smette subito di leggere i dati.'))) return;
    try {
      await apiFetch(`${base}/${b.dataset.revokeKey}`, { method: 'DELETE' });
      toast(tr('Chiave revocata.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  }));
}

function bindStaffPanel(org, members) {
  const base = `/organizations/${encodeURIComponent(org.slug)}/members`;
  $('#memberForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch(base, { method: 'POST', body: JSON.stringify({
        email: $('#mEmail').value.trim(), role: $('#mRole').value,
      })});
      toast(tr('Aggiunto allo staff.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  });
  $('#panel').querySelectorAll('[data-member-role]').forEach((sel) => sel.addEventListener('change', async () => {
    try {
      await apiFetch(`${base}/${sel.dataset.memberRole}`, { method: 'PATCH', body: JSON.stringify({ role: sel.value }) });
      toast(tr('Ruolo aggiornato.'));
      if (String(sel.dataset.memberRole) === String(session.sub)) _myStore = null;
    } catch (err) {
      toast('Errore: ' + err.message);
    }
    renderNegozio();
  }));
  $('#panel').querySelectorAll('[data-member-drop]').forEach((b) => b.addEventListener('click', async () => {
    const self = b.dataset.self === '1';
    const member = members.find((m) => String(m.user_id) === b.dataset.memberDrop);
    const question = self
      ? tr('Uscire dallo staff di {negozio}? Non gestirai più i suoi tornei.', { negozio: org.name })
      : tr('Togliere {nome} dallo staff? I tornei che ha creato restano al negozio.', { nome: member?.display_name || '' });
    if (!confirm(question)) return;
    try {
      await apiFetch(`${base}/${b.dataset.memberDrop}`, { method: 'DELETE' });
      if (self) { storeChanged(); return; }
      toast(tr('Tolto dallo staff.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  }));
}

function locationsPanel(locations) {
  const rows = locations.map((loc) => `
    <tr>
      <td><strong>${esc(loc.name)}</strong>${loc.notes ? `<div class="muted" style="font-size:.82rem">${esc(loc.notes)}</div>` : ''}</td>
      <td class="muted">${esc([loc.address, loc.city].filter(Boolean).join(', ') || '—')}</td>
      <td>${loc.latitude != null ? esc(tr('Sì')) : `<span class="muted">${esc(tr('No: non esce nella ricerca per distanza'))}</span>`}</td>
      <td class="row-actions">
        <button class="mini-button" data-edit-loc="${loc.id}" type="button">${esc(tr('Modifica'))}</button>
        <button class="mini-button" data-drop-loc="${loc.id}" type="button" style="color:var(--danger,#ef6a5e)">${esc(tr('Elimina'))}</button>
      </td>
    </tr>`).join('')
    || `<tr><td colspan="4" class="muted">${esc(tr("Nessuna sede: i tornei usano l'indirizzo del negozio o il luogo scritto a mano."))}</td></tr>`;
  return `<div class="panel" style="margin-top:16px">
    <h3>${esc(tr('Sedi'))}</h3>
    <p class="muted" style="margin-top:0;font-size:.85rem">${esc(tr('Dove si gioca: un secondo punto vendita, una sala per gli eventi grandi. Ogni torneo sceglie la sua sede e ne prende indirizzo e posizione sulla mappa.'))}</p>
    <table class="bo"><thead><tr><th>${esc(tr('Sede'))}</th><th>${esc(tr('Indirizzo'))}</th><th>${esc(tr('Coordinate'))}</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>
    <form id="locForm" class="bo-grid" style="margin-top:12px">
      <input type="hidden" id="lId" />
      <label class="span-2">${esc(tr('Nome'))}<input id="lName" required minlength="2" maxlength="120" placeholder="${esc(tr('Sala eventi'))}" /></label>
      <label class="span-2">${esc(tr('Città'))}<input id="lCity" maxlength="120" /></label>
      <label style="grid-column:1/-1">${esc(tr('Indirizzo'))}<input id="lAddr" maxlength="240" /></label>
      <label class="span-2">${esc(tr('Latitudine'))}<input id="lLat" type="number" step="0.0001" /></label>
      <label class="span-2">${esc(tr('Longitudine'))}<input id="lLng" type="number" step="0.0001" /></label>
      <label style="grid-column:1/-1">${esc(tr('Note per chi arriva'))}<input id="lNotes" placeholder="${esc(tr('Piano, parcheggio, accessibilità'))}" /></label>
      <div style="grid-column:1/-1;display:flex;gap:8px;flex-wrap:wrap">
        <button class="secondary" id="lGeocode" type="button">Trova coordinate dall'indirizzo</button>
        <button class="primary" id="lSave" type="submit">${esc(tr('Aggiungi sede'))}</button>
        <button class="secondary" id="lCancel" type="button" style="display:none">${esc(tr('Annulla'))}</button>
      </div>
    </form>
  </div>`;
}

function bindLocationsPanel(org, locations) {
  const base = `/organizations/${encodeURIComponent(org.slug)}/locations`;
  const num = (id) => ($(id).value === '' ? null : +$(id).value);
  const fill = (loc) => {
    $('#lId').value = loc?.id ?? '';
    $('#lName').value = loc?.name ?? '';
    $('#lCity').value = loc?.city ?? '';
    $('#lAddr').value = loc?.address ?? '';
    $('#lLat').value = loc?.latitude ?? '';
    $('#lLng').value = loc?.longitude ?? '';
    $('#lNotes').value = loc?.notes ?? '';
    $('#lSave').textContent = loc ? tr('Salva sede') : tr('Aggiungi sede');
    $('#lCancel').style.display = loc ? '' : 'none';
  };
  $('#panel').querySelectorAll('[data-edit-loc]').forEach((b) => b.addEventListener('click', () => {
    fill(locations.find((loc) => String(loc.id) === b.dataset.editLoc));
    $('#lName').focus();
  }));
  $('#panel').querySelectorAll('[data-drop-loc]').forEach((b) => b.addEventListener('click', async () => {
    const loc = locations.find((l) => String(l.id) === b.dataset.dropLoc);
    if (!confirm(tr('Eliminare la sede "{nome}"? I tornei che la usavano tengono scritto dove si sono giocati.', { nome: loc.name }))) return;
    try {
      await apiFetch(`${base}/${loc.id}`, { method: 'DELETE' });
      toast(tr('Sede eliminata.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  }));
  $('#lCancel').addEventListener('click', () => fill(null));
  $('#lGeocode').addEventListener('click', async () => {
    const q = [$('#lAddr').value, $('#lCity').value].filter(Boolean).join(', ');
    if (!q) { toast('Inserisci prima indirizzo o città.'); return; }
    try {
      const hit = await geocode(q);
      if (!hit) { toast('Indirizzo non trovato.'); return; }
      $('#lLat').value = hit.lat;
      $('#lLng').value = hit.lng;
    } catch { toast('Geocoding non disponibile: inserisci le coordinate a mano.'); }
  });
  $('#locForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = $('#lId').value;
    const body = {
      name: $('#lName').value.trim(), city: $('#lCity').value.trim(),
      address: $('#lAddr').value.trim(), notes: $('#lNotes').value.trim(),
      latitude: num('#lLat'), longitude: num('#lLng'),
    };
    try {
      await apiFetch(id ? `${base}/${id}` : base, { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) });
      toast(id ? tr('Sede salvata.') : tr('Sede aggiunta.'));
      renderNegozio();
    } catch (err) { toast('Errore: ' + err.message); }
  });
}
