/**
 * inbox.js — La campanella in alto: lo storico delle notifiche, in un menu a tendina.
 *
 * Il server salva il tipo e i pezzi della frase (services/inbox.py); la frase la
 * scrive phrase(), nella lingua di chi legge. Aprire il menu le segna come viste:
 * il numero sparisce, e quelle nuove restano evidenziate finché il menu è aperto.
 *
 * La monta site.js su ogni pagina pubblica, a chi è collegato. Il numero lo
 * richiede ogni tanto, e solo con la pagina in vista.
 */
import { esc } from './escape.js';
import { getLang, t as tr } from './i18n.js';
import { apiRequest, getSession } from './session.js';

const PAGE = 30;
const POLL_MS = 90_000;

const BELL = `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>`;

function money(detail) {
  const [amount, currency] = String(detail).split(' ');
  const value = Number(amount);
  if (!currency || Number.isNaN(value)) return detail;
  try {
    return new Intl.NumberFormat(getLang(), { style: 'currency', currency }).format(value);
  } catch {
    return detail;
  }
}

/** La riga in grassetto di una notifica, dal suo tipo. */
export function phrase(n) {
  const d = n.detail || '';
  switch (n.kind) {
    case 'registered': return tr('Iscrizione confermata');
    case 'waitlisted': return tr("Sei in lista d'attesa");
    case 'waitlist_in': return d ? tr('Si è liberato un posto: paga entro {ore} ore', { ore: d })
      : tr('Si è liberato un posto: sei iscritto');
    case 'paid': return tr('Pagamento ricevuto: {importo}', { importo: money(d) });
    case 'reminder': return d ? tr('Si gioca domani alle {ora}', { ora: d }) : tr('Si gioca domani');
    case 'started': return tr('Il torneo è iniziato');
    case 'pairings': return tr('Turno {turno}: abbinamenti pronti', { turno: d });
    case 'announcement': return tr('Nuovo annuncio');
    case 'cancelled':
      if (d === 'refunded') return tr('Torneo annullato: il rimborso è partito');
      if (d === 'requested') return tr('Torneo annullato: il rimborso lo fa il negozio');
      return tr('Torneo annullato');
    case 'ticket_new': return tr('Nuova segnalazione');
    case 'ticket_reply': return tr('Nuova risposta a una segnalazione');
    default: return tr('Notifica');
  }
}

/** Quando, detto come lo si dice: "5 min fa", "ieri", poi la data. */
export function timeAgo(iso, now = Date.now()) {
  const then = new Date(iso).getTime();
  const minutes = Math.max(0, Math.round((now - then) / 60_000));
  if (minutes < 1) return tr('adesso');
  if (minutes < 60) return tr('{n} min fa', { n: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return tr('{n} ore fa', { n: hours });
  if (hours < 48) return tr('ieri');
  return new Date(iso).toLocaleDateString(getLang(), { day: 'numeric', month: 'short' });
}

function itemHtml(n) {
  const where = [n.context, n.title].filter(Boolean).join(' · ');
  const inner = `<span class="inbox-line"><strong>${esc(phrase(n))}</strong>
      <time datetime="${esc(n.created_at)}">${esc(timeAgo(n.created_at))}</time></span>
    ${where ? `<span class="inbox-where">${esc(where)}</span>` : ''}
    ${n.body ? `<span class="inbox-body">${esc(n.body)}</span>` : ''}
    ${n.for_name ? `<span class="inbox-for">${esc(tr('Per {nome}', { nome: n.for_name }))}</span>` : ''}`;
  const cls = `inbox-item${n.read ? '' : ' unread'}`;
  // Solo percorsi del sito: l'url lo scrive il server, ma un link resta un link.
  return n.url && n.url.startsWith('/') && !n.url.startsWith('//')
    ? `<a class="${cls}" href="${esc(n.url)}">${inner}</a>`
    : `<div class="${cls}">${inner}</div>`;
}

export function mountInbox(header = document.querySelector('.public-header')) {
  if (!header || !getSession() || header.querySelector('.inbox')) return;

  const wrap = document.createElement('div');
  wrap.className = 'inbox';
  wrap.innerHTML = `<button class="inbox-bell" type="button" aria-haspopup="true" aria-expanded="false"
      aria-controls="inboxPanel" title="${esc(tr('Notifiche'))}">${BELL}<span class="inbox-count" hidden></span></button>`;
  header.insertBefore(wrap, header.querySelector('.lang-select'));
  const bell = wrap.querySelector('.inbox-bell');
  const count = wrap.querySelector('.inbox-count');

  // Il pannello sta nel body: l'header ha backdrop-filter, e dentro di lui
  // position: fixed si misurerebbe dall'header invece che dalla finestra.
  const panel = document.createElement('section');
  panel.className = 'inbox-panel';
  panel.id = 'inboxPanel';
  panel.hidden = true;
  panel.setAttribute('aria-label', tr('Notifiche'));
  panel.innerHTML = `<header><h2>${esc(tr('Notifiche'))}</h2></header>
    <div class="inbox-list" data-list></div>
    <button class="secondary inbox-more" type="button" data-more hidden>${esc(tr('Mostra le precedenti'))}</button>`;
  document.body.append(panel);
  const list = panel.querySelector('[data-list]');
  const more = panel.querySelector('[data-more]');
  let loaded = 0;

  const showCount = (unread) => {
    count.hidden = !unread;
    count.textContent = unread > 99 ? '99+' : String(unread);
    bell.setAttribute('aria-label', unread
      ? tr('Notifiche: {n} da leggere', { n: unread }) : tr('Notifiche'));
  };

  const refresh = async () => {
    if (document.visibilityState !== 'visible' || !getSession()) return;
    try {
      showCount((await apiRequest('/notifications/unread')).unread);
    } catch { /* la campanella resta com'era */ }
  };

  const place = () => {
    const box = bell.getBoundingClientRect();
    panel.style.top = `${Math.round(box.bottom + 10)}px`;
    // clientWidth e non innerWidth: la barra di scorrimento non è spazio della pagina.
    panel.style.right = `${Math.max(8, Math.round(document.documentElement.clientWidth - box.right))}px`;
  };

  const load = async (offset) => {
    try {
      const page = await apiRequest(`/notifications?limit=${PAGE}&offset=${offset}`);
      if (!offset && !page.items.length) {
        list.innerHTML = `<p class="inbox-empty">${esc(tr('Nessuna notifica, per ora.'))}</p>`;
      } else {
        list.insertAdjacentHTML('beforeend', page.items.map(itemHtml).join(''));
      }
      loaded = offset + page.items.length;
      more.hidden = page.items.length < PAGE;
      // Aperte vuol dire viste: il numero va a zero, l'evidenza resta finché si guarda.
      if (page.unread) showCount((await apiRequest('/notifications/read', { method: 'POST', body: '{}' })).unread);
    } catch {
      if (!offset) list.innerHTML = `<p class="inbox-empty">${esc(tr('Le notifiche non si sono potute caricare.'))}</p>`;
    }
  };

  const close = (focusBell = false) => {
    if (panel.hidden) return;
    panel.hidden = true;
    bell.setAttribute('aria-expanded', 'false');
    removeEventListener('resize', place);
    if (focusBell) bell.focus();
  };

  const open = () => {
    list.innerHTML = '';
    more.hidden = true;
    place();
    panel.hidden = false;
    bell.setAttribute('aria-expanded', 'true');
    addEventListener('resize', place);
    load(0);
  };

  bell.addEventListener('click', () => (panel.hidden ? open() : close()));
  more.addEventListener('click', () => load(loaded));
  document.addEventListener('click', (e) => {
    if (!panel.hidden && !panel.contains(e.target) && !wrap.contains(e.target)) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close(true);
  });
  document.addEventListener('visibilitychange', refresh);
  setInterval(refresh, POLL_MS);
  refresh();
}
