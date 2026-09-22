"""
Piccola cache in memoria con scadenza, per processo.

Per i dati che cambiano di rado e costano cari da rifare: le carte di Scryfall,
le classifiche dei tornei conclusi. A differenza di core/cache.py non serve Redis:
ogni worker tiene la sua copia, quindi va usata solo dove un dato vecchio di
qualche minuto non fa danni.
"""
import threading
import time
from collections import OrderedDict


class TtlCache:
    def __init__(self, ttl: float, size: int) -> None:
        self.ttl, self.size = ttl, size
        self._data: OrderedDict[object, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: object) -> tuple[bool, object]:
        """(True, valore) se c'è e non è scaduto; (False, None) altrimenti.
        La coppia distingue un valore None salvato da una chiave assente."""
        with self._lock:
            hit = self._data.get(key)
            if not hit or hit[0] < time.monotonic():
                return False, None
            self._data.move_to_end(key)
            return True, hit[1]

    def set(self, key: object, value: object) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
