# L'app Android

L'app **è il sito**, aperto da Chrome a schermo intero: una *Trusted Web
Activity* (TWA), costruita con [Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap).
Deciso il 24/11/2026, scartando Capacitor e un'app nativa: con un solo codice,
ogni deploy aggiorna anche l'app, e le due cose difficili — l'accesso con Google
e le notifiche — funzionano già così. In una WebView (Capacitor) Google rifiuta
l'accesso, e le notifiche andrebbero rifatte con Firebase.

I comandi sono per **PowerShell**, dalla cartella del progetto:

```powershell
cd "C:\Users\Zero\Documents\Project\Tournament Organizer"
```

**Niente chiavi né password qui**: il repository è pubblico. La chiave di
caricamento sta fuori dal progetto, la sua password nel password manager.

---

## Come funziona

| | Produzione | Staging |
|---|---|---|
| Pacchetto | `it.mull2five.app` | `it.mull2five.app.staging` |
| Apre | `https://mull2five.it` | `https://mull2five-staging.onrender.com` |
| Firmata con | la chiave di Google Play (Play App Signing) | la chiave di debug del PC che la compila |
| Si installa | da Google Play | a mano, dall'APK |

Le due app hanno pacchetti diversi, quindi stanno sullo stesso telefono. Serve
Android 7.0 o più recente (`minSdkVersion` 24: meno di così la libreria di Google
per le TWA non compila).

**La barra dell'indirizzo.** Chrome apre l'app a schermo intero solo se il sito
la riconosce: `/.well-known/assetlinks.json` deve nominare il pacchetto e
l'impronta SHA-256 del certificato con cui l'app è firmata. Lo scrive il backend
(`routers/site.py`, `asset_links`) da due variabili su Render:

- `ANDROID_PACKAGE` — il pacchetto; in produzione resta quello predefinito
  (`it.mull2five.app`), lo staging ha `it.mull2five.app.staging`;
- `ANDROID_CERT_FINGERPRINTS` — le impronte, separate da virgola.

Senza impronte la risposta è `[]`: l'app si apre lo stesso, ma con la barra
dell'indirizzo in cima, come una scheda qualsiasi. Non si rompe niente.

**Cosa funziona come sul sito.**
- **Accesso**, con la password e con Google: per Google è Chrome, non una
  WebView, e lo lascia passare.
- **Pagamenti**: le pagine di Stripe e PayPal si aprono con la loro barra in
  cima, perché sono un altro dominio; tornati sul sito, la barra sparisce.
- **Notifiche**: è il Web Push che c'è già (`sw.js`, `push.js`), consegnato
  all'app. Da Android 13 il permesso lo chiede l'app. L'icona piccola delle
  notifiche è `icon-monochrome-512.png`: Android la disegna in un colore solo, e
  un'icona piena diventerebbe un quadrato.
- **Posizione** ("Usa la mia posizione"): il permesso lo chiede l'app.
- **I link al sito**, compresi i QR dell'iscrizione, aprono l'app se è
  installata: lo stesso `assetlinks.json` vale anche per questo.
- Tenendo premuta l'icona compaiono due scorciatoie: **Cerca eventi** e
  **Le mie iscrizioni**.

Senza Chrome (o un altro browser che sappia fare da TWA) l'app apre il sito in
una *Custom Tab*, con la barra.

**Quando va ricompilata.** Quasi mai: le pagine arrivano dal sito, quindi un
deploy aggiorna l'app da solo. Si ricompila solo se cambiano nome, icone,
colori, scorciatoie o pacchetto, per un Bubblewrap nuovo, e quando Google Play
chiede un `targetSdk` più recente (una volta l'anno, ad agosto).

## Cosa c'è nel repository

| File | A cosa serve |
|---|---|
| `android/produzione/twa-manifest.json` | La descrizione dell'app vera: pacchetto, indirizzo, icone, colori, versione, chiave |
| `android/staging/twa-manifest.json` | La stessa, per l'app di prova sullo staging |
| `android/strumenti.ps1` | Installa JDK 17 e Android SDK, una volta per PC |
| `android/compila.ps1` | Rifà il progetto Gradle dal `twa-manifest.json` e lo compila |
| `android/package.json` | Bubblewrap, a una versione fissa (1.27.0) |

Il progetto Gradle **non** sta nel repository: `compila.ps1` lo rigenera ogni
volta da `twa-manifest.json` (lo ignora `android/.gitignore`, insieme a ogni
`*.jks` e `*.keystore`). Per cambiare l'app si cambia il `twa-manifest.json`.

## La prima volta su un PC

Servono Node.js (c'è già per il frontend) e circa 1 GB:

```powershell
powershell -ExecutionPolicy Bypass -File android\strumenti.ps1
```

Scarica il JDK 17 (Temurin, 64 bit) e l'Android SDK in
`%USERPROFILE%\.bubblewrap`, e scrive `%USERPROFILE%\.bubblewrap\config.json`,
che Bubblewrap legge. **Chiede di accettare la licenza dell'Android SDK**
(https://developer.android.com/studio/terms): si risponde `y`. Con
`-AccettoLicenzeSdk` la accetta senza chiedere. Rilanciato, salta quello che
c'è già.

Perché non lo fa Bubblewrap da solo: su Windows prende un JDK a 32 bit, con cui
Gradle resta senza memoria. E perché gli strumenti dell'SDK sono fermi alla
19.0: dalla 23.0 `sdkmanager` è diventato la "Android CLI", che non capisce i
nomi dei pacchetti, scarica 300 MB in `%USERPROFILE%\.android` ed esce con 0
anche quando non ha installato niente (24/11/2026).

## L'app di prova (staging)

```powershell
powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente staging
```

La prima volta Gradle scarica sé stesso e le sue librerie: qualche minuto. Esce
`android\staging\mull2five-staging.apk`, e lo script stampa l'impronta della
chiave di debug di questo PC.

**La prima volta su un PC**, quell'impronta va detta allo staging: Render →
`mull2five-staging` → *Environment* → `ANDROID_CERT_FINGERPRINTS`. Se c'è già
quella di un altro PC, si aggiunge dopo una virgola. Salvato, il servizio
riparte. Per controllare:

```powershell
Invoke-RestMethod https://mull2five-staging.onrender.com/.well-known/assetlinks.json | ConvertTo-Json -Depth 5
```

**Installarla sul telefono**, in uno di due modi:
- copiare l'APK sul telefono e aprirlo (Android chiede di permettere
  l'installazione da quell'app: si permette solo per questa volta);
- con il cavo e il *Debug USB* acceso (Impostazioni → Info sul telefono → sette
  tocchi su *Numero build* → Opzioni sviluppatore → Debug USB):
  ```powershell
  powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente staging -Installa
  ```

Lo staging è sul piano gratuito e **si addormenta** dopo 15 minuti: la prima
apertura dopo una pausa resta sulla schermata iniziale per un minuto circa.

## L'app vera sul telefono, senza Google Play

Per provare l'app di produzione (`it.mull2five.app`, apre `mull2five.it`) prima
che ci sia Google Play, la si firma con la chiave di debug come lo staging:

```powershell
powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente produzione -ChiaveDebug
```

Esce `android\produzione\mull2five-produzione-debug.apk`, e lo script stampa
l'impronta: va in `ANDROID_CERT_FINGERPRINTS` del servizio `mull2five`, accanto
alle altre. Due cose da sapere:
- quando arriverà quella di Google Play, questa va **disinstallata** prima: la
  firma è diversa e Android non la sovrascrive;
- arrivate le impronte della Play Console, quella di debug si toglie da Render.

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
password nel password manager. Il percorso e l'alias (`upload`) sono quelli
scritti in `android/produzione/twa-manifest.json`, sotto `signingKey`.

### Compilare

Il sito di produzione deve avere già le icone di questo commit (il merge in
`main` fatto e pubblicato), perché Bubblewrap le scarica da lì.

```powershell
powershell -ExecutionPolicy Bypass -File android\compila.ps1 -Ambiente produzione
```

Bubblewrap chiede la password della chiave due volte (*keystore* e *key*: con
`keytool` di oggi sono la stessa). Escono, in `android\produzione\`:
- `app-release-bundle.aab` — quello da caricare su Google Play;
- `app-release-signed.apk` — per provarlo sul telefono prima di caricarlo.

**Ogni caricamento vuole una versione più alta.** Prima di compilare un
aggiornamento si alzano `appVersionCode` (1, 2, 3…) e `appVersion` ("1.0.1"…)
in `android/produzione/twa-manifest.json`, e si fa il commit.

### Il primo caricamento

1. Play Console → *Crea app*: nome **Mull2Five**, lingua predefinita italiano,
   app, gratuita.
2. *Test e rilascio* → *Test chiuso* (con l'account personale) → nuova versione
   → carica `app-release-bundle.aab`. La firma la lascia gestire a Google Play
   (è la scelta proposta).
3. I tester: una lista di email o un gruppo Google, e il link di adesione da
   mandare loro. Servono 12 tester che restino iscritti per 14 giorni.
4. Le schede da compilare prima di uscire:
   - **Accesso all'app**: alcune parti vogliono un account; si dà a Google un
     account di prova creato apposta sul sito di produzione;
   - **Sicurezza dei dati**: cosa raccoglie il sito, coerente con
     `privacy.html`; la posizione non si raccoglie, resta sul telefono;
   - **Pubblico di destinazione**: dai 14 anni in su, come i termini (sotto i 13
     scattano le regole per le famiglie);
   - classificazione dei contenuti, pubblicità (nessuna), scheda dello store:
     descrizione breve e lunga, icona 512×512 (`android\produzione\store_icon.png`,
     la genera Bubblewrap), immagine in evidenza 1024×500, almeno due
     schermate del telefono.
5. Dopo i 14 giorni: *Richiedi l'accesso alla produzione*.

### Il legame col sito, dopo il primo caricamento

L'app scaricata da Google Play è firmata con la chiave di Google, non con la
nostra: è quella che il sito deve conoscere.

1. Play Console → *Test e rilascio* → *Integrità dell'app* → *Firma dell'app*:
   ci sono due impronte SHA-256, quella del **certificato della chiave di firma
   dell'app** (di Google) e quella del **certificato della chiave di
   caricamento** (la nostra).
2. Render → `mull2five` → *Environment* → `ANDROID_CERT_FINGERPRINTS`: tutte e
   due, separate da una virgola. Salvato, il servizio riparte.
3. Controllo:
   ```powershell
   Invoke-RestMethod https://mull2five.it/.well-known/assetlinks.json | ConvertTo-Json -Depth 5
   ```
   Deve comparire `it.mull2five.app` con le due impronte. In Play Console,
   *Deep link* dice se il dominio risulta verificato.

## Aggiornare Bubblewrap

Serve quando Google Play chiede un `targetSdk` più recente di quello del
progetto generato (oggi 36).

```powershell
cd android; npm.cmd install --save-dev --save-exact @bubblewrap/cli@latest; cd ..
```

Poi si guardano due numeri del Bubblewrap nuovo e si riportano in
`android\strumenti.ps1` (`$buildTools`, `$platform`):
- `BUILD_TOOLS_VERSION` in
  `android\node_modules\@bubblewrap\core\dist\lib\androidSdk\AndroidSdkTools.js`;
- `compileSdkVersion` in
  `android\node_modules\@bubblewrap\core\template_project\app\build.gradle`.

Si rilancia `strumenti.ps1`, si compila lo staging e lo si prova sul telefono,
poi la produzione con la versione alzata.

## Quando qualcosa non va

| Sintomo | Perché | Cosa fare |
|---|---|---|
| L'app ha la barra dell'indirizzo in cima | Il sito non riconosce la firma dell'app | `assetlinks.json` (comando sopra): pacchetto giusto? Impronta giusta? L'APK di staging compilato su un altro PC ha un'altra chiave di debug; quella di Google Play ha l'impronta della *chiave di firma dell'app*. Corretto Render, Chrome ricontrolla alla riapertura dell'app; se resta, si disinstalla e si reinstalla |
| `compila.ps1`: *Manca …config.json* | Strumenti mai installati su questo PC | `android\strumenti.ps1` |
| `bubblewrap update` fallisce scaricando un'icona | Il sito è spento, o non ha ancora il commit con le icone | Lo staging si sveglia aprendolo nel browser; in produzione serve il deploy di `main` |
| `npm ci` o `node` non trovati | Node.js manca dal `PATH` | Lo stesso Node del frontend: `node --version` |
| Le notifiche non arrivano nell'app | Permesso negato, o VAPID spento sul server | Impostazioni di Android → App → Mull2Five → Notifiche; sul sito, `VAPID_*` su Render |
| *Accedi con Google* dà errore solo nell'app | L'app è finita in una WebView invece che in Chrome | Non dovrebbe: `fallbackType` è `customtabs`. Controllare che Chrome sia installato e aggiornato |
