/**
 * i18n.js — internazionalizzazione leggera per la SPA pubblica.
 *
 * Uso:
 *   import { initI18n, t, setLang } from './i18n.js';
 *   initI18n();            // traduce gli elementi [data-i18n] e monta il selettore
 *   t('nav.tournaments');  // stringa tradotta nella lingua corrente
 *
 * La lingua è persistita in localStorage ('arcana-lang'); default dal browser → it.
 */
const STORE_KEY = 'arcana-lang';

const DICT = {
  it: {
    'nav.tournaments': 'Tornei',
    'nav.leaderboard': 'Classifica stagionale',
    'nav.my': 'Le mie iscrizioni',
    'nav.organize': 'Organizza',
    'auth.login': 'Accedi',
    'auth.register': 'Registrati',
    'auth.logout': 'Esci',
    'home.eyebrow': 'MTG Tournament Platform',
    'home.title': 'Trova e partecipa ai tornei Magic vicino a te.',
    'home.subtitle': "Iscriviti, paga l'entry fee, carica la decklist e segui i tuoi pairings — tutto in un posto.",
    'search.name': 'Nome torneo…',
    'search.allFormats': 'Tutti i formati',
    'search.city': 'Città…',
    'search.submit': 'Cerca',
    'events.empty': 'Nessun torneo trovato.',
    'push.enable': '🔔 Attiva notifiche',
    'push.disable': '🔕 Disattiva notifiche',
    'history.title': 'Storico tornei',
    'history.empty': 'Nessun torneo concluso ancora.',
  },
  en: {
    'nav.tournaments': 'Tournaments',
    'nav.leaderboard': 'Season standings',
    'nav.my': 'My registrations',
    'nav.organize': 'Organize',
    'auth.login': 'Sign in',
    'auth.register': 'Sign up',
    'auth.logout': 'Sign out',
    'home.eyebrow': 'MTG Tournament Platform',
    'home.title': 'Find and join Magic tournaments near you.',
    'home.subtitle': 'Register, pay the entry fee, upload your decklist and follow your pairings — all in one place.',
    'search.name': 'Tournament name…',
    'search.allFormats': 'All formats',
    'search.city': 'City…',
    'search.submit': 'Search',
    'events.empty': 'No tournaments found.',
    'push.enable': '🔔 Enable notifications',
    'push.disable': '🔕 Disable notifications',
    'history.title': 'Tournament history',
    'history.empty': 'No completed tournaments yet.',
  },
};

let _lang = 'it';

function detectLang() {
  const saved = localStorage.getItem(STORE_KEY);
  if (saved && DICT[saved]) return saved;
  const nav = (navigator.language || 'it').slice(0, 2);
  return DICT[nav] ? nav : 'it';
}

export function getLang() { return _lang; }

export function t(key) {
  return (DICT[_lang] && DICT[_lang][key]) || (DICT.it[key]) || key;
}

/** Traduce tutti gli elementi con data-i18n (testo) e data-i18n-attr (placeholder ecc.). */
export function applyTranslations(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  root.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
    el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
  });
  document.documentElement.lang = _lang;
}

export function setLang(lang) {
  if (!DICT[lang]) return;
  _lang = lang;
  localStorage.setItem(STORE_KEY, lang);
  applyTranslations();
  document.dispatchEvent(new CustomEvent('langchange', { detail: { lang } }));
}

/** Monta un piccolo selettore IT/EN nell'header (se presente) e applica le traduzioni. */
export function initI18n() {
  _lang = detectLang();
  applyTranslations();
  const header = document.querySelector('.public-header .public-auth') || document.querySelector('.public-header');
  if (header && !document.querySelector('#langSwitch')) {
    const wrap = document.createElement('div');
    wrap.id = 'langSwitch';
    wrap.style.cssText = 'display:inline-flex;gap:4px;margin-left:8px';
    for (const code of ['it', 'en']) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = code.toUpperCase();
      b.className = 'secondary-link';
      b.style.cssText = 'padding:2px 6px;font-size:.78rem;opacity:' + (code === _lang ? '1' : '.5');
      b.addEventListener('click', () => {
        setLang(code);
        wrap.querySelectorAll('button').forEach((x) => {
          x.style.opacity = x.textContent.toLowerCase() === code ? '1' : '.5';
        });
      });
      wrap.appendChild(b);
    }
    header.appendChild(wrap);
  }
}
