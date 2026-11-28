# CODE.MD — Stato del lavoro

Ultimo aggiornamento: 27 novembre 2026.

Questo file raccoglie quello che è stato fatto e quello che resta da fare sul
bug del negozio che restava pubblico dopo l'eliminazione dell'account, sulle
notifiche Android e sui dati massivi di staging usati per provare le leghe.

---

## 1. Stato in breve

- Il bug del negozio è corretto, testato e deployato su **staging**.
- Le notifiche istantanee Firebase sono state provate sull'emulatore Android:
  la prima notifica dopo il login ora arriva.
- **La produzione non è stata toccata.** `main` resta a `b522b74`, schema
  `0014`; il fix arriverà solo con il prossimo rilascio.
- Resta aperto un caso: i tornei futuri di un negozio chiuso restano pubblici,
  iscrivibili e pagabili.

Ambienti:

| Ambiente | Branch | Commit | Schema |
|---|---|---|---|
| Staging | `develop` | `80bbf62` | `0017_store_closed_at` |
| Produzione | `main` | `b522b74` | `0014_season_scoring` |

---

## 2. Cosa è stato fatto

### 2.1 Chiusura del negozio quando l'organizzatore elimina l'account

Prima, eliminando l'account di un organizzatore, il negozio creato
automaticamente restava pubblico con il nome dell'account eliminato.

Ora:

- se il negozio non ha altri membri attivi, viene **chiuso**;
- se restano altri membri attivi, il negozio **continua** e la titolarità passa
  al membro attivo più anziano;
- il negozio di default non viene mai chiuso;
- i negozi chiusi non compaiono più:
  - nell'elenco pubblico `/api/organizations`;
  - nella pagina pubblica del negozio;
  - nella sitemap.

Alla chiusura:

- nome e slug diventano anonimi (`Negozio chiuso`,
  `negozio-chiuso-<id>`);
- vengono cancellati descrizione, città, indirizzo, sito, logo e coordinate;
- viene cancellata l'email PayPal;
- vengono cancellate le sedi del negozio;
- i tornei restano, con luogo e coordinate copiati nel torneo;
- i riferimenti agli incassi restano sui pagamenti, perché servono ai rimborsi.

### 2.2 Migrazione `0017_store_closed_at`

La migrazione:

- aggiunge `organizations.closed_at`;
- chiude i negozi già rimasti orfani, cioè quelli con membri ma senza nessun
  account attivo;
- fa lo stesso lavoro di `close_store`: anonimizza il negozio, cancella le
  sedi, conserva luogo e coordinate dei tornei;
- è idempotente: può essere rieseguita su un database già aggiornato.

La migrazione parte da `0016_device_tokens`.

### 2.3 Notifiche Android

Trovato un bug nell'app: al login veniva aggiornato solo il contatore della
campanella, non il punto di partenza delle notifiche. Il primo messaggio
ricevuto diventava quindi il punto di partenza e non veniva mostrato.

Correzione in `AppRoot.kt`: `showNew()` viene chiamato **prima** di
`registerDevice()`, così il punto di partenza viene segnato subito al login.

### 2.4 Privacy: email PayPal

`close_store()` ora azzera anche `paypal_email`. Non serve ai rimborsi: quelli
usano il payee salvato sul singolo pagamento.

### 2.5 Pulizia staging

- Eliminati i tornei di prova 18, 19 e 20.
- Eliminati gli account di prova 75, 76 e 77.
- Eliminati i file temporanei con token e credenziali di prova.
- Restano solo i 3 negozi reali già presenti (prima dei dati BULK27).

### 2.6 Dati massivi per le leghe (staging)

Creati via API con `scripts/seed_bulk_staging.py`, codice `BULK27`:

- 2 negozi con una sede ciascuno: Fumetteria Drago (Milano) e Fumetteria
  Fenice (Torino);
- pool di 128 giocatori `bulk.bulk27.p001@example.com` …
  `bulk.bulk27.p128@example.com`, senza password, creati dall'import iscritti;
- 10 tornei da 32 iscritti, 5 per negozio, su formati diversi:
  - Drago: Standard, Pioneer, Modern, Legacy, Pauper;
  - Fenice: Vintage, Premodern, Commander, Sealed, Draft;
- 32 decklist valide per torneo (320 in totale);
- 5 turni svizzeri con risultati casuali; tutti i tornei sono conclusi;
- 2 circuiti con scarto del peggior risultato dopo 4 tappe:
  - `[BULK27] Lega Drago`, tornei 21–25;
  - `[BULK27] Lega Fenice`, tornei 26–30;
- date dal 19/09/2026 al 18/10/2026, così i tornei sono passati.

Lo script è ripartibile: salta i tornei già conclusi e riprende quelli avviati.
Le email sono su `example.com`: non esistono e non ricevono posta. La password
degli organizzatori è `BulkTest2026!`.

### 2.7 Liste reali per il metashare (staging)

Secondo test massivo, codice `META27`, con liste vere prese da MTGTop8
(metagame delle ultime due settimane):

- 5 tornei Modern (31–35) e 5 Standard (36–40), 32 iscritti ciascuno;
- 320 liste reali (160 per formato), tutte valide e con sideboard;
- ogni giocatore tiene la stessa lista per tutta la lega;
- 10 archetipi per formato, distribuiti secondo il meta reale:
  - Modern: Broodscale Bloodchief e Rakdos Aggro 15,6%, Boros Aggro 12,5%,
    Affinity, Amulet Titan, Mono Black Aggro e UR Aggro 9,4%, Creatures
    Toolbox, Instant Reanimator e UrzaTron 6,2%;
  - Standard: Selesnya Aggro 15,6%, Dimir Control 12,5%, 4/5C Control,
    Azorius Aggro, Boros Aggro, Izzet Control, Jund Aggro, Mardu Aggro e
    UW Control 9,4%, Dimir Aggro 6,2%;
- 2 circuiti con scarto del peggior risultato dopo 4 tappe:
  - `[META27] Lega Modern`, tornei 31–35;
  - `[META27] Lega Standard`, tornei 36–40;
- date dal 06/10/2026 al 04/11/2026.

Le liste finte BULK27 di Modern e Standard sono state nascoste dall'archivio
(`decklists_public = false`), così il metashare mostra solo le liste vere.
I tornei BULK27 restano, con classifiche e circuiti.

---

## 3. Verifiche fatte

### Backend

- Suite completa: `600 passed, 1 skipped`.
- Ruff: nessun errore.
- 5 test nuovi in `tests/test_store_closure.py`:
  - chiusura del negozio con un solo organizzatore;
  - passaggio di titolarità al membro più anziano;
  - eliminazione di un membro senza chiusura del negozio;
  - nessun negozio nuovo per un account eliminato;
  - migrazione sui negozi già orfani.

### Staging

- `/health` riporta commit `80bbf62`, schema `0017_store_closed_at`.
- Il vecchio negozio orfano “Prova notifiche” non è più pubblico.
- Il negozio di prova si è chiuso dopo l'eliminazione dell'organizzatore:
  - profilo `404`;
  - assente dall'elenco;
  - assente dalla sitemap.
- I tornei 18, 19 e 20 rispondono `404`.
- Nessuna traccia dei negozi di prova nella sitemap.
- Dati BULK27 verificati dalle API:
  - 10 tornei conclusi, 32 iscritti e 32 liste valide ciascuno;
  - 50 turni e 800 abbinamenti, tutti con risultato;
  - 128 giocatori distinti, 2–3 presenze a testa;
  - classifiche da 32 righe per torneo;
  - 2 circuiti da 80 giocatori e 160 presenze ciascuno, 5 titoli, pagina
    pubblica raggiungibile.
- Gli scarti delle leghe sono a 0: con 3 tappe a testa nessuno supera la
  soglia di 4, quindi la regola non scatta (comportamento atteso).
- Dati META27 verificati dalle API:
  - 10 tornei conclusi, 32 iscritti e 32 liste valide ciascuno;
  - 50 turni, tutti con risultato;
  - 2 circuiti da 32 giocatori e 160 presenze ciascuno, 5 titoli;
  - scarto del peggior risultato applicato a tutti (5 tappe a testa);
  - archivio: 160 liste Modern e 160 Standard, 10 archetipi per formato;
  - metashare globale pulito: le liste finte BULK27 non compaiono.

### Android / Firebase

- APK staging ricompilato e installato sull'emulatore `m2f`
  (Android 35, Google APIs, x86_64).
- Login pulito con account nuovo.
- Prima notifica dopo il login pubblicata correttamente:
  - titolo: “Registration confirmed”;
  - testo: “Serata prova notifiche 2”;
  - id notifica: 6.
- Tap sulla notifica: apre la pagina del torneo.
- Il primo tentativo era stato negato dal permesso notifiche; con il permesso
  concesso il retest è passato.

---

## 4. Cosa resta da fare

### 4.1 Rilascio in produzione

Da fare quando si decide di rilasciare:

- [ ] merge `develop` → `main`;
- [ ] CI verde;
- [ ] deploy automatico della produzione;
- [ ] verificare `/health`: schema `0017_store_closed_at`;
- [ ] verificare che gli eventuali negozi orfani di produzione siano chiusi;
- [ ] verificare elenco negozi, profili e sitemap;
- [ ] provare una notifica reale sull'app di produzione.

Prima del rilascio, controllare sul servizio Render di produzione:

- [ ] `FCM_SERVICE_ACCOUNT` presente e valido;
- [ ] `ANDROID_CERT_FINGERPRINTS` aggiornate per l'app di produzione;
- [ ] `SECRET_KEY` adeguata.

Nota: la produzione non ha ancora la funzione “un negozio per organizzatore”,
quindi il leak non è live lì. Il fix deve però partire insieme a quella
funzione.

### 4.2 Tornei futuri dei negozi chiusi

Problema noto, ancora aperto: un negozio chiuso sparisce da elenco, profilo e
sitemap, ma i suoi tornei futuri restano pubblici, iscrivibili e pagabili.

Per chiuderli davvero serve:

- [ ] annullare i tornei futuri del negozio chiuso;
- [ ] rimborsare le iscrizioni già pagate;
- [ ] avvisare gli iscritti;
- [ ] escluderli da elenchi e sitemap;
- [ ] impedire nuove iscrizioni e nuovi pagamenti.

È il lavoro successivo più importante.

### 4.3 Opzionali

- [ ] Test su un telefono Android fisico: l'emulatore ha funzionato, ma un
      dispositivo reale non è ancora stato provato.
- [ ] Allungare la `SECRET_KEY` di staging: il log avvisa che è corta. È
      innocuo su staging, ma è meglio sistemarlo.
- [ ] Rimuovere emulatore e immagine Android se non servono più: occupano
      spazio su disco.
- [ ] Rimuovere i dati BULK27 dallo staging quando non servono più: 2 negozi,
      128 account, 10 tornei e 2 circuiti.
- [ ] Rimuovere i dati META27 quando non servono più: 10 tornei, 2 circuiti
      e le 320 liste reali (prima di eliminare i negozi BULK27).

---

## 5. Commit

Sul branch `develop`:

| Commit | Contenuto |
|---|---|
| `0a2135f` | Chiusura del negozio quando l'ultimo organizzatore elimina l'account |
| `e6969ae` | App: la prima notifica dopo l'accesso non si perde più |
| `80bbf62` | Il negozio chiuso non tiene l'email PayPal di chi se n'è andato |

`main` non è stata toccata.

I dati massivi BULK27 e questo file sono stati aggiunti con un commit successivo
sempre su `develop`.

---

## 6. File toccati

Backend:

- `backend/app/models.py` — colonna `Organization.closed_at`;
- `backend/app/services/stores.py` — `close_store`, `leave_stores`,
  filtro account attivi, azzeramento email PayPal;
- `backend/app/routers/auth.py` — chiamata a `leave_stores` e invalidazione
  cache;
- `backend/app/routers/organizations.py` — esclusione negozi chiusi da elenco
  e profilo;
- `backend/app/routers/site.py` — esclusione negozi chiusi dalla sitemap;
- `migrations/versions/0017_store_closed_at.py` — colonna e backfill;
- `tests/test_store_closure.py` — test del comportamento e della migrazione.

Android:

- `android/app/src/main/java/it/mull2five/app/ui/AppRoot.kt` — `showNew()`
  prima di `registerDevice()`.

Strumenti:

- `scripts/seed_bulk_staging.py` — generatore dei dati massivi BULK27;
- `scripts/seed_meta_staging.py` — generatore dei dati reali META27;
- `scripts/data/mtgtop8_decks.json` — 64 liste reali Modern/Standard;
- `CODE.MD` — questo stato del lavoro.

---

## 7. Regole di comportamento

- Un negozio senza membri attivi viene chiuso solo se non è il negozio di
  default.
- Se restano membri attivi, il negozio non si chiude.
- Se nessun membro rimasto è titolare, lo diventa il più anziano.
- Un account eliminato non riceve un negozio nuovo all'avvio.
- I negozi chiusi restano nel database per lo storico dei tornei, ma non sono
  più raggiungibili pubblicamente.
- I tornei di un negozio chiuso conservano il luogo scritto, anche dopo la
  cancellazione delle sedi.
