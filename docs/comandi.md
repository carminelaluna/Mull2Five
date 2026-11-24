# Comandi — la bibbia per quando qualcosa non va

Tutto quello che serve per capire e rimettere in piedi Mull2Five da soli. Ogni
sezione parte dal sintomo e arriva al comando. Il perché delle cose sta in
[`hosting.md`](hosting.md) e in `CLAUDE.md` (le "Trappole").

**Qui non ci sono password né token**: il repository è pubblico. Stanno nel
password manager, e su Render e GitHub come variabili e segreti.

**Dove si scrivono i comandi.**
- In **PowerShell**, sul PC, tutti quelli senza indicazioni. Si parte dalla
  cartella del progetto:
  ```powershell
  cd "C:\Users\Zero\Documents\Project\Tournament Organizer"
  ```
- Il lato Python gira **sotto WSL**, mai con il Python di Windows. Sono i comandi
  che cominciano con `wsl --cd "C:\…"`: il percorso è quello di Windows, e WSL lo
  traduce da solo. La forma `wsl bash -lc 'cd "…" && …'` che c'è in `CLAUDE.md`
  funziona da Git Bash ma **non da PowerShell**, perché PowerShell toglie le
  virgolette interne e il percorso con lo spazio si spezza.
- **Git Bash** serve solo per decifrare e ripristinare i backup: ha già `gpg`.
- In PowerShell `curl` non è curl: si scrive `curl.exe`.

⚠️ segna i comandi che cambiano qualcosa di vero.

---

## 1. Prima di tutto: com'è messo il sito

```powershell
Invoke-RestMethod https://mull2five.it/health | ConvertTo-Json
```
```powershell
Invoke-RestMethod https://mull2five-staging.onrender.com/health | ConvertTo-Json
```

| Campo | Se va bene | Se no |
|---|---|---|
| `status` | `ok` | `degraded`: il database non risponde, o lo schema è indietro |
| `database` | `ok` | `error`: Supabase non risponde → sezione 3 |
| `commit` | lo sha dell'ultimo push su `main` (staging: `develop`) | un commit vecchio: il deploy non è arrivato → sezione 4 |
| `schema.indietro` | `false` | `true`: le migrazioni non sono state applicate → sezione 6 |

Nessuna risposta? Prima di cercare un guasto nostro, guarda se è giù qualcuno
dei fornitori:
- Render: https://status.render.com
- Supabase: https://status.supabase.com
- GitHub: https://www.githubstatus.com

**I pannelli.**

| Cosa | Dove |
|---|---|
| Server, log, deploy, variabili | https://dashboard.render.com → `mull2five` (produzione) o `mull2five-staging` |
| Database | https://supabase.com/dashboard → progetto di produzione o di staging |
| Codice, CI, backup, controlli | https://github.com/carminelaluna/Mull2Five/actions |
| Dominio, DNS, caselle email | pannello di register.it (chiede un codice per le aree protette) |
| Accesso con Google | https://console.cloud.google.com → progetto `mull2five` |
| Bot Telegram | `@BotFather` su Telegram |

---

## 2. Gli avvisi su Telegram: cosa vogliono dire

| Avviso | Vuol dire | Cosa fare |
|---|---|---|
| 🔴 mull2five.it non risponde | Tre tentativi andati a vuoto | Status page (sezione 1), poi i log di Render (sezione 3) |
| 🟠 risponde, ma il database non risponde | Supabase giù o irraggiungibile | Sezione 3, "Il database non risponde" |
| 🟠 risponde, ma lo schema è a X invece che a Y | Migrazioni non applicate | Sezione 6 |
| 🟢 è di nuovo su, dopo … | Risolto | Niente |
| 🚀 In produzione abc1234: titolo | Deploy arrivato | Niente |
| ⏳ main è a X, ma in produzione gira ancora Y | Il deploy è fallito o è fermo | Sezione 4, "Il deploy non arriva" |
| ❌ CI rossa su main | Codice rotto già in produzione: il deploy non aspetta la CI | Sezione 5, poi correggere o fare un revert (sezione 4) |
| 🔴 Backup del database fallito | Il backup di oggi non c'è | Sezione 7, "Il backup fallisce" |
| 🗄️ Nessun backup riuscito da … | GitHub non l'ha fatto partire | Sezione 7, lanciarlo a mano |
| ✅ Backup di nuovo a posto | Risolto | Niente |
| 🧪 Prova, il database sta bene | Una prova lanciata a mano | Niente |
| 😴 Lo staging non risponde o ha il database in pausa | Supabase di staging in pausa | Sezione 3, "Lo staging non parte" |
| ⏸️ Il controllo da GitHub non passa da più di 3 ore | GitHub ha fermato i lavori pianificati | Sezione 5, "I lavori pianificati non partono" |
| ▶️ Il controllo da GitHub è ripartito | Risolto | Niente |
| 📬 casella / Da / Oggetto | È arrivata un'email | Leggerla |
| ⚠️ Non riesco a leggere casella@… | Il sito non entra nella casella | Sezione 8, "Una casella non si legge" |
| ✅ casella si legge di nuovo | Risolto | Niente |
| [Mull2Five CRITICAL] Database non raggiungibile | Lo dice il sito stesso, ogni minuto | Sezione 3 |
| [Mull2Five INFO] Database tornato raggiungibile | Risolto | Niente |
| [Mull2Five ERROR] Errore 500 su METODO /percorso | Un bug, al massimo un avviso ogni 5 minuti per endpoint | Log di Render: cercare il percorso e leggere il traceback |
| [Mull2Five ERROR] Email non partite da casella@… | Quella casella non manda | Sezione 8, "Le email non partono" |
| [Mull2Five WARNING] Database a N MB | Vicino al limite gratuito di Supabase (500 MB) | Passare a Supabase Pro |

Se il bot è spento, nessun avviso **non** vuol dire che va tutto bene. Per
provarlo: GitHub → Actions → **Stato del sito** → *Run workflow*. Deve arrivare
"✅ mull2five.it sta bene", oppure il riassunto di cosa non va.

---

## 3. Il sito è giù o zoppica

### I log
Render → `mull2five` → **Logs**. Gli errori dell'app sono le righe `ERROR`; un
500 ha il traceback subito sotto. Gli eventi di deploy (partito, fallito,
riuscito) sono in **Events**.

### Riavviare
⚠️ Render → `mull2five` → **Restart service**, accanto o dentro il menu
*Manual Deploy*. Riavvia la stessa versione, senza ricostruire.

### Ripubblicare l'ultimo commit
⚠️ Render → `mull2five` → **Manual Deploy** → **Deploy latest commit**.
Se il problema era la cache della build: **Clear build cache & deploy**.

### Il database non risponde
1. Supabase → progetto di produzione: c'è scritto *Paused*? → **Resume project**
   (circa sei minuti), poi su Render **Deploy latest commit**. In produzione non
   dovrebbe succedere: si mette in pausa solo dopo una settimana senza richieste.
2. Status page di Supabase.
3. Render → Environment: `DATABASE_URL` dev'essere il **session pooler**
   (`…pooler.supabase.com:5432`), con `postgresql+psycopg://`. Il collegamento
   diretto è solo IPv6, e Render esce in IPv4.

### Lo staging non parte ("Failed service" su Render)
Di solito il database dello staging è in pausa.
⚠️ Supabase → progetto di staging → **Resume project**, aspettare, poi Render →
`mull2five-staging` → **Manual Deploy** → **Deploy latest commit**.
Lo tiene sveglio `staging-keepalive.yml`, ogni tre giorni.

---

## 4. Deploy, rami e come tornare indietro

`develop` va sullo staging, `main` va in produzione. **Il push su `main` è
l'unico gesto che tocca il sito vero**, e il deploy parte da solo senza
aspettare la CI.

### Dov'è il codice
```powershell
git status
```
```powershell
git log --oneline -10
```
```powershell
git fetch origin
git log --oneline -1 origin/main origin/develop
```
Il commit che gira davvero lo dice `/health` (sezione 1).

### Pubblicare sullo staging
⚠️
```powershell
git push origin develop
```

### Portare in produzione quello che c'è su develop
Prima si controlla che `main` non abbia commit che `develop` non ha. Poi `main`
si porta avanti fino a `develop`, senza merge e senza force.
⚠️
```powershell
git fetch origin
git merge-base --is-ancestor origin/main develop
if ($LASTEXITCODE -eq 0) { git push origin develop:main } else { "main ha commit che develop non ha: fermati e guarda" }
```
**Mai `git push --force` su `main`.**

### Il deploy non arriva (⏳, o `commit` vecchio in /health)
1. Render → `mull2five` → **Events**: l'ultimo deploy è *failed*, *canceled* o
   in corso da tanto?
2. **Fallito**: i log del deploy dicono perché. Se c'è "Database non pronto",
   è fallita una migrazione (sezione 6). Il sito intanto resta sulla versione
   di prima: non è giù.
3. **Fermo da tanto**, magari con *Timed Out / no open ports*: quasi sempre è
   una migrazione che aspetta un lock (29/09/2026). ⚠️ **Restart service**, e
   subito dopo **Manual Deploy → Deploy latest commit**: l'istanza vecchia
   molla le connessioni, e il lock si libera.
4. Il deploy non è proprio partito: GitHub → *Settings → GitHub Apps* → l'app
   **Render** deve essere installata sul repository. Intanto, **Deploy latest commit**.

### Tornare a una versione precedente
**Strada veloce, da Render.** ⚠️ Render → `mull2five` → **Events** → sul deploy
buono **Rollback**, oppure **Manual Deploy → Deploy a specific commit**. Dopo,
controlla in *Settings* che l'**Auto-Deploy** sia ancora acceso. Il prossimo
push su `main` ripubblica comunque il codice nuovo.

**Strada pulita, da git**: il revert resta nella storia.
⚠️
```powershell
git revert <sha-del-commit-rotto>
git push origin develop
```
Poi si porta in produzione come sopra.

**Attenzione allo schema**: tornare indietro col codice **non** toglie le
migrazioni già applicate. Il codice vecchio con uno schema nuovo di solito
funziona, perché le colonne nuove le ignora; ma prima di un rollback che passa
sopra una migrazione, guarda quale (sezione 6).

---

## 5. GitHub Actions: CI, controlli, backup

Si usa `gh`, già autenticato sul PC.

```powershell
gh run list --limit 10
```
```powershell
gh run list --workflow ci.yml --branch main --limit 5
```
```powershell
gh run view <id-del-run> --log-failed
```
⚠️ Rilanciare solo la parte fallita:
```powershell
gh run rerun <id-del-run> --failed
```

### La CI è rossa
`gh run view <id> --log-failed` dice quale job e quale test. I job sono quattro:
Backend su SQLite, Backend su PostgreSQL, Frontend, E2E (solo su `main`).
Gli stessi controlli si lanciano in locale (sezione 11). Due rossi già visti
che non erano bug del sito:
- `ModuleNotFoundError: No module named 'tests'`: un test importa da un altro.
  Lo risolve `pythonpath = ["."]` in `pyproject.toml`.
- `Playwright does not support chromium on ubuntuXX`: GitHub ha cambiato
  Ubuntu. Il job E2E è fissato su `ubuntu-24.04` in `ci.yml`.

### I lavori pianificati non partono (⏸️, 🗄️)
GitHub **spegne i workflow pianificati dopo 60 giorni senza commit** sul
repository, e nelle giornate storte li fa partire in ritardo o li salta.
```powershell
gh workflow list --all
```
Se uno è `disabled_inactivity`: ⚠️
```powershell
gh workflow enable stato-sito.yml
gh workflow enable backup.yml
gh workflow enable staging-keepalive.yml
```

### Lanciare a mano
⚠️ Lo stato del sito: scrive sempre, quindi fa anche da prova del bot.
```powershell
gh workflow run stato-sito.yml --ref main
```
⚠️ Il backup, sezione 7.

⚠️ La prova dell'avviso di backup fallito: fallisce apposta, il database non viene toccato.
```powershell
gh workflow run backup.yml --ref main -f prova_avviso=true
```

### I segreti di GitHub
```powershell
gh secret list
```
⚠️ Cambiarne uno: chiede il valore e non lo mostra.
```powershell
gh secret set TELEGRAM_BOT_TOKEN
```
I segreti che servono: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`BACKUP_DATABASE_URL`, `BACKUP_PASSPHRASE`.

---

## 6. Database e migrazioni

**Lo schema lo descrivono i modelli e lo applica Alembic.** Niente `ALTER TABLE`
a mano: una revisione nuova in `migrations/versions/`. Le migrazioni girano a
ogni deploy prima che il sito si accenda (`backend/app/prepara_database.py`): se
falliscono il deploy si ferma, e resta su la versione di prima.

### A che punto è
Lo dice `/health`, in `schema.applicata` e `schema.attesa`. In locale:
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" DATABASE_URL=sqlite:///./mull2five_dev.db ./.venv/bin/alembic current
```
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" ./.venv/bin/alembic history
```

### Cosa cambia rispetto alla produzione
**Prima di toccare lo schema**: in produzione gira l'ultimo commit
*pubblicato*, non quello che hai in locale.
```powershell
git diff <sha-di-health>..HEAD -- backend/app/models.py migrations/versions
```

### Una migrazione nuova
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" DATABASE_URL=sqlite:///./mull2five_dev.db ./.venv/bin/alembic upgrade head
```
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" DATABASE_URL=sqlite:///./mull2five_dev.db ./.venv/bin/alembic revision --autogenerate -m "cosa cambia"
```
Rileggi il file generato, poi provala su un database **con molte righe**: lo
staging riempito da un backup (sezione 7). Con poche righe gli errori di
unicità non si vedono, ed è la trappola del 23/09/2026.

### Una migrazione fallita in produzione
1. Il sito resta sulla versione di prima: nessun panico.
2. Render → Events → il deploy fallito → log: la riga dopo "Database non
   pronto" dice cosa.
3. Si corregge con una **revisione nuova**, su `develop`; si prova sullo staging
   pieno, poi si porta su `main`.
4. Se il messaggio parla di `lock timeout`: la DDL aspettava un'altra
   transazione. Si rilancia il deploy (sezione 4, "Fermo da tanto").

### Guardare dentro il database di produzione
Supabase → progetto di produzione → **SQL Editor**. Per leggere:
```sql
select pg_size_pretty(pg_database_size(current_database()));   -- quanto pesa
select version_num from alembic_version;                         -- revisione applicata
select id, email, role from users where email = 'qualcuno@esempio.it';
```
⚠️ Rendere admin un account esistente:
```sql
update users set role = 'admin' where email = 'qualcuno@esempio.it';
```
Ogni altra scrittura a mano su produzione: **prima un backup** (sezione 7).

---

## 7. Backup e ripristino

Ogni notte GitHub fa un backup cifrato dello schema `public`, e lo tiene **30
giorni**. "Ogni notte" in pratica vuol dire fra le 8 e le 12, e a volte salta.
Supabase gratuito **non** fa backup suoi.

### Lanciare un backup adesso
⚠️
```powershell
gh workflow run backup.yml --ref main
```
```powershell
gh run list --workflow backup.yml --limit 5
```

### Il backup fallisce
```powershell
gh run view <id-del-run> --log-failed
```
- "Mancano i segreti": `gh secret list`, e rimettere quello che manca.
- `pg_dump: error: aborting because of server version mismatch`: Supabase è
  passato a una versione di PostgreSQL più nuova di 17. Alzare `postgres:17` in
  `.github/workflows/backup.yml`.
- Errori di connessione: il database è giù (sezione 3) o
  `BACKUP_DATABASE_URL` è cambiato. Dev'essere il session pooler con
  `postgresql://`, **senza** `+psycopg`.

### Scaricare un backup
```powershell
gh run list --workflow backup.yml --status success --limit 5
```
```powershell
gh run download <id-del-run> -D C:\temp\backup-m2f
```
Si scarica fuori dal progetto, così un dump non finisce mai in un commit. Il
file `mull2five-AAAA-MM-GG_HHMM.dump.gpg` sta in `C:\temp\backup-m2f`, o in una
sottocartella con lo stesso nome.

### Decifrare (Git Bash)
Chiede la passphrase, quella di `BACKUP_PASSPHRASE` nel password manager.
**Senza passphrase i backup sono illeggibili.** Dalla cartella dove sta il file:
```bash
gpg --output mull2five.dump --decrypt mull2five-AAAA-MM-GG_HHMM.dump.gpg
```

### Ripristinare nello staging, per riempirlo e per provare il ripristino (Git Bash, Docker acceso)
⚠️ Cancella e riscrive lo schema `public` del database indicato.
```bash
docker run --rm -v "$PWD:/backup" postgres:17 pg_restore --clean --if-exists \
  --no-owner --dbname "<URL dello staging, con postgresql://>" /backup/mull2five.dump
```
**Subito dopo** si tolgono i dati personali, da PowerShell. L'URL si scrive a
mano: lo script non lo legge mai da `.env`. Con `--exec` niente shell in mezzo,
così una password con `&` o `$` arriva intera.
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" --exec ./.venv/bin/python scripts/anonimizza.py "<URL dello staging>" anonimizza-davvero
```
Se si ferma a metà, quel database non è utilizzabile: si butta e si rifà. Poi
una password per entrare: la procedura è in `hosting.md`, "Riempire lo staging
da un backup", punto 6.

### Ripristinare la produzione (il giorno brutto)
⚠️⚠️ Solo se i dati di produzione sono persi o rovinati.
1. **Prima** un backup di com'è adesso, anche se rotto: `gh workflow run backup.yml --ref main`.
2. Scegli il backup buono più recente, scaricalo e decifralo (sopra).
3. Due strade:
   - **Stesso progetto Supabase**: `pg_restore --clean --if-exists` come sopra,
     con l'URL di produzione. Il sito resta acceso, quindi meglio farlo quando
     c'è poca gente sopra.
   - **Progetto Supabase nuovo**, a Francoforte: ripristina lì, poi Render →
     `mull2five` → Environment → `DATABASE_URL` nuovo (session pooler,
     `postgresql+psycopg://`). Salvare fa partire il deploy. Va aggiornato anche
     il segreto `BACKUP_DATABASE_URL` su GitHub, e chiusa la Data API del
     progetto nuovo (`hosting.md`, Passo 4).
4. `/health`: `database: ok`, e `schema.indietro` deve tornare `false` (il
   deploy applica le migrazioni mancanti).
5. Quello che è successo dopo il backup è perso: avvisare i negozi.

### Alla fine, sempre
Cancella `mull2five.dump`: è il database in chiaro.
```powershell
Remove-Item -Recurse -Force C:\temp\backup-m2f
```

---

## 8. Email

| | Server | Porta |
|---|---|---|
| Invio (SMTP) | `authsmtp.securemail.pro` | 587, STARTTLS |
| Lettura (IMAP, per gli avvisi 📬) | `pop.securemail.pro` (sì, "pop") | 993, SSL |

Le caselle sono tre: `info@` per l'accesso, `commercial@` per i pagamenti, la
casella admin per tutto il resto. Le variabili `SMTP_*` sono su Render, solo in
produzione: sullo staging sono vuote di proposito.

### Le email non partono
- Su Telegram arriva "Email non partite da …"; nei log di Render c'è "Email non
  inviata".
- `SMTPAuthenticationError`: la password della casella è cambiata. Rimetterla
  su Render (`SMTP_PASSWORD`, `SMTP_ACCOUNT_PASSWORD` o
  `SMTP_PAYMENTS_PASSWORD`), poi salvare e far partire il deploy.
- Timeout o connessione rifiutata: register.it ha un problema. Si controlla con
  ```powershell
  Test-NetConnection authsmtp.securemail.pro -Port 587
  ```
- La prova vera: "Password dimenticata" sul sito con un tuo indirizzo.
- Piano B: **Brevo**, già autenticato su `avvisi.mull2five.it`. Come passarci è
  in `hosting.md`, Passo 8, punto 5.

### Una casella non si legge (⚠️ su Telegram)
- `AUTHENTICATIONFAILED` su **tutte** le caselle: `IMAP_HOST` sbagliato. Dev'essere
  `pop.securemail.pro`, non `mail.securemail.pro`.
- Su **una** sola: è cambiata la sua password. Si cambia la variabile `SMTP_*`
  di quella casella.
- Per escludere la password: entra nella webmail di register.it con la stessa.

---

## 9. Accesso con Google

```powershell
Invoke-RestMethod https://mull2five.it/api/auth/rules
```
`google_login` dev'essere `True`. Se è `False`, mancano `GOOGLE_CLIENT_ID` o
`GOOGLE_CLIENT_SECRET` su Render.

Google rifiuta l'accesso? Guarda il `client_id` che il sito manda a Google:
```powershell
(Invoke-RestMethod -Method Post -Uri https://mull2five.it/api/auth/google/start -ContentType 'application/json' -Body '{"next":""}').authorization_url
```
Nell'indirizzo, `client_id=` deve finire con `.apps.googleusercontent.com`. Se
comincia con `GOCSPX-`, ID e secret sono scambiati su Render: correggi, e
⚠️ **rigenera il secret** nella Google Cloud Console, perché è finito in un
indirizzo pubblico.

`redirect_uri_mismatch`: l'indirizzo registrato nella console dev'essere
identico, `https://mull2five.it/api/auth/google/callback`, senza `/` in fondo.

---

## 10. Dominio, DNS, Telegram

### Il dominio
```powershell
nslookup mull2five.it
```
```powershell
nslookup www.mull2five.it
```
```powershell
nslookup -type=mx mull2five.it
```
Deve venire fuori: `mull2five.it` → `216.24.57.1`; `www` → `mull2five.onrender.com`;
la posta → `mail.register.it`. I record si cambiano nel pannello di register.it,
alla voce zona DNS.

Il vecchio indirizzo deve rimandare al dominio:
```powershell
curl.exe -sI https://mull2five.onrender.com/events.html
```
Deve rispondere `301` con `location: https://mull2five.it/events.html`.

Certificato scaduto o non valido: Render → `mull2five` → *Settings* →
*Custom Domains*. Se il dominio non è *Verified*, è il DNS. Il primo
certificato può fallire per qualche minuto, poi Render ritenta da solo.

### Il bot Telegram
- **Il token è finito dove non doveva**: ⚠️ `@BotFather` → `/revoke` → scegli
  il bot. Poi il token nuovo va in Render → `mull2five` → Environment →
  `TELEGRAM_BOT_TOKEN`, e su GitHub con `gh secret set TELEGRAM_BOT_TOKEN`.
- **Il chat id**: scrivi qualcosa al bot, poi apri nel browser
  `https://api.telegram.org/bot<TOKEN>/getUpdates` e leggi il numero dopo
  `"chat":{"id":`.
- **Prova**: GitHub → Actions → Stato del sito → *Run workflow*.
- Gli avvisi dal sito (📬, ⚠️, ⏸️, errori 500) partono solo con
  `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` su Render. Quelli da GitHub partono
  solo con i due segreti omonimi.

---

## 11. Lavorare in locale

### Avviare il sito
L'API, in un terminale. Va riavviata dopo ogni modifica al backend: gira senza `--reload`.
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" DATABASE_URL=sqlite:///./mull2five_dev.db ./.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
Le pagine, in un altro terminale (http://localhost:5173, inoltra `/api` alla 8000):
```powershell
cd frontend
npx vite
```
Il `.env` punta a un PostgreSQL su `localhost:5432` che è di un altro progetto:
per questo `DATABASE_URL` si scrive sempre a mano. Non aprire
`mull2five_dev.db` dal Python di Windows mentre l'API gira.

### Prima di dire che è fatto
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" ./.venv/bin/python -m pytest -q
```
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" ./.venv/bin/ruff check backend tests migrations scripts
```
```powershell
cd frontend
npm run lint
npm run test:run
npx vite build
```
I test anche su PostgreSQL, come in produzione e in CI (Docker acceso):
```powershell
docker run --rm -d --name m2f-test-pg -p 127.0.0.1:5441:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=mull2five_test postgres:16-alpine
```
```powershell
wsl --cd "C:\Users\Zero\Documents\Project\Tournament Organizer" DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5441/mull2five_test ./.venv/bin/python -m pytest -q
```
```powershell
docker stop m2f-test-pg
```
I test end-to-end avviano da soli API e pagine. Se la 5173 è occupata, si usa
un'altra porta:
```powershell
cd frontend
$env:E2E_PORT = "5180"
npx playwright test --reporter=line
```

### Fermare un pytest rimasto appeso
Chiudere il terminale di Windows **non** ferma il pytest dentro WSL:
```powershell
wsl pkill -f pytest
```
Mai modificare file mentre pytest gira.

---

## 12. Le regole che hanno già fatto danni

- **Non pushare su `main` senza volerlo**: parte il deploy sul sito vero, anche
  con la CI rossa.
- **In produzione gira l'ultimo commit pubblicato**, non quello che hai in locale.
- **Mai `ALTER TABLE` a mano**: una revisione Alembic.
- **Mai committare** `reports/`, `*.db*`, `.env`, dump o dati personali: il
  repository è pubblico.
- **Sullo staging**: `DATABASE_URL` sempre il progetto Supabase **separato**,
  chiavi Stripe/PayPal **di test**, `SMTP_*` **vuote**.
- **`/assets/` è in cache per un anno**: lì solo i file con l'hash che crea Vite.
- Il resto delle trappole, con la storia di ognuna: `CLAUDE.md`, "Trappole che
  sono già costate tempo".
