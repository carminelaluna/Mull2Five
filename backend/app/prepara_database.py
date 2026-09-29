"""Prepara il database, prima che il sito si accenda.

Le migrazioni giravano dentro l'avvio dell'app, e uvicorn apre la porta solo
quando l'avvio è finito. Da lì venivano due guasti opposti, capitati entrambi:

- una migrazione che **aspetta** non fa aprire la porta, e Render vede un
  servizio che non parte — il 29/09/2026 il deploy è scaduto due volte prima
  che si capisse che era un lock;
- una migrazione che **fallisce** veniva annotata e ignorata: il sito partiva,
  il deploy risultava riuscito, e metà back-office dava 500 — il 23/09/2026.

Qui è un passo a sé, prima di uvicorn. Se fallisce, esce con un codice d'errore
e scrive perché: il deploy si ferma, la versione precedente resta su, e il
motivo è nel log invece che nascosto dietro un timeout.
"""
import logging
import sys

from backend.app.db import create_all


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("prepara_database")
    try:
        create_all()
    except Exception as exc:   # noqa: BLE001 — qualunque guasto qui ferma il deploy, ed è giusto
        log.error("Database non pronto: %s", exc)
        log.error("Il sito non viene acceso: meglio la versione di prima che una rotta.")
        return 1
    log.info("Database pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
