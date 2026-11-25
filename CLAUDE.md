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
cambia cosa fa una schermata. **`docs/comandi.md`** è il manuale per i guasti,
dal sintomo o dall'avviso su Telegram fino al comando, scritto per PowerShell:
va aggiornato quando cambia una procedura o arriva un avviso nuovo.

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
- **Il deploy non aspettava la CI**: fino al 24/11/2026 un push con la CI rossa
  andava in produzione lo stesso. Ora Render pubblica solo a CI verde
  (`autoDeployTrigger: checksPass`, e nel cruscotto *After CI Checks Pass*);
  *Manual Deploy* invece non la guarda. Lo staging si aggiorna a ogni push.
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
- **ID e secret Google scambiati su Render** (24/11/2026): il bottone compare lo
  stesso, ma Google rifiuta l'accesso e il secret finisce nell'URL pubblico che
  restituisce `/api/auth/google/start`. Controllo: lì il `client_id` deve finire
  con `.apps.googleusercontent.com`; se comincia con `GOCSPX-` è il secret.

## Dov'è arrivato

Parità con Melee completata (26 passi), checklist di lancio fatta, revisione
critica chiusa tranne tre punti. Il backend è diviso in `tournaments.py`,
`tournament_registrations.py`, `tournament_rounds.py` più i servizi; il
back-office in `organizer.js`, `organizer-store.js`, `organizer-common.js`.
ESLint sul frontend, Alembic sullo schema. Test: 588 backend (SQLite e
PostgreSQL), 74 frontend, 17 dell'app Android, 9 end-to-end. `/health` dice quale commit sta girando
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

Dal 24 novembre 2026 **si entra anche con Google**, in produzione con lo schema
`0013` (tabella `user_identities`). Il giro è lato server
(`routers/google_auth.py`, `services/google_login.py`): il token di accesso non
passa mai dall'URL, lo si ritira con `POST /api/auth/google/finish`, e il cookie
`m2f_google` vale solo durante l'accesso. **Un'email verificata da Google uguale
a quella di un account esistente è lo stesso account**: Google gli si collega, e
se l'account aveva una password questa si spegne, insieme alle sessioni e ai
link di reset (`_merge_by_email`). Il motivo: la registrazione con password non
verifica l'email. Collegare Google dal profilo, da dentro l'account, la password
la lascia. L'unione di due account con email diverse l'utente l'ha scartata:
basta "Collega Google". Credenziali: progetto Google Cloud `mull2five`, due
client (produzione e staging+localhost), `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`
su Render; senza, il bottone non compare. Dettagli in `docs/hosting.md` e
`docs/pubblico.md`.

Sempre dal 24 novembre c'è il **QR dell'iscrizione**. Porta a
`event.html?id=<id>&iscriviti=1`, dove la finestra d'iscrizione si apre da sola
(dopo il login, se serve). Lo disegna il server con `segno`
(`services/registration_qr.py`, `GET /api/tournaments/{id}/registration-qr.svg|png`,
pubblico come la pagina) sull'indirizzo di `SITE_URL`: un QR preso dallo staging
punta allo staging. Si apre in due punti: nel back-office, dentro il torneo,
"▦ QR iscrizione" porta al foglio A4 da stampare (`qr.html`); sulla pagina
pubblica, sotto "Iscriviti", lo stesso pulsante apre una finestra col QR, "Copia
link" e il foglio. Il ritorno dal login passa da `safeNext` in `session.js`:
toglie una barra davanti (`/event.html?…`, da `location.pathname`) e rifiuta
`//altro.sito`. Quando la barra veniva rifiutata, "Accedi per iscriverti"
finiva su "Le mie iscrizioni".

Sempre dal 24 novembre c'è la **lega, cioè i Circuiti** (nel codice `Season`,
"stagione"). Nel back-office la sezione **Circuiti** (`organizer-circuits.js`)
crea il circuito e ne sceglie i tornei fra quelli che si gestiscono, già giocati
o in calendario, tutti insieme o uno alla volta man mano che si giocano; "Togli"
ne toglie uno, e il torneo resta. **Un torneo sta in un circuito solo**
(`tournaments.season_id`): sceglierlo in un altro lo sposta, e il back-office
chiede conferma. Un circuito chiuso non prende tornei; lo gestisce chi l'ha creato
e lo staff del suo negozio. API in `routers/seasons.py`: `/mine`, `POST
/{id}/tournaments` (più tornei, o tutti o nessuno), `DELETE
/{id}/tournaments/{tid}`, `DELETE /{id}`. La pagina pubblica è
`series.html?c=<slug>`.

**La classifica** la calcola `season_leaderboard`, in blocco con query costanti
(c'è il test che lo controlla), con 30 secondi di cache che si svuota quando
cambiano tornei o regole. Ogni tappa dà a ogni giocatore un punteggio, e il
totale somma le tappe:
- vittorie e pareggi (un bye è una vittoria) e i **punti presenza**, per ogni
  torneo in cui si è giocato almeno un turno: chi è solo iscritto a una tappa
  futura non compare;
- il **bonus vincitore**: chi vince la finale se c'è un taglio, altrimenti il
  primo con gli spareggi del gioco;
- il **bonus imbattuto**, a chi vince *tutti* i match di un torneo concluso;
  basta un pareggio per perderlo;
- gli **scarti**, che il back-office **non offre più** dal 24/11/2026 ("non
  serve al momento"): con più di `drop_above_tournaments` tornei *giocati* nel
  circuito, a ognuno si tolgono i suoi `drop_worst_scores` punteggi di tappa
  peggiori, e una tappa saltata vale 0. Il calcolo e le colonne restano, ma il
  modulo manda sempre `drop_worst_scores: 0`: un circuito salvato da lì somma
  tutto. Per riaccenderli basta rimettere i due campi in `organizer-circuits.js`.

**Le regole della lega del negozio** sono quelle con cui parte un circuito
nuovo dal back-office (`NEW_CIRCUIT`): vittorie e pareggi come sempre (3 e 1),
**1 punto presenza, 1 punto bonus imbattuto, nient'altro** (bonus vincitore a
zero, niente scarti). Bonus imbattuto e scarti sono colonne dello schema
`0014`; sui circuiti nati prima valgono zero, e la loro classifica non è
cambiata. Dettagli in `docs/back-office.md`, test in `tests/test_circuits.py`.

Sempre il 24 novembre, una passata per l'uso di tutti i giorni:
- **I posti di un torneo li conta una richiesta alla volta**: `lock_seats` in
  `services/registrations.py` blocca la riga del torneo (`FOR UPDATE`) prima di
  contare. Senza, due iscrizioni insieme sull'ultimo posto entravano tutte e
  due. Ogni punto nuovo che conta i posti e poi iscrive va dopo `lock_seats`.
  Su SQLite non fa niente: il test (`tests/test_concurrency.py`) gira solo su
  PostgreSQL.
- **Un doppio clic è un 409, non un 500**: un vincolo di unicità violato passa
  da `integrity_error_handler` in `main.py`, senza avviso su Telegram.
- **Iscrizione e annullamento sono `def`**: Stripe e PayPal si chiamano in modo
  sincrono, e in una funzione `async` fermavano tutto il server. Il codice
  asincrono dei pagamenti ci arriva con `anyio.from_thread.run`.
- `/metrics` fuori dallo sviluppo vuole `METRICS_TOKEN`, sennò è un 404; il sito
  non parte con la `SECRET_KEY` scritta nel repository (`secret_key_problem` in
  `core/config.py`, controllata anche da `prepara_database.py`).
- **Il battito**: ogni cinque minuti il sito chiama il proprio `/health` dal
  dominio e, se è `ok`, lo dice a Healthchecks.io (`HEARTBEAT_URL`). Se smette,
  è Healthchecks.io ad avvisare su Telegram: l'unico avviso che non dipende né
  dal sito né da GitHub. **Acceso il 25/11/2026**: controllo `mull2five.it`,
  ogni 5 minuti più 10 di tolleranza, avvisi su Telegram e per email
  all'indirizzo dell'account Healthchecks.io. Il valore di
  `HEARTBEAT_URL` va incollato **senza a capo**: con l'a capo httpx rifiuta
  l'indirizzo e il battito tace, senza che Healthchecks.io veda niente.
- Sulle pagine di ricerca, da telefono, i filtri stanno dietro un pulsante
  (`js/facets-toggle.js`). DMARC del dominio acceso (`p=none`), DKIM c'era già.

Il 24 novembre è nata **l'app Android**, il 25 rifatta **nativa** (Kotlin e
Jetpack Compose, in `android/`): la prima, il sito dentro Chrome (TWA), "è
praticamente una pagina web". È **tutto il lato del giocatore**, senza rimandi
al sito (solo privacy e termini): ricerca con tutti i filtri e "vicino a me",
pagina del torneo e iscrizione, Scopri (negozi, circuiti, archivio delle liste
e metagame), risultati pubblici, le mie iscrizioni con il torneo dal vivo
(check-in, pagamento, lista, turno e tutti gli abbinamenti, risultato,
classifica, ritiro, ID Wizards), statistiche, le mie liste con l'editor,
segnalazioni, account (Google, profili dei figli con `X-Act-As`, esporta,
elimina) — sulla stessa API del sito; niente back-office. Pacchetto `it.mull2five.app`, e `it.mull2five.app.staging` che parla
con lo staging. **L'accesso con Google dell'app** è un giro a sé con PKCE
(`/api/auth/google/app/start|finish|complete` in `routers/google_auth.py`):
Chrome non passa il cookie all'app, quindi la `/callback` rimanda a
`<pacchetto>://google?code=…` e il `code` si ritira solo col segreto dell'app.
"Collega Google" dall'account fa lo stesso giro con un biglietto
(`/api/auth/google/app/link` e `/link/finish`). I testi sono in `res/values*/strings.xml`; gli errori del server l'app li
traduce con `frontend/locales`, copiati a ogni compilazione. Un endpoint che
l'app usa (`data/Api.kt`, `Models.kt`) si allarga, non si cambia: l'app
installata resta indietro finché non si aggiorna. I link a `/event.html` (e i
QR) aprono l'app se `/.well-known/assetlinks.json` (`routers/site.py`) nomina
pacchetto e impronta: `ANDROID_PACKAGE` e `ANDROID_CERT_FINGERPRINTS` su Render.
Si compila con `android\compila.ps1` (JDK 17 e SDK da `android\strumenti.ps1`,
in `%USERPROFILE%\.bubblewrap`); gli strumenti dell'SDK restano alla 19.0,
perché dalla 23.0 `sdkmanager` è la "Android CLI", che non installa i pacchetti
ed esce con 0. Tutto in `docs/android.md`.

Il 25 novembre, tre richieste:
- **Ogni organizzatore ha il suo negozio.** Un torneo creato da chi non faceva
  parte di un negozio finiva in quello di default e usciva "a nome di
  Mull2Five". Ora `working_store` (`services/stores.py`) gliene apre uno col
  nome dell'account al primo torneo, evento o circuito; chi aveva già creato
  qualcosa lo riceve all'avvio da `seed_own_stores` (`db.py`), una volta, con
  tornei, eventi, circuiti, modelli e tag (`_OWN_ROWS`). Il negozio di default
  non è più di nessuno e non compare fra i Negozi. Test in
  `tests/test_own_store.py`.
- **Le liste si guardano come su Melee** (`js/deck-view.js`): immagini ordinate
  per tipo e costo col sideboard a lato, testo per tipo, e una **grafica** 16:9
  o 1:1 da scaricare, disegnata su un canvas. Le carte le chiede **il server** a
  Scryfall (`POST /api/cards/lookup`, pubblico): la CSP non lascia al browser
  `api.scryfall.com`, ed è per questo che prima le immagini non comparivano.
- **La campanella**: lo storico delle notifiche (tabella `notifications`, schema
  `0015`), in un menu a tendina in alto (`js/inbox.js`) e nell'app. Ci finisce
  tutto quello che il sito dice da solo, **anche con le email spente**:
  quell'interruttore spegne le email, non la campanella. Il server salva il
  tipo e i pezzi della frase (`services/inbox.py`), la frase la scrive chi la
  mostra: un tipo nuovo vuole la sua frase in `phrase()` di `js/inbox.js` e di
  `notify/Inbox.kt`. Dopo 90 giorni se ne vanno (`prune`, nel giro dei
  promemoria). **L'app** le mette fra le notifiche del telefono **senza
  Firebase**: WorkManager chiede ogni 15 minuti quelle nuove
  (`GET /api/notifications?after_id=`). Per averle all'istante servirebbe
  Firebase Cloud Messaging, con un progetto e delle chiavi dell'utente.

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

**Infrastruttura** — niente di aperto. Il guasto del 23/09 è chiuso del tutto:
il deploy aspetta la CI, gli avvisi su Telegram sono accesi, il battito su
Healthchecks.io anche (25/11/2026), il ripristino dal backup è stato provato il
29/09, e lo staging esiste.

**Rimandabili**
Locator (spento per le condizioni d'uso di Wizards), ri-podding, l'app Android
su Google Play (account sviluppatore, chiave, 12 tester per 14 giorni:
`docs/android.md`), e le idee in fondo al TODO.
