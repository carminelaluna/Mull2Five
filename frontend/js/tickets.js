/**
 * tickets.js — Le segnalazioni: quelle che ho aperto e quelle che ricevo.
 *
 * Due livelli, come il backend: una segnalazione va a chi organizza un torneo
 * oppure a chi tiene il sito. La stessa pagina serve il giocatore ("Le mie") e
 * chi le riceve ("Ricevute"); la scheda "Ricevute" compare solo a chi ne ha.
 */
import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { toast, updateAuthNav } from './catalog.js';
import { esc } from './escape.js';
import { t as tr } from './i18n.js';
import { apiRequest, requireSession } from './session.js';

const session = requireSession();
const $ = (s) => document.querySelector(s);
const apiFetch = (path, opts = {}) => apiRequest(path, { requireLogin: true, ...opts });

const STATI = {
  open: { label: 'In attesa', cls: 'warn' },
  answered: { label: 'Risposta', cls: 'ok' },
  closed: { label: 'Chiusa', cls: '' },
};

let _box = 'mine';
let _tickets = { mine: [], inbox: [] };
let _aperta = null;      // id della segnalazione espansa

const quando = (iso) => new Date(iso).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' });

function messaggio(m) {
  const mio = String(m.author_id) === String(session.sub);
  return `<div class="ticket-msg${mio ? ' mine' : ''}">
    <div class="muted" style="font-size:.78rem">${esc(m.author_name)} · ${esc(quando(m.created_at))}</div>
    <div>${esc(m.body)}</div>
  </div>`;
}

function scheda(t) {
  const stato = STATI[t.status] || STATI.open;
  const aperta = t.id === _aperta;
  return `<article class="panel" style="margin-bottom:12px">
    <div class="tile-meta" style="justify-content:space-between">
      <div>
        <strong>${esc(t.subject)}</strong>
        <div class="muted" style="font-size:.82rem">
          ${esc(t.tournament_name || tr('Segnalazione al sito'))} ·
          ${esc(tr('aperta da'))} ${esc(t.opened_by_name)} · ${esc(quando(t.created_at))}
        </div>
      </div>
      <span class="pill ${stato.cls}">${esc(tr(stato.label))}</span>
    </div>
    <div style="margin-top:10px">
      <button class="mini-button" data-open="${t.id}" type="button">
        ${esc(aperta ? tr('Chiudi conversazione') : tr('Apri conversazione ({n})', { n: t.messages.length }))}
      </button>
    </div>
    ${aperta ? `<div class="ticket-thread">${t.messages.map(messaggio).join('')}
      ${t.status === 'closed'
        ? `<button class="secondary" data-reopen="${t.id}" type="button">${esc(tr('Riapri'))}</button>`
        : `<label>${esc(tr('Rispondi'))}<textarea data-reply="${t.id}" maxlength="4000" style="min-height:90px"></textarea></label>
           <div class="row-actions">
             <button class="primary" data-send="${t.id}" type="button">${esc(tr('Invia'))}</button>
             <button class="secondary" data-close="${t.id}" type="button">${esc(tr('Chiudi la segnalazione'))}</button>
           </div>`}
    </div>` : ''}
  </article>`;
}

function render() {
  const lista = _tickets[_box];
  $('#ticketList').innerHTML = lista.length
    ? lista.map(scheda).join('')
    : `<p class="empty">${esc(_box === 'mine'
        ? tr('Non hai aperto nessuna segnalazione.')
        : tr('Nessuna segnalazione ricevuta.'))}</p>`;
  document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.box === _box));
}

async function load() {
  const [mine, inbox] = await Promise.all([
    apiFetch('/tickets/mine').catch(() => []),
    apiFetch('/tickets/inbox').catch(() => []),
  ]);
  _tickets = { mine: mine || [], inbox: inbox || [] };
  // La scheda "Ricevute" esiste solo per chi organizza o tiene il sito.
  $('[data-box="inbox"]').hidden = !_tickets.inbox.length;
  render();
}

async function azione(id, path, body) {
  try {
    await apiFetch(`/tickets/${id}${path}`, body ? { method: 'POST', body: JSON.stringify(body) } : { method: 'POST' });
    await load();
  } catch (err) { toast(err.message); }
}

async function openDialog() {
  $('#tkError').textContent = '';
  $('#tkSubject').value = '';
  $('#tkBody').value = '';
  const miei = await apiFetch('/tournaments/me/registrations').catch(() => []);
  const scelte = (miei || []).map((r) => r.tournament);
  $('#tkTournament').innerHTML = scelte.length
    ? scelte.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('')
    : `<option value="">${esc(tr('Nessun torneo a cui sei iscritto'))}</option>`;
  // Senza tornei resta solo la segnalazione al sito: non c'è un organizzatore a cui scrivere.
  $('#tkScope').value = scelte.length ? 'organizer' : 'admin';
  syncScope();
  $('#ticketDialog').showModal();
}

function syncScope() {
  $('#tkTournamentRow').style.display = $('#tkScope').value === 'organizer' ? '' : 'none';
}

async function send() {
  const scope = $('#tkScope').value;
  const body = {
    scope,
    subject: $('#tkSubject').value.trim(),
    body: $('#tkBody').value.trim(),
    tournament_id: scope === 'organizer' ? Number($('#tkTournament').value) || null : null,
  };
  if (body.subject.length < 3 || body.body.length < 3) {
    $('#tkError').textContent = tr('Scrivi un oggetto e cosa è successo.');
    return;
  }
  try {
    await apiFetch('/tickets', { method: 'POST', body: JSON.stringify(body) });
    $('#ticketDialog').close();
    toast(tr('Segnalazione inviata.'));
    _box = 'mine';
    await load();
  } catch (err) { $('#tkError').textContent = err.message; }
}

onReady(async () => {
  updateAuthNav();
  $('#newTicket').addEventListener('click', openDialog);
  $('#tkScope').addEventListener('change', syncScope);
  $('#tkSend').addEventListener('click', send);
  $('#ticketTabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    _box = tab.dataset.box;
    _aperta = null;
    render();
  });
  $('#ticketList').addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.dataset.open) {
      _aperta = _aperta === +btn.dataset.open ? null : +btn.dataset.open;
      render();
    } else if (btn.dataset.send) {
      const testo = document.querySelector(`[data-reply="${btn.dataset.send}"]`).value.trim();
      if (testo) azione(btn.dataset.send, '/messages', { body: testo });
    } else if (btn.dataset.close) {
      azione(btn.dataset.close, '/close');
    } else if (btn.dataset.reopen) {
      azione(btn.dataset.reopen, '/reopen');
    }
  });
  await load();
});
