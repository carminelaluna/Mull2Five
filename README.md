# Mull2Five

Piattaforma full-stack per gestione tornei MTG: backend Python, database relazionale,
login, dashboard utente, dashboard tornei, iscrizioni, decklist, round e pagamenti
Stripe/PayPal.

## Brand

Palette: lime `#c6ff3d`, nero `#0d0d0f`, bianco. Gli asset stanno in
`frontend/public/` (favicon, icone PWA, anteprima social) e `frontend/public/brand/`
(logo orizzontale per l'header, verticale per il login, badge per gli spazi stretti).
Il nome si scrive sempre `Mull2Five`.

Restano volutamente con il vecchio nome gli identificatori tecnici: chiavi
localStorage (`manabind-jwt-v1`), header tenant `X-Manabind-Org`, metriche
Prometheus. Rinominarli sloggherebbe gli utenti.

## Funzionalità

App **interamente online** (tutto passa dal backend, niente localStorage): accessibile
da più PC contemporaneamente, pensata anche per tornei grandi.

### Giocatori
- Home "Scopri": rail per eventi, negozi e circuiti con filtri rapidi
- Ricerca eventi a facet: tipo evento, formati multipli, REL, periodo, distanza in km, ricerche salvate
- Profili negozio e pagine circuito pubbliche, con classifica e soglia di qualificazione
- Iscrizione + pagamento obbligatorio (Stripe/PayPal/sandbox)
- "Le mie iscrizioni": pairings, risultati, decklist self-service, QR check-in, storico tornei
- Notifiche Web Push (annunci, nuovo round) + profilo pubblico condivisibile
- Interfaccia bilingue IT/EN

### Organizzatori
- Back-office (`organizer.html`): tornei, iscritti, liste, annunci, penalità, classifica, report
- Console Regia (`control.html`): timer round (restart/extend), +min per tavolo, risultati, genera round, vista judge
- Schermi condivisibili full-screen: `timer.html?t=ID`, `display.html?t=ID` (TV negozio)
- Pairing svizzero, Top 8 bracket, multi-tenant (più negozi)

### Infrastruttura
- Redis (cache + lockout), Web Push (VAPID), Prometheus `/metrics`, alerting email/Telegram + watchdog DB
- Alembic migrations, backup PostgreSQL cifrati ogni notte (GitHub Actions)
- Rate limiting (slowapi), account lockout, JWT expiry, CSP headers
- GitHub Actions CI/CD; test: pytest (backend) + Vitest + Playwright E2E

---

## Architettura

**Un solo frontend online** in `frontend/` (Vite multi-page). In produzione la build
(`frontend/dist`) la serve lo stesso processo FastAPI dell'API, su `/`; l'API sta su `/api`.
Il vecchio organizer tool offline (localStorage) è stato rimosso: ogni funzione passa
ora dal backend ed è accessibile da qualunque dispositivo.

---

## Avvio rapido

Il modo più comune in sviluppo: backend in WSL, Vite su Windows.

**Terminale 1 — backend (WSL):**
```bash
cp .env.example .env   # solo la prima volta
./scripts/dev.sh
```

**Terminale 2 — frontend (Windows):**
```bash
cd frontend
npm install            # solo la prima volta
npm run dev            # apre http://localhost:5173
```

> Il proxy Vite inoltra automaticamente `/api` e `/health` al backend su `127.0.0.1:8000`.
> Nessuna configurazione CORS necessaria in sviluppo.

---

## Comandi frontend (npm)

> Tutti i comandi npm vanno eseguiti da `frontend/` oppure con `make fe-*` dalla root.

| Comando | Da `frontend/` | Dalla root |
|---|---|---|
| Dev server | `npm run dev` | `make fe-dev` |
| Build produzione | `npm run build` | `make fe-build` |
| Anteprima build | `npm run preview` | — |
| Test unit (watch) | `npm run test` | `make fe-test` |
| Test unit (una volta) | `npm run test:run` | `make fe-test-run` |
| Test unit con coverage | `npm run test:cover` | — |
| E2E test | `npm run e2e` | — |
| E2E con UI interattiva | `npm run e2e:ui` | — |
| Installa browser Playwright | `npm run e2e:install` | — |

---

## Comandi backend (Python / WSL)

| Comando | Descrizione |
|---|---|
| `./scripts/dev.sh` | Installa dipendenze e avvia uvicorn con reload |
| `make dev` | Alias per `dev.sh` |
| `make install` | Solo installazione dipendenze |
| `make lint` | Linting con ruff |
| `make test` | Test suite Python |
| `docker compose up --build` | Avvio completo con PostgreSQL |
| `docker compose down` | Spegni i container |

---

## Test

### Frontend (Vitest)

```bash
cd frontend   # tutti i comandi npm si eseguono da qui

# Una volta sola
npm run test:run

# Modalità watch (riesegue al salvataggio)
npm run test

# Con report coverage
npm run test:cover
```

I test vivono in `tests/` e coprono:

| File | Cosa testa |
|---|---|
| `tests/utils.test.js` | `invertResult`, `parseDeck` (duplicati, Commander), `haversine`, `Paginator`, `escapeHtml`, `storageKB` |
| `tests/state.test.js` | `computeStandings`, `swissPairing`, `isRoundComplete`, `getResultObj` (retrocompat) |
| `tests/auth.test.js` | `registerUser`, `loginUser`, `startSession`, `isOrganizer` |
| `tests/round.test.js` | Coerenza risultati pair[0]/pair[1], lock giocatore, formato stringa |
| `tests/search.test.js` | `filterEventsSync` (nome, formato, data, venue, raggio), edge cases deck parser |

### Backend (Python)

```bash
# Dalla root del progetto (venv attivo)
python -m unittest discover -s tests -v

# Oppure con make
make test
```

---

## Struttura Progetto

```text
.
├── backend/                    # FastAPI — API, DB, auth, pagamenti
│   └── app/
│       ├── routers/            # auth, tournaments, payments, admin
│       ├── services/           # oauth, pagamenti
│       └── core/               # config, db
├── frontend/                   # Vite — app online unica (tutto via backend)
│   ├── js/                     # Moduli ES (un file per pagina)
│   │   ├── app.js              # Home pubblica (lista tornei, ricerca)
│   │   ├── login-public.js     # Login/registrazione (JWT)
│   │   ├── my-registrations.js # Iscrizioni giocatore + storico + push
│   │   ├── organizer.js        # Back-office organizzatore
│   │   ├── control.js          # Console Regia (timer, risultati, round)
│   │   ├── event.js            # Pagina evento pubblica
│   │   ├── player.js           # Profilo giocatore
│   │   ├── i18n.js             # Internazionalizzazione it/en
│   │   └── push.js             # Web Push (subscribe/unsubscribe)
│   ├── public/                 # Asset statici serviti da Vite alla root
│   │   ├── icons/icon.svg
│   │   ├── manifest.json       # PWA manifest
│   │   └── sw.js               # Service Worker + push handler
│   ├── tests/                  # Vitest unit (i18n, push)
│   ├── e2e/                    # Playwright E2E (flusso online)
│   ├── index.html  login.html  event.html  my-registrations.html
│   ├── player.html  leaderboard.html  organizer.html  control.html
│   ├── timer.html  display.html  forgot-password.html  reset-password.html
│   ├── sandbox-checkout.html
│   ├── styles.css  app.css
│   ├── vite.config.js
│   ├── vitest.config.js
│   └── package.json
├── deploy/
│   └── prometheus-alerts.yml
├── scripts/
│   └── dev.sh                  # Avvio backend (WSL)
├── .env.example
├── Makefile
├── pyproject.toml
├── docker-compose.yml
└── README.md
```

---

## Configurazione

Copia `.env.example` in `.env` e modifica i valori necessari.

**Sviluppo locale (SQLite):**
```env
DATABASE_URL=sqlite:///./arcana_events.db
SECRET_KEY=cambia-questo-valore
```

**Docker Compose (PostgreSQL):**
```env
DATABASE_URL=postgresql+psycopg://arcana:arcana@db:5432/arcana_events
```

**Backend URL per il proxy Vite:**
```env
# .env.local (solo frontend, gitignored)
# Imposta solo se il proxy non funziona (es. WSL con IP diverso da 127.0.0.1)
VITE_API_URL=http://127.0.0.1:8000/api
```

---

## OAuth

**Google** — aggiungi in `.env`:
```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```
Callback: `http://127.0.0.1:8000/api/auth/oauth/google/callback`

**Apple** — aggiungi in `.env`:
```env
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY_PATH=/opt/manabind/AuthKey_XXXXXXXXXX.p8
```
Callback: `http://127.0.0.1:8000/api/auth/oauth/apple/callback`

---

## Pagamenti

**Stripe:**
```env
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```
Webhook: `https://tuo-dominio.it/api/payments/stripe/webhook`

**PayPal:**
```env
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_ENV=sandbox
PAYMENT_SANDBOX_MOCK=true
```
Webhook: `https://tuo-dominio.it/api/payments/paypal/webhook`

Con `PAYMENT_SANDBOX_MOCK=true` il backend genera una pagina sandbox locale per testare i pagamenti senza credenziali reali.

---

## Deploy

Versione di prova online: Render (un servizio Docker per API e pagine) e
Supabase (PostgreSQL), con backup cifrati ogni notte. Passaggi, variabili
d'ambiente e ripristino in [HOSTING.md](HOSTING.md).

---

## Note

Per produzione servono: credenziali reali OAuth / Stripe / PayPal, HTTPS, e un `SECRET_KEY` lungo e casuale (`python -c "import secrets; print(secrets.token_hex(32))"`).
