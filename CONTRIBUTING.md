# Contribuire a Mull2Five

## Setup sviluppo

**Backend (WSL/Linux):**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
./scripts/dev.sh          # avvia uvicorn su 0.0.0.0:8000
```

**Frontend (Windows o WSL):**
```bash
cd frontend
npm install
npm run dev               # Vite su localhost:5173 con proxy → backend
```

## Struttura

```
backend/app/
  main.py          → FastAPI app, CORS, rate limiting, middleware
  models.py        → SQLAlchemy ORM (Tournament, Registration, Round, Pairing…)
  schemas.py       → Pydantic schemas (input/output)
  security.py      → JWT creation/verification, hashing, lockout
  core/
    config.py      → Settings da .env
    limiter.py     → slowapi rate limiter
    lockout.py     → account lockout in-memory
  routers/
    auth.py        → /api/auth/* (login, register, me, OAuth)
    tournaments.py → /api/tournaments/* (CRUD, round, pairings, standings…)
    payments.py    → /api/payments/* (Stripe, PayPal, sandbox)
    admin.py       → /api/admin/* (solo admin)
  services/
    email.py           → invio SMTP
    notifications.py   → notifiche su eventi torneo
    payments.py        → Stripe + PayPal
    decklists.py       → validazione decklist
    oauth.py           → Google + Apple OAuth

frontend/                → app online unica (tutto via backend, niente localStorage)
  *.html                 → pagine: index, login, event, my-registrations, player,
                           leaderboard, organizer (back-office), control (Regia),
                           timer/display (schermi condivisi), forgot/reset-password
  js/
    app.js               → home pubblica (lista tornei, ricerca)
    login-public.js      → login/registrazione (JWT)
    my-registrations.js  → iscrizioni giocatore + storico + push
    organizer.js         → back-office (tornei, iscritti, liste, annunci, penalità…)
    control.js           → console Regia (timer, risultati, genera round)
    event.js / player.js → pagina evento pubblica / profilo giocatore
    push.js              → Web Push (subscribe/unsubscribe)
  tests/                 → Vitest unit tests (escape, push)
  e2e/                   → Playwright E2E (flusso online register/login)
```

## Convenzioni codice

- **JavaScript**: ES2022 modules, no TypeScript, no framework
- **Nomi variabili**: camelCase, prefisso `_` per privati di modulo
- **Funzioni esportate**: sempre annotate con JSDoc per funzioni pubbliche
- **State mutations**: solo attraverso `saveState()` — mai scrivere direttamente in localStorage
- **DOM manipulation**: `escapeHtml()` obbligatorio per ogni stringa utente nel DOM
- **Async**: `async/await`, errori sempre catchati e gestiti (mai promise silenti)
- **Python**: type hints, ruff per linting, pytest per test

## Aggiungere un endpoint API

1. Aggiungi schema in `backend/app/schemas.py`
2. Aggiungi modello (se nuovo) in `backend/app/models.py`
3. Aggiungi endpoint in `backend/app/routers/[router].py`
4. Aggiungi funzione corrispondente in `frontend/js/api.js`
5. Scrivi test in `tests/` (Python) o `frontend/tests/` (Vitest)

## Aggiungere una feature frontend

1. Logica pura → `utils.js` o modulo dedicato
2. Stato persistente → aggiungi a `state.js`, aggiorna `seedState()`
3. Sync API → aggiungi a `sync.js` nella fase push/pull
4. UI → HTML + handler nel file `.js` della pagina
5. Stili → `styles.css` nella sezione appropriata con commento `/* ── Nome ─ */`
6. Test → `frontend/tests/[feature].test.js`

## Glossario MTG usato nel codice

| Termine | Significato |
|---|---|
| `rel` / `rules_enforcement_level` | Livello arbitrato: Regular, Competitive, Professional |
| `OMW%` / `omwp` | Opponent Match Win % — tiebreaker primario |
| `GW%` / `gwp` | Game Win % — tiebreaker secondario |
| `OGW%` / `ogwp` | Opponent Game Win % — tiebreaker terziario |
| `bye` / `BYE` | Vittoria automatica assegnata con numero dispari di giocatori |
| `swiss` | Sistema di abbinamento svizzero — stessi punti si affrontano |
| `top_cut` | Fase ad eliminazione diretta con i migliori N giocatori |
| `deck check` | Verifica fisica della decklist da parte di un giudice |
| `pairing` | Abbinamento tra due giocatori per un round |
| `result` | Risultato partita nel formato `X-Y` (game vinti dal player 1) |

## Come eseguire i test

```bash
# Backend
pytest --tb=short

# Frontend unit (Vitest)
cd frontend && npm run test:run

# Frontend E2E (Playwright — richiede Vite in esecuzione)
cd frontend && npm run e2e:install   # solo prima volta
cd frontend && npm run e2e

# Coverage
cd frontend && npm run test:cover
```

## Messa online

Variabili d'ambiente, servizi e backup della versione online: vedi `HOSTING.md`.
