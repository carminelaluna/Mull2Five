# Mull2Five — istruzioni per chi lavora qui

Piattaforma per tornei di carte: ricerca eventi, iscrizioni, pagamenti, turni,
abbinamenti, liste dei mazzi. Live su **https://mull2five.it** (dal 23/11/2026;
`mull2five.onrender.com` rimanda lì, tranne API e webhook) su Render, Docker,
piano 0.5c-512mb, regione Frankfurt, con PostgreSQL su Supabase Frankfurt.
Dominio e DNS su register.it.
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
- **Lo staging che non parte di solito ha solo il database in pausa** (23/11/2026):
  il progetto Supabase gratuito si ferma dopo una settimana senza richieste,
  `prepara_database.py` non lo trova e Render dice *Failed service*. Supabase →
  *Resume project*, poi *Manual Deploy*. Ora lo tiene sveglio
  `.github/workflows/staging-keepalive.yml`, che se fallisce manda un'email.
- **`/assets/` è in cache per un anno, immutabile** (`main.py`): lì ci vanno solo i
  file con l'hash che crea Vite. Un file messo a mano in `frontend/public/assets/`
  resterebbe vecchio nei browser anche dopo averlo cambiato.
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
ESLint sul frontend, Alembic sullo schema. Test: 380 backend (SQLite e
PostgreSQL), 60 frontend, 9 end-to-end. `/health` dice quale commit sta girando
e se lo schema è allineato al codice.

Il 5 ottobre 2026 sono state chiuse le ultime idee in coda al TODO: promemoria
del giorno prima e link di pagamento nell'email della lista d'attesa, calendario
mensile nella ricerca, modelli di torneo, early bird, codici sconto, win rate per
formato e archetipo sul profilo. **Il prezzo lo decide un posto solo**:
`entry_fee_now()` per la vetrina e `amount_due()` per chi è già iscritto, in
`backend/app/services/payments.py` — se una pagina mostra una cifra e il banco
ne incassa un'altra, è perché qualcuno ha ricalcolato il prezzo altrove.

Il 23 novembre 2026 è stata fatta una passata sulle prestazioni, in produzione
con lo schema `0011`. Le pagine arrivano compresse (Gzip). Gli elenchi pubblici,
admin e dell'API v1 si paginano con `limit`/`offset`, 500 righe di default. La
ricerca pubblica carica in blocco i dati collegati, invece di una query per
torneo. Le chiavi esterne su cui le pagine cercano hanno un indice. Infine
`tests/test_query_counts.py` fallisce se le query tornano a crescere con il
numero di righe: un elenco nuovo va scritto allo stesso modo, con
`tournament_with_counts` o una query raggruppata, mai `len(relazione)` in un
ciclo.

## Cosa resta — in ordine

Dettaglio in `TODO.md`. Quelle che contano:

**Bloccano l'apertura ai negozi** — nessuna è codice: sono decisioni o cruscotti.
1. Far verificare a un legale privacy, termini e cookie (sono bozze) e riempire i `LEGAL_*`.
2. Attivare Stripe Connect sull'account vero e il webhook `account.updated`.
3. Creare il webhook PayPal, iscriverlo a `CHECKOUT.ORDER.APPROVED` e
   `PAYMENT.CAPTURE.COMPLETED`, e mettere il suo identificativo in
   `PAYPAL_WEBHOOK_ID`. Il codice è pronto; senza quell'identificativo le
   notifiche vengono rifiutate, ed è il comportamento voluto.
4. Webhook Stripe/PayPal spostati su `mull2five.it`: l'ultimo punto del "Passo 8"
   in `docs/hosting.md`. Piano a pagamento, dominio ed email sono fatti
   (23/11/2026): le email partono dalle caselle register.it del dominio, una per
   tipo — `info@` l'accesso, `commercial@` i pagamenti, la casella admin il resto
   (`Sender` in `services/email.py`). Il reset password è stato provato e arriva.

**Infrastruttura, quel che resta del guasto del 23/09**
5. Far aspettare la CI al deploy (nel cruscotto Render) e impostare `ALERT_EMAIL`.
   Il ripristino dal backup è stato provato il 29/09, e lo staging esiste.

**Rimandabili**
Locator (spento per le condizioni d'uso di Wizards), ri-podding, app mobile,
e le idee in fondo al TODO.
