/**
 * Service Worker — Manabind (item 15: PWA offline)
 * Strategia: cache-first per asset statici, network-first per API.
 * In produzione (npm run build) usa vite-plugin-pwa per gestione
 * automatica dei file con hash. Questo SW è ottimizzato per dev/server locale.
 */

const CACHE = 'manabind-v1';

const STATIC = [
  '/', '/index.html', '/login.html', '/event.html', '/my-registrations.html',
  '/leaderboard.html', '/player.html', '/organizer.html', '/control.html',
  '/styles.css', '/app.css', '/manifest.json', '/icons/icon.svg',
  '/js/app.js', '/js/login-public.js', '/js/event.js', '/js/my-registrations.js',
  '/js/player.js', '/js/organizer.js', '/js/control.js', '/js/i18n.js', '/js/push.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  /* API calls: network-first, fallback offline message */
  if (url.pathname.startsWith('/api/') || url.hostname !== location.hostname) {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(JSON.stringify({ detail: 'Offline — dati non disponibili.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } })
      )
    );
    return;
  }

  /* Static assets: cache-first, update in background */ // (push handlers sotto)
  e.respondWith(
    caches.match(e.request).then(cached => {
      const network = fetch(e.request).then(resp => {
        if (resp.ok) caches.open(CACHE).then(c => c.put(e.request, resp.clone()));
        return resp;
      });
      return cached || network;
    })
  );
});


/* ── Web Push ───────────────────────────────────────────
   Riceve le notifiche dal backend (annunci, nuovi round) e le mostra anche
   quando la tab è chiusa. Il click apre/focalizza l'app sulla URL indicata. */
self.addEventListener('push', e => {
  let data = { title: 'Manabind', body: '', url: '/my-registrations.html' };
  try { data = { ...data, ...(e.data ? e.data.json() : {}) }; } catch { /* payload non-JSON */ }
  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/icons/icon.svg',
      badge: '/icons/icon.svg',
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if (c.url.includes(target) && 'focus' in c) return c.focus();
      }
      return self.clients.openWindow(target);
    })
  );
});
