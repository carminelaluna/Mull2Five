/**
 * site.js — Quello che serve a ogni pagina pubblica, oltre alla lingua.
 *
 * - Le visite: una richiesta a /api/analytics/hit con pagina, sito di
 *   provenienza e larghezza dello schermo. Niente cookie né identificativi, e
 *   chi ha Do Not Track o Global Privacy Control non viene contato.
 * - L'avviso sulla privacy, una volta sola: il sito usa solo archiviazione
 *   tecnica, quindi è un avviso e non una richiesta di consenso (cookie.html).
 * - La CTA fissa in basso sul telefono (stickyCta), quando quella della pagina
 *   esce dallo schermo.
 */
import { onReady } from './lang.js';
import { esc } from './escape.js';
import { t as tr } from './i18n.js';
import { getSession, refreshSession } from './session.js';

const NOTICE_KEY = 'mull2five-privacy-notice-v1';
// Finché il sito è in prova lo dice in cima a ogni pagina.
// Quando non lo è più: false, e la striscia sparisce da tutto il sito.
const TESTING = true;

/* L'altezza la misura il browser: sul telefono la frase va a capo, e header e
   filtri devono scendere di altrettanto. */
function testingBanner() {
  if (!TESTING) return;
  const bar = document.createElement('div');
  bar.className = 'testing-banner';
  bar.textContent = tr('Sito in testing: puoi trovare errori o pagine incomplete.');
  document.body.prepend(bar);
  const measure = () => document.documentElement.style.setProperty('--testing-h', `${bar.offsetHeight}px`);
  measure();
  addEventListener('resize', measure);
}

/* L'header prova quattro disposizioni, dalla più larga: tutto in una riga; in una
   riga ma senza l'email; il menu su una riga sua; anche i link del profilo su una
   riga loro. Se ne sceglie una
   misurando, non con una larghezza fissa, perché lingue e link cambiano lo spazio
   che serve: in tedesco e da collegati ne serve molto di più. */
function fitHeader() {
  const header = document.querySelector('.public-header');
  if (!header) return;
  const overflows = () => {
    if (header.scrollWidth > header.clientWidth + 1) return true;
    // Nella seconda disposizione la prima riga non deve andare a capo.
    const row = [...header.children].filter((el) => !el.matches('.public-nav') && el.offsetParent);
    const top = Math.min(...row.map((el) => el.getBoundingClientRect().bottom));
    return row.some((el) => el.getBoundingClientRect().top >= top);
  };
  const fit = () => {
    header.classList.remove('is-tight', 'is-stacked', 'is-compact');
    if (overflows()) header.classList.add('is-tight');
    if (overflows()) header.classList.add('is-stacked');
    if (overflows()) header.classList.add('is-compact');
  };
  fit();
  addEventListener('resize', fit);
  // I link del profilo arrivano dopo, e cambiano con la lingua.
  new MutationObserver(fit).observe(header, { childList: true, subtree: true, characterData: true });
  document.fonts?.ready.then(fit);
}

/* Il back-office non è per chi gioca: a un giocatore la voce "Organizza" non
   compare nemmeno. A chi non è collegato resta, perché lì è un invito. */
function hideOrganizerNav() {
  const s = getSession();
  if (!s || s.role === 'organizer' || s.role === 'admin') return;
  document.querySelectorAll('.public-nav a[href="organizer.html"]').forEach((a) => a.remove());
}

function countVisit() {
  if (navigator.doNotTrack === '1' || window.doNotTrack === '1' || navigator.globalPrivacyControl) return;
  const body = JSON.stringify({ path: location.pathname, referrer: document.referrer, width: window.innerWidth });
  try {
    if (navigator.sendBeacon?.('/api/analytics/hit', new Blob([body], { type: 'application/json' }))) return;
  } catch { /* si riprova con fetch */ }
  fetch('/api/analytics/hit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true })
    .catch(() => {});
}

/* L'altezza dell'avviso sposta in su la CTA fissa, che altrimenti ci finisce sotto. */
function setNoticeHeight(px) {
  document.documentElement.style.setProperty('--notice-h', `${px}px`);
}

function privacyNotice() {
  try {
    if (localStorage.getItem(NOTICE_KEY)) return;
  } catch { return; }
  const bar = document.createElement('div');
  bar.className = 'privacy-notice';
  bar.setAttribute('role', 'region');
  bar.setAttribute('aria-label', tr('Privacy'));
  bar.innerHTML = `<p>${esc(tr('Usiamo solo archiviazione tecnica (accesso e preferenze) e statistiche anonime senza cookie. Nessuna profilazione.'))}
      <a href="/cookie.html">${esc(tr('Dettagli'))}</a></p>
    <button class="primary" type="button">${esc(tr('Ho capito'))}</button>`;
  bar.querySelector('button').addEventListener('click', () => {
    try { localStorage.setItem(NOTICE_KEY, '1'); } catch { /* resta per questa pagina */ }
    bar.remove();
    setNoticeHeight(0);
  });
  document.body.append(bar);
  setNoticeHeight(bar.offsetHeight + 16);
}

/**
 * La CTA della pagina ripetuta in una barra fissa in basso, sul telefono,
 * quando l'originale è uscita dallo schermo verso l'alto. Un link si copia;
 * un pulsante si copia e il clic passa all'originale, che ha già il suo
 * comportamento.
 */
let _sticky = null;
export function stickyCta(source) {
  _sticky?.remove();
  _sticky = null;
  if (!source) return;
  const bar = document.createElement('div');
  bar.className = 'sticky-cta';
  const copy = document.createElement(source.tagName === 'A' ? 'a' : 'button');
  copy.className = 'primary';
  copy.textContent = source.textContent.trim();
  if (source.tagName === 'A') {
    copy.href = source.href;
    if (source.target) copy.target = source.target;
    if (source.rel) copy.rel = source.rel;
  } else {
    copy.type = 'button';
    copy.addEventListener('click', () => source.click());
  }
  bar.append(copy);
  document.body.append(bar);
  _sticky = bar;
  new IntersectionObserver(([entry]) => {
    bar.classList.toggle('show', !entry.isIntersecting && entry.boundingClientRect.top < 0);
  }).observe(source);
}

onReady(() => {
  testingBanner();
  hideOrganizerNav();
  fitHeader();
  countVisit();
  privacyNotice();
  refreshSession();   // il token si rinnova da solo finché si usa il sito
  // Le pagine con una CTA fissa nell'HTML la segnano con data-sticky-cta.
  const marked = document.querySelector('[data-sticky-cta]');
  if (marked) stickyCta(marked);
});
