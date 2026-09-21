"""
Classifica di un torneo, con gli spareggi del gioco.

Funzione pura su dati semplici, senza database: ogni sistema di spareggi si
verifica con pochi numeri scritti a mano (tests/test_standings.py).

Sistemi (fonti in TODO.md, "Parità con Melee"):
- "mtr": Magic Tournament Rules, usato anche da Lorcana e Star Wars Unlimited.
  Punti, poi OMW%, GW%, OGW%; nessuna percentuale sotto un terzo.
- "onepiece": Tournament Rules Manual 5.4. Punti, poi win rate proprio, poi win
  rate medio degli avversari; bye esclusi dal calcolo, minimo 0,33.
- "pokemon": Play! Pokémon Tournament Rules Handbook 5.3. Punti, poi Op Win %,
  poi Op Op Win %, poi lo scontro diretto; win % tra 25% e 100% (75% per chi
  ha lasciato), e un bye non conta come vittoria.
"""
from dataclasses import dataclass, field

MTR_FLOOR = 1 / 3
ONE_PIECE_FLOOR = 0.33
POKEMON_FLOOR = 0.25
POKEMON_DROP_CAP = 0.75


@dataclass
class Player:
    id: int
    name: str
    dropped: bool = False


@dataclass
class Match:
    a: int
    b: int | None            # None: bye per a
    result: str | None       # "A", "B", "D" (patta) o None se non ancora giocato
    wins_a: int = 0
    wins_b: int = 0
    draws: int = 0


@dataclass
class _Record:
    points: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    byes: int = 0
    game_points: int = 0      # 3 per gioco vinto, 1 per gioco patto (MTR)
    games: int = 0
    opponents: list[int] = field(default_factory=list)
    beaten: set[int] = field(default_factory=set)

    @property
    def rounds(self) -> int:
        return self.wins + self.losses + self.draws


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _records(players: list[Player], matches: list[Match]) -> dict[int, _Record]:
    records = {p.id: _Record() for p in players}
    for m in matches:
        a = records.get(m.a)
        if a is None:
            continue
        if m.b is None:
            # Bye: una vittoria per 2-0 nei punti e nei giochi (MTR), ma non un avversario.
            a.points += 3
            a.wins += 1
            a.byes += 1
            a.game_points += 6
            a.games += 2
            continue
        b = records.get(m.b)
        if b is None or not m.result:
            continue
        a.opponents.append(m.b)
        b.opponents.append(m.a)
        games = m.wins_a + m.wins_b + m.draws
        a.games += games
        b.games += games
        a.game_points += 3 * m.wins_a + m.draws
        b.game_points += 3 * m.wins_b + m.draws
        if m.result == "A":
            a.points += 3
            a.wins += 1
            b.losses += 1
            a.beaten.add(m.b)
        elif m.result == "B":
            b.points += 3
            b.wins += 1
            a.losses += 1
            b.beaten.add(m.a)
        else:
            a.points += 1
            b.points += 1
            a.draws += 1
            b.draws += 1
    return records


def _mtr(records: dict[int, _Record]) -> dict[int, tuple]:
    mwp = {pid: max(r.points / (3 * r.rounds), MTR_FLOOR) if r.rounds else 0.0
           for pid, r in records.items()}
    gwp = {pid: max(r.game_points / (3 * r.games), MTR_FLOOR) if r.games else 0.0
           for pid, r in records.items()}
    out = {}
    for pid, r in records.items():
        omw = _average([mwp[o] for o in r.opponents])
        ogw = _average([gwp[o] for o in r.opponents])
        # (chiavi di ordinamento dopo i punti), poi i valori da mostrare
        out[pid] = ((omw, gwp[pid], ogw), {
            "match_win_percentage": mwp[pid],
            "opponent_match_win_percentage": omw,
            "game_win_percentage": gwp[pid],
            "opponent_game_win_percentage": ogw,
        })
    return out


def _onepiece(records: dict[int, _Record]) -> dict[int, tuple]:
    def own(r: _Record) -> float:
        rounds = r.rounds - r.byes
        points = r.points - 3 * r.byes
        return max(points / (3 * rounds), ONE_PIECE_FLOOR) if rounds else ONE_PIECE_FLOOR

    mwr = {pid: own(r) for pid, r in records.items()}
    out = {}
    for pid, r in records.items():
        opp = _average([mwr[o] for o in r.opponents]) if r.opponents else ONE_PIECE_FLOOR
        out[pid] = ((mwr[pid], opp), {
            "match_win_percentage": mwr[pid],
            "opponent_match_win_percentage": opp,
        })
    return out


def _pokemon(players: list[Player], records: dict[int, _Record], total_rounds: int) -> dict[int, tuple]:
    dropped = {p.id for p in players if p.dropped}

    def win_pct(pid: int, r: _Record) -> float:
        # Chi ha finito si divide per i turni del torneo, chi ha lasciato per quelli giocati.
        rounds = r.rounds if pid in dropped else max(total_rounds, r.rounds)
        if not rounds:
            return POKEMON_FLOOR
        cap = POKEMON_DROP_CAP if pid in dropped else 1.0
        return min(max((r.wins - r.byes) / rounds, POKEMON_FLOOR), cap)

    wp = {pid: win_pct(pid, r) for pid, r in records.items()}
    owp = {pid: _average([wp[o] for o in r.opponents]) for pid, r in records.items()}
    out = {}
    for pid, r in records.items():
        oowp = _average([owp[o] for o in r.opponents])
        out[pid] = ((owp[pid], oowp), {
            "match_win_percentage": wp[pid],
            "opponent_match_win_percentage": owp[pid],
            "opponent_opponent_win_percentage": oowp,
        })
    return out


def compute_standings(
    players: list[Player],
    matches: list[Match],
    system: str = "mtr",
    total_rounds: int | None = None,
) -> list[dict]:
    """La classifica ordinata. Le percentuali escono da 0 a 100, a un decimale."""
    records = _records(players, matches)
    if system == "onepiece":
        breakers = _onepiece(records)
    elif system == "pokemon":
        rounds = total_rounds if total_rounds is not None else max((r.rounds for r in records.values()), default=0)
        breakers = _pokemon(players, records, rounds)
    else:
        breakers = _mtr(records)

    def key(pid: int) -> tuple:
        return (records[pid].points, *breakers[pid][0])

    order = sorted(records, key=key, reverse=True)

    if system == "pokemon":
        # Scontro diretto: tra due giocatori pari in tutto, prima chi ha vinto la sfida.
        for i in range(len(order) - 1):
            first, second = order[i], order[i + 1]
            if key(first) == key(second) and first in records[second].beaten:
                order[i], order[i + 1] = second, first

    names = {p.id: p.name for p in players}
    rows = []
    for position, pid in enumerate(order, start=1):
        r = records[pid]
        values = {name: round(value * 100, 1) for name, value in breakers[pid][1].items()}
        rows.append({
            "position": position,
            "registration_id": pid,
            "name": names[pid],
            "points": r.points,
            "record": f"{r.wins}/{r.losses}/{r.draws}",
            **values,
        })
    return rows
