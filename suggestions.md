# Suggerimenti — Manabind Frontend

## Funzionalità mancanti (alta priorità)

### ~~1. Inserimento risultati round~~ ✅
### ~~2. Classifica~~ ✅ Punti 3/1/0, record V/P/S, tiebreaker OMW%/GW%/OGW%, top-8 evidenziato, stampa.
### ~~3. Pairing svizzero reale~~ ✅ Ordinamento per punti, no rematches, BYE al player con meno punti senza BYE precedente.

### ~~4. Filtro distanza nella ricerca eventi~~ ✅ Nominatim geocoding + Haversine lato client, cache in localStorage, ordinamento per distanza, fallback testuale se offline.
Il filtro "Luogo" fa un match testuale sul campo venue. Per filtrare per distanza reale
(es. "entro 50 km da Milano") servono coordinate geografiche. Opzioni:
- API Nominatim (OpenStreetMap, gratuita) per geocodifica venue e input utente
- Calcolo distanza con formula Haversine lato client
- Salvare `lat`/`lng` nel record evento quando viene creato

### ~~5. Profilo giocatore esteso~~ ✅ Wizards/DCI + archetipo preferito, modificabili dal modal avatar. Pre-compilano l'iscrizione automaticamente.
Aggiungere campi al profilo utente (accessibili da un modale "Modifica profilo"):
- Wizards account / DCI number
- Archetipo preferito
- Foto profilo (avatar personalizzato)
Questi campi vengono pre-compilati automaticamente all'iscrizione a un torneo.

### ~~6. Decklist giocatore self-service~~ ✅ Pulsante "Carica lista" in "Le mie iscrizioni", dialog con textarea, validazione con parseDeck().

---

## Ottimizzazioni tecniche

### ~~7. Conferma prima di eliminare~~ ✅ confirmDialog() riusabile, applicato a rimozione giocatori ed eventi.
`removePlayer` e `removeEvent` eliminano senza conferma. Aggiungere un `confirm()` o un
`<dialog>` di conferma per evitare perdita accidentale di dati.

### ~~8. Limite localStorage~~ ✅ Storage monitor in sidebar (barra + KB usati), warning toast quando supera 4 MB, geocache pulibile con reset demo.
localStorage ha un limite di ~5 MB. Per tornei grandi (molti round + decklist raw) si
potrebbe raggiungere il limite. Valutare il passaggio a IndexedDB via `idb` (3 kB gzipped).

### ~~9. ES modules + bundler~~ ✅ Tutti i file JS convertiti a import/export ES2022. Vite configurato con multi-page input. Dev: `npm run dev`. Build: `npm run build`.
Attualmente i file JS usano variabili globali (`var`) ed è necessario caricarli in ordine.
Refactoring verso ES modules (`import`/`export`) con Vite permetterebbe tree-shaking,
hot-reload in sviluppo, e un unico bundle ottimizzato in produzione.

### ~~10. Ricerca in tempo reale~~ ✅ Listener input su nome/formato/data (istantaneo) e venue/raggio (debounce 400ms per geocoding).
Il filtro eventi ora si applica al submit del form. Aggiungere un listener `input` sui
campi di ricerca per filtrare in tempo reale senza premere "Cerca".

### ~~11. Paginazione / virtualizzazione lista eventi~~ ✅ Classe Paginator riusabile, applicata a: event cards (8/pagina), tabella tornei (15/pagina), tabella iscritti (20/pagina).
Con molti tornei la lista può diventare lenta. Aggiungere paginazione semplice
(es. 10 eventi per pagina) o virtualizzazione con Intersection Observer.

---

## Integrazione con il backend

### ~~12. Connessione all'API FastAPI~~ ✅ js/api.js con client completo (auth, tornei, iscrizioni, decklist, round, risultati). Login/register ibrido: tenta API, fallback locale. Endpoint corretti da security.py.
Il backend già espone endpoint per eventi, iscrizioni, decklist, pagamenti e round.
Il frontend locale (localStorage) potrebbe fare `fetch()` verso `http://127.0.0.1:8000/api/`
e sincronizzare lo stato, eliminando la dipendenza dal solo browser.

### ~~13. Sincronizzazione ruoli con il backend~~ ✅ JWT decodificato lato client ({sub, email, role, exp}). isOrganizer() preferisce il ruolo JWT quando disponibile. Indicatore ● verde/grigio in sidebar.
I ruoli `player`/`organizer` sono attualmente solo in localStorage. Quando il tool si
connette all'API, i ruoli devono venire dal JWT del backend, non dal client.

### ~~14. Stampa slip abbinamenti~~ ✅ Pulsante nella pagina Round, finestra di stampa con tavoli e colonna risultato vuota.

### ~~15. Progressive Web App~~ ✅ manifest.json, sw.js (cache-first static / network-first API), icons/icon.svg, meta theme-color. Registrazione SW automatica in auth.js.
Aggiungere `manifest.json` e un service worker minimale per permettere l'uso offline
(utile in luoghi senza connessione stabile). La logica è già tutta client-side.

---

## Qualità del codice

### ~~16. Validazione decklist: duplicati~~ ✅ Controllo max 4 copie per carta (max 1 in Commander). Liste di terre base escluse. Errori con nome carta e quantità.
Il parser conta le carte ma non controlla i duplicati (es. 8 copie di Lightning Bolt in
formati non Commander). Aggiungere un controllo: nessuna carta può superare 4 copie
salvo le terre base (richiede una lista di terre base nota o un flag manuale).

### ~~17. Feedback errore form più visibile~~ ✅ setFieldError() / clearAllErrors() in utils.js, border rosso + messaggio inline sui campi, applicati a registrazione giocatore e creazione torneo.
Gli errori di validazione HTML5 sono discreti. Aggiungere classi CSS `.field-error` e
messaggi inline sotto i campi per una UX più chiara su mobile.

### ~~18. QR code check-in~~ ✅ QR generato lato client (qrcodejs), codice 6 char univoco. Giocatore mostra QR dal dashboard, organizzatore fa check-in dalla pagina Iscritti.

---

## Richieste del cliente — "cosa mi serve davvero il giorno del torneo"

> Prospettiva: negozio che organizza 2-3 tornei a settimana (FNM, RCQ, prerelease).
> Ordinate per impatto sulla giornata-tipo.

### ~~19. Recupero password~~ ✅ /auth/forgot-password + /auth/reset-password (token JWT 30 min), pagine forgot/reset-password.html, link nei due login.
Il sabato mattina c'è SEMPRE qualcuno che non ricorda la password e l'iscrizione si blocca
al banco. Serve "Password dimenticata?" nella pagina di login: email con link/codice di
reset a scadenza (il backend ha già il servizio email per gli annunci, si può riusare).
Senza questa funzione devo cancellare e ricreare account a mano.

### ~~20. Lista d'attesa~~ ✅ Registration.waitlisted, iscrizione a torneo pieno → waitlist, promozione automatica su drop con email, badge nella SPA.
Quando il torneo è pieno (capienza raggiunta) oggi l'iscrizione viene semplicemente
rifiutata. Voglio una waitlist: il giocatore si mette in coda, se qualcuno fa drop o
non paga entro la deadline, il primo in lista riceve un'email e ha N ore per pagare.
Riempire i posti vuoti a mano per telefono è il mio incubo attuale.

### ~~21. Schermo pubblico (TV)~~ ✅ display.html?t=ID full-screen senza login: pairing grandi, timer, rotazione pairing/standings, auto-refresh 10s su /public-display.
In negozio ho una TV dietro al bancone. Mi serve una pagina full-screen, senza login,
con: pairing del round corrente in caratteri GRANDI, timer del round, e auto-refresh.
Oggi i giocatori si accalcano al bancone per chiedere il tavolo. Una route tipo
`/display/{tournament_id}` con rotazione automatica pairing → standings risolverebbe.

### ~~22. Notifica "pairing pronti"~~ ✅ Polling 30s in "Le mie iscrizioni": beep + vibrazione + Notification API al nuovo round. (Web Push server-side rimandato.)
L'email c'è ma nessuno la legge in tempo durante il torneo. Servirebbero Web Push
notifications (la PWA c'è già, manca solo il push): "Round 3 — Tavolo 7 vs Mario Rossi".
In alternativa anche solo un suono/vibrazione quando la pagina "Le mie iscrizioni"
rileva un nuovo round.

### ~~23. Drop self-service~~ ✅ POST /my-registration/drop (bloccato a partita in corso), bottone "Ritirati" con conferma nella SPA.
Il campo `dropped` esiste ma solo io posso impostarlo. Il giocatore che se ne va a metà
torneo deve potersi ritirare da solo da "Le mie iscrizioni" (con conferma), così non
genero pairing fantasma e il suo avversario non aspetta 10 minuti un BYE non dichiarato.
Regola: drop consentito solo tra un round e l'altro, non a metà round.

### ~~24. Classifica stagionale~~ ✅ Modello Season (punti configurabili), /seasons/{id}/leaderboard pubblica, pagina leaderboard.html con podio.
I giocatori tornano se c'è una season: punti cumulativi sui tornei del trimestre,
leaderboard pubblica, premio al primo. Servirebbe un'entità "Stagione" che raggruppa
tornei e somma i punti (3/1/0 o configurabile). È IL motivo per cui sceglierei questa
piattaforma invece di un foglio Excel.

### ~~25. Incassi e statistiche~~ ✅ Pagina Report (local-first) con incassi/presenze/formati + export CSV; /tournaments/reports/mine per i dati API.
A fine mese devo sapere: quanto ho incassato per torneo (entry fee × paganti, già tutto
nel DB), quanti giocatori unici, quali formati tirano di più, trend presenze. Una pagina
"Report" con questi numeri e un export CSV per il commercialista.

### ~~26. Account staff/judge~~ ✅ TournamentStaff per torneo (invito email): può inserire risultati e penalità, non elimina né vede i pagamenti.
Nei tornei grossi ho un judge che inserisce risultati e penalità, ma NON deve poter
eliminare il torneo o vedere gli incassi. Oggi dovrei dargli il mio account organizer.
Serve un ruolo "staff" invitabile per singolo torneo.

### ~~27. Export iCal~~ ✅ /ical per torneo + feed /calendar/feed.ics, link "Aggiungi al calendario" nella SPA. (Vista calendario mensile: prossima iterazione.)
La lista eventi c'è, ma i giocatori chiedono "cosa c'è giovedì?". Una vista calendario
mensile pubblica e un link "Aggiungi al calendario" (.ics) per ogni torneo. Anche feed
iCal del negozio da far seguire ai regular.

### ~~28. Pod per draft e sealed~~ ✅ "Genera pod (draft)" in Round: pod da 8 bilanciati, seating casuale, stampa con accoppiamenti consigliati.
Organizzo anche limited: servono pod da 8 con seating casuale visualizzato (chi siede
dove), e gli accoppiamenti del pod (1° round: posto 1 vs 5, ecc.). Oggi la struttura
supporta solo Swiss/eliminazione su torneo intero.

### ~~29. Export per EventLink~~ ✅ CSV iscritti + risultati round per round: bottone in Classifica (locale) e GET /export.csv (API).
Per i tornei sanzionati devo ricaricare i risultati su EventLink a mano, partita per
partita. Un export (CSV o formato compatibile) di iscritti + risultati round per round
mi farebbe risparmiare mezz'ora a torneo.

### ~~30. Privacy / GDPR~~ ✅ "Scarica i miei dati" (JSON) ed "Elimina account" (anonimizzazione) nel modal profilo + endpoint /auth/me/export e DELETE /auth/me.
Gestisco email e nomi di centinaia di persone: servono "Scarica i miei dati" ed
"Elimina il mio account" self-service nel profilo giocatore, e una privacy policy
linkata in registrazione. Prima o poi qualcuno me lo chiederà.

---

## Cosa manca ora — roadmap post-implementazione

> Stato: le 30 voci sopra sono tutte ✅. Questa sezione raccoglie il prossimo giro,
> diviso per punto di vista. Aggiornata dopo l'implementazione di waitlist, display TV,
> stagioni, staff, report, GDPR.

### Tecnico / infrastruttura

### ~~31. Web Push reale~~ ✅
Chiavi VAPID (`python -m backend.app.core.webpush genkeys`), tabella `push_subscriptions`,
endpoint `/api/push/{vapid-key,subscribe,unsubscribe}`, handler `push`/`notificationclick`
nel service worker, invio da `push_to_tournament()` agganciato agli annunci. Bottone
"Attiva notifiche" in "Le mie iscrizioni". No-op graceful se VAPID non configurato.

### 32. Scadenza promozione waitlist 🟡
Oggi il promosso dalla waitlist resta dentro per sempre anche se non paga. Serve una
deadline (es. 6 ore): scaduta, torna in coda e si promuove il successivo. Richiede un
job schedulato (APScheduler o cron) — primo pezzo di infrastruttura asincrona.

### ~~33. Redis per cache e lockout~~ ✅
`core/redis.py` con client unificato e fallback in-memory thread-safe. `cache.py` e
`lockout.py` ora passano da Redis (condiviso tra worker/istanze). Servizio `redis` in
docker-compose + `REDIS_URL`. Se Redis è giù, fallback automatico senza crash.

### 34. Email transazionali complete 🟢
Mancano: ricevuta di pagamento, reminder il giorno prima del torneo, conferma
promozione waitlist con link pagamento diretto. Il servizio SMTP c'è già.

### 35. Vista calendario mensile 🟢
Il feed iCal c'è; manca la griglia mensile visuale nella SPA pubblica
("cosa c'è giovedì?"). Componente puro frontend su dati già esposti.

### Punto di vista organizzatore

### 36. Tornei ricorrenti / template 🔴
Organizzo FNM OGNI venerdì: oggi ricreo il torneo a mano ogni settimana. Serve
"Duplica torneo" (un click, data +7 giorni) e/o template salvati. È la feature
che mi fa risparmiare più tempo in assoluto dopo la waitlist.

### 37. Gestione no-show 🟡
Round 1 generato e due iscritti non si presentano: oggi devo fare drop manuale uno
a uno e rigenerare. Serve "segna assenti e rigenera round 1" in un click.

### 38. Time extension per tavolo 🟡
Il judge dà +5 minuti al tavolo 7 dopo un ruling: il timer del display deve
mostrarlo. Oggi il timer è unico per il round.

### 39. Correzione risultati post-torneo con audit log 🟡
A torneo chiuso i risultati sono immutabili. Capita di scoprire un errore di
inserimento il giorno dopo: serve una correzione da organizer che ricalcoli le
standings e la leaderboard stagionale, tracciata (chi, quando, cosa).

### 40. Early bird e codici sconto 🟢
Quota ridotta per chi si iscrive entro una data, codici sconto per i regular.
Il campo entry_fee è fisso oggi.

### 41. Statistiche meta 🟢
Nel report manca: archetipi più giocati e win rate per archetipo (i dati ci sono
già nelle registrazioni + risultati). Utile per pre-ordinare il prodotto giusto.

### Punto di vista giocatore

### 42. Storico personale e statistiche 🔴
"Quante ne ho vinte quest'anno?" Oggi vedo solo le iscrizioni attive. Serve una
pagina storico: tornei giocati, record cumulativo, win rate per formato/archetipo,
piazzamenti. I dati sono tutti nel DB.

### 43. Rimborso self-service pre-torneo 🟡
Se non posso più venire venerdì, oggi devo scrivere al negozio. Serve "Annulla
iscrizione" con rimborso automatico se mancano più di N ore all'inizio
(il refund flow backend esiste già, manca il bottone collegato alla policy).

### 44. Decklist avversari a torneo finito 🟡
`decklists_public` esiste come flag ma il giocatore non ha una pagina per
sfogliare le liste degli altri dopo il torneo. È metà del divertimento competitivo.

### 45. Ricevuta di pagamento 🟢
Dopo il checkout non ricevo nulla: serve email con ricevuta (importo, torneo, data)
— vedi #34.

### 46. Bracket Top 8 visibile dalla SPA 🟢
Il bracket esiste nell'organizer tool; il giocatore in Top 8 non lo vede dal
telefono. Esporre /bracket nella pagina evento pubblica.

### Più in là (parcheggiate consapevolmente)

### 47. TODO: Pannello di controllo arbitri 📌 (richiesto, pianificato più avanti)
Vista dedicata per il judge invitato (#26): coda dei tavoli chiamati, ruling log
con timer, penalità rapide per tavolo, time extension (#38), deck check casuale
suggerito. Oggi lo staff usa le stesse pagine dell'organizer — funziona, ma un
pannello focalizzato ridurrebbe gli errori nei tornei competitivi.

### ~~48. Multi-lingua (EN)~~ ✅
`js/i18n.js` con dizionari it/en, attributi `data-i18n`/`data-i18n-placeholder`,
selettore IT/EN nell'header, lingua persistita in localStorage (default dal browser).

### ~~49. Multi-negozio / multi-tenant~~ ✅
Modello `Organization` + `organization_id` su `User`/`Tournament`, org di default
auto-seedata con backfill. Risoluzione tenant via header `X-Manabind-Org` o `?org=slug`
(`core/tenant.py`); il listing pubblico filtra per organizzazione. Router
`/api/organizations` (list/current/create-admin).

---

## Affidabilità operativa (post-incidente startup PostgreSQL — 2026-06-13)

> Contesto: `make prod-restart` falliva con tutti i worker in crash perché PostgreSQL
> (container Docker) non era avviato. Risolto rendendo lo startup robusto, ma l'episodio
> ha evidenziato lacune di "giorno della partita".

### 50. Dipendenza DB esplicita e auto-start 🔴 RISOLTO PARZIALE
`make dev`/`prod-server` ora dipendono da `db-wait` (avvia il container e attende
`pg_isready`), `create_all()` riprova con backoff, e le migrazioni sono serializzate
con advisory lock tra i worker. Resta da fare: **healthcheck dell'app** (endpoint
`/health` che verifica davvero il DB, non solo "il processo è vivo") e un
**systemd/Docker restart policy** in produzione perché i worker si riavviino da soli.

### ~~51. Migrazioni vere (Alembic)~~ ✅
Alembic configurato (`alembic.ini`, `migrations/env.py` legato a `Base.metadata` e a
`settings.database_url`, `render_as_batch` per SQLite). Revisione iniziale autogenerata
con tutte le 18 tabelle. `migrate_existing_schema()` runtime resta come fallback per dev
e per le istanze già in produzione. Uso: `alembic upgrade head`.

### ~~52. Backup automatico del database~~ ✅
`scripts/backup_db.sh` (pg_dump formato custom + retention configurabile), unit
`deploy/manabind-backup.{service,timer}` (giornaliero alle 03:30, Persistent), servizio
`backup` in docker-compose (profilo `backup`), endpoint admin `GET/POST /api/admin/backups`
per listare e triggerare. `postgresql-client` aggiunto all'immagine.

### ~~53. Monitoraggio e alert~~ ✅
**Monitoring**: `core/monitoring.py` con metriche Prometheus (`manabind_http_requests_total`,
`manabind_http_request_duration_seconds`) via middleware, endpoint `/metrics` (protetto
da `METRICS_TOKEN` opzionale), `/health` profondo che verifica DB e backend cache.
**Alerting**: `core/alerting.py` con canali email + Telegram, throttle anti-spam
cross-worker via Redis. Agganciato a: handler globale eccezioni 5xx (in main.py) e
**watchdog** del DB nel lifespan (alert su "DB giù" e su recupero). Endpoint admin
`GET /api/admin/alerting` (stato) e `POST /api/admin/alerting/test`. Regole Prometheus
di secondo livello in `deploy/prometheus-alerts.yml`. No-op graceful se nessun canale
è configurato.

---

## Cosa manca — dal punto di vista dell'ORGANIZZATORE

> "Ho usato il gestionale per qualche torneo. Ecco cosa mi fa ancora perdere tempo o
> mi mette in difficoltà davanti ai giocatori."

- **Onboarding a freddo difficile**: la prima volta non capisco l'ordine delle cose
  (crea torneo → apri iscrizioni → check-in → genera round). Manca una *guida iniziale*
  o uno stato "prossima azione consigliata" sulla dashboard del torneo.
- **Niente annullamento/rinvio torneo con avviso di massa**: se piove e rinvio, devo
  avvisare 40 persone a mano. Serve "Rinvia/Annulla" che manda email+notifica a tutti
  gli iscritti e gestisce i rimborsi in blocco.
- **Correzione errori durante il torneo**: ho sbagliato a digitare un risultato e
  l'ho confermato. Tornare indietro è macchinoso. Serve "modifica risultato" con
  ricalcolo standings e log di chi ha cambiato cosa (collegato a #39).
- **Gestione bye manuale**: a volte voglio dare un bye a una persona specifica
  (è arrivata tardi, accordi presi). Ora il bye è automatico e non controllabile.
- **Stampa elenco iscritti / foglio firme**: per il cartaceo di riserva quando salta
  la rete, voglio un PDF stampabile con nomi e spazio firma.
- **Vista "tavoli liberi"**: a fine round vedo a colpo d'occhio quali tavoli hanno
  ancora consegnato il risultato e quali no, per sollecitare. Oggi devo scorrere tutto.
- **Limite iscrizioni per formato/data e orari**: voglio chiudere le iscrizioni online
  X ore prima e riaprirle al banco. Controllo fine sugli orari manca.

## Cosa manca — dal punto di vista del GIOCATORE

> "Gioco ai tornei del mio negozio col telefono in mano. Ecco cosa mi frustra."

- **Non so MAI quando inizia il mio match**: la notifica c'è solo a pagina aperta.
  Voglio una notifica push vera (#31) o almeno un suono forte e ripetuto, perché tra
  un round e l'altro sono al bar di fianco.
- **Non vedo CONTRO CHI gioco e a quale tavolo in modo immediato**: devo entrare in
  "Le mie iscrizioni", aprire il torneo... Troppi tap. Voglio la mia prossima partita
  in cima, grande, appena apro l'app.
- **Non posso segnalare un problema al giudice dal telefono**: se c'è una disputa devo
  alzare la mano e aspettare. Un bottone "Chiama il giudice al tavolo X" sarebbe oro
  (collegato al pannello arbitri #47).
- **Non vedo il mio storico né i miei progressi**: quante ne ho vinte? Sto salendo in
  classifica stagionale? (#42 lo copre, ma è ancora da fare lato giocatore.)
- **Iscrizione macchinosa da mobile**: il flusso iscrizione→pagamento→decklist su
  telefono ha troppi passaggi e schermate. Va snellito per il pollice.
- **Non ricevo conferme**: mi iscrivo e non arriva niente via email. Non ho la certezza
  di essere dentro finché non controllo l'app (#34/#45 ricevute).
- **Le decklist degli altri dopo il torneo non sono sfogliabili comodamente** (#44):
  metà del divertimento competitivo è vedere cosa giocavano i top.

---

## TODO esplicito del committente

### 📌 Pannello di controllo arbitri (vedi #47) — PIANIFICATO, da fare più in là
Vista dedicata per il giudice: coda chiamate ai tavoli, ruling log con timer, penalità
rapide, time extension per tavolo (#38), deck check casuale. Esplicitamente rimandato
a una fase successiva su indicazione del committente.

---

## Migrazione "tutto online" — ✅ COMPLETATA (V2, 2026-06-14)

> Obiettivo del committente: niente più tool offline (localStorage), tutto via backend,
> accessibile da più PC contemporaneamente. **Il tool offline è stato eliminato**: esiste
> un solo frontend online in `frontend/` (vedi [[project-architecture]]).

### ✅ Tutto online (backend, multi-device)
- **Creazione/gestione tornei** — `organizer.html` (tab Tornei): crea, avvia, chiudi, duplica; scelta metodi pagamento; pubblicazione abbinamenti/classifica; **Classifica anche per i tornei conclusi** (storico).
- **Iscritti** (tab Iscritti): walk-in al banco, segna pagato contanti, check-in, drop, filtro, paginazione.
- **Liste / Annunci / Penalità** — tab dedicate nel back-office (decklist degli iscritti, invio annunci, assegnazione penalità judge).
- **Regia torneo** — `control.html`: timer round (avvia/stop/restart/extend, **non parte all'avvio**), +min per tavolo, inserimento risultati, genera round (cambia tab), vista judge.
- **Classifica e Report** — tab dedicate (standings live, incassi/presenze).
- **Schermi condivisi** — `display.html?t=ID`, `timer.html?t=ID` (timer negativo + per-tavolo, solo server-mode).
- **Lato giocatore** — iscrizione, pagamento (Stripe/PayPal/sandbox), decklist self-service, pairings, **risultati con conferma/contestazione (chiama Judge)**, drop, storico, leaderboard, profilo pubblico.
- **Ricerca tornei** — filtri server-side per nome/formato/data/città/stato.
- **Permessi staff/judge** — gli endpoint timer/risultati/penalità accettano lo staff invitato.

### ℹ️ Note operative
- La cache (`core/cache.py`) è **no-op senza Redis** per evitare stale tra più worker Gunicorn; con `REDIS_URL` torna attiva e condivisa. Vedi [[cache-multiworker-pitfall]].
- Test: pytest 48, vitest 7, E2E Playwright sul flusso online.
