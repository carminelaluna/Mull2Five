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
import { refreshSession } from './session.js';

const NOTICE_KEY = 'mull2five-privacy-notice-v1';

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
  countVisit();
  privacyNotice();
  refreshSession();   // il token si rinnova da solo finché si usa il sito
  // Le pagine con una CTA fissa nell'HTML la segnano con data-sticky-cta.
  const marked = document.querySelector('[data-sticky-cta]');
  if (marked) stickyCta(marked);
});
