# Arcana Events

Piattaforma full-stack per gestione tornei MTG: backend Python, database relazionale,
login, dashboard utente, dashboard tornei, iscrizioni, decklist, round e pagamenti
Stripe/PayPal.

## Funzionalita

- Backend FastAPI.
- DB SQLAlchemy con SQLite per sviluppo e PostgreSQL per Docker/Linux.
- Registrazione/login email + password.
- OAuth Google e Apple configurabile.
- Ruoli `player`, `organizer`, `admin`.
- Gli organizzatori possono creare eventi.
- Gli organizzatori possono vedere iscritti, stato pagamento e decklist complete.
- Dashboard utente con tornei propri e iscrizioni.
- Dashboard tornei pubblici con iscrizione.
- Dopo l'iscrizione il giocatore viene mandato subito al checkout.
- Decklist con validazione base.
- Pagamenti Stripe Checkout e PayPal Checkout.
- Sandbox locale per testare il pagamento quando le chiavi provider non sono configurate.
- Webhook Stripe e PayPal per aggiornare lo stato pagamento.
- Start torneo, round e pairings.
- Strutture torneo: svizzera, eliminazione diretta, svizzera + top cut.
- Classifica con punti, record V/S/P e tie-breaker in stile torneo.

## Requisiti

- Linux.
- Python 3.11+.
- PostgreSQL 16 consigliato in produzione.
- Docker e Docker Compose opzionali.

## Avvio Rapido Linux

```bash
cp .env.example .env
./scripts/dev.sh
```

Apri:

```text
http://127.0.0.1:8000
```

## Avvio Manuale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Avvio con Docker

```bash
cp .env.example .env
docker compose up --build
```

Il servizio web ascolta su:

```text
http://127.0.0.1:8000
```

## Configurazione

Le variabili sono in `.env`.

Per sviluppo locale puoi lasciare:

```env
DATABASE_URL=sqlite:///./arcana_events.db
```

Per Docker viene usato PostgreSQL:

```env
DATABASE_URL=postgresql+psycopg://arcana:arcana@db:5432/arcana_events
```

## OAuth Google

Compila in `.env`:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

Callback da configurare nella Google Cloud Console:

```text
http://127.0.0.1:8000/api/auth/oauth/google/callback
```

## OAuth Apple

Compila in `.env`:

```env
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY_PATH=/opt/arcana-events/AuthKey_XXXXXXXXXX.p8
```

Callback:

```text
http://127.0.0.1:8000/api/auth/oauth/apple/callback
```

## Pagamenti

Stripe:

```env
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```

Webhook Stripe:

```text
https://tuo-dominio.it/api/payments/stripe/webhook
```

PayPal:

```env
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_ENV=sandbox
PAYMENT_SANDBOX_MOCK=true
```

Webhook PayPal:

```text
https://tuo-dominio.it/api/payments/paypal/webhook
```

Con `PAYMENT_SANDBOX_MOCK=true`, in sviluppo il backend genera una pagina locale:

```text
/sandbox-checkout
```

Da li puoi completare un pagamento finto e vedere lo stato aggiornato nella dashboard
organizzatore. In produzione imposta le credenziali reali Stripe/PayPal e disattiva il mock.

I rimborsi possono essere richiesti dal giocatore dalla pagina torneo. L'organizzatore li approva
dalla lista iscritti. Stripe usa `STRIPE_SECRET_KEY` e il payment intent del checkout; PayPal usa
il capture ID ricevuto dal webhook `PAYMENT.CAPTURE.COMPLETED`.

## Notifiche Email

Gli annunci evento possono inviare email agli iscritti se SMTP e notifiche evento sono attivi:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=noreply@example.com
SMTP_USE_TLS=true
```

## Deploy Linux

Sono inclusi esempi di configurazione:

- `deploy/systemd/arcana-events.service`
- `deploy/nginx/arcana-events.conf`

Flusso tipico:

```bash
sudo mkdir -p /opt/arcana-events
sudo cp -R . /opt/arcana-events
cd /opt/arcana-events
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
sudo cp deploy/systemd/arcana-events.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arcana-events
```

## Struttura Progetto

```text
.
+-- backend/
|   +-- app/
|       +-- routers/
|       +-- services/
+-- index.html
+-- styles.css
+-- app.js
+-- frontend/
+-- deploy/
+-- assets/
|   +-- tournament-hall.png
+-- screenshots/
    +-- arcana-events-qa.png
```

## Note

La versione include il core applicativo e le integrazioni provider-ready. Per produzione
servono credenziali reali OAuth, Stripe e PayPal, HTTPS e un `SECRET_KEY` robusto.
