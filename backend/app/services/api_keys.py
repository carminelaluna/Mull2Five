"""
Chiavi dell'API pubblica.

La chiave in chiaro si mostra una volta, quando si crea; nel database resta solo
lo SHA-256. È una stringa casuale lunga (non una password scelta da una
persona): per confrontarla basta l'hash, senza sale né bcrypt.
"""
import hashlib
import secrets

KEY_PREFIX = "m2f_"
# Quanto della chiave si mostra nell'elenco per riconoscerla: "m2f_AbCdEfGh".
SHOWN_CHARS = 12


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
