"""
site_watch.py — Due avvisi che il sito manda di suo.

Il controllo da GitHub che non passa più. `scripts/stato_sito.py` chiama /health
ogni cinque minuti, e si presenta con il suo User-Agent. Se per ore non passa,
nessuno avvisa più se il sito cade, e di solito è fermo anche il backup: GitHub
spegne i lavori pianificati di un repository che resta 60 giorni senza commit,
e nelle giornate storte gli eventi pianificati li salta (il 24/11/2026 alle 13
né il backup della notte né il controllo ogni cinque minuti erano partiti). Chi
controlla il controllore è il sito: solo lui resta acceso comunque.

Il database che si avvicina al limite. Il piano gratuito di Supabase arriva a
500 MB; quando si avvicina è ora di passare a Pro (docs/hosting.md, passo 8).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sqlalchemy import text

from backend.app.core.alerting import send_alert, send_telegram
from backend.app.core.config import get_settings
from backend.app.db import engine

logger = logging.getLogger(__name__)

STATUS_CHECK_AGENT = "mull2five-stato-sito"     # lo User-Agent di scripts/stato_sito.py
DB_SIZE_ALERT_SECS = 24 * 3600

_LATE = ("⏸️ Il controllo da GitHub non passa da più di {hours} ore. Finché non riparte "
         "nessuno avvisa se il sito cade, e forse è fermo anche il backup: GitHub "
         "spegne i lavori pianificati dopo 60 giorni senza commit. "
         "GitHub → Actions → Stato del sito e Backup.")
_BACK = "▶️ Il controllo da GitHub è ripartito."


class StatusCheckWatch:
    """Quando è passato l'ultima volta il controllo da GitHub, e se è ora di dirlo.

    Lo stato sta in memoria: dopo un riavvio si riparte concedendo un giro
    intero, così un deploy non fa scattare l'avviso."""

    def __init__(self, notify: Callable[[str], bool] = send_telegram,
                 clock: Callable[[], float] = time.monotonic):
        self.notify = notify
        self.clock = clock
        self.last_seen = clock()
        self.told = False

    def seen(self) -> None:
        self.last_seen = self.clock()

    def check(self, hours: int) -> None:
        if hours <= 0:
            return
        late = self.clock() - self.last_seen > hours * 3600
        # Se Telegram non risponde, si riprova al giro dopo.
        if late and not self.told:
            self.told = self.notify(_LATE.format(hours=hours))
        elif not late and self.told:
            self.told = not self.notify(_BACK)


status_check = StatusCheckWatch()


def database_size_mb() -> float | None:
    """Quanto pesa il database, in MB. Solo PostgreSQL: SQLite non ha limiti da guardare."""
    if engine.dialect.name != "postgresql":
        return None
    with engine.connect() as conn:
        size = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()
    return size / (1024 * 1024)


def check_database_size(size_mb: float | None, limit_mb: int) -> bool:
    """Avvisa (una volta al giorno) se il database ha passato la soglia."""
    if not limit_mb or size_mb is None or size_mb < limit_mb:
        return False
    return send_alert(
        "db-size", f"Database a {size_mb:.0f} MB",
        f"Il piano gratuito di Supabase arriva a 500 MB, e l'avviso parte da {limit_mb}: "
        "è ora di passare a Supabase Pro (docs/hosting.md, passo 8).",
        level="warning", throttle_secs=DB_SIZE_ALERT_SECS,
    )


def check() -> None:
    """Un giro: il controllo da GitHub e il peso del database."""
    settings = get_settings()
    status_check.check(settings.status_check_alert_hours)
    try:
        check_database_size(database_size_mb(), settings.db_size_alert_mb)
    except Exception:  # noqa: BLE001 — il database giù lo dice già il watchdog
        logger.warning("Non riesco a leggere quanto pesa il database", exc_info=True)
