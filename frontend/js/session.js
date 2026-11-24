/**
 * session.js — La sessione e le chiamate all'API, in un posto solo.
 *
 * Il token di accesso (JWT) sta nel localStorage sotto TOKEN_KEY. Qui lo si
 * legge, lo si decodifica per sapere chi è collegato, lo si rinnova a metà vita
 * (refreshSession, chiamata da site.js a ogni pagina) e lo si manda all'API.
 * Le pagine usano apiRequest con due scelte:
 *   acting        — per chi gestisce il profilo di un figlio: agisce per lui (X-Act-As);
 *   requireLogin  — senza sessione valida si torna al login, e poi di nuovo qui.
 */
import { actingHeaders } from './acting.js';
import { t as tr } from './i18n.js';

export const TOKEN_KEY = 'mull2five-jwt-v1';
const API = '/api';
// Il token vale tre giorni: dopo mezza giornata se ne chiede uno nuovo.
const REFRESH_AFTER_SECONDS = 12 * 3600;

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* niente da togliere */ }
}

/** Il contenuto del token, senza verificarlo: la verifica la fa il server. */
export function decodeToken(token = getToken()) {
  if (!token) return null;
  try {
    return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return null;
  }
}

/** Chi è collegato (email, ruolo, id), se il token c'è e non è scaduto. */
export function getSession() {
  const payload = decodeToken();
  return payload && payload.exp * 1000 > Date.now() ? payload : null;
}

/* Il login, e al ritorno di nuovo la pagina di adesso. */
export function loginUrl() {
  return `login.html?next=${encodeURIComponent(location.pathname.replace(/^\//, '') + location.search)}`;
}

/** Per le pagine riservate: la sessione, o il login se manca o è scaduta. */
export function requireSession() {
  const session = getSession();
  if (session) return session;
  clearToken();
  location.replace(loginUrl());
  // `location.replace` avvia la navigazione ma non ferma lo script: senza
  // questo il modulo proseguiva con `session` a null, e la riga dopo esplodeva
  // su `.role`, `.email` o `.pid` prima che il browser cambiasse pagina. Chi
  // capitava su una pagina riservata senza essere entrato vedeva una pagina
  // rotta invece dell'invito ad accedere.
  throw new Error('Sessione assente: vado al login');
}

export function logout(to = null) {
  clearToken();
  if (to) location.replace(to);
  else location.reload();
}

/** Il messaggio d'errore del server nella lingua della pagina: una frase, o la lista di FastAPI. */
export function errorText(detail, fallback = '') {
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join(' · ') || fallback;
  return detail ? tr(String(detail)) : fallback;
}

export async function apiRequest(path, { acting = false, requireLogin = false, ...opts } = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(acting && token ? actingHeaders() : {}), ...(opts.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(API + path, { ...opts, headers });
  if (r.status === 401 && requireLogin) {
    clearToken();
    location.replace(loginUrl());
    throw new Error(tr('Sessione scaduta'));
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const err = new Error(errorText(body.detail, r.statusText));
    err.status = r.status;
    throw err;
  }
  return r.status === 204 ? null : r.json();
}

/**
 * La pagina a cui tornare dopo l'accesso, se è una pagina di questo sito.
 * `next` arriva dall'indirizzo: "https://altrove" o "javascript:…" non si seguono.
 */
export function safeNext(value, fallback = '') {
  const next = String(value || '').trim();
  return next.length <= 300 && /^[A-Za-z0-9_-][A-Za-z0-9_\-./?=&%+]*$/.test(next) ? next : fallback;
}

/* ── Accesso con Google ──────────────────────────────────────────────────
   Il giro lo fa il server (routers/google_auth.py): qui si chiede l'indirizzo
   di Google, ci si va, e al ritorno si ritira il token di accesso. Il token
   non passa mai dall'indirizzo: sta in un cookie che solo il server legge. */

/** Accesso o registrazione con Google: porta il browser da Google. */
export async function startGoogleLogin(next = '') {
  const { authorization_url: url } = await apiRequest('/auth/google/start', {
    method: 'POST', body: JSON.stringify({ next: safeNext(next) }),
  });
  location.assign(url);
}

/** Dal profilo: collega Google all'account con cui si è dentro. */
export async function startGoogleLink() {
  const { authorization_url: url } = await apiRequest('/auth/google/link', { method: 'POST', requireLogin: true });
  location.assign(url);
}

/**
 * Di ritorno da Google. Se si entra, salva il token e restituisce la risposta
 * con `access_token`; se l'account è da creare, `signup_email` e `signup_name`.
 */
export async function finishGoogleLogin() {
  const result = await apiRequest('/auth/google/finish', { method: 'POST' });
  if (result.access_token) setToken(result.access_token);
  return result;
}

/** Chi è nuovo: nome, ruolo, età e termini, e l'account nasce. */
export async function completeGoogleSignup(data) {
  const { access_token: token } = await apiRequest('/auth/google/complete', {
    method: 'POST', body: JSON.stringify(data),
  });
  setToken(token);
}

/** Perché l'accesso con Google non è andato, dal codice che il server mette nell'indirizzo. */
export function googleErrorText(code) {
  const texts = {
    annullato: tr('Accesso con Google annullato.'),
    stato: tr("L'accesso con Google è scaduto o è partito da un'altra finestra: riprova."),
    rifiutato: tr("Google non ha confermato l'accesso: riprova."),
    non_verificata: tr('Il tuo indirizzo Google non è verificato: verificalo su Google, o registrati con email e password.'),
    disattivato: tr('Questo account è disattivato.'),
    gia_collegato: tr('Questo account Google è già collegato a un altro account Mull2Five.'),
    altro_google: tr('Al tuo account è già collegato un altro account Google: entra con quello o con la password.'),
    non_disponibile: tr("L'accesso con Google non è attivo."),
  };
  return texts[code] || tr('Accesso con Google non riuscito: riprova.');
}

/**
 * Scarica un file dall'API. Come apiRequest, ma il corpo e un file e non JSON:
 * serve per i CSV che genera il server (il report ufficiale del torneo).
 */
export async function apiDownload(path, filename) {
  const token = getToken();
  const r = await fetch(API + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!r.ok) throw new Error(tr('Download non riuscito'));
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Rinnova il token quando ha più di mezza giornata: chi usa il sito resta
 * collegato, un token rubato scade in pochi giorni. Se il server lo rifiuta
 * (password cambiata, uscita da tutti i dispositivi) la sessione si chiude.
 */
export async function refreshSession(now = Date.now()) {
  const token = getToken();
  const payload = decodeToken(token);
  if (!payload || payload.exp * 1000 <= now) return false;
  if (!payload.iat || now / 1000 - payload.iat < REFRESH_AFTER_SECONDS) return false;
  try {
    const r = await fetch(`${API}/auth/refresh`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
    if (r.status === 401) { clearToken(); return false; }
    if (!r.ok) return false;
    setToken((await r.json()).access_token);
    return true;
  } catch {
    return false;   // offline: si riprova alla prossima pagina
  }
}
