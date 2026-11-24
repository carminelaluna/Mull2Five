# Mull2Five online — versione di prova

Obiettivo: farla provare a chi è interessato. Niente dominio, un solo repository
pubblico (`carminelaluna/Mull2Five`), un solo branch (`main`), backup cifrati.
Tutto con piani gratuiti.

```
https://mull2five.onrender.com ──▶ Render    un solo servizio: API FastAPI + pagine
                                     │
                                     └──▶ Supabase  PostgreSQL, Francoforte

GitHub: codice, CI, deploy automatico a ogni push su main, backup notturno cifrato
```

**Perché serve Render.** Né GitHub né Supabase eseguono un server Python: GitHub
Pages serve solo file statici, Supabase offre il database e funzioni in Deno.

**Perché le pagine le serve Render e non GitHub Pages.** Senza dominio, Pages
pubblica sotto `carminelaluna.github.io/Mull2Five/`, cioè in una sottocartella. Il
sito oggi usa percorsi dalla radice in 19 pagine (icone, manifest, logo), nel
service worker e nelle chiamate all'API: andrebbero corretti tutti, più CORS e
indirizzo dell'API. Servendo tutto da un indirizzo solo, niente di questo serve.
Pages si può riprendere quando ci sarà un dominio.

Render e Supabase vanno nella **stessa regione** (Francoforte): ogni pagina fa
decine di query, e con i due servizi lontani ognuna pagherebbe decine di
millisecondi in più. Dati dei giocatori in UE, come vuole il GDPR.

---

## Passo 1 — Codice ✓ fatto

- `Dockerfile` in due fasi: Node costruisce `frontend/dist`, l'immagine Python lo
  serve. Porta da `$PORT` (la assegna Render); si fida dell'IP inoltrato dal proxy,
  altrimenti il rate limit vedrebbe tutti i visitatori come uno solo.
- `backend/app/main.py`: con `FRONTEND_DIST` (impostata nell'immagine) le pagine
  sono servite su `/`, dopo `/api`, `/health` e `/docs`. In sviluppo non cambia niente.
- `backend/app/db.py`: pool da `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`; RLS attiva su
  tutte le tabelle quando il database è PostgreSQL.
- `.github/workflows/backup.yml`: backup cifrato ogni notte e a richiesta.
- Tolti i file dell'EC2 (`scripts/deploy.sh`, `deploy/systemd`, `deploy/nginx`, i
  timer di backup) e i riferimenti in README e `.env.example`.
- Falla XSS fra utenti chiusa (`frontend/js/escape.js`, test in `frontend/tests/escape.test.js`).

Provato in locale con Docker e PostgreSQL 17: l'immagine si costruisce e parte
sulla porta di Render, serve pagine, service worker e API; la RLS è attiva su 24
tabelle su 24, l'app funziona e un ruolo non proprietario non legge niente; il
backup cifrato si ripristina senza errori con gli stessi dati.

## Passo 2 — Un solo branch

Il lavoro di queste sessioni è tutto **non committato** su `V2`.

1. Commit su `V2`, poi merge in `main`.
2. Cancellare `V2`, in locale e su GitHub.
3. Aggiornare l'indirizzo del repo rinominato (GitHub reindirizza, ma meglio non contarci):
   ```bash
   git remote set-url origin https://github.com/carminelaluna/Mull2Five.git
   ```

La CI (`.github/workflows/ci.yml`) gira già su `main`.

## Passo 3 — Repo pubblico

1. Storia già controllata: nessun `.env`, database o chiave è mai stato committato.
2. *Settings → General → Danger Zone → Change visibility → Public*.
3. *Settings → Code security*: attivare **secret scanning** e **push protection**
   (gratuiti sui repo pubblici): bloccano un push che contiene una chiave.

Da quel momento chiunque abbia un account GitHub può scaricare gli artifact delle
Actions: per questo i backup del passo 6 sono cifrati.

## Passo 4 — Supabase

1. *New project*, regione **`eu-central-1` (Frankfurt)**. Salvare subito la password
   del database in un password manager.
2. *Connect → Session pooler*: copiare la stringa e adattarla per SQLAlchemy:
   ```
   postgresql+psycopg://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres?sslmode=require
   ```
   Il collegamento diretto è solo IPv6, Render esce in IPv4: il session pooler va bene per entrambi.
3. **Chiudere la Data API**: *Settings → Data API*, disattivarla o togliere `public`
   dagli schemi esposti. L'app non la usa, ma di serie Supabase espone via REST
   tutte le tabelle, compresi gli utenti con gli hash delle password. La RLS del
   passo 1 è la seconda protezione.
4. Lo schema lo crea il backend al primo avvio (passo 7).

Piano gratuito: si mette in **pausa dopo 7 giorni senza attività** (si riattiva dal
pannello) e **non fa backup**: per quello c'è il passo 6.

## Passo 5 — Render

1. *New → Web Service → GitHub → `Mull2Five`*, branch `main`, runtime **Docker**,
   regione **Frankfurt**, istanza **Free**. Il nome del servizio dà l'indirizzo:
   `mull2five` → `https://mull2five.onrender.com`, se libero.
2. Variabili d'ambiente:
   ```
   APP_ENV=production
   SECRET_KEY=<nuovo valore casuale lungo>
   DATABASE_URL=<session pooler del passo 4>
   APP_URL=https://mull2five.onrender.com
   FRONTEND_URL=https://mull2five.onrender.com
   DB_POOL_SIZE=5
   DB_MAX_OVERFLOW=5
   PAYMENT_SANDBOX_MOCK=false
   ONLINE_PAYMENTS_ENABLED=false
   ```
   Per generare `SECRET_KEY`:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   In produzione `PAYMENT_SANDBOX_MOCK` va **spento**: acceso, il checkout finto
   segna pagata un'iscrizione con un clic, senza incassare. Qui c'era scritto
   `true`, ed è rimasto acceso sul sito vero fino al 23/11/2026. Si paga al banco
   (`ONLINE_PAYMENTS_ENABLED=false`, vedi "Pagamenti" più sotto).
   Facoltative: `SMTP_*` (senza, il reset password non manda l'email) e `VAPID_*`
   (senza, niente notifiche push).
3. *Health check path*: `/health`. *Auto-Deploy*: a ogni push su `main`.

   Il deploy automatico parte solo se l'app **Render** è installata sul repository
   (GitHub → *Settings → GitHub Apps*). Collegare GitHub dal pannello di Render
   basta per creare il servizio e per i deploy a mano, non per ricevere i push:
   senza l'app il sito resta fermo all'ultimo deploy fatto a mano
   (*Manual Deploy → Deploy latest commit*).

Piano gratuito: il servizio **si addormenta dopo 15 minuti** senza visite e la prima
richiesta dopo impiega circa un minuto. Va detto a chi prova.

## Passo 6 — Backup

Workflow `.github/workflows/backup.yml`, ogni notte e a richiesta (*Run workflow*):

1. `pg_dump` 17, in formato custom. Legge server fino alla versione 17: se Supabase
   (*Settings → Infrastructure*) mostra una versione più nuova, va alzata nel workflow.
2. Cifratura con `gpg --symmetric --cipher-algo AES256` e una passphrase.
3. Caricamento come artifact, tenuto **30 giorni**.

Segreti del repo (*Settings → Secrets and variables → Actions*):
- `BACKUP_DATABASE_URL`: il session pooler, ma con `postgresql://` invece di
  `postgresql+psycopg://` (`pg_dump` non conosce il driver);
- `BACKUP_PASSPHRASE`: anche nel password manager. **Senza, i backup sono illeggibili.**

Ripristino, da Git Bash (ha già `gpg`) con Docker Desktop acceso:

1. *Actions → Backup →* il run che interessa *→ Artifacts*: scaricare lo zip ed estrarlo.
2. Decifrare (chiede la passphrase):
   ```bash
   gpg --output mull2five.dump --decrypt mull2five-AAAA-MM-GG_HHMM.dump.gpg
   ```
3. Caricare nel database di destinazione (`postgresql://…`, senza `+psycopg`):
   ```bash
   docker run --rm -v "$PWD:/backup" postgres:17 pg_restore --clean --if-exists --no-owner --dbname "<URL del database>" /backup/mull2five.dump
   ```
4. Cancellare `mull2five.dump`: è il database in chiaro.

Un ripristino va provato una volta, su un secondo progetto Supabase (il piano
gratuito ne concede due), prima di averne bisogno davvero.

## Passo 7 — Primo avvio

1. Primo deploy su Render: nei log deve comparire `Application startup complete`.
   Lo schema su Supabase è creato.
2. Supabase → *Advisors → Security*: nessun avviso "RLS disabled".
3. Aprire il sito, registrare un account organizzatore, creare un torneo di prova.
4. *Actions → Backup → Run workflow*, scaricare l'artifact e verificare che si decifri.

## Passo 8 — Dominio vero e server sempre acceso

Scelto il 23/11/2026, come la soluzione più economica che regge l'apertura ai negozi:
Render Starter (circa 7 $/mese) per il server, Supabase gratuito per il database
come adesso, un dominio (.it, circa 9–12 €/anno di rinnovo), le caselle email di
register.it per spedire (500 email al giorno ciascuna; Brevo gratuito come riserva). Niente migrazione dei dati. Quando il database si avvicina ai
500 MB, o serve il ripristino al minuto, si passa a Supabase Pro (25 $/mese).

**Stato al 23/11/2026:** fatti i punti 1–5 e le prove del punto 7 (il reset
password arriva da `info@mull2five.it`).
Dominio `mull2five.it` su register.it (zona DNS: record A `@` → `216.24.57.1`,
CNAME `www` → `mull2five.onrender.com.`; posta, PEC e DKIM di register.it lasciati
com'erano), servizio sul piano 0.5c-512mb (il vecchio "Starter"). Restano i
webhook (punto 6). Due cose viste lungo la strada: register.it chiede
un codice di verifica per ogni area protetta del pannello (DNS compresi), e il
primo certificato del dominio nudo può fallire se Let's Encrypt vede ancora il
vecchio IP in cache — Render ritenta da solo entro qualche minuto.

Il codice è già pronto: `SITE_URL` decide il redirect da `*.onrender.com` al
dominio (`redirect_to_site_domain` in `backend/app/main.py`, solo pagine in GET;
API e webhook restano raggiungibili anche dal vecchio indirizzo) e gli indirizzi
scritti nelle pagine al momento della build (`ARG SITE_URL` nel `Dockerfile`).

1. **Dominio.** Comprarlo guardando il prezzo del *rinnovo*, non del primo anno.
   Il DNS conviene gestirlo su Cloudflare (gratuito) anche se il dominio è altrove.
2. **Render → Mull2Five → Settings → Instance Type**: Starter.
3. **Render → Mull2Five → Settings → Custom Domains**: aggiungere `<dominio>` e
   `www.<dominio>`. Render mostra i record DNS da creare (per il dominio nudo un
   record A, per `www` un CNAME verso `mull2five.onrender.com`): copiarli così come
   sono. Su Cloudflare, con la nuvola **grigia** (solo DNS), altrimenti Render non
   riesce a emettere il certificato. Aspettare che Render dica *Verified* e
   *Certificate issued*.
4. **Render → Mull2Five → Environment**: `APP_URL`, `FRONTEND_URL` e `SITE_URL`
   diventano `https://<dominio>`. Salvare fa partire un deploy, che serve: le
   pagine si ricostruiscono con l'indirizzo nuovo.
5. **Email.** Scelte il 23/11/2026 le caselle di register.it, una per tipo di
   email (`Sender` in `backend/app/services/email.py`):

   | Email | Casella | Variabili su Render |
   |---|---|---|
   | reset password, invito a scegliere la password | `info@` | `SMTP_ACCOUNT_FROM_EMAIL`, `SMTP_ACCOUNT_USERNAME`, `SMTP_ACCOUNT_PASSWORD` |
   | ricevuta di pagamento, posto da pagare dalla lista d'attesa | `commercial@` | `SMTP_PAYMENTS_FROM_EMAIL`, `SMTP_PAYMENTS_USERNAME`, `SMTP_PAYMENTS_PASSWORD` |
   | tutto il resto (iscrizioni, turni, annunci, promemoria, allarmi) | la casella admin | `SMTP_FROM_EMAIL`, `SMTP_USERNAME`, `SMTP_PASSWORD` |

   Server comune: `SMTP_HOST` `authsmtp.securemail.pro`; la porta 587 con
   STARTTLS è già il default (`core/config.py`, provata il 23/11: risponde anche
   la 465 in SSL, che il codice non usa). Utente = indirizzo completo della
   casella, password = quella della casella. Il mittente deve essere la casella
   con cui si entra, quindi `Mull2Five <info@mull2five.it>` con utente
   `info@mull2five.it`. Ogni casella manda fino a 500 email al giorno; SPF
   (`include:spf.webapps.net`) e DKIM del dominio sono già di register.it.

   Una casella senza variabili sue usa quella generale; un mittente senza
   credenziali sue entra con quelle generali (il caso di Brevo: una chiave, più
   mittenti). Ordine che evita email perse: prima tutte le altre variabili con
   *Save only*, `SMTP_HOST` per ultimo, insieme al deploy. Senza `SMTP_HOST` il
   sito non prova a spedire; con l'host e senza password ogni invio fallisce, e il
   reset password direbbe "email mandata" senza mandarla.

   **Brevo resta pronto come alternativa**: il sottodominio `avvisi.mull2five.it`
   è autenticato (TXT `avvisi` con il `brevo-code`, CNAME
   `brevo1._domainkey.avvisi` e `brevo2._domainkey.avvisi`, TXT `_dmarc.avvisi`
   con `p=none`; su register.it i nomi sono relativi alla zona e i TXT fra
   virgolette doppie). Per passarci: `SMTP_HOST` `smtp-relay.brevo.com`, utente e
   chiave di Brevo nelle tre variabili generali, i mittenti `...@avvisi.mull2five.it`
   e le `SMTP_ACCOUNT_USERNAME`/`SMTP_PAYMENTS_USERNAME` vuote. L'account Brevo è
   condiviso con un altro progetto, e con lui il limite di 300 email al giorno.
6. **Webhook.** Nel cruscotto Stripe e in quello PayPal l'indirizzo diventa
   `https://<dominio>/api/payments/stripe/webhook` e `.../paypal/webhook`. Il
   vecchio continua a funzionare finché non lo si cambia, quindi l'ordine non conta.
7. **Prove.**
   - `curl https://<dominio>/health`: `"status":"ok"` e il commit giusto.
   - `curl -I https://mull2five.onrender.com/events.html`: `301` verso il dominio.
   - Il sorgente della home: `og:image` e `canonical` col dominio.
   - "Password dimenticata" con un proprio indirizzo: l'email arriva, non nello spam,
     e il link porta al dominio.
   - Google Search Console: aggiungere il dominio e inviare `/sitemap.xml`.

## Da sapere prima di mandare il link

- **Chiunque può registrarsi come organizzatore**: la registrazione accetta il ruolo
  scelto da chi si iscrive (`backend/app/routers/auth.py`). Per una prova va bene,
  anzi serve; per l'apertura vera no.
- In produzione si paga solo al banco (vedi "Pagamenti"); le email partono solo con
  un SMTP configurato.
- Primo accesso lento (Render che si sveglia); database in pausa dopo una settimana
  senza visite.

Costo: 0 € finché bastano i piani gratuiti.

## I due ambienti

Dal 29/09/2026 non c'è più un solo ramo: il passo 2 qui sopra è superato.

| | Ramo | Servizio | Database |
|---|---|---|---|
| Produzione | `main` | `mull2five` | Supabase, progetto di produzione |
| Staging | `develop` | `mull2five-staging` | Supabase, progetto separato |

Si lavora su `develop`, si guarda lo staging, si fonde in `main`. Il push su
`main` è l'unico gesto che tocca il sito vivo.

La configurazione dei servizi sta in [`render.yaml`](../render.yaml), che elenca
anche cosa lo staging deve cambiare. Tre variabili, se sbagliate, fanno danni:

- `DATABASE_URL` → il progetto Supabase **separato**. Puntarlo a quello di
  produzione cancella dati veri.
- `STRIPE_*`, `PAYPAL_*` → chiavi di **test**. Con quelle vere una prova incassa
  soldi da un giocatore.
- `SMTP_*` → vuote. Altrimenti lo staging manda email a persone vere.

E `APP_ENV=staging`, che tiene lo staging fuori dai motori di ricerca: una copia
risponde `Disallow: /` e manda `X-Robots-Tag: noindex` (`core/config.py`,
`is_copy`).

### Pagamenti: al banco in produzione, online sullo staging

Deciso il 23/11/2026: la produzione si prova in una fumetteria prima che il legale
guardi termini e privacy, e il legale viene per ultimo. Quindi:

| | `ONLINE_PAYMENTS_ENABLED` | `PAYMENT_SANDBOX_MOCK` | Chiavi |
|---|---|---|---|
| Produzione | `false`: solo al banco | `false` | nessuna |
| Staging | `true` | `false` con le chiavi di test, `true` senza | Stripe `sk_test_…`, PayPal sandbox |

Con `ONLINE_PAYMENTS_ENABLED=false` (`in_person_only` in
`backend/app/services/payments.py`) Stripe e PayPal non si salvano su nessun
torneo (modulo, modello, duplica, ripeti, import), le pagine li mostrano spenti
anche sui tornei salvati prima, il checkout risponde 409 e il back-office
nasconde le due caselle (`GET /api/payments/options`). Chi aveva scelto solo
l'online paga al banco.

Gli account Stripe e PayPal stanno su `commercial@mull2five.it`. Per lo staging
bastano le modalità di prova, che non chiedono dati dell'azienda: Stripe in
*Test mode* (chiave `sk_test_…`), PayPal su developer.paypal.com → *Apps &
Credentials* → **Sandbox**. Le chiavi le inserisce chi ha l'account, solo nel
servizio di staging. Per accendere l'online in produzione, dopo il legale:
chiavi vere, webhook su `mull2five.it` (punto 6 del Passo 8) e
`ONLINE_PAYMENTS_ENABLED=true`.

I webhook dello staging (23/11/2026): Stripe con una *destinazione eventi*
sull'ambito **Il tuo account**, payload **Snapshot** (il codice legge
`data.object`: con *Thin* non c'è), solo `checkout.session.completed`; il
segreto `whsec_…` va in `STRIPE_WEBHOOK_SECRET`. PayPal sull'app sandbox, con
`CHECKOUT.ORDER.APPROVED` e `PAYMENT.CAPTURE.COMPLETED`, e il suo ID in
`PAYPAL_WEBHOOK_ID`. Un ordine PayPal si incassa quando il giocatore torna su
`grazie.html` (`POST /api/payments/paypal/capture`): la notifica è solo una
rete. Finché l'incasso aspettava lei, sullo staging i pagamenti PayPal restavano
in attesa.

**Verifica, appena è su:**

```bash
curl -s https://mull2five-staging.onrender.com/robots.txt   # deve dire Disallow: /
curl -s https://mull2five-staging.onrender.com/health       # commit e revisione dello schema
```

**Il database di staging va riempito.** Con tre righe dentro non intercetta
niente: è la trappola del 23/09/2026, dove una migrazione sembrava buona e in
produzione è morta su un errore di unicità che con poche righe non si vede.

### Accesso con Google: le credenziali

Il codice è pronto (`backend/app/services/google_login.py`,
`backend/app/routers/google_auth.py`); finché le credenziali mancano il bottone
"Accedi con Google" non compare. Le crea chi ha l'account Google del progetto,
nella [Google Cloud Console](https://console.cloud.google.com/):

1. **Un progetto** (per esempio "Mull2Five"), poi *APIs & Services* → *OAuth
   consent screen* (nella console nuova: *Google Auth Platform* → *Branding*).
   Tipo **External**; nome Mull2Five, email di supporto, dominio autorizzato
   `mull2five.it`, privacy `https://mull2five.it/privacy.html`, termini
   `https://mull2five.it/termini.html`. Gli ambiti sono solo `openid`, `email`
   e `profile`: non sensibili, quindi Google non chiede una verifica.
   Pubblica l'app (*In production*): in *Testing* entrano solo i tester elencati.
2. **Due client OAuth**, *Credentials* → *Create credentials* → *OAuth client
   ID* → **Web application**. Due e non uno, così un segreto dello staging non
   apre la produzione:
   - **produzione** — *Authorized redirect URIs*:
     `https://mull2five.it/api/auth/google/callback`
   - **staging e sviluppo** — *Authorized redirect URIs*:
     `https://mull2five-staging.onrender.com/api/auth/google/callback` e, per
     provare in locale, `http://localhost:5173/api/auth/google/callback`

   Le *Authorized JavaScript origins* non servono: il `code` lo scambia il server.
3. **Su Render**, in ciascun servizio → *Environment*: `GOOGLE_CLIENT_ID` e
   `GOOGLE_CLIENT_SECRET` del suo client (in `render.yaml` sono `sync: false`).
   `GOOGLE_REDIRECT_URI` si lascia vuota: vale `FRONTEND_URL` +
   `/api/auth/google/callback`, e deve coincidere carattere per carattere con
   quella registrata nella console, `https` e niente `/` in fondo compresi.
4. **Prova**: `/api/auth/rules` risponde `"google_login": true` e `login.html`
   mostra il bottone.

Il giro passa da un cookie (`m2f_google`, solo su `/api/auth/google`) che vive
sull'host da cui parte: per questo l'indirizzo di ritorno è quello delle pagine
(`FRONTEND_URL`, cioè `mull2five.it`), non `mull2five.onrender.com`. In locale
lo stesso vale per Vite: si entra da `localhost:5173`, non da `127.0.0.1`.

Sullo staging l'email che avvisa dell'unione con un account esistente non parte,
perché lì l'SMTP è vuoto di proposito.

### Riempire lo staging da un backup

Fa due cose in una: riempie lo staging **e** mette alla prova il ripristino, che
è l'unico modo di sapere se i backup servono davvero a qualcosa.

Da Git Bash, con Docker acceso. I passi 1-3 sono quelli del passo 6 qui sopra,
con lo staging come destinazione.

1. *Actions → Backup →* il run che interessa *→ Artifacts*: scarica ed estrai.
2. Decifra (chiede la passphrase):
   ```bash
   gpg --output mull2five.dump --decrypt mull2five-AAAA-MM-GG_HHMM.dump.gpg
   ```
3. Carica **nel database di staging**:
   ```bash
   docker run --rm -v "$PWD:/backup" postgres:17 pg_restore --clean --if-exists \
     --no-owner --dbname "<URL staging, con postgresql:// >" /backup/mull2five.dump
   ```
4. **Subito**, senza passare dal via:
   ```bash
   python scripts/anonimizza.py "<URL staging>" anonimizza-davvero
   ```
   Fino a qui quel database contiene dati di persone vere: trattalo come la
   produzione. Lo script sostituisce email e nomi, cancella le password, i
   riferimenti veri a Stripe e PayPal, le notifiche push e le chiavi API, e
   svuota il testo libero — note dei judge, motivi delle sospensioni, messaggi
   delle segnalazioni. Tornei, iscrizioni, turni e mazzi restano: sono quelli che
   servono a provare una migrazione.

   Se si ferma, quel database **non è utilizzabile**: buttalo e rifai.
5. Cancella `mull2five.dump` dal disco: è il database in chiaro.
6. Per entrare nello staging serve una password: le vecchie sono state
   cancellate tutte. Se ne mette una a un utente — con `-c`, non con un
   heredoc: quello occuperebbe lo stdin e la password non si potrebbe digitare.
   ```bash
   DATABASE_URL="<URL staging>" ./.venv/bin/python -c "
   import getpass
   from backend.app.db import SessionLocal
   from backend.app.models import User
   from backend.app.security import hash_password
   s = SessionLocal()
   u = s.query(User).filter_by(email='utente1@esempio.test').one()
   u.password_hash = hash_password(getpass.getpass('password per lo staging: '))
   u.role = 'admin'
   s.commit()
   print('fatto:', u.email)
   "
   ```

Dopo il ripristino, `/health` dello staging dice se lo schema del backup è più
vecchio del codice: `"indietro": true` significa che all'avvio è stata applicata
una migrazione, ed è esattamente la prova che si voleva.

**Va rifatto ogni tanto.** I dati dello staging sono una fotografia: invecchiano,
e uno staging con dati vecchi intercetta meno di uno aggiornato. Dieci minuti,
questa procedura. Conviene prima di una migrazione che tocchi tabelle grosse.

**Il progetto Supabase gratuito si mette in pausa** dopo circa una settimana
senza attività, e lo staging si addormenta con lui. Per evitarlo,
`.github/workflows/staging-keepalive.yml` chiama `/health` dello staging ogni tre
giorni: quella chiamata interroga il database e Supabase la conta come attività.
Se il workflow fallisce, GitHub manda un'email: il database è già in pausa. Si
riaccende dal cruscotto di Supabase ("Resume project", circa sei minuti), poi su
Render *Manual Deploy* → *Deploy latest commit*. Non è un guasto del codice.

## Avvisi su Telegram

Un bot solo, due fonti (24/11/2026):

- **da fuori, GitHub** (`.github/workflows/stato-sito.yml` e
  `scripts/stato_sito.py`): ogni cinque minuti chiama `/health` di
  `mull2five.it` e scrive solo quando qualcosa cambia — 🔴 non risponde (dopo tre
  tentativi), 🟠 risponde ma il database no o lo schema è indietro, 🟢 di nuovo
  su e dopo quanto, 🚀 un commit nuovo in produzione con il suo titolo. Serve
  perché se a cadere è Render il sito non può dirlo da solo. GitHub non
  garantisce i cinque minuti: nelle ore di punta un giro parte in ritardo;
- **dal sito**: il database che cade e torna (ogni minuto), un errore 500 (al
  massimo uno ogni cinque minuti per endpoint), e 📬 ogni email che arriva a
  `info@`, `commercial@` o alla casella admin, con casella, mittente e oggetto.
  Il testo resta nella casella, che non viene toccata: l'email non risulta
  letta. Se una casella non si legge per tre minuti di fila (password cambiata,
  server giù) arriva ⚠️, e ✅ quando torna (`services/mail_watch.py`).

Le caselle si leggono via IMAP con le stesse credenziali `SMTP_*` con cui
mandano; su register.it il server è **`pop.securemail.pro`**, porta 993 (sì,
"pop": è lo stesso server delle email in arrivo, `mail.register.it`, che però ha
il certificato a nome `*.securemail.pro`). Non `mail.securemail.pro`: risponde
anche lui, ma è un altro gruppo di server e rifiuta tutte e tre le caselle con
`AUTHENTICATIONFAILED` (24/11/2026). Dove si era arrivati lo tiene la memoria
del processo: un'email arrivata proprio nel minuto di un riavvio può non essere
avvisata, o esserlo due volte (resta comunque nella casella). Per lo stesso
motivo, dopo un deploy il primo giro prende solo nota: un accesso che riesce
non manda niente, e la prova è un'email vera.

Per accenderlo:

1. **Il bot.** Su Telegram, `@BotFather` → `/newbot`: un nome (per esempio
   "Mull2Five avvisi") e un nome utente che finisce in `bot`. BotFather risponde
   con il **token** (`123456789:AA…`): è una password, va solo su Render e nei
   segreti di GitHub.
2. **La chat.** Scrivi un messaggio qualsiasi al bot, poi apri nel browser
   `https://api.telegram.org/bot<TOKEN>/getUpdates`: il numero dopo
   `"chat":{"id":` è il **chat id**. Per un gruppo: aggiungi il bot al gruppo,
   scrivi lì, e l'id (negativo) è quello del gruppo.
3. **Render → Mull2Five → Environment**, solo la produzione:
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` e `IMAP_HOST` = `pop.securemail.pro`.
   Salvare fa partire il deploy. Sullo staging no: le caselle lì sono vuote di
   proposito, e i suoi errori arriverebbero mescolati a quelli veri.
4. **GitHub → Settings → Secrets and variables → Actions → New repository
   secret**: `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`, gli stessi.
5. **Prove.** *Actions → Stato del sito → Run workflow*: lanciato a mano scrive
   sempre, "✅ mull2five.it sta bene, commit …". Il workflow lo vede e lo fa
   girare solo il ramo `main`: c'è dal primo merge in poi. Poi un'email da un tuo
   indirizzo a `info@mull2five.it`: entro un minuto arriva 📬.

`ALERT_EMAIL` può restare vuota: con Telegram gli allarmi arrivano già. Se
punta a una delle tre caselle, ogni allarme arriva due volte — com'è, e come
email arrivata.
