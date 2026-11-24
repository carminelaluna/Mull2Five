/**
 * qr.js — Il QR che porta all'iscrizione di un torneo, pronto da stampare.
 *
 * Lo apre l'organizzatore dal back-office ("QR iscrizione"). Il disegno lo fa
 * il server (`/api/tournaments/{id}/registration-qr.svg`), che conosce
 * l'indirizzo pubblico del sito: qui si impagina il foglio — nome, data, luogo,
 * codice — e la stampa tiene solo quello.
 */
import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { apiGet, esc, fmtDate, placeLabel, toast, updateAuthNav } from './catalog.js';
import { t as tr } from './i18n.js';

const $ = (s) => document.querySelector(s);

/** L'indirizzo che il QR contiene: la pagina del torneo con l'iscrizione aperta. */
function registrationLink(origin, id) {
  return `${origin.replace(/\/$/, '')}/event.html?id=${encodeURIComponent(id)}&iscriviti=1`;
}

async function copyLink(link) {
  try {
    await navigator.clipboard.writeText(link);
    toast(tr('Link copiato'));
  } catch {
    // Senza permesso sugli appunti: si seleziona il testo, e lo si copia a mano.
    getSelection().selectAllChildren($('#qrUrl'));
    toast(tr('Seleziona il link e copialo'));
  }
}

async function load() {
  const id = new URLSearchParams(location.search).get('t');
  const page = $('#qrPage');
  if (!id) { page.innerHTML = `<p class="empty">${esc(tr('Torneo non indicato.'))}</p>`; return; }

  let t;
  try { t = await apiGet(`/tournaments/${encodeURIComponent(id)}`); }
  catch (err) { page.innerHTML = `<p class="empty">${esc(err.message)}</p>`; return; }

  const link = registrationLink(location.origin, t.id);
  const qr = `/api/tournaments/${t.id}/registration-qr`;
  document.title = `${t.name} — ${tr('QR iscrizione')}`;
  $('#qrName').textContent = t.name;
  $('#qrWhen').textContent = [t.format, fmtDate(t.starts_on), t.start_time].filter(Boolean).join(' · ');
  $('#qrWhere').textContent = [t.organization_name, t.is_online ? tr('Online') : placeLabel(t)]
    .filter(Boolean).join(' — ');
  $('#qrImage').src = `${qr}.svg`;
  $('#qrUrl').textContent = link.replace(/^https?:\/\//, '');
  $('#qrPng').href = `${qr}.png?download=1`;
  $('#qrSvg').href = `${qr}.svg?download=1`;
  $('#qrPrint').addEventListener('click', () => print());
  $('#qrCopy').addEventListener('click', () => copyLink(link));
  $('#qrTools').hidden = false;
  $('#qrPoster').hidden = false;
}

onReady(() => { updateAuthNav(); load(); });
