"""Toglie i dati personali da un database ripristinato, prima che serva a qualcosa.

Lo staging ha senso solo con dati realistici: con tre righe dentro non
intercetta niente, ed è la trappola del 23/09/2026 — una migrazione che sembrava
buona e in produzione è morta su un errore di unicità che con poche righe non si
vede. Ma quei dati sono di persone vere, e un ambiente di prova non è il posto
dove tenerli.

Quindi: si ripristina il backup nello staging, si lancia subito questo, e finché
non è finito quel database va trattato come se fosse la produzione.

    python scripts/anonimizza.py "postgresql://..." anonimizza-davvero

L'indirizzo si passa a mano, di proposito: non viene mai letto da `.env` né da
`DATABASE_URL`, così una distrazione non può puntarlo al database vero. Tutto
gira in una transazione sola: se qualcosa si rompe non viene scritto niente e il
database resta pieno di dati veri — lo script lo dice, e quel database va buttato.

Cosa resta: tornei, iscrizioni, turni, abbinamenti, risultati, mazzi, negozi e
sedi. Cioè tutto quello che serve a provare una migrazione.
"""
import sys

from sqlalchemy import create_engine, text

CONFERMA = "anonimizza-davvero"

# Le colonne che nominano o descrivono una persona.
RISCRITTURE = (
    ("users", "email = 'utente' || id || '@esempio.test'"),
    ("users", "display_name = 'Giocatore ' || id"),
    # Nessuno entra con le password vere. Un accesso allo staging si crea dopo,
    # a mano: vedi docs/hosting.md.
    ("users", "password_hash = NULL"),
    # Account di gioco e nickname identificano la persona quanto il nome.
    ("registrations", "wizards_account = '', game_handle = '', prize_note = ''"),
    # Testo che qualcuno ha scritto su qualcun altro.
    ("penalties", "note = 'nota rimossa'"),
    ("suspensions", "reason = 'motivo rimosso'"),
    ("announcements", "body = 'testo rimosso'"),
    ("ticket_messages", "body = 'messaggio rimosso'"),
    ("registration_answers", "value = 'risposta rimossa'"),
    ("audit_logs", "detail = 'dettaglio rimosso'"),
    ("page_views", "referrer = ''"),
    # Riferimenti veri a Stripe e PayPal: non devono esistere fuori dalla produzione.
    ("payments", "provider_checkout_id = '', provider_payment_id = '', refund_reason = ''"),
)

# Righe che fuori dalla produzione non servono e possono fare danni: notifiche
# ai telefoni veri, chiavi API che sembrano valide, impronte dei visitatori.
SVUOTATE = ("push_subscriptions", "api_keys", "visitor_days")


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[2] != CONFERMA:
        print('Uso: python scripts/anonimizza.py "<url del database>" ' + CONFERMA)
        print("L'indirizzo va scritto a mano: non viene letto da .env.")
        return 2

    # `pg_restore` vuole `postgresql://`, SQLAlchemy con quel prefisso cerca
    # psycopg2, che qui non c'è. Nella stessa procedura servono entrambe le
    # forme: le accettiamo tutte e due, invece di far inciampare chi copia
    # l'indirizzo dal comando precedente.
    url = argv[1]
    for prefisso in ("postgresql://", "postgres://"):
        if url.startswith(prefisso):
            url = "postgresql+psycopg://" + url[len(prefisso):]
            break
    engine = create_engine(url)
    with engine.connect() as connection:
        nome, server, utenti = connection.execute(text(
            "SELECT current_database(), coalesce(inet_server_addr()::text, 'locale'), "
            "(SELECT count(*) FROM users)")).one()
    print(f"database: {nome}   server: {server}   utenti: {utenti}")

    with engine.connect() as connection:
        esistenti = {r[0] for r in connection.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))}
    # Saltare in silenzio una tabella che non si trova è il modo migliore per
    # lasciare in giro dati veri credendo di averli tolti: un refuso nel nome
    # basterebbe. Se lo script e lo schema non vanno d'accordo, si ferma.
    mancanti = sorted(({t for t, _ in RISCRITTURE} | set(SVUOTATE)) - esistenti)
    if mancanti:
        print("FERMO: queste tabelle non esistono nel database — " + ", ".join(mancanti))
        print("Lo script e lo schema non vanno d'accordo: non è stato toccato niente.")
        return 1

    with engine.begin() as connection:
        for tabella, assegnazione in RISCRITTURE:
            connection.execute(text(f"UPDATE {tabella} SET {assegnazione}"))
        for tabella in SVUOTATE:
            connection.execute(text(f"DELETE FROM {tabella}"))

    # Verificare, non fidarsi: basta una email vera rimasta perché quel database
    # non sia utilizzabile.
    with engine.connect() as connection:
        vere = connection.execute(text(
            "SELECT count(*) FROM users WHERE email NOT LIKE '%@esempio.test'")).scalar()
        password = connection.execute(text(
            "SELECT count(*) FROM users WHERE password_hash IS NOT NULL")).scalar()
    if vere or password:
        print(f"NON RIUSCITA: restano {vere} email vere e {password} password. "
              "Butta questo database, non usarlo.")
        return 1

    print(f"Fatto: {utenti} utenti anonimizzati, nessuna password, "
          f"{len(SVUOTATE)} tabelle svuotate.")
    print("Tornei, iscrizioni, turni e mazzi sono rimasti: servono a provare le migrazioni.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
