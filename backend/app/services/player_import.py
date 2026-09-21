"""
player_import.py — Leggere una lista di giocatori da un file.

Arriva da un foglio di calcolo o da un'altra piattaforma: separatore virgola o
punto e virgola (Excel in italiano salva così), intestazioni in italiano o in
inglese, oppure nessuna intestazione. Qui si capisce solo cosa c'è scritto;
cosa farne lo decide chi iscrive.
"""
import csv
import io
from dataclasses import dataclass


@dataclass
class ImportedPlayer:
    line: int
    email: str
    name: str = ""
    publisher_id: str = ""
    paid: bool = False


HEADERS = {
    "email": {"email", "e-mail", "mail", "indirizzo email", "email address"},
    "name": {"nome", "name", "giocatore", "player", "display name", "nome e cognome", "full name"},
    "publisher_id": {
        "id editore", "wizards", "wizards account", "player id", "id giocatore", "dci",
        "konami id", "publisher id", "pokemon id", "play! pokemon id", "bandai id",
    },
    "paid": {"pagato", "paid", "pagamento", "payment"},
}
TRUE = {"sì", "si", "s", "yes", "y", "x", "1", "true", "vero", "pagato", "paid", "ok"}


def _norm(cell: str) -> str:
    return cell.strip().lower().replace("_", " ")


def parse_players_csv(text: str) -> list[ImportedPlayer]:
    lines = [line for line in text.lstrip("﻿").splitlines() if line.strip()]
    if not lines:
        raise ValueError("Il file è vuoto")
    try:
        delimiter = csv.Sniffer().sniff("\n".join(lines[:5]), delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ";" if ";" in lines[0] else ","
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))

    header = [_norm(cell) for cell in rows[0]]
    columns: dict[str, int] = {}
    for key, names in HEADERS.items():
        found = next((i for i, cell in enumerate(header) if cell in names), None)
        if found is not None:
            columns[key] = found
    first_data = 1
    if "email" not in columns:
        # Niente intestazione: la colonna con la chiocciola è l'email, le altre
        # sono nome e ID dell'editore, nell'ordine in cui compaiono.
        at = next((i for i, cell in enumerate(rows[0]) if "@" in cell), None)
        if at is None:
            raise ValueError("Non trovo la colonna delle email")
        others = [i for i in range(len(rows[0])) if i != at]
        columns = {"email": at, **dict(zip(("name", "publisher_id"), others, strict=False))}
        first_data = 0

    def cell(row: list[str], key: str) -> str:
        i = columns.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    return [
        ImportedPlayer(
            line=number,
            email=cell(row, "email"),
            name=cell(row, "name"),
            publisher_id=cell(row, "publisher_id"),
            paid=cell(row, "paid").lower() in TRUE,
        )
        for number, row in enumerate(rows[first_data:], start=first_data + 1)
    ]
