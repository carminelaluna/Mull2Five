"""
clock.py — Che giorno è, e che ora, dove si gioca.

Le date e gli orari dei tornei sono quelli del negozio ("venerdì alle 20:00"),
non UTC. Tra mezzanotte e le due, in Italia, UTC è ancora ieri: una sospensione
"fino al 21" sarebbe ancora in corso il 22, e un torneo delle 20:00 letto come
UTC chiuderebbe le liste alle 21:30 invece che alle 19:30.
"""
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from backend.app.core.config import get_settings


@lru_cache
def local_zone() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


def local_today() -> date:
    """Il giorno di calendario dove si gioca."""
    return datetime.now(local_zone()).date()
