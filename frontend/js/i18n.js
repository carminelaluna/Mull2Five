/**
 * i18n.js — Lingue dell'interfaccia.
 *
 * La chiave è il testo italiano: t('Nuovo annuncio') restituisce la traduzione
 * nella lingua scelta, o il testo stesso se manca. Una stringa non ancora
 * tradotta resta così leggibile invece di diventare un codice, e il sorgente si
 * legge in italiano come prima. I segnaposto si scrivono {nome}:
 * t('Si gioca il {data}', { data }).
 *
 * Il dizionario della lingua scelta si carica una volta, all'avvio della pagina
 * (ready()); l'italiano non ne ha bisogno.
 */
export const LANGUAGES = [
  { code: 'it', label: 'Italiano' },
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
];
const CODES = LANGUAGES.map((l) => l.code);
const STORE_KEY = 'mull2five-lang';

// Vite prepara un file per lingua e carica solo quello che serve.
const DICTIONARIES = import.meta.glob('../locales/*.json');

let current = 'it';
let dictionary = {};

function readStored() {
  try { return localStorage.getItem(STORE_KEY); } catch { return null; }
}

/** La lingua salvata, altrimenti quella del browser se la supportiamo, altrimenti l'italiano. */
export function detectLanguage() {
  const stored = readStored();
  if (CODES.includes(stored)) return stored;
  const browser = (globalThis.navigator?.language || '').slice(0, 2).toLowerCase();
  return CODES.includes(browser) ? browser : 'it';
}

export function getLang() { return current; }

/** Carica il dizionario di `lang` (o di quella rilevata). Da attendere prima di disegnare. */
export async function ready(lang = detectLanguage()) {
  current = CODES.includes(lang) ? lang : 'it';
  dictionary = {};
  if (current !== 'it') {
    const load = DICTIONARIES[`../locales/${current}.json`];
    if (load) dictionary = (await load()).default || {};
  }
  if (globalThis.document?.documentElement) document.documentElement.lang = current;
  return current;
}

/** Cambia lingua e ricarica la pagina: ogni testo viene ridisegnato da capo. */
export function setLang(lang) {
  if (!CODES.includes(lang)) return;
  try { localStorage.setItem(STORE_KEY, lang); } catch { /* storage bloccato: vale per questa pagina */ }
  globalThis.location?.reload();
}

/** Il testo nella lingua corrente, con i segnaposto {nome} sostituiti. */
export function t(text, params) {
  const out = (current !== 'it' && dictionary[text]) || text;
  if (!params) return out;
  return out.replace(/\{(\w+)\}/g, (m, name) => (name in params ? String(params[name]) : m));
}

/**
 * Il testo tradotto se è una frase intera del dizionario, altrimenti com'è; gli
 * spazi attorno restano dove sono. Serve alle stringhe che non passano da t():
 * il markup delle pagine e i template scritti prima delle traduzioni.
 */
export function translateText(text) {
  if (current === 'it' || !text) return text;
  const trimmed = text.trim();
  const found = trimmed && dictionary[trimmed.replace(/\s+/g, ' ')];
  if (!found) return text;
  const start = text.indexOf(trimmed);
  return text.slice(0, start) + found + text.slice(start + trimmed.length);
}

// Dentro questi elementi il testo è di chi scrive (liste, note), non dell'interfaccia.
const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE']);
const ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
const skipped = (el) => SKIP.has(el.tagName) || el.getAttribute('translate') === 'no' || el.isContentEditable;

function translateNode(node) {
  const next = translateText(node.nodeValue);
  if (next !== node.nodeValue) node.nodeValue = next;
}

function translateAttrs(el) {
  for (const name of ATTRS) {
    const value = el.getAttribute(name);
    if (!value) continue;
    const next = translateText(value);
    if (next !== value) el.setAttribute(name, next);
  }
}

/** Traduce i testi e gli attributi (placeholder, title…) che corrispondono a una voce del dizionario. */
export function autoTranslate(root) {
  if (current === 'it' || !root) return;
  if (root.nodeType === 3) { translateNode(root); return; }
  if (root.nodeType !== 1 || skipped(root)) return;
  translateAttrs(root);
  const walker = root.ownerDocument.createTreeWalker(root, 5 /* SHOW_ELEMENT | SHOW_TEXT */, {
    acceptNode: (node) => (node.nodeType === 1 && skipped(node) ? 2 /* FILTER_REJECT */ : 1),
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === 3) translateNode(node);
    else translateAttrs(node);
  }
}

/**
 * Tiene tradotta la pagina: quello che c'è e quello che le pagine disegnano dopo.
 * Una frase già tradotta non è una chiave, quindi le nostre modifiche si fermano lì.
 */
export function watchTranslations(root = globalThis.document?.body) {
  if (current === 'it' || !root) return null;
  autoTranslate(root);
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'childList') record.addedNodes.forEach(autoTranslate);
      else if (record.type === 'characterData') translateNode(record.target);
      else if (record.target.nodeType === 1) translateAttrs(record.target);
    }
  });
  observer.observe(root, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  return observer;
}

/**
 * Traduce il markup statico delle pagine: gli elementi con data-i18n (il testo) e
 * data-i18n-attr="placeholder,title" (gli attributi). Il testo originale resta
 * nell'HTML, così la pagina è italiana anche senza JavaScript.
 */
export function translatePage(root = globalThis.document) {
  if (!root || current === 'it') return;
  root.querySelectorAll('[data-i18n]').forEach((el) => {
    const source = el.dataset.i18nSource || el.textContent.trim();
    el.dataset.i18nSource = source;
    el.textContent = t(source);
  });
  root.querySelectorAll('[data-i18n-attr]').forEach((el) => {
    for (const attr of el.dataset.i18nAttr.split(',').map((a) => a.trim())) {
      const value = el.getAttribute(attr);
      if (value) el.setAttribute(attr, t(value));
    }
  });
}

/** Un selettore di lingua pronto da inserire nell'header. */
export function languageSelect() {
  const select = document.createElement('select');
  select.className = 'lang-select';
  select.setAttribute('aria-label', t('Lingua'));
  for (const { code, label } of LANGUAGES) {
    const option = document.createElement('option');
    option.value = code;
    option.textContent = label;
    option.selected = code === current;
    select.append(option);
  }
  select.addEventListener('change', () => setLang(select.value));
  return select;
}
