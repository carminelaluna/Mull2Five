/**
 * grazie.js — La pagina dopo l'iscrizione e dopo il pagamento online: cosa è
 * successo, cosa resta da fare (pagare, caricare la lista) e il torneo da
 * mettere in calendario. ?t=ID del torneo; ?pagamento=ok al ritorno da
 * Stripe o PayPal, quando la conferma del pagamento può essere ancora in viaggio.
 */
import { onReady } from './lang.js';
import { actingHeaders } from './acting.js';
import { esc, fmtDate, fmtMoney, getSession, updateAuthNav } from './catalog.js';
import { t as tr } from './i18n.js';

const $ = (s) => document.querySelector(s);
const params = new URLSearchParams(location.search);
const TOURNAMENT_ID = Number(params.get('t')) || 0;
const PAID_ONLINE = params.get('pagamento') === 'ok';

async function api(path) {
  const token = localStorage.getItem('mull2five-jwt-v1');
  const r = await fetch(`/api${path}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...actingHeaders() },
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

/* Il torneo come evento di calendario (.ics): ora locale, quattro ore di durata. */
function icsFile(t) {
  const text = (s) => String(s || '').replace(/\\/g, '\\\\').replace(/[,;]/g, (c) => `\\${c}`).replace(/\n/g, '\\n');
  const pad = (n) => String(n).padStart(2, '0');
  const day = String(t.starts_on).slice(0, 10).replaceAll('-', '');
  const now = new Date();
  const stamp = `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}T${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}00Z`;
  return [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Mull2Five//IT', 'CALSCALE:GREGORIAN', 'BEGIN:VEVENT',
    `UID:torneo-${t.id}@mull2five`, `DTSTAMP:${stamp}`,
    t.start_time ? `DTSTART:${day}T${t.start_time.replace(':', '')}00` : `DTSTART;VALUE=DATE:${day}`,
    t.start_time ? 'DURATION:PT4H' : '',
    `SUMMARY:${text(t.name)}`,
    t.venue ? `LOCATION:${text(t.venue)}` : '',
    `URL:${location.origin}/event.html?id=${t.id}`,
    'END:VEVENT', 'END:VCALENDAR',
  ].filter(Boolean).join('\r\n');
}

function steps(t, reg) {
  const out = [];
  const fee = fmtMoney(t.entry_fee_cents);
  if (reg.waitlisted) {
    out.push(['⏳', tr("Sei in lista d'attesa: se si libera un posto passi tra gli iscritti e te lo diciamo.")]);
  } else if (reg.payment_status === 'paid') {
    out.push(['✓', tr('Quota pagata.')]);
  } else if (PAID_ONLINE) {
    out.push(['✓', tr('Pagamento ricevuto: la conferma arriva tra pochi secondi.')]);
  } else if (t.entry_fee_cents > 0 && (t.pay_stripe || t.pay_paypal)) {
    out.push(['€', tr('Resta da pagare la quota ({quota}): puoi farlo online dalle tue iscrizioni.', { quota: fee }),
      'my-registrations.html', tr('Paga ora')]);
  } else if (t.entry_fee_cents > 0) {
    out.push(['€', tr('La quota ({quota}) si paga al banco il giorno del torneo.', { quota: fee })]);
  }
  if (t.decklist_required && reg.decklist_status === 'missing') {
    out.push(['↑', tr('Carica la tua lista prima del torneo.'), 'my-registrations.html', tr('Carica la lista')]);
  }
  if (t.is_online) out.push(['⌁', tr('Il link della stanza è nelle tue iscrizioni.')]);
  return out;
}

function render(t, reg) {
  const box = $('#thanks');
  box.removeAttribute('aria-busy');
  const heading = reg.waitlisted ? tr("Sei in lista d'attesa") : PAID_ONLINE ? tr('Pagamento ricevuto!') : tr('Sei iscritto!');
  const when = [fmtDate(t.starts_on), t.start_time, t.is_online ? tr('Online') : t.venue].filter(Boolean).join(' · ');
  const list = steps(t, reg).map(([mark, text, href, label]) => `<li>
      <span class="step-mark" aria-hidden="true">${esc(mark)}</span>
      <span class="step-text">${esc(text)}</span>
      ${href ? `<a class="primary step-action" href="${esc(href)}">${esc(label)}</a>` : ''}</li>`).join('');
  box.innerHTML = `
    <div class="thanks-icon${reg.waitlisted ? ' warn' : ''}" aria-hidden="true">${reg.waitlisted ? '⏳' : '✓'}</div>
    <h1>${esc(heading)}</h1>
    <p class="muted" style="margin:0"><strong>${esc(t.name)}</strong> · ${esc(t.format)}</p>
    <p class="muted" style="margin:4px 0 0">${esc(when)}</p>
    ${list ? `<ul class="thanks-steps">${list}</ul>` : ''}
    <div class="hero-cta">
      <a class="primary" href="my-registrations.html">${esc(tr('Le mie iscrizioni'))}</a>
      <a class="secondary" id="icsLink" href="#" download="torneo-${t.id}.ics">${esc(tr('Aggiungi al calendario'))}</a>
      <a class="secondary" href="event.html?id=${t.id}">${esc(tr('Torna al torneo'))}</a>
    </div>`;
  $('#icsLink').href = URL.createObjectURL(new Blob([icsFile(t)], { type: 'text/calendar;charset=utf-8' }));
  document.title = `${heading} — Mull2Five`;
}

function renderMessage(title, text, href, label) {
  const box = $('#thanks');
  box.removeAttribute('aria-busy');
  box.innerHTML = `<div class="thanks-icon" aria-hidden="true">✓</div>
    <h1>${esc(title)}</h1><p class="muted">${esc(text)}</p>
    <div class="hero-cta"><a class="primary" href="${esc(href)}">${esc(label)}</a></div>`;
}

async function load() {
  if (!TOURNAMENT_ID) {
    renderMessage(tr('Grazie!'), tr('Trovi tutte le tue iscrizioni nella tua pagina.'), 'my-registrations.html', tr('Le mie iscrizioni'));
    return;
  }
  if (!getSession()) {
    renderMessage(tr('Grazie!'), tr('Accedi per vedere la tua iscrizione.'), `login.html?next=${encodeURIComponent(location.pathname + location.search)}`, tr('Accedi'));
    return;
  }
  try {
    const [t, reg] = await Promise.all([api(`/tournaments/${TOURNAMENT_ID}`), api(`/tournaments/${TOURNAMENT_ID}/my-registration`)]);
    render(t, reg);
  } catch {
    renderMessage(tr('Grazie!'), tr('Trovi tutte le tue iscrizioni nella tua pagina.'), 'my-registrations.html', tr('Le mie iscrizioni'));
  }
}

onReady(() => {
  updateAuthNav();
  load();
});
