import { vi, beforeEach } from 'vitest';
import 'fake-indexeddb/auto';   /* Polyfill IDB per JSDOM — deve essere il primo import */

/* ── Mock localStorage ──────────────────────────────── */
let _store = {};
const localStorageMock = {
  getItem:    (k)    => _store[k] ?? null,
  setItem:    (k, v) => { _store[k] = String(v); },
  removeItem: (k)    => { delete _store[k]; },
  clear:      ()     => { _store = {}; },
  get length()       { return Object.keys(_store).length; },
  key:        (i)    => Object.keys(_store)[i] ?? null,
};
Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  writable: true,
  configurable: true,
});

/* ── Mock location (previene auto-redirect di auth.js) ─ */
Object.defineProperty(globalThis, 'location', {
  value: { pathname: '/login.html', replace: vi.fn(), href: 'http://localhost/login.html' },
  writable: true,
  configurable: true,
});

/* ── Mock crypto.randomUUID ─────────────────────────── */
let _uuid = 0;
Object.defineProperty(globalThis, 'crypto', {
  value: { randomUUID: () => `test-uuid-${String(++_uuid).padStart(3, '0')}` },
  writable: true,
  configurable: true,
});

/* ── Mock navigator.storage (IDB size estimate) ──────── */
Object.defineProperty(globalThis, 'navigator', {
  value: {
    storage: { estimate: async () => ({ usage: 0, quota: 5 * 1024 * 1024 * 1024 }) },
  },
  writable: true,
  configurable: true,
});

/* ── Reset tra ogni test ────────────────────────────── */
beforeEach(() => {
  _store = {};
  _uuid  = 0;
  vi.clearAllMocks();
  /* Resetta fake-indexeddb tra i test */
  if (globalThis.indexedDB?.deleteDatabase) {
    globalThis.indexedDB.deleteDatabase('arcana-events-db');
  }
});
