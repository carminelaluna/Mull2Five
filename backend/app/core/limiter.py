"""Rate limiting centralizzato con slowapi."""
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.app.core.config import get_settings

# Nei test le richieste partono tutte dallo stesso "indirizzo" e in pochi secondi:
# con il limite acceso una suite lunga si spegne da sola a metà.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    enabled=get_settings().app_env != "test",
)
