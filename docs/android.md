# L'app Android

Un'**app nativa** in Kotlin e Jetpack Compose, che parla con la stessa API del
sito (`/api`). Dal 25/11/2026: la prima versione del 24/11 era il sito dentro
Chrome (TWA, con Bubblewrap), ma "è praticamente una pagina web", e l'utente ha
scelto l'app nativa.

I comandi sono per **PowerShell**, dalla cartella del progetto:

```powershell
cd "C:\Users\Zero\Documents\Project\Tournament Organizer"
```

**Niente chiavi né password qui**: il repository è pubblico. La chiave di
caricamento sta fuori dal progetto, la sua password nel password manager.

---

## Cosa fa

È il lato del **giocatore**, tutto dentro l'app (dal 25/11/2026 nessuna voce
rimanda al sito, tranne privacy e termini), in quattro schede:

- **Eventi** — la ricerca dei tornei, come `index.html`: per nome, periodo
  (da oggi a un anno), dal vivo od online, **vicino a me** con la distanza
  (la posizione la chiede il telefono, solo approssimativa), tipo di evento,
  formato e livello (REL), e i **conclusi**. La pagina del torneo ha le
  informazioni, "Condividi", il calendario, la mappa, i collegamenti alla
  **manifestazione**, al **negozio** e al **circuito**, "Classifica e
  risultati" da quando è partito, e **l'iscrizione**: Wizards Account o nome
  in gioco se il gioco li vuole, le domande dell'organizzatore, il codice
  sconto e il modo di pagare. Il pagamento online apre Stripe o PayPal in una
  scheda di Chrome dentro l'app; tornati, la pagina si ricarica da sola.
- **Scopri** — i **negozi** (cerca, vicino a me, Premium) con la loro pagina:
  sedi, tornei in programma e giocati; i **circuiti** con regole, classifica e
  tappe; l'**archivio delle liste** (`decklists.html`): filtri per formato,
  piazzamento, periodo, archetipo e carta, il metagame del periodo, e la lista
  aperta da copiare, salvare fra le proprie o seguire fino ai risultati.
- **Iscrizioni** — i tornei a cui si è iscritti, da giocare e conclusi. Dentro
  ognuno, **il torneo dal vivo**: quota ("Paga", o "Non pago: libera il posto"
  per chi aveva scelto di pagare online), check-in, lista (fra quelle salvate,
  incollata o da file; quella consegnata si rilegge per ogni segmento),
  Wizards Account negli eventi ufficiali e nome in gioco online, il turno con
  tavolo e avversario e tutti gli abbinamenti del turno, il risultato da
  mandare, confermare o contestare, la classifica, i risultati pubblici, e
  "Ritirati" o "Annulla l'iscrizione". Mentre il torneo è in corso la
  schermata si aggiorna ogni 30 secondi.
- **Profilo** — accesso con password o con Google, registrazione, password
  dimenticata, uscita, e poi:
  - **Statistiche e storico**: quello che mostra `player.html` di sé, con il
    record per formato e per archetipo e i tornei giocati;
  - **Le mie liste**: l'editor, con la ricerca delle carte, il controllo di
    legalità, "Carica da file" e "Manda a un torneo" a cui si è iscritti;
  - **Segnalazioni**: all'organizzatore di un torneo o al sito, con la
    conversazione, chiudi e riapri;
  - **Account e privacy**: Google collegato o da collegare (anche da qui, con
    lo stesso giro PKCE dell'accesso: `POST /api/auth/google/app/link` dà un
    biglietto, la scheda di Chrome lo porta a Google, il ritorno passa da
    `/api/auth/google/app/link/finish`), la password (l'email per sceglierla),
    i **profili dei figli** ("Usa" fa agire l'app come quel profilo, con
    l'intestazione `X-Act-As` come il sito; una fascia in alto lo ricorda),
    "Scarica i miei dati", "Esci da tutti i dispositivi" ed "Elimina
    l'account".

**La campanella** (dal 25/11/2026) sta in alto nelle quattro schede, col numero
da leggere: è lo stesso storico del sito (`GET /api/notifications`, vedi
`docs/pubblico.md`, "La campanella"), e aprirla le segna come viste. Toccarne
una porta alla schermata giusta: il torneo, il torneo dal vivo fra le
iscrizioni, le segnalazioni.

Le stesse arrivano **fra le notifiche del telefono**, senza Firebase: ogni
quindici minuti WorkManager sveglia `InboxWorker` (`notify/Inbox.kt`), che
chiede al server quelle dopo l'ultima mostrata e le mette sul telefono, nel
canale "Tornei". Non sono istantanee: arrivano entro un quarto d'ora, di più se
il telefono è in risparmio energetico. La prima volta per un account segna solo
il punto da cui partire, così chi installa l'app non riceve lo storico intero.
Da Android 13 il permesso lo si chiede una volta, appena si entra; negato, la
campanella dentro l'app funziona lo stesso. Il giro usa il token dell'app e lo
rinnova come fa l'app aperta: si ferma solo uscendo, o con "Esci da tutti i
dispositivi".

Per averle all'istante servirebbe Firebase Cloud Messaging: un progetto
Firebase, il `google-services.json` nell'app e la chiave del servizio sul
server, che manderebbe a Firebase oltre che al browser.

**Non c'è** il back-office: gli organizzatori usano il sito.

**Le lingue** sono quelle del sito: italiano, inglese, spagnolo, francese e
tedesco, scelte da quella del telefono. I testi dell'app stanno in
`android/app/src/main/res/values*/strings.xml`; i messaggi d'errore del server,
che arrivano in italiano, l'app li traduce con gli stessi
`frontend/locales/*.json` del sito, copiati dentro a ogni compilazione.

**Il QR dell'iscrizione e i link al torneo** (`/event.html?id=…`) aprono l'app,
se è installata, sulla pagina del torneo (con `&iscriviti=1` apre anche
l'iscrizione). Android lo fa solo se il sito la riconosce: vedi "Il legame col
sito".

## Come funziona

| | Produzione | Staging |
|---|---|---|
| Pacchetto | `it.mull2five.app` | `it.mull2five.app.staging` |
| Nome sul telefono | Mull2Five | M2F staging |
| Parla con | `https://mull2five.it` | `https://mull2five-staging.onrender.com` |
| Firmata con | la chiave di Google Play (Play App Signing) | la chiave di debug del PC che la compila |
| Si installa | da Google Play | a mano, dall'APK |

Le due app hanno pacchetti diversi, quindi stanno sullo stesso telefono. Serve
Android 8.0 o più recente (`minSdk` 26).

**La sessione** è la stessa del sito: lo stesso token, tenuto nelle preferenze
private dell'app. A ogni ritorno nell'app, passata mezza giornata, se ne chiede
uno nuovo; se il server risponde 401, l'app esce.

**L'accesso con Google** non può usare il giro del sito, che passa il risultato
con un cookie del browser: la scheda di Chrome il cookie non lo dà all'app.
Così l'app fa un giro suo, con PKCE (RFC 7636), in `routers/google_auth.py`:

1. l'app inventa un segreto e apre in una scheda di Chrome
   `GET /api/auth/google/app/start?app=<pacchetto>&challenge=<hash del segreto>`;
2. da lì si va da Google e si torna alla `/callback` di sempre, che invece di
   tornare al sito rimanda a `<pacchetto>://google?code=…` (o `?error=…`): un
   indirizzo che apre solo l'app;
3. l'app ritira il token con `POST /api/auth/google/app/finish`, mandando il
   `code` e il segreto; per un account nuovo, completa con
   `POST /api/auth/google/app/complete` (età e termini, come sul sito).

Il `code` da solo non serve a niente: un'altra app che lo intercettasse non ha
il segreto. I pacchetti accettati sono solo i due della tabella
(`APP_PACKAGES`). Su Google Cloud non cambia niente: l'indirizzo di ritorno che
Google conosce resta quello del sito.

## Cosa c'è nel repository

| Percorso | A cosa serve |
|---|---|
| `android/app/src/main/java/it/mull2five/app/` | Il codice: `data/` (API, sessione, modelli), `ui/` (le schermate) |
| `android/app/src/main/res/` | Testi, icone, tema |
| `android/app/build.gradle.kts` | Versione, ambienti, firma, librerie |
| `android/app/src/test/` | I test che girano sul PC, senza telefono |
| `android/strumenti.ps1` | Installa JDK 17 e Android SDK, una volta per PC |
| `android/compila.ps1` | Compila, firma, stampa l'impronta, installa |
| `android/gradlew.bat`, `android/gradle/` | Gradle, a una versione fissa (8.11.1) |

`android/.gitignore` tiene fuori quello che Gradle rigenera, gli APK e gli AAB,
e ogni `*.jks` e `*.keystore`.

Per lavorarci con Android Studio si apre la cartella `android`.

## La prima volta su un PC

Servono circa 1,5 GB:

```powershell
powershell -ExecutionPolicy Bypass -File android\strumenti.ps1
```

Scarica il JDK 17 (Temurin, 64 bit) e l'Android SDK in
`%USERPROFILE%\.bubblewrap` (il nome viene dalla prima versione dell'app; non
serve più Bubblewrap), e scrive `%USERPROFILE%\.bubblewrap\config.json`, che
`compila.ps1` legge. **Chiede di accettare la licenza dell'Android SDK**
(https://developer.android.com/studio/terms): si risponde `y`. Con
`-AccettoLicenzeSdk` la accetta senza chiedere. Rilanciato, salta quello che
c'è già.

Gli strumenti dell'SDK sono fermi alla 19.0: dalla 23.0 `sdkmanager` è diventato
la "Android CLI", che non capisce i nomi dei pacchetti, scarica 300 MB in
`%USERPROFILE%\.android` ed esce con 0 anche quando non ha installato niente
(24/11/2026).

## L'app di prova (staging)

```powershell
powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente staging
```

La prima volta Gradle scarica sé stesso e le sue librerie: qualche minuto. Esce
`android\mull2five-staging.apk`, e lo script stampa l'impronta della firma.

**Installarla sul telefono**, in uno di due modi:
- copiare l'APK sul telefono e aprirlo (Android chiede di permettere
  l'installazione da quell'app: si permette solo per questa volta);
- con il cavo e il *Debug USB* acceso (Impostazioni → Info sul telefono → sette
  tocchi su *Numero build* → Opzioni sviluppatore → Debug USB):
  ```powershell
  powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente staging -Installa
  ```

Lo staging è sul piano gratuito e **si addormenta** dopo 15 minuti: dopo una
pausa la prima richiesta può non rispondere in tempo, e l'app dice "Nessuna
connessione". Un minuto, e "Riprova".

Perché i link allo staging aprano l'app, l'impronta va detta allo staging (la
prima volta su ogni PC): Render → `mull2five-staging` → *Environment* →
`ANDROID_CERT_FINGERPRINTS`, dopo una virgola se c'è già quella di un altro PC.

## L'app vera sul telefono, senza Google Play

Per provare l'app di produzione (`it.mull2five.app`, parla con `mull2five.it`)
prima che ci sia Google Play, la si firma con la chiave di debug come lo staging:

```powershell
powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente produzione -ChiaveDebug
```

Esce `android\mull2five-produzione-debug.apk`. Quando arriverà quella di Google
Play, questa va **disinstallata** prima: la firma è diversa e Android non la
sovrascrive. Lo stesso vale per la prima versione (il sito dentro Chrome),
se è ancora sul telefono: si disinstalla, poi si installa questa.

## Con l'API di sviluppo, dall'emulatore

Con l'API accesa sul PC (`docs/comandi.md`, "Lavorare in locale") e un
emulatore di Android Studio:

```powershell
powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente staging -Api http://10.0.2.2:8000 -Installa
```

`10.0.2.2` è il PC visto dall'emulatore. Solo con `-Api http://…` l'app accetta
indirizzi senza HTTPS. L'accesso con Google in locale non va: Google rimanda a
`localhost:5173`, che dall'emulatore non è il PC.

## I test

```powershell
cd android; .\gradlew.bat testProduzioneDebugUnitTest; cd ..
```

Prima, `JAVA_HOME` e `ANDROID_HOME` come li mette `compila.ps1`:

```powershell
$c = Get-Content "$HOME\.bubblewrap\config.json" -Raw | ConvertFrom-Json; $env:JAVA_HOME = $c.jdkPath; $env:ANDROID_HOME = $c.androidSdkPath
```

Il giro dell'accesso con Google lato server lo provano i test del backend
(`tests/test_google_login.py`, quelli con `app`, anche il collegamento
dall'account). La lettura delle liste (`DeckLines`, la stessa regola di
`frontend/js/deck-view.js`) ha i suoi test nell'app.

**Un endpoint che l'app usa si allarga, non si cambia**: l'app installata resta
indietro finché non si aggiorna. Se un campo di una risposta cambia nome, i
modelli in `data/*Models.kt` lo leggono come assente (prendono il valore di
partenza) senza errori: quando si tocca una risposta usata dall'app, si
controlla che il nome in `@SerialName` sia ancora quello.

## Pubblicare su Google Play

### Una volta sola: l'account

1. **Account sviluppatore** su https://play.google.com/console/signup: 25 $ una
   tantum e la verifica dell'identità.
   - Un account **personale** nuovo, prima di poter pubblicare, deve fare un
     **test chiuso con almeno 12 tester per 14 giorni di fila**. Solo dopo si
     chiede l'accesso alla produzione.
   - Un account **organizzazione** salta il test, ma vuole il numero D-U-N-S
     dell'azienda.
2. **La privacy policy**: Google Play vuole il suo indirizzo
   (`https://mull2five.it/privacy.html`). Oggi è una bozza in attesa del legale
   (`CLAUDE.md`, "Cosa resta", punto 1).

### Una volta sola: la chiave di caricamento

Firma i pacchetti che si caricano su Google Play. Google li rifirma con la sua
chiave (*Play App Signing*), quindi se questa si perde si può farla
sostituire dall'assistenza di Google Play, senza perdere l'app. Si crea fuori dal
progetto, e la password la sceglie chi la crea:

```powershell
New-Item -ItemType Directory -Force "$HOME\.mull2five" | Out-Null
```
```powershell
& "$((Get-Content "$HOME\.bubblewrap\config.json" -Raw | ConvertFrom-Json).jdkPath)\bin\keytool.exe" -genkeypair -v -keystore "$HOME\.mull2five\mull2five-upload.jks" -alias upload -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Mull2Five"
```

`keytool` chiede la password due volte. Il file
`%USERPROFILE%\.mull2five\mull2five-upload.jks` va copiato nel backup, la
password nel password manager. Percorso e alias sono quelli che
`compila.ps1` e `android/app/build.gradle.kts` si aspettano; per usarne altri,
prima di compilare: `$env:M2F_KEYSTORE = "…"` e `$env:M2F_KEY_ALIAS = "…"`.

### Compilare

```powershell
powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente produzione
```

Lo script chiede la password della chiave (una volta: con il `keytool` di oggi
*keystore* e *key* hanno la stessa) e la passa a Gradle solo per quella
compilazione. Escono, in `android\`:
- `mull2five-produzione.aab` — quello da caricare su Google Play;
- `mull2five-produzione.apk` — per provarlo sul telefono prima di caricarlo.

**Ogni caricamento vuole una versione più alta.** Prima di compilare un
aggiornamento si alzano `versionCode` (2, 3, 4…: l'1 era la prima versione) e
`versionName` ("2.0.1"…) in `android/app/build.gradle.kts`, e si fa il commit.

### Il primo caricamento

1. Play Console → *Crea app*: nome **Mull2Five**, lingua predefinita italiano,
   app, gratuita.
2. *Test e rilascio* → *Test chiuso* (con l'account personale) → nuova versione
   → carica `mull2five-produzione.aab`. La firma la lascia gestire a Google Play
   (è la scelta proposta).
3. I tester: una lista di email o un gruppo Google, e il link di adesione da
   mandare loro. Servono 12 tester che restino iscritti per 14 giorni.
4. Le schede da compilare prima di uscire:
   - **Accesso all'app**: alcune parti vogliono un account; si dà a Google un
     account di prova creato apposta sul sito di produzione;
   - **Sicurezza dei dati**: cosa raccoglie il sito, coerente con
     `privacy.html`; l'app non raccoglie la posizione;
   - **Pubblico di destinazione**: dai 14 anni in su, come i termini (sotto i 13
     scattano le regole per le famiglie);
   - classificazione dei contenuti, pubblicità (nessuna), scheda dello store:
     descrizione breve e lunga, icona 512×512 (`frontend/public/icon-512.png`),
     immagine in evidenza 1024×500, almeno due schermate del telefono.
5. Dopo i 14 giorni: *Richiedi l'accesso alla produzione*.

### Il legame col sito

Perché i link a `/event.html` (e i QR dell'iscrizione) aprano l'app, Android
controlla `/.well-known/assetlinks.json` del sito: deve nominare il pacchetto e
l'impronta SHA-256 del certificato con cui l'app è firmata. Lo scrive il backend
(`routers/site.py`, `asset_links`) da due variabili su Render:

- `ANDROID_PACKAGE` — il pacchetto: vuota in produzione (vale
  `it.mull2five.app`), `it.mull2five.app.staging` sullo staging;
- `ANDROID_CERT_FINGERPRINTS` — le impronte, separate da virgola.

Senza, i link si aprono nel browser come sempre: l'app funziona lo stesso.

L'app scaricata da Google Play è firmata con la chiave di Google, non con la
nostra: è quella che il sito deve conoscere.

1. Play Console → *Test e rilascio* → *Integrità dell'app* → *Firma dell'app*:
   ci sono due impronte SHA-256, quella del **certificato della chiave di firma
   dell'app** (di Google) e quella del **certificato della chiave di
   caricamento** (la nostra).
2. Render → `mull2five` → *Environment* → `ANDROID_CERT_FINGERPRINTS`: tutte e
   due, separate da una virgola (più quelle di debug finché servono). Salvato,
   il servizio riparte.
3. Controllo:
   ```powershell
   Invoke-RestMethod https://mull2five.it/.well-known/assetlinks.json | ConvertTo-Json -Depth 5
   ```
   Deve comparire `it.mull2five.app` con le impronte. In Play Console,
   *Deep link* dice se il dominio risulta verificato.

## Aggiornare

**Ogni anno, ad agosto**, Google Play chiede un `targetSdk` più recente. Si
alzano `compileSdk` e `targetSdk` in `android/app/build.gradle.kts`, la
piattaforma in `android/strumenti.ps1` (`$platform`), e di solito il plugin
Android in `android/build.gradle.kts` (e Gradle in
`android/gradle/wrapper/gradle-wrapper.properties`, alla versione che il plugin
vuole). Si rilancia `strumenti.ps1`, si compila lo staging e lo si prova sul
telefono, poi la produzione con la versione alzata.

**Quando cambia l'API.** L'app è un client come il sito: se un endpoint che usa
cambia forma (`android/app/src/main/java/it/mull2five/app/data/Api.kt` e
`Models.kt`), l'app installata smette di capirlo finché non si aggiorna. Si
aggiungono campi, non si tolgono né si rinominano; i campi nuovi l'app li
ignora.

## Quando qualcosa non va

| Sintomo | Perché | Cosa fare |
|---|---|---|
| Il link a un torneo apre il browser, non l'app | Il sito non riconosce la firma dell'app | `assetlinks.json` (comando sopra): pacchetto giusto? Impronta giusta? L'APK compilato su un altro PC ha un'altra chiave di debug; quella di Google Play ha l'impronta della *chiave di firma dell'app*. Corretto Render, Android ricontrolla quando l'app si reinstalla o si aggiorna |
| "Nessuna connessione" sullo staging | Lo staging dormiva | Un minuto, poi "Riprova" |
| Le notifiche non arrivano sul telefono, ma la campanella nell'app sì | Permesso negato, canale "Tornei" spento, o il risparmio energetico ferma il giro | Impostazioni di Android → App → Mull2Five → Notifiche; per la batteria, "Senza restrizioni". Il giro passa ogni 15 minuti, non subito |
| *Accesso con Google non è attivo* | Il servizio non ha `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` | `docs/hosting.md`, "Accesso con Google" |
| `compila.ps1`: *Manca …config.json* | Strumenti mai installati su questo PC | `android\strumenti.ps1` |
| `compila.ps1`: *Manca la chiave di caricamento* | La chiave non è in `%USERPROFILE%\.mull2five` | Si ripristina dal backup, o si indica con `$env:M2F_KEYSTORE` |
| `adb install` fallisce con `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | Sul telefono c'è la stessa app firmata con un'altra chiave (un altro PC, Google Play, o la prima versione) | Si disinstalla quella e si riprova |
