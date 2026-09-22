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
  if (!session) {
    clearToken();
    location.replace(loginUrl());
  }
  return session;
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
