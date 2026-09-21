import { defineConfig } from 'vite';

/* In WSL2, 'localhost' può risolvere a ::1 (IPv6) ma uvicorn ascolta solo
   su IPv4. Usiamo 127.0.0.1 esplicitamente per forzare IPv4. */
const BACKEND = 'http://127.0.0.1:8000';

export default defineConfig({
  root: '.',
  publicDir: 'public',   // assets statici, manifest.json, sw.js, icons/

  server: {
    port: 5173,
    proxy: {
      '/api':    { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
    },
  },

  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        /* App online — frontend unico (rimosso il tool offline) */
        index:              'index.html',          // home "Scopri" a rail
        events:             'events.html',         // ricerca eventi con facet
        stores:             'stores.html',         // elenco negozi
        store:              'store.html',          // profilo negozio
        series:             'series.html',         // pagina circuito
        circuits:           'circuits.html',       // elenco circuiti
        coverage:           'coverage.html',       // scheda social del torneo
        'event-page':       'event-page.html',     // programma di una manifestazione
        login:              'login.html',
        history:            'history.html',
        event:              'event.html',
        'my-registrations': 'my-registrations.html',
        player:             'player.html',
        leaderboard:        'leaderboard.html',
        'sandbox-checkout': 'sandbox-checkout.html',
        organizer:          'organizer.html',      // back-office organizzatore
        control:            'control.html',         // console Regia
        /* Schermi condivisi e pagine auth */
        timer:             'timer.html',
        display:           'display.html',
        'forgot-password': 'forgot-password.html',
        'reset-password':  'reset-password.html',
      },
    },
  },
});
