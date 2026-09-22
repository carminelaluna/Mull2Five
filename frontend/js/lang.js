/**
 * lang.js — La prima cosa di ogni pagina: la lingua dell'interfaccia.
 *
 * Carica il dizionario della lingua scelta (i18n.js) e, grazie al top-level
 * await, le pagine che lo importano per primo partono a dizionario pronto: le
 * loro t() escono già tradotte. Il resto — il markup delle pagine, i template
 * scritti in italiano, le finestre di conferma — lo traduce watchTranslations
 * quando il testo è una frase intera del dizionario. Mette anche il selettore
 * della lingua nell'header.
 */
import { languageSelect, ready, translateText, watchTranslations } from './i18n.js';

await ready();

// confirm(), alert() e prompt() mostrano il testo del browser: passano dal dizionario anche loro.
for (const name of ['alert', 'confirm', 'prompt']) {
  const native = globalThis[name]?.bind(globalThis);
  if (native) globalThis[name] = (message, ...rest) => native(translateText(String(message ?? '')), ...rest);
}

function mount() {
  document.title = translateText(document.title);
  watchTranslations(document.body);
  const header = document.querySelector('.public-header');
  if (header && !header.querySelector('.lang-select')) header.append(languageSelect());
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
else mount();

/**
 * Per le pagine: fn appena il documento è pronto. Con il top-level await qui
 * sopra il loro codice gira quando DOMContentLoaded è già passato, e un loro
 * listener su quell'evento non scatterebbe mai.
 */
export function onReady(fn) {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn, { once: true });
  else fn();
}
