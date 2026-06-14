# Manabind

Piattaforma full-stack per gestione tornei MTG: backend Python, database relazionale,
login, dashboard utente, dashboard tornei, iscrizioni, decklist, round e pagamenti
Stripe/PayPal.

## Funzionalità

App **interamente online** (tutto passa dal backend, niente localStorage): accessibile
da più PC contemporaneamente, pensata anche per tornei grandi.

### Giocatori
- Sfoglia tornei con filtri: nome, formato, data, luogo, distanza GPS (Nominatim + Haversine)
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
- Alembic migrations, backup automatici PostgreSQL (cron/systemd)
- Rate limiting (slowapi), account lockout, JWT expiry, CSP headers
- GitHub Actions CI/CD; test: pytest (backend) + Vitest + Playwright E2E

---

## Architettura

**Un solo frontend online** in `frontend/` (Vite multi-page), servito in produzione da
nginx (`frontend/dist`, `try_files $uri $uri.html`). Backend FastAPI su `/api`.
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
│   ├── systemd/arcana-events.service
│   └── nginx/arcana-events.conf
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

**Docker / Produzione (PostgreSQL):**
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
APPLE_PRIVATE_KEY_PATH=/opt/arcana-events/AuthKey_XXXXXXXXXX.p8
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

## Deploy Linux

```bash
sudo mkdir -p /opt/arcana-events
sudo cp -R . /opt/arcana-events
cd /opt/arcana-events

# Build frontend
npm install && npm run build

# Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # poi modifica .env

# Systemd
sudo cp deploy/systemd/arcana-events.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arcana-events

# Nginx
sudo cp deploy/nginx/arcana-events.conf /etc/nginx/sites-available/arcana-events
sudo ln -s /etc/nginx/sites-available/arcana-events /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**Nginx** — aggiorna `arcana-events.conf` per servire il build statico:
```nginx
server {
    root /opt/arcana-events/dist;
    try_files $uri $uri.html $uri/ =404;

    location /api    { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
    location /health { proxy_pass http://127.0.0.1:8000; }
}
```

---

## Note

Per produzione servono: credenziali reali OAuth / Stripe / PayPal, HTTPS, e un `SECRET_KEY` lungo e casuale (`python -c "import secrets; print(secrets.token_hex(32))"`).
