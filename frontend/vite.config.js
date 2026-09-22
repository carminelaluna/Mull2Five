import { defineConfig } from 'vite';

/* In WSL2, 'localhost' può risolvere a ::1 (IPv6) ma uvicorn ascolta solo
   su IPv4. Usiamo 127.0.0.1 esplicitamente per forzare IPv4. */
const BACKEND = 'http://127.0.0.1:8000';

/* L'indirizzo pubblico del sito, per og:image, og:url e canonical: i social
   vogliono indirizzi assoluti. Nelle pagine si scrive __SITE_URL__. */
const SITE_URL = (process.env.SITE_URL || 'https://mull2five.onrender.com').replace(/\/$/, '');
const siteUrl = {
  name: 'site-url',
  transformIndexHtml: (html) => html.replaceAll('__SITE_URL__', SITE_URL),
};

export default defineConfig({
  root: '.',
  publicDir: 'public',   // asset statici: brand/, icone, site.webmanifest, sw.js
  plugins: [siteUrl],

  server: {
    port: 5173,
    proxy: {
      '/api':    { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
      '/robots.txt':  { target: BACKEND, changeOrigin: true },
      '/sitemap.xml': { target: BACKEND, changeOrigin: true },
    },
  },

  build: {
    outDir: 'dist',
    // es2022 per il top-level await di js/lang.js: la pagina aspetta la sua lingua.
    target: 'es2022',
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
        decks:              'decks.html',          // le mie liste e il costruttore
        decklists:          'decklists.html',      // archivio pubblico delle liste
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
        /* Pagine di servizio: errore, ringraziamento, testi legali */
        'not-found':       '404.html',
        grazie:            'grazie.html',          // dopo l'iscrizione e il pagamento
        privacy:           'privacy.html',
        termini:           'termini.html',
        cookie:            'cookie.html',
      },
    },
  },
});
