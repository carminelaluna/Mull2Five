"""
pairings.py — Il motore del torneo: abbinamenti, turni, risultati e classifica.

Svizzera e tabellone a eliminazione, tavoli, bye, squadre e pod, punteggi e
spareggi. Qui non si risponde a nessuna richiesta: si calcola soltanto.
"""
import math
import random

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload  # noqa: F401

from backend.app.games import ALLOWED_SCORES, get_game
from backend.app.models import (
    DecklistStatus,
    Pairing,
    PaymentStatus,
    Registration,
    Round,
    Team,
    Tournament,
    TournamentStatus,
    TournamentStructure,
)
from backend.app.schemas import (
    ManualPairingIn,
    PairingOut,
    PairingResultIn,
    RoundOut,
    StandingOut,
)

NO_ROUNDS = "Evento di sola iscrizione: non ci sono turni. Quando è finito, chiudilo."


def validate_pairing_registration(tournament_id: int, registration_id: int, db: Session) -> None:
    exists = db.scalar(
        select(func.count(Registration.id)).where(
            Registration.id == registration_id,
            Registration.tournament_id == tournament_id,
            Registration.dropped == False,  # noqa: E712
        )
    )
    if not exists:
        raise HTTPException(status_code=422, detail="Questa iscrizione non può stare in questa partita")


def validate_manual_pairing_conflicts(pairing: Pairing, payload: ManualPairingIn, db: Session) -> None:
    requested_ids = {payload.player_a_registration_id}
    if payload.player_b_registration_id:
        requested_ids.add(payload.player_b_registration_id)
    round_pairings = db.scalars(
        select(Pairing).where(Pairing.round_id == pairing.round_id, Pairing.id != pairing.id)
    ).all()
    for existing in round_pairings:
        if existing.table_number == payload.table_number:
            raise HTTPException(status_code=409, detail="Questo numero di tavolo è già usato")
        existing_ids = {existing.player_a_registration_id}
        if existing.player_b_registration_id:
            existing_ids.add(existing.player_b_registration_id)
        if requested_ids & existing_ids:
            raise HTTPException(status_code=409, detail="Il giocatore ha già una partita in questo turno")


def eligible_registrations(tournament: Tournament, db: Session) -> list[Registration]:
    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id == tournament.id)
        .options(
            selectinload(Registration.player),
            selectinload(Registration.decklists),
            selectinload(Registration.payment),
        )
    ).all()
    return [
        registration
        for registration in registrations
        if registration.payment
        and registration.payment.status == PaymentStatus.PAID
        and not registration.dropped
        and not registration.waitlisted
        and (not tournament.check_in_required or registration.checked_in)
        and (
            not tournament.decklist_required
            or (registration.decklist and registration.decklist.status == DecklistStatus.VALID)
        )
    ]


def create_round_for_tournament(tournament: Tournament, db: Session) -> RoundOut:
    if tournament.structure == TournamentStructure.REGISTRATION_ONLY:
        raise HTTPException(status_code=409, detail=NO_ROUNDS)
    eligible = eligible_registrations(tournament, db)
    if len(eligible) < 2:
        raise HTTPException(status_code=409, detail="Servono almeno due giocatori idonei")

    current_round_number = len(tournament.rounds) + 1
    phase = next_phase(tournament, len(tournament.rounds), len(eligible))
    # Chi ha bye assegnati salta i primi turni della svizzera: li vince senza giocare.
    with_bye = [r for r in eligible if phase == "swiss" and (r.byes or 0) >= current_round_number]
    playing = [r for r in eligible if r not in with_bye]
    # A squadre si abbinano le squadre; ogni incontro sono i match posto contro
    # posto (A contro A, B contro B…), su tavoli vicini. Con la squadra in bye
    # ogni suo giocatore ha il bye. I bye assegnati ai singoli qui non valgono.
    if (tournament.team_size or 1) > 1:
        with_bye = []
        groups = team_round_groups(tournament, eligible, db)
    # In svizzera con i pod di draft ogni pod gioca per conto suo: al primo turno
    # contro chi siede di fronte, poi svizzera dentro il pod.
    elif phase == "swiss" and playing and all(r.pod for r in playing):
        groups = [pod_pair_order(tournament, [r for r in playing if r.pod == pod], db)
                  for pod in sorted({r.pod for r in playing})]
    else:
        groups = [pair_order(tournament, playing, phase, db)] if playing else []
    ordered = [r for group in groups for r in group]
    if phase in {"elimination", "topcut"} and len(ordered) < 2:
        tournament.status = TournamentStatus.COMPLETED
        db.add(tournament)
        db.commit()
        raise HTTPException(status_code=409, detail="Il tabellone è completo")
    round_obj = Round(
        tournament_id=tournament.id,
        number=current_round_number,
        # Online-first: il round è subito pubblicato così i giocatori possono
        # inserire i propri risultati. `pairings_public` controlla separatamente
        # la visibilità sul display pubblico/TV, non la possibilità di refertare.
        phase=phase,
        is_published=True,
        # Il timer NON parte automaticamente: l'organizzatore lo avvia a mano
        # ("Avvia timer" in Regia). Finché ends_at è None il timer è fermo.
        starts_at=None,
        ends_at=None,
    )
    db.add(round_obj)
    db.flush()

    matches = [(group[i], group[i + 1] if i + 1 < len(group) else None)
               for group in groups for i in range(0, len(group), 2)]
    pairings = []
    for (player_a, player_b), table in zip(matches, assign_tables(matches), strict=True):
        pairing = Pairing(
            round_id=round_obj.id,
            table_number=table,
            player_a_registration_id=player_a.id,
            player_b_registration_id=player_b.id if player_b else None,
            result="A" if not player_b else "",
            match_wins_a=2 if not player_b else 0,
            match_wins_b=0,
        )
        db.add(pairing)
        pairings.append(pairing)
    for offset, registration in enumerate(with_bye, start=max([p.table_number for p in pairings], default=0) + 1):
        db.add(Pairing(round_id=round_obj.id, table_number=offset,
                       player_a_registration_id=registration.id, player_b_registration_id=None,
                       result="A", match_wins_a=2, match_wins_b=0))
    db.commit()
    db.refresh(round_obj)
    return round_out(round_obj)


def next_phase(tournament: Tournament, completed_rounds: int, player_count: int) -> str:
    if tournament.structure == TournamentStructure.SINGLE_ELIMINATION:
        return "elimination"
    if tournament.structure == TournamentStructure.SWISS_TOPCUT:
        swiss_rounds = tournament.swiss_rounds or default_swiss_rounds(player_count)
        return "topcut" if completed_rounds >= swiss_rounds else "swiss"
    return "swiss"


def pair_order(tournament: Tournament, eligible: list[Registration], phase: str, db: Session) -> list[Registration]:
    if phase in {"elimination", "topcut"}:
        advancing = elimination_advancers(tournament.id, phase, db)
        if advancing is not None:
            return advancing
        standings = calculate_standings(tournament.id, db)
        top_cut_size = tournament.top_cut_size if phase == "topcut" else len(eligible)
        seed_ids = [standing.registration_id for standing in standings[:top_cut_size]]
        seeded = [registration for registration_id in seed_ids for registration in eligible if registration.id == registration_id]
        return seed_for_elimination(seeded)

    if not tournament.rounds:
        shuffled = eligible[:]
        random.shuffle(shuffled)
        return shuffled

    standings = calculate_standings(tournament.id, db)
    by_id = {registration.id: registration for registration in eligible}
    ordered = [by_id[standing.registration_id] for standing in standings if standing.registration_id in by_id]
    ordered, bye = set_aside_bye(ordered, players_with_bye(tournament.id, db))
    return swiss_pair_order(ordered, previous_opponents(tournament.id, db)) + bye


def complete_teams(tournament: Tournament, eligible: list[Registration], db: Session) -> list[tuple[Team, list[Registration]]]:
    """Le squadre che possono giocare: tutti i posti occupati da giocatori pronti."""
    ready = {r.id: r for r in eligible}
    out = []
    for team in db.scalars(select(Team).where(Team.tournament_id == tournament.id).order_by(Team.id)):
        members = sorted((r for r in ready.values() if r.team_id == team.id), key=lambda r: r.team_seat or 0)
        if len(members) == tournament.team_size and [m.team_seat for m in members] == list(range(1, tournament.team_size + 1)):
            out.append((team, members))
    return out


def team_matches(tournament_id: int, db: Session) -> list:
    """Gli incontri fra squadre giocati finora, ricostruiti dai match individuali."""
    from backend.app.services.standings import TeamMatch

    team_of = dict(db.execute(
        select(Registration.id, Registration.team_id).where(Registration.tournament_id == tournament_id)
    ).all())
    grouped: dict[tuple, TeamMatch] = {}
    for rnd in db.scalars(select(Round).where(Round.tournament_id == tournament_id).options(selectinload(Round.pairings))):
        for p in rnd.pairings:
            ta = team_of.get(p.player_a_registration_id)
            tb = team_of.get(p.player_b_registration_id) if p.player_b_registration_id else None
            if ta is None:
                continue
            if tb is None:
                grouped.setdefault((rnd.id, ta, None), TeamMatch(a=ta, b=None))
                continue
            key = (rnd.id, *sorted((ta, tb)))
            match = grouped.setdefault(key, TeamMatch(a=key[1], b=key[2]))
            winner = {"A": ta, "B": tb}.get(p.result)
            if not p.result:
                match.complete = False
            if winner == match.a:
                match.seats_a += 1
            elif winner == match.b:
                match.seats_b += 1
    return list(grouped.values())


def team_round_groups(tournament: Tournament, eligible: list[Registration], db: Session) -> list[list[Registration]]:
    """Gli abbinamenti di un turno a squadre, come gruppi da due (un match) o
    da uno (un bye). Primo turno a caso, poi svizzera sulla classifica a squadre."""
    from backend.app.services.standings import compute_team_standings

    teams = complete_teams(tournament, eligible, db)
    if len(teams) < 2:
        raise HTTPException(status_code=409, detail="Servono almeno due squadre complete")
    by_id = {team.id: (team, members) for team, members in teams}
    played = team_matches(tournament.id, db)
    if not tournament.rounds:
        ordered = [team for team, _ in teams]
        random.shuffle(ordered)
    else:
        table = compute_team_standings({t.id: t.name for t, _ in teams}, played)
        ordered = [by_id[row["team_id"]][0] for row in table]
        ordered, bye = set_aside_bye(ordered, {m.a for m in played if m.b is None})
        previous = {tuple(sorted((m.a, m.b))) for m in played if m.b is not None}
        ordered = swiss_pair_order(ordered, previous) + bye
    groups: list[list[Registration]] = []
    for i in range(0, len(ordered), 2):
        home = by_id[ordered[i].id][1]
        away = by_id[ordered[i + 1].id][1] if i + 1 < len(ordered) else None
        if away is None:
            groups += [[member] for member in home]
        else:
            groups += [[a, b] for a, b in zip(home, away, strict=True)]
    return groups


def assign_tables(matches: list[tuple[Registration, Registration | None]]) -> list[int]:
    """I numeri di tavolo: chi ha un tavolo fisso gioca lì (se due lo chiedono,
    vince il primo), gli altri riempiono i numeri liberi in ordine."""
    fixed: dict[int, int] = {}
    for index, (a, b) in enumerate(matches):
        wanted = a.fixed_table or (b.fixed_table if b else None)
        if wanted and wanted not in fixed.values():
            fixed[index] = wanted
    used = set(fixed.values())
    tables, next_free = [], 1
    for index in range(len(matches)):
        if index in fixed:
            tables.append(fixed[index])
            continue
        while next_free in used:
            next_free += 1
        tables.append(next_free)
        used.add(next_free)
    return tables


def pod_pair_order(tournament: Tournament, members: list[Registration], db: Session) -> list[Registration]:
    """L'ordine di abbinamento dentro un pod. Al primo turno si gioca contro chi
    siede di fronte (posto 1 contro 5, 2 contro 6 in un pod da 8); con un pod
    dispari resta senza avversario l'ultimo della prima metà. Poi svizzera."""
    if tournament.rounds:
        return pair_order(tournament, members, "swiss", db)
    seated = sorted(members, key=lambda r: r.pod_seat or 0)
    half = (len(seated) + 1) // 2
    ordered: list[Registration] = []
    for i in range(half):
        if i + half < len(seated):
            ordered += [seated[i], seated[i + half]]
    return ordered + [r for r in seated[:half] if r not in ordered]


def players_with_bye(tournament_id: int, db: Session) -> set[int]:
    """Chi ha già avuto un bye, naturale o assegnato."""
    return set(db.scalars(
        select(Pairing.player_a_registration_id).join(Round)
        .where(Round.tournament_id == tournament_id, Pairing.player_b_registration_id.is_(None))
    ).all())


def set_aside_bye(ordered: list[Registration], had_bye: set[int]) -> tuple[list[Registration], list[Registration]]:
    """Con un numero dispari il bye va al più basso in classifica che non l'ha
    ancora avuto (se l'hanno avuto tutti, all'ultimo): lo si mette da parte prima
    di abbinare gli altri, così non finisce abbinato per sbaglio."""
    if len(ordered) % 2 == 0:
        return ordered, []
    chosen = next((r for r in reversed(ordered) if r.id not in had_bye), ordered[-1])
    return [r for r in ordered if r is not chosen], [chosen]


def elimination_advancers(tournament_id: int, phase: str, db: Session) -> list[Registration] | None:
    latest_phase_round = db.scalar(
        select(Round)
        .where(Round.tournament_id == tournament_id, Round.phase == phase)
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.assigned_judge),
        )
        .order_by(Round.number.desc())
    )
    if not latest_phase_round:
        return None
    if any(not pairing.result and pairing.player_b_registration_id for pairing in latest_phase_round.pairings):
        raise HTTPException(status_code=409, detail="Prima completa i risultati del tabellone")

    winners: list[Registration] = []
    for pairing in sorted(latest_phase_round.pairings, key=lambda item: item.table_number):
        if not pairing.player_b_registration_id or pairing.result == "A":
            winners.append(pairing.player_a)
        elif pairing.result == "B" and pairing.player_b:
            winners.append(pairing.player_b)
    return winners


def swiss_pair_order(ordered: list[Registration], previous: set[tuple[int, int]]) -> list[Registration]:
    remaining = ordered[:]
    pairs: list[Registration] = []
    while remaining:
        player = remaining.pop(0)
        opponent_index = 0
        for index, candidate in enumerate(remaining):
            if tuple(sorted((player.id, candidate.id))) not in previous:
                opponent_index = index
                break
        pairs.append(player)
        if remaining:
            pairs.append(remaining.pop(opponent_index))
    return pairs


def seed_for_elimination(seeded: list[Registration]) -> list[Registration]:
    ordered: list[Registration] = []
    left = 0
    right = len(seeded) - 1
    while left <= right:
        ordered.append(seeded[left])
        if left != right:
            ordered.append(seeded[right])
        left += 1
        right -= 1
    return ordered


def previous_opponents(tournament_id: int, db: Session) -> set[tuple[int, int]]:
    pairs = db.scalars(select(Pairing).join(Round).where(Round.tournament_id == tournament_id)).all()
    return {
        tuple(sorted((pairing.player_a_registration_id, pairing.player_b_registration_id)))
        for pairing in pairs
        if pairing.player_b_registration_id
    }


def ensure_latest_round_has_results(tournament_id: int, db: Session) -> None:
    latest_round = db.scalar(
        select(Round)
        .where(Round.tournament_id == tournament_id)
        .options(selectinload(Round.pairings))
        .order_by(Round.number.desc())
    )
    if latest_round and any(
        not pairing.result and pairing.player_b_registration_id for pairing in latest_round.pairings
    ):
        raise HTTPException(status_code=409, detail="Prima completa i risultati del turno")


def decklists_locked(tournament: Tournament) -> bool:
    """Delega al modello: la regola vive accanto ai campi che la determinano."""
    return tournament.decklist_locked


def apply_pairing_result(
    tournament_id: int,
    pairing: Pairing,
    payload: PairingResultIn,
    db: Session,
) -> None:
    latest_round_number = db.scalar(
        select(func.max(Round.number)).where(Round.tournament_id == tournament_id)
    )
    if latest_round_number and pairing.round.number < latest_round_number:
        raise HTTPException(status_code=409, detail="Risultato bloccato: c'è già un turno successivo")
    if not pairing.player_b_registration_id:
        raise HTTPException(status_code=409, detail="Il risultato di un bye è automatico")
    ensure_allowed_score(payload, pairing, db)
    pairing.match_wins_a = payload.match_wins_a
    pairing.match_wins_b = payload.match_wins_b
    pairing.draws = payload.draws
    if payload.match_wins_a > payload.match_wins_b:
        pairing.result = "A"
    elif payload.match_wins_b > payload.match_wins_a:
        pairing.result = "B"
    else:
        pairing.result = "D"
    db.commit()


def ensure_allowed_score(payload: PairingResultIn, pairing: Pairing, db: Session) -> None:
    """Il punteggio deve essere possibile nel formato del match: al meglio di 1, 2
    o 3 in svizzera; nei playoff sempre al meglio di 3 e senza patta."""
    phase, best_of = db.execute(
        select(Round.phase, Tournament.best_of)
        .join(Tournament, Tournament.id == Round.tournament_id)
        .where(Round.id == pairing.round_id)
    ).one()
    if phase != "swiss":
        allowed = {score for score in ALLOWED_SCORES[3] if score[0] != score[1]}
    else:
        allowed = ALLOWED_SCORES.get(best_of or 3, ALLOWED_SCORES[3])
    if (payload.match_wins_a, payload.match_wins_b) not in allowed:
        raise HTTPException(status_code=422, detail="Risultato non ammesso")


def default_swiss_rounds(player_count: int) -> int:
    """Numero di turni svizzeri = ceil(log2(iscritti)).
    Es: 8→3, 16→4, 32→5, 64→6 (standard MTG). Minimo 1."""
    return max(1, math.ceil(math.log2(max(2, player_count))))


def planned_swiss_rounds(tournament: Tournament, eligible_count: int) -> int:
    """Turni svizzeri previsti per il torneo: override manuale se impostato,
    altrimenti calcolo automatico ceil(log2(iscritti))."""
    return tournament.swiss_rounds or default_swiss_rounds(eligible_count)


def calculate_standings(tournament_id: int, db: Session) -> list[StandingOut]:
    """La classifica del torneo, con gli spareggi del suo gioco (services/standings.py)."""
    from backend.app.services.standings import Match as StandingMatch
    from backend.app.services.standings import Player as StandingPlayer
    from backend.app.services.standings import compute_standings

    tournament = db.get(Tournament, tournament_id)
    registrations = db.scalars(
        select(Registration)
        .where(Registration.tournament_id == tournament_id)
        .options(selectinload(Registration.player))
    ).all()
    pairings = db.scalars(select(Pairing).join(Round).where(Round.tournament_id == tournament_id)).all()
    swiss_rounds = db.scalar(
        select(func.count(Round.id)).where(Round.tournament_id == tournament_id, Round.phase == "swiss")
    ) or 0
    rows = compute_standings(
        [StandingPlayer(r.id, r.player.display_name, dropped=r.dropped) for r in registrations],
        [
            StandingMatch(p.player_a_registration_id, p.player_b_registration_id, p.result,
                          p.match_wins_a, p.match_wins_b, p.draws)
            for p in pairings
        ],
        system=get_game(tournament.game if tournament else None).tiebreakers,
        total_rounds=swiss_rounds,
    )
    return [StandingOut(**row) for row in rows]


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def round_out(
    round_obj: Round,
    report_map: dict[int, dict] | None = None,
    pairings: list[Pairing] | None = None,
) -> RoundOut:
    """Costruisce RoundOut da un Round SQLAlchemy.

    report_map deve essere dict[pairing_id, dict] (plain dict, non oggetti SQLAlchemy)
    per evitare DetachedInstanceError quando il risultato viene servito dalla cache.
    pairings, se fornito, sostituisce round_obj.pairings senza mutare la relazione ORM
    (assegnare round_obj.pairings dissocerebbe gli altri pairing dal round).
    """
    report_map = report_map or {}
    pairing_list = pairings if pairings is not None else round_obj.pairings
    return RoundOut(
        id=round_obj.id,
        tournament_id=round_obj.tournament_id,
        number=round_obj.number,
        phase=round_obj.phase,
        format=round_obj.format,
        is_published=round_obj.is_published,
        starts_at=round_obj.starts_at,
        ends_at=round_obj.ends_at,
        pairings=[
            PairingOut(
                id=pairing.id,
                table_number=pairing.table_number,
                player_a=pairing.player_a.player.display_name,
                player_a_registration_id=pairing.player_a_registration_id,
                player_b=pairing.player_b.player.display_name if pairing.player_b else None,
                player_b_registration_id=pairing.player_b_registration_id,
                result=pairing.result,
                match_wins_a=pairing.match_wins_a,
                match_wins_b=pairing.match_wins_b,
                draws=pairing.draws,
                extra_seconds=pairing.extra_seconds,
                assigned_judge_id=pairing.assigned_judge_id,
                assigned_judge_name=(
                    pairing.assigned_judge.display_name if pairing.assigned_judge else ""
                ),
                table_status=pairing.table_status or "playing",
                report_id=report_map[pairing.id]["id"] if pairing.id in report_map else None,
                report_status=report_map[pairing.id]["status"] if pairing.id in report_map else "",
                report_score=(
                    f"{report_map[pairing.id]['match_wins_a']}-{report_map[pairing.id]['match_wins_b']}"
                    if pairing.id in report_map
                    else ""
                ),
                report_reporter_registration_id=(
                    report_map[pairing.id]["reporter_registration_id"] if pairing.id in report_map else None
                ),
                report_reporter_name=(
                    report_map[pairing.id]["reporter_name"] if pairing.id in report_map else ""
                ),
            )
            for pairing in sorted(pairing_list, key=lambda item: item.table_number)
        ],
    )
