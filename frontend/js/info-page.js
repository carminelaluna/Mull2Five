/**
 * info-page.js — Le pagine di servizio (404, privacy, termini, cookie): il menu
 * dell'account e, nei testi legali, i dati di chi gestisce il sito (LEGAL_* sul
 * server) e l'età minima per aprire un account.
 */
import { onReady } from './lang.js';
import { apiGet, esc, updateAuthNav } from './catalog.js';

async function fillLegal() {
  const slots = document.querySelectorAll('[data-legal]');
  const ages = document.querySelectorAll('[data-min-age]');
  if (!slots.length && !ages.length) return;
  const [legal, rules] = await Promise.all([
    slots.length ? apiGet('/site/legal').catch(() => null) : null,
    ages.length ? apiGet('/auth/rules').catch(() => null) : null,
  ]);
  if (legal) {
    slots.forEach((el) => {
      const value = legal[el.dataset.legal];
      if (!value) return;
      if (el.dataset.legal === 'email') el.innerHTML = `<a href="mailto:${esc(value)}">${esc(value)}</a>`;
      else el.textContent = value;
    });
    const todo = document.querySelector('#legalTodo');
    if (todo) todo.hidden = legal.complete;
  }
  if (rules?.min_account_age) ages.forEach((el) => { el.textContent = rules.min_account_age; });
}

onReady(() => {
  updateAuthNav();
  fillLegal();
  // In un'altra lingua, la nota che il testo legale che fa fede è quello italiano.
  const note = document.querySelector('.legal-lang-note');
  if (note) note.hidden = document.documentElement.lang === 'it';
});
