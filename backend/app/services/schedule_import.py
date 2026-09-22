"""
schedule_import.py — Il calendario del negozio da un file.

EventLink non esporta il calendario: il negozio lo tiene su un foglio di
calcolo (o lo ricopia da EventLink) e lo carica qui, un torneo per riga.
Come per player_import: virgole o punti e virgola (Excel in italiano salva
così), intestazioni in italiano o in inglese, date all'italiana. Qui si legge
soltanto; cosa creare lo decide il router, riga per riga.
"""
import csv
import io
import re
from dataclasses import dataclass
from datetime import date


@dataclass
class ScheduleRow:
    line: int
    name: str = ""
    starts_on: date | None = None
    start_time: str | None = None
    format: str = ""
    entry_fee_cents: int | None = None
    capacity: int | None = None
    event_type: str = "locals"
    rules_enforcement_level: str = ""
    description: str = ""
    error: str = ""


HEADERS = {
    "name": {"nome", "name", "evento", "event", "event name", "nome evento", "titolo", "title", "torneo", "tournament"},
    "date": {"data", "date", "giorno", "day", "event date", "data evento"},
    "time": {"ora", "orario", "time", "inizio", "start", "start time", "ora inizio", "orario inizio"},
    "format": {"formato", "format", "event format"},
    "fee": {"quota", "costo", "prezzo", "entry fee", "fee", "price", "iscrizione", "entry"},
    "capacity": {"posti", "capienza", "capacity", "max players", "max giocatori", "giocatori", "players"},
    "event_type": {"tipo", "type", "tipo evento", "event type"},
    "rel": {"rel", "livello", "level", "rules enforcement level"},
    "description": {"descrizione", "description", "note", "notes", "dettagli", "details"},
}
FREE = {"", "0", "gratis", "gratuito", "free", "-"}
RELS = {"casual": "Regular", "regular": "Regular", "competitive": "Competitive", "competitivo": "Competitive",
        "professional": "Professional", "professionale": "Professional"}


def _norm(cell: str) -> str:
    return cell.strip().lower().replace("_", " ")


def parse_date(text: str) -> date:
    """2026-10-03, 03/10/2026, 3/10/26, 03.10.2026: giorno prima del mese.
    Da Excel può arrivare anche l'ora attaccata: qui conta solo la data."""
    s = re.split(r"[ T]", text.strip(), maxsplit=1)[0]
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        year, month, day = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})", s):
        day, month, year = map(int, m.groups())
        year += 2000 if year < 100 else 0
    else:
        raise ValueError("Data non valida: usa gg/mm/aaaa")
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError("Data non valida: usa gg/mm/aaaa") from exc


def parse_time(text: str) -> str | None:
    """20:30, 20.30, 20, 8:30 PM → "20:30"."""
    s = text.strip().lower().replace(".", ":")
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*(am|pm)?", s)
    if not m:
        raise ValueError("Orario non valido: usa hh:mm")
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "pm" and hour < 12:
        hour += 12
    elif m.group(3) == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ValueError("Orario non valido: usa hh:mm")
    return f"{hour:02d}:{minute:02d}"


def parse_fee(text: str) -> int:
    """5, 5,00, € 5.50, 5€, gratis → centesimi."""
    s = re.sub(r"[€$£\s]|eur|usd", "", text.strip().lower())
    if s in FREE:
        return 0
    s = s.replace(".", "").replace(",", ".") if "," in s and "." in s else s.replace(",", ".")
    try:
        value = float(s)
    except ValueError as exc:
        raise ValueError("Quota non valida") from exc
    if value < 0:
        raise ValueError("Quota non valida")
    return round(value * 100)


def guess_event_type(text: str) -> str:
    """Dal tipo scritto nel file, o dal nome del torneo se il tipo manca."""
    t = text.lower()
    if "prerelease" in t or "pre-release" in t or "pre release" in t:
        return "prerelease"
    if "rcq" in t or "qualifier" in t or "qualificazione" in t:
        return "rcq"
    if "store championship" in t or "campionato" in t:
        return "store_championship"
    return "locals"


def guess_format(name: str, formats: tuple[str, ...]) -> str:
    """Un formato del gioco citato nel nome ("FNM Modern"), se c'è."""
    words = set(re.findall(r"[a-zà-ú]+", name.lower()))
    return next((f for f in formats if f.lower() in words), "")


def parse_schedule_csv(text: str, formats: tuple[str, ...] = ()) -> list[ScheduleRow]:
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
    if "name" not in columns or "date" not in columns:
        raise ValueError("Servono almeno le colonne nome e data nella prima riga: scarica il modello")

    def cell(row: list[str], key: str) -> str:
        i = columns.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    parsed: list[ScheduleRow] = []
    for number, row in enumerate(rows[1:], start=2):
        item = ScheduleRow(line=number, name=cell(row, "name")[:180], description=cell(row, "description")[:4000])
        parsed.append(item)
        item.format = cell(row, "format")[:80] or guess_format(item.name, formats)
        item.event_type = guess_event_type(cell(row, "event_type") or item.name)
        item.rules_enforcement_level = RELS.get(cell(row, "rel").lower(), "")
        raw_date = cell(row, "date")
        # L'ora può stare nella sua colonna o attaccata alla data (Excel, che
        # però scrive mezzanotte quando l'ora non c'è).
        date_time = raw_date.split(" ", 1)[1] if " " in raw_date else ""
        if date_time.startswith("00:00"):
            date_time = ""
        try:
            if not item.name:
                raise ValueError("Manca il nome")
            if not raw_date:
                raise ValueError("Manca la data")
            item.starts_on = parse_date(raw_date)
            item.start_time = parse_time(cell(row, "time") or date_time)
            if "fee" in columns:
                item.entry_fee_cents = parse_fee(cell(row, "fee"))
            if cell(row, "capacity"):
                if not cell(row, "capacity").isdigit():
                    raise ValueError("Posti non validi")
                item.capacity = int(cell(row, "capacity"))
            if not item.format:
                raise ValueError("Manca il formato")
        except ValueError as exc:
            item.error = str(exc)
    return parsed
