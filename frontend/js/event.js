import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { esc } from './escape.js';
import { bestOfLabel, gameInfo, gameLabel } from './games.js';
import { t as tr } from './i18n.js';
import { actingAs, actingBanner, bindActingBanner, setActing } from './acting.js';
import { earlyBirdOn, feeNow, fmtDate, fmtMoney, toast, updateAuthNav, placeLabel } from './catalog.js';
import { busy } from './form-state.js';
import { decksFor, deckOptions, deckSegments } from './saved-decks.js';
import { apiRequest, getSession } from './session.js';
import { stickyCta } from './site.js';

const params = new URLSearchParams(location.search);
const TOURNAMENT_ID = params.get('id');
// Di ritorno da Stripe o PayPal senza aver pagato: non è iscritto.
const PAYMENT_CANCELLED = params.get('pagamento') === 'annullato';
/* Dal QR dell'organizzatore (qr.html): si arriva con la finestra d'iscrizione aperta. */
const OPEN_REGISTRATION = params.get('iscriviti') === '1';

/* Chi gestisce il profilo di un figlio lo iscrive per lui (X-Act-As). */
const apiFetch = (path, opts = {}) => apiRequest(path, { acting: true, ...opts });

/* I modi di pagare che il torneo accetta su questo sito: Stripe e PayPal solo
   se i pagamenti online sono accesi (in produzione si paga al banco). */
const methodLabel = (method) => ({
  at_event: tr('Al banco, il giorno del torneo'),
  stripe: tr('Carta di credito (Stripe)'),
  paypal: 'PayPal',
}[method]);
function paymentMethods(t, online) {
  return [
    t.pay_at_event && 'at_event',
    online && t.pay_stripe && 'stripe',
    online && t.pay_paypal && 'paypal',
  ].filter(Boolean);
}

/* Il modo scelto, o "" se non c'era niente da scegliere (torneo gratuito). */
const chosenMethod = () => (document.querySelector('#regPaymentWrap').style.display === 'none'
  ? '' : document.querySelector('#regPayment').value);

/* Il pulsante dice cosa succede: iscritto subito, o prima si paga. */
function syncPaymentChoice() {
  const method = chosenMethod();
  const online = method === 'stripe' || method === 'paypal';
  document.querySelector('#confirmRegister').textContent = online ? tr('Iscriviti e paga') : tr('Iscriviti');
  document.querySelector('#regPaymentNote').textContent = online
    ? tr('Sei iscritto quando il pagamento è completato. Il posto resta tuo per 30 minuti.')
    : method === 'at_event' ? tr('Sei iscritto subito: la quota la paghi al banco il giorno del torneo.') : '';
}


/* Il QR dell'iscrizione (lo disegna il server, come quello del foglio qr.html):
   si fa inquadrare a chi è accanto, o si apre il foglio da stampare. */
function openQr(t) {
  const link = `${location.origin}/event.html?id=${t.id}&iscriviti=1`;
  document.querySelector('#qrDialogTitle').textContent = t.name;
  document.querySelector('#qrDialogImage').src = `/api/tournaments/${t.id}/registration-qr.svg`;
  document.querySelector('#qrDialogSheet').href = `qr.html?t=${t.id}`;
  document.querySelector('#qrDialogCopy').onclick = async () => {
    try {
      await navigator.clipboard.writeText(link);
      toast(tr('Link copiato'));
    } catch {
      toast(link, 8000);   // senza permesso sugli appunti: il link si legge e si copia a mano
    }
  };
  document.querySelector('#qrDialog').showModal();
}


async function loadEvent() {
  if (!TOURNAMENT_ID) { document.querySelector('#eventDetail').innerHTML = '<p class="empty">ID torneo mancante.</p>'; return; }
  try {
    const session = getSession();
    if (PAYMENT_CANCELLED && session) {
      // Prima di leggere l'iscrizione: il posto tenuto per lui si libera subito.
      await apiFetch(`/tournaments/${TOURNAMENT_ID}/my-registration/abandon-payment`, { method: 'POST' }).catch(() => null);
      history.replaceState(null, '', `event.html?id=${TOURNAMENT_ID}`);
      toast(tr('Pagamento annullato: non sei iscritto. Puoi riprovare quando vuoi.'), 6000);
    }
    const t = await apiFetch(`/tournaments/${TOURNAMENT_ID}`);
    // La lista completa iscritti è riservata all'organizzatore: per il giocatore
    // usiamo il conteggio pubblico (registered_players) e la sua iscrizione.
    const myReg = session
      ? await apiFetch(`/tournaments/${TOURNAMENT_ID}/my-registration`).catch(() => null)
      : null;
    const spots  = Math.max(t.capacity - (t.registered_players || 0), 0);
    // Chi ha annullato prima dell'inizio può iscriversi di nuovo.
    const isReg  = !!myReg && !(myReg.dropped && t.status === 'published');
    // Solo i tornei ancora aperti: uno concluso o annullato non accetta
    // iscrizioni nemmeno se la data è più avanti (il server risponde 404).
    const aperto = ['published', 'running'].includes(t.status)
      && (t.status !== 'running' || t.late_registration_enabled);
    const canReg = session && !isReg && spots > 0 && t.registration_mode === 'open' && aperto;
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
            : placeLabel(t) ? `<p class="muted-text">${esc(placeLabel(t))}</p>` : ''}
          ${imported ? `<p class="muted-text locator-note">${esc(tr('Dal Wizards Event Locator: iscrizione e pagamento si fanno presso il negozio.'))}</p>` : ''}
        </div>
        <div style="display:grid;gap:8px;text-align:right">
          ${imported
            ? `<a class="primary" id="eventCta" href="${esc(t.external_url)}" target="_blank" rel="noopener" style="text-align:center;text-decoration:none;padding:10px 18px;border-radius:8px">${esc(tr('Iscriviti presso il negozio ↗'))}</a>`
            : isReg && myReg.dropped
            // Ritirato a torneo in corso: non gioca più i prossimi turni.
            ? `<span class="badge">${esc(tr('Ritirato'))}</span>`
            : isReg && myReg.payment_due_by && myReg.payment_status !== 'paid'
            // Ha scelto di pagare online e il pagamento non è ancora arrivato:
            // non è iscritto, ha solo il posto tenuto.
            ? `<span class="badge warn">${esc(tr('Pagamento in corso'))}</span>
               <a class="secondary-link" href="my-registrations.html">${esc(tr('Completa il pagamento'))}</a>`
            : isReg
            ? `<span class="badge ok" style="font-size:1rem">✓ Iscritto</span>${deckButton(t, myReg)}`
            : canReg
              ? `<button class="primary" id="registerBtn" type="button">Iscriviti — ${fmtMoney(feeNow(t))}</button>`
              : !session
                ? `<a class="primary" id="eventCta" href="login.html?next=${encodeURIComponent(location.pathname + location.search)}" style="text-align:center;text-decoration:none;padding:10px 18px;border-radius:8px">Accedi per iscriverti</a>`
                : `<span class="badge warn">${spots === 0 ? 'Torneo pieno' : 'Iscrizioni chiuse'}</span>`}
          ${!imported && aperto
            ? `<button class="secondary" id="qrOpen" type="button">▦ ${esc(tr('QR iscrizione'))}</button>` : ''}
        </div>
      </div>

      <div class="event-info-grid">
        <div class="panel">
          <h3>${esc(tr('Dettagli'))}</h3>
          <dl class="info-dl">
            <dt>${esc(tr('Data'))}</dt>       <dd>${fmtDate(t.starts_on)}${t.start_time ? ' · ' + esc(t.start_time) : ''}</dd>
            <dt class="game-detail">${esc(tr('Gioco'))}</dt> <dd class="game-detail">${esc(game?.name || gameLabel(t.game))}</dd>
            <dt>${esc(tr('Formato'))}</dt>    <dd>${esc(t.format)}</dd>
            ${t.is_online ? `<dt>${esc(tr('Dove'))}</dt> <dd>${esc(tr('Online · {dove}', { dove: platform?.name || '' }))}</dd>` : ''}
            ${t.structure === 'registration_only'
              ? `<dt>${esc(tr('Formula'))}</dt> <dd>${esc(tr('Solo iscrizioni, senza turni'))}</dd>`
              : `<dt>${esc(tr('Match'))}</dt> <dd>${esc(bestOfLabel(t.best_of))}</dd>`}
            ${(t.team_size || 1) > 1 ? `<dt>${esc(tr('Formula'))}</dt> <dd>${esc(tr('Squadre da {n}', { n: t.team_size }))}</dd>` : ''}
            ${organizer ? `<dt>${esc(tr('Organizzatore'))}</dt> <dd>${esc(organizer)}</dd>` : ''}
            <dt>REL</dt>        <dd>${esc(t.rules_enforcement_level || 'Regular')}</dd>
            <dt>${esc(tr('Entry fee'))}</dt>
            <dd>${fmtMoney(feeNow(t))}
              ${earlyBirdOn(t)
                // Senza la data lo sconto sembra il prezzo di sempre, e chi
                // rimanda scopre la differenza al banco.
                ? `<span class="badge ok">${esc(tr('Early bird fino al {data}', { data: fmtDate(t.early_bird_until) }))}</span>
                   <span class="col-sub">${esc(tr('poi'))} ${fmtMoney(t.entry_fee_cents)}</span>`
                : ''}</dd>
            ${imported
              ? (t.capacity ? `<dt>${esc(tr('Posti'))}</dt> <dd>${t.capacity}</dd>` : '')
              // Gli iscritti, non i posti liberi: "Posti 0 / 64" su un torneo
              // pieno si legge come "nessuno si e' iscritto". Lo stesso conto
              // che fa il back-office ("0/48 iscritti"). `spots` resta ai suoi
              // due usi veri: il pulsante d'iscrizione e il distintivo "pieno".
              : `<dt>${esc(tr('Posti'))}</dt> <dd>${t.registered_players || 0} / ${t.capacity}</dd>`}
          </dl>
        </div>
        ${t.description ? `<div class="panel"><h3>${esc(tr('Descrizione'))}</h3><p>${esc(t.description)}</p></div>` : ''}
        ${t.refund_policy ? `<div class="panel"><h3>${esc(tr('Policy rimborsi'))}</h3><p>${esc(t.refund_policy)}</p></div>` : ''}
      </div>`;

    // Sul telefono la CTA resta a portata di pollice anche scorrendo la pagina.
    stickyCta(document.querySelector('#registerBtn, #eventCta'));
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
      await fillRegDecks(t);
      // Su un torneo gratuito un campo "codice sconto" è solo una domanda in più.
      document.querySelector('#regDiscountWrap').style.display = feeNow(t) ? '' : 'none';
      // Come si paga: solo i modi che il torneo accetta. Gratis, niente da scegliere.
      const { online } = await apiFetch('/payments/options').catch(() => ({ online: false }));
      const methods = feeNow(t) ? paymentMethods(t, online) : [];
      document.querySelector('#regPaymentWrap').style.display = methods.length ? '' : 'none';
      document.querySelector('#regPayment').innerHTML = methods
        .map((m) => `<option value="${m}">${esc(methodLabel(m))}</option>`).join('');
      const noWay = feeNow(t) > 0 && !methods.length;
      document.querySelector('#regError').textContent = noWay
        ? tr('Questo torneo non ha un modo per pagare la quota: contatta l\'organizzatore') : '';
      document.querySelector('#confirmRegister').disabled = noWay;
      syncPaymentChoice();
      document.querySelector('#registerDialog').showModal();
    });
    document.querySelector('#qrOpen')?.addEventListener('click', () => openQr(t));
    // Chi iscrive il figlio sceglie fra le liste del figlio.
    document.querySelector('#regWho')?.addEventListener('change', () => fillRegDecks(t));
    document.querySelector('#deckSendOpen')?.addEventListener('click', () => openDeckSend(t, myReg));
    document.querySelector('#deckSendSubmit')?.addEventListener('click', () => submitDeckSend(t, myReg));
    document.querySelector('#regPayment')?.addEventListener('change', syncPaymentChoice);
    document.querySelector('#confirmRegister')?.addEventListener('click', () => doRegister(t));
    bindActingBanner(document.querySelector('#eventDetail'));

    // Senza accesso il parametro resta: torna qui dal login, e la finestra si apre allora.
    if (OPEN_REGISTRATION && session) {
      history.replaceState(null, '', `event.html?id=${TOURNAMENT_ID}`);
      document.querySelector('#registerBtn')?.click();
    }

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
  const method = chosenMethod();
  busy(btn, true, method === 'stripe' || method === 'paypal' ? tr('Reindirizzamento al pagamento…') : tr('Iscrizione in corso…'));
  try {
    const who = document.querySelector('#regWho')?.value || '';
    const reg = await apiFetch(`/tournaments/${t.id}/registrations`, {
      method: 'POST',
      headers: { 'X-Act-As': who },
      body: JSON.stringify({
        player_display_name: getSession()?.email || '',
        wizards_account:     document.querySelector('#regWizards').value.trim(),
        game_handle:         document.querySelector('#regHandle').value.trim(),
        discount_code:       document.querySelector('#regDiscount').value.trim(),
        payment_method:      chosenMethod() || null,
        answers:             collectAnswers(),
      }),
    });
    // La lista scelta nel modulo parte subito, prima di andare a pagare. Se non
    // parte l'iscrizione resta, e la pagina di ringraziamento ricorda di caricarla.
    await sendPicked(document.querySelector('#regDecks'), t, { 'X-Act-As': who }).catch(() => null);
    // Si prosegue come chi è stato iscritto: il ritorno dal pagamento è suo.
    setActing(who ? { id: who, name: document.querySelector('#regWho').selectedOptions[0].textContent } : null);
    // Ha scelto di pagare online: si paga adesso, e l'iscrizione vale solo dopo.
    if (reg?.checkout_url) {
      location.href = reg.checkout_url;
      return;
    }
    document.querySelector('#registerDialog').close();
    // La pagina di ringraziamento dice cosa resta da fare: pagare al banco,
    // caricare la lista.
    location.href = `grazie.html?t=${t.id}`;
  } catch (err) {
    document.querySelector('#regError').textContent = err.message;
    busy(btn, false);
  }
}

/* ── Una lista di "Le mie liste" ─────────────────────────
   Si manda iscrivendosi, nel modulo, o dopo da iscritto: il testo della lista
   salvata va a POST /decklist, come se lo si incollasse in "Le mie iscrizioni". */
let _decks = [];

/** Un menu per ogni lista che il torneo vuole: di solito una, in un evento misto una per porzione. */
function deckPickers(t, first, sent = new Set()) {
  const segments = deckSegments(t);
  return segments.map((seg) => {
    const label = segments.length > 1 ? tr('Lista {formato}', { formato: seg || t.format }) : tr('La tua lista');
    const decks = decksFor(_decks, { format: seg || t.format });
    const empty = sent.has(seg) ? tr('Lascia quella già inviata') : first;
    return `<label>${esc(label)}<select data-segment="${esc(seg)}">${deckOptions(decks, empty)}</select></label>`;
  }).join('');
}

/** Manda le liste scelte nei menu. Dice se una non rispetta le regole del formato. */
async function sendPicked(box, t, headers = {}) {
  let invalid = false;
  for (const select of box.querySelectorAll('select[data-segment]')) {
    const deck = _decks.find((d) => String(d.id) === select.value);
    if (!deck) continue;
    const out = await apiFetch(`/tournaments/${t.id}/decklist`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ raw_text: deck.raw_text, archetype: deck.archetype || '', format: select.dataset.segment }),
    });
    invalid ||= out?.status === 'invalid';
  }
  return { invalid };
}

/** Nel modulo d'iscrizione, se il torneo vuole la lista e chi si iscrive ne ha di salvate. */
async function fillRegDecks(t) {
  const box = document.querySelector('#regDecks');
  const who = document.querySelector('#regWho')?.value || '';
  _decks = t.decklist_required && !t.decklist_locked
    ? decksFor(await apiFetch('/decks', { headers: { 'X-Act-As': who } }).catch(() => []), { game: t.game })
    : [];
  box.style.display = _decks.length ? '' : 'none';
  box.innerHTML = _decks.length
    ? deckPickers(t, tr('Nessuna, la carico dopo'))
      + `<p class="muted-text" style="margin:0">${esc(tr('La puoi cambiare fino alla chiusura delle liste.'))}</p>`
    : '';
}

const deckButtonLabel = (t, reg) => (deckSegments(t).every((seg) => (reg.decklist_formats || []).includes(seg))
  ? tr('Cambia la lista') : tr('Invia la lista'));

/** Da iscritto, accanto a "✓ Iscritto", finché le liste sono aperte. */
function deckButton(t, reg) {
  if (!t.decklist_required || t.decklist_locked || reg.dropped) return '';
  return `<button class="secondary" id="deckSendOpen" type="button">${esc(deckButtonLabel(t, reg))}</button>`;
}

async function openDeckSend(t, reg) {
  const box = document.querySelector('#deckSendPickers');
  const submit = document.querySelector('#deckSendSubmit');
  document.querySelector('#deckSendError').textContent = '';
  box.innerHTML = `<p class="muted-text" style="margin:0">${esc(tr('Caricamento…'))}</p>`;
  submit.disabled = true;
  submit.style.display = '';
  document.querySelector('#deckSendDialog').showModal();
  _decks = decksFor(await apiFetch('/decks').catch(() => []), { game: t.game });
  box.innerHTML = _decks.length
    ? deckPickers(t, tr('— Scegli una lista —'), new Set(reg.decklist_formats || []))
    : `<p class="muted-text" style="margin:0">${esc(tr('Non hai ancora liste salvate.'))}
         <a href="decks.html">${esc(tr('Creane una in Le mie liste'))}</a></p>`;
  submit.disabled = !_decks.length;
  // Spento e acceso hanno lo stesso aspetto: senza liste da mandare non c'è.
  submit.style.display = _decks.length ? '' : 'none';
}

async function submitDeckSend(t, reg) {
  const box = document.querySelector('#deckSendPickers');
  const errEl = document.querySelector('#deckSendError');
  const picked = [...box.querySelectorAll('select[data-segment]')].filter((s) => s.value);
  if (!picked.length) { errEl.textContent = tr('Scegli una lista.'); return; }
  const btn = document.querySelector('#deckSendSubmit');
  busy(btn, true);
  try {
    const { invalid } = await sendPicked(box, t);
    reg.decklist_formats = [...new Set([...(reg.decklist_formats || []), ...picked.map((s) => s.dataset.segment)])];
    document.querySelector('#deckSendDialog').close();
    document.querySelector('#deckSendOpen').textContent = deckButtonLabel(t, reg);
    toast(invalid
      ? tr('Lista inviata, ma non rispetta le regole del formato: controllala in Le mie iscrizioni.')
      : tr('Lista inviata ✓'), invalid ? 7000 : 3200);
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    busy(btn, false);
  }
}

onReady(() => { updateAuthNav(); loadEvent(); });
