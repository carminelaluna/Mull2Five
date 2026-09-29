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
   PAYMENT_SANDBOX_MOCK=true
   ```
   Per generare `SECRET_KEY`:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   `PAYMENT_SANDBOX_MOCK=true`: in prova nessun pagamento è reale.
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

## Da sapere prima di mandare il link

- **Chiunque può registrarsi come organizzatore**: la registrazione accetta il ruolo
  scelto da chi si iscrive (`backend/app/routers/auth.py`). Per una prova va bene,
  anzi serve; per l'apertura vera no.
- I pagamenti sono simulati, le email partono solo con un SMTP configurato.
- Primo accesso lento (Render che si sveglia); database in pausa dopo una settimana
  senza visite.

Costo: 0 € finché bastano i piani gratuiti.
