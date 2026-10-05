# Mull2Five — istruzioni per chi lavora qui

Piattaforma per tornei di carte: ricerca eventi, iscrizioni, pagamenti, turni,
abbinamenti, liste dei mazzi. Live su https://mull2five.onrender.com
(Render, Docker, regione Frankfurt) con PostgreSQL su Supabase Frankfurt.
Repository **pubblico**, deploy automatico al push. Due rami, due ambienti:
`develop` → staging (`mull2five-staging.onrender.com`, con un progetto Supabase
suo), `main` → produzione. Si lavora su `develop`, si guarda lo staging, si fonde
in `main`: **il push su `main` è l'unico gesto che tocca il sito vivo.** I servizi
stanno in `render.yaml`, la procedura in `docs/hosting.md`.

Solo **Magic** è acceso: gli altri giochi esistono nel codice e si accendono
con `ENABLED_GAMES`.

## Come si lavora

Il lato Python gira **sotto WSL**, non Windows (`.venv/bin`, non `.venv/Scripts`).

```
wsl bash -lc 'cd "/mnt/c/Users/Zero/Documents/Project/Tournament Organizer" && ./.venv/bin/python -m pytest -q'
```

- **API di sviluppo**: va avviata con `DATABASE_URL=sqlite:///./mull2five_dev.db`.
  Il `.env` punta a un PostgreSQL su `localhost:5432` che ora è di un altro
  progetto. Gira **senza `--reload`**: dopo una modifica al backend va riavviata,
  altrimenti serve codice vecchio.
- **Frontend**: `cd frontend && npx vite` (porta 5173, inoltra `/api` alla 8000).
- **Prima di dire che è fatto**: `pytest` (SQLite e PostgreSQL), `ruff check
  backend tests migrations scripts`, e nel frontend `npm run lint`, `npm run test:run`,
  `npx vite build`.
- **Mai modificare i file mentre pytest gira**, e sappi che fermare il task
  Windows non ferma il pytest dentro WSL.

## Come funziona il sito

`docs/` spiega ogni parte: back-office (Community e tag compresi), regia, lato
pubblico, ruoli, e la messa online (`docs/hosting.md`). Da aggiornare quando si
cambia cosa fa una schermata.

## Regole del progetto

- Nomi in inglese nel codice, commenti e interfaccia in italiano.
- Le traduzioni partono dall'italiano: `t('testo italiano')` è la chiave, e la
  stessa frase sta in `frontend/locales/{en,es,fr,de}.json`. Un test lo verifica.
- **Lo schema lo descrivono i modelli e lo applica Alembic.** Niente `ALTER
  TABLE` scritte a mano: una revisione nuova in `migrations/versions/`.
- Sessione e chiamate all'API passano da `frontend/js/session.js`.
- Non committare `reports/`, `*.db*` o dati personali: il repository è pubblico.
- **Non pushare senza l'ok esplicito**: il push fa partire il deploy sul sito vivo.

## Trappole che sono già costate tempo

- **La produzione gira l'ultimo commit *pubblicato*, non `main`.** Il 23/09/2026
  togliere le migrazioni a mano ha rotto il sito perché la colonna
  `users.public_id` era in un commit mai pushato. Prima di toccare lo schema:
  ricostruisci il database com'è in produzione (`git diff <sha-live>..HEAD --
  backend/app/models.py` per il delta) e mettici **più righe**, o gli errori di
  unicità non si vedono.
- **Una migrazione fallita sembrava un deploy riuscito** (23/09/2026):
  `sync_alembic` catturava l'errore e il sito partiva lo stesso, dando 500 sugli
  endpoint interessati. Adesso l'errore risale, e le migrazioni girano in un
  passo a sé prima di uvicorn (`backend/app/prepara_database.py`, chiamato dal
  `CMD` del Dockerfile): se falliscono il contenitore esce con un errore, il
  deploy si ferma e resta su la versione di prima. In più `/health` dice se lo
  schema è rimasto indietro, e in quel caso lo stato è `degraded`.
- **Il deploy non aspetta la CI**: un push con la CI rossa va in produzione lo stesso.
- **Un `ALTER TABLE` che aspetta un lock bloccava il deploy per sempre**
  (29/09/2026, con `0006_tag_author`): l'istanza vecchia è ancora viva e serve
  traffico, la porta non si apriva mai e Render diceva `Timed Out / no open
  ports`. Tre difese, tutte in piedi: le connessioni hanno
  `idle_in_transaction_session_timeout` a un minuto, così una transazione
  dimenticata smette di tenere i lock; `migrations/env.py` mette
  `lock_timeout` a cinque secondi, così la DDL fallisce dicendo cosa aspetta; e
  le migrazioni stanno fuori dall'avvio. Se ricapita: *Restart* del servizio e
  subito *Manual Deploy* — l'istanza vecchia molla le connessioni.
- SQLite su `/mnt/c` è inaffidabile: il database dei test sta in `/tmp`, uno per
  processo (`tests/conftest.py`).
- **Un orologio che si corregge all'indietro buttava fuori chi era appena
  entrato**: PyJWT rifiuta un token il cui `iat` sia anche solo un millesimo
  avanti. Erano i rossi intermittenti della suite — sempre un 401, ogni volta su
  un test diverso. `SCARTO_OROLOGIO` in `backend/app/security.py` concede
  sessanta secondi.

## Dov'è arrivato

Parità con Melee completata (26 passi), checklist di lancio fatta, revisione
critica chiusa tranne tre punti. Il backend è diviso in `tournaments.py`,
`tournament_registrations.py`, `tournament_rounds.py` più i servizi; il
back-office in `organizer.js`, `organizer-store.js`, `organizer-common.js`.
ESLint sul frontend, Alembic sullo schema. Test: 346 backend (SQLite e
PostgreSQL), 49 frontend, 9 end-to-end. `/health` dice quale commit sta girando
e se lo schema è allineato al codice.

## Cosa resta — in ordine

Dettaglio in `TODO.md` (14 voci aperte). Quelle che contano:

**Bloccano l'apertura ai negozi**
1. Far verificare a un legale privacy, termini e cookie (sono bozze) e riempire i `LEGAL_*`.
2. Attivare Stripe Connect sull'account vero e il webhook `account.updated`.
3. Decidere il piano di Render: oggi è **gratuito**, quindi il servizio si
   addormenta e il primo visitatore aspetta fino a un minuto.

**Difetto vero, non ancora sfruttabile**
4. Il webhook PayPal non verifica la firma e tratta `CHECKOUT.ORDER.APPROVED`
   come incasso (`backend/app/routers/payments.py`). Da chiudere **prima** di
   accendere PayPal.

**Infrastruttura, dal guasto del 23/09**
5. Far aspettare la CI al deploy; avvisi su `ALERT_EMAIL`; provare un ripristino
   dal backup; valutare uno staging.

**Rimandabili**
Locator (spento per le condizioni d'uso di Wizards), ri-podding, app mobile,
e le idee in fondo al TODO.
