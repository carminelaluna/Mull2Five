/**
 * acting.js — Per chi sta agendo la pagina: l'account, o il profilo di un minore
 * che l'account gestisce. Il server lo sa dall'intestazione X-Act-As e la
 * accetta solo dal genitore di quel profilo.
 */
import { esc } from './escape.js';
import { t } from './i18n.js';

const KEY = 'mull2five-act-as';

export function actingAs() {
  try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; }
}

export function setActing(profile) {
  try {
    if (profile) localStorage.setItem(KEY, JSON.stringify({ id: +profile.id, name: profile.name }));
    else localStorage.removeItem(KEY);
  } catch { /* senza storage si resta l'account */ }
}

export function actingHeaders() {
  const who = actingAs();
  return who ? { 'X-Act-As': String(who.id) } : {};
}

/** La striscia che ricorda per chi si sta agendo, con "Torna a te". */
export function actingBanner() {
  const who = actingAs();
  if (!who) return '';
  return `<div class="acting-banner">
    <span>${esc(t('Stai gestendo il profilo di {nome}', { nome: who.name }))}</span>
    <button class="secondary" type="button" data-stop-acting>${esc(t('Torna a te'))}</button>
  </div>`;
}

export function bindActingBanner(root = document) {
  root.querySelectorAll('[data-stop-acting]').forEach((b) => b.addEventListener('click', () => {
    setActing(null);
    location.reload();
  }));
}
