/**
 * push.js — Web Push lato browser.
 * Registra il service worker, ottiene la chiave VAPID dal backend, si iscrive
 * e invia la subscription a /api/push/subscribe. No-op se il browser non supporta
 * le notifiche o se il backend non ha VAPID configurato.
 */
import { getToken } from './session.js';

export function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export function pushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

async function authFetch(path, opts = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch('/api' + path, { ...opts, headers });
}

/** Stato attuale: 'unsupported' | 'disabled' (no VAPID) | 'denied' | 'subscribed' | 'default' */
export async function pushStatus() {
  if (!pushSupported()) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  try {
    const r = await authFetch('/push/vapid-key');
    const { enabled } = await r.json();
    if (!enabled) return 'disabled';
  } catch {
    return 'disabled';
  }
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = reg && (await reg.pushManager.getSubscription());
  return sub ? 'subscribed' : 'default';
}

/** Attiva le notifiche push. Ritorna true se sottoscritto con successo. */
export async function enablePush() {
  if (!pushSupported()) return false;
  const keyResp = await authFetch('/push/vapid-key');
  const { public_key: publicKey, enabled } = await keyResp.json();
  if (!enabled || !publicKey) return false;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return false;

  const reg =
    (await navigator.serviceWorker.getRegistration()) ||
    (await navigator.serviceWorker.register('/sw.js'));

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
  }
  const json = sub.toJSON();
  const resp = await authFetch('/push/subscribe', {
    method: 'POST',
    body: JSON.stringify({ endpoint: sub.endpoint, keys: json.keys }),
  });
  return resp.ok;
}

/** Disattiva le notifiche push su questo browser. */
export async function disablePush() {
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = reg && (await reg.pushManager.getSubscription());
  if (!sub) return true;
  await authFetch('/push/unsubscribe', {
    method: 'POST',
    body: JSON.stringify({ endpoint: sub.endpoint }),
  });
  await sub.unsubscribe();
  return true;
}
