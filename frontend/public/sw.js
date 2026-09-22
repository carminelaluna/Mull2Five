/**
 * Service Worker — Mull2Five.
 * Strategia: le pagine HTML dalla rete (la cache solo da offline), cosi' dopo
 * un aggiornamento non si vede la versione vecchia; i file con l'hash nel nome
 * (/assets/) dalla cache, perche' a ogni build cambiano nome; l'API dalla rete.
 * Riceve anche le notifiche Web Push.
 */

const CACHE = 'mull2five-v2';   // nuova versione: le pagine in cache si riscaricano

/* Solo file che hanno lo stesso nome in sviluppo e nella build. JS e CSS nella
   build prendono un nome con l'hash (/assets/...): finiscono in cache al primo
   uso, dal gestore fetch qui sotto. */
const STATIC = [
  '/', '/index.html', '/login.html', '/event.html', '/my-registrations.html',
  '/player.html', '/organizer.html', '/control.html',
  '/site.webmanifest', '/icon-192.png',
];

self.addEventListener('install', e => {
  // Un file mancante non deve bloccare l'installazione. Con addAll bastava un 404
  // e il service worker non partiva mai, notifiche push comprese.
  e.waitUntil(
    caches.open(CACHE)
      .then(c => Promise.allSettled(STATIC.map(url => c.add(url))))
      .then(() => self.skipWaiting())
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

  /* Pagine: prima la rete, la cache solo come rete di sicurezza offline. */
  if (e.request.mode === 'navigate' || e.request.destination === 'document') {
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          if (resp.ok) caches.open(CACHE).then((c) => c.put(e.request, resp.clone()));
          return resp;
        })
        .catch(() => caches.match(e.request).then((cached) => cached || caches.match('/index.html')))
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
  let data = { title: 'Mull2Five', body: '', url: '/my-registrations.html' };
  try { data = { ...data, ...(e.data ? e.data.json() : {}) }; } catch { /* payload non-JSON */ }
  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
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
