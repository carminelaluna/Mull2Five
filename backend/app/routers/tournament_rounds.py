"""
tournament_rounds.py — Il torneo mentre si gioca.

Turni e abbinamenti, risultati (dello staff e dei giocatori), correzioni,
timer, tabellone, classifica, schermi in sala, controlli delle liste e day 2.
Le rotte stanno sotto /tournaments come le altre: qui cambia solo il file,
perché tournaments.py era diventato illeggibile.
"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.app.db import get_db
from backend.app.models import (
    AuditLog,
    DeckCheck,
    Pairing,
    PairingResultReport,
    Penalty,
    Registration,
    ResultReportStatus,
    Round,
    Tournament,
    TournamentStatus,
    TournamentStructure,
    User,
)
from backend.app.schemas import (
    AuditLogOut,
    BracketMatchOut,
    Day2ConversionRow,
    Day2In,
    DeckCheckIn,
    DeckCheckOut,
    ManualPairingIn,
    MetaStatRow,
    PairingResultIn,
    PairingResultRejectIn,
    PublicDisplayOut,
    PublicPairingOut,
    PublicResultsOut,
    PublicStandingRow,
    RegenerateRoundIn,
    RoundFormatIn,
    RoundOut,
    StandingOut,
    TableAssignIn,
    TableExtendIn,
    TableStatusIn,
    TardinessIn,
    TimerExtendIn,
    TimerRestartIn,
)
from backend.app.security import get_current_user, require_organizer
from backend.app.services.audit import write_audit
from backend.app.services.pairings import (
    apply_pairing_result,
    calculate_standings,
    create_round_for_tournament,
    eligible_registrations,
    ensure_allowed_score,
    ensure_latest_round_has_results,
    planned_swiss_rounds,
    round_out,
    validate_manual_pairing_conflicts,
    validate_pairing_registration,
)
from backend.app.services.stores import store_role
from backend.app.services.tournament_access import (
    ensure_tournament_live,
    is_tournament_staff,
    load_owned_tournament,
    load_registration_for_tournament,
    load_tournament_for_head_judge,
    load_tournament_for_staff,
    owns_tournament,
)

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


@router.get("/{tournament_id}/standings", response_model=list[StandingOut])
def get_standings(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StandingOut]:
    from backend.app.core.cache import cache_get, cache_set
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    if not tournament.standings_public and not owns_tournament(tournament, user, db):
        return []
    cache_key = f"standings:{tournament_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    result = calculate_standings(tournament_id, db)
    cache_set(cache_key, result, ttl=30.0)   # 30s — invalidata esplicitamente dopo ogni risultato
    return result


@router.get("/{tournament_id}/rounds", response_model=list[RoundOut])
def list_rounds(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RoundOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    is_staff = owns_tournament(tournament, user, db) or is_tournament_staff(tournament_id, user.id, db)
    rounds = db.scalars(
        select(Round)
        .where(Round.tournament_id == tournament_id)
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.assigned_judge),
        )
        .order_by(Round.number)
    ).all()
    report_map = latest_result_reports(tournament_id, db)
    if not is_staff:
        rounds = [round_obj for round_obj in rounds if round_obj.is_published and tournament.pairings_public]
    return [round_out(round_obj, report_map) for round_obj in rounds]


@router.get("/{tournament_id}/my-pairings", response_model=list[RoundOut])
def my_pairings(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RoundOut]:
    # Niente cache: dato live e per-giocatore. Con più worker Gunicorn la cache
    # in-memory è per-processo e l'invalidazione non si propaga: un avversario
    # potrebbe non vedere il risultato appena inserito (sezione conferma assente).
    # La query carica solo i 3 pairing del giocatore, è economica.
    registration = db.scalar(
        select(Registration).where(
            Registration.tournament_id == tournament_id,
            Registration.player_id == user.id,
        )
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Iscrizione non trovata")

    # Carica SOLO i pairing di questo giocatore (3 righe), non tutti i 1500
    pairings = db.scalars(
        select(Pairing)
        .join(Round)
        .where(
            Round.tournament_id == tournament_id,
            (Pairing.player_a_registration_id == registration.id)
            | (Pairing.player_b_registration_id == registration.id),
        )
        .options(
            selectinload(Pairing.round),
            selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Pairing.player_b).selectinload(Registration.player),
        )
        .order_by(Round.number)
    ).all()

    # Raggruppa per round
    round_map: dict[int, tuple[Round, list[Pairing]]] = {}
    for pairing in pairings:
        rnd = pairing.round
        if rnd.id not in round_map:
            round_map[rnd.id] = (rnd, [])
        round_map[rnd.id][1].append(pairing)

    report_map = latest_result_reports(tournament_id, db)
    result = []
    for rnd, player_pairings in sorted(round_map.values(), key=lambda x: x[0].number):
        # NON mutare rnd.pairings: assegnare la relazione ORM dissocia gli altri
        # pairing dal round (UPDATE round_id=NULL al commit successivo)
        result.append(round_out(rnd, report_map, pairings=player_pairings))

    if registration.tournament.is_online:
        # Online l'avversario si cerca col suo nome in gioco: lo vede solo chi ci gioca.
        by_id = {pairing.id: pairing for pairing in pairings}
        for rnd_out in result:
            for item in rnd_out.pairings:
                pairing = by_id[item.id]
                item.player_a_handle = pairing.player_a.game_handle
                item.player_b_handle = pairing.player_b.game_handle if pairing.player_b else ""
    return result


@router.post("/{tournament_id}/rounds", response_model=RoundOut)
def create_round(
    tournament_id: int,
    force: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Genera il round successivo. Organizzatore o capojudge: in sala è il capojudge
    a mandare avanti i turni, e se l'organizzatore esce dal negozio il torneo non
    deve fermarsi."""
    tournament, _ = load_tournament_for_head_judge(tournament_id, user, db)
    ensure_tournament_live(tournament)   # su torneo chiuso dà il messaggio giusto
    if tournament.status != TournamentStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Avvia il torneo prima di creare i turni")
    ensure_latest_round_has_results(tournament_id, db)

    # Torneo svizzero "puro": i turni previsti sono ceil(log2(iscritti)). Generare
    # un turno oltre quel numero può ripetere gli abbinamenti → richiede conferma.
    if tournament.structure == TournamentStructure.SWISS and not force:
        eligible_count = len(eligible_registrations(tournament, db))
        planned = planned_swiss_rounds(tournament, eligible_count)
        next_number = len(tournament.rounds) + 1
        if next_number > planned:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"EXTRA_SWISS_ROUND: i {planned} turni svizzeri previsti per "
                    f"{eligible_count} giocatori sono completati. Un turno aggiuntivo "
                    "può ripetere gli abbinamenti: è sconsigliato."
                ),
            )

    result = create_round_for_tournament(tournament, db)
    # Notifica email pairings pronti
    try:
        from backend.app.services.notifications import notify_pairings_ready
        regs = eligible_registrations(tournament, db)
        notify_pairings_ready(tournament, result.number, regs)
    except Exception:
        pass
    return result


@router.patch("/{tournament_id}/pairings/{pairing_id}", response_model=RoundOut)
def update_manual_pairing(
    tournament_id: int,
    pairing_id: int,
    payload: ManualPairingIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RoundOut:
    load_owned_tournament(tournament_id, organizer, db)
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_a)
            .selectinload(Registration.player),
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_b)
            .selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Partita non trovata")
    latest_round_number = db.scalar(select(func.max(Round.number)).where(Round.tournament_id == tournament_id))
    if latest_round_number and pairing.round.number < latest_round_number:
        raise HTTPException(status_code=409, detail="Partita bloccata: c'è già un turno successivo")
    if pairing.result:
        raise HTTPException(status_code=409, detail="Questa partita ha già un risultato")
    validate_pairing_registration(tournament_id, payload.player_a_registration_id, db)
    if payload.player_b_registration_id:
        validate_pairing_registration(tournament_id, payload.player_b_registration_id, db)
        if payload.player_a_registration_id == payload.player_b_registration_id:
            raise HTTPException(status_code=422, detail="Un giocatore non può giocare contro sé stesso")
    validate_manual_pairing_conflicts(pairing, payload, db)
    pairing.table_number = payload.table_number
    pairing.player_a_registration_id = payload.player_a_registration_id
    pairing.player_b_registration_id = payload.player_b_registration_id
    db.commit()
    db.refresh(pairing.round)
    return round_out(pairing.round)


@router.get("/{tournament_id}/bracket", response_model=list[BracketMatchOut])
def get_bracket(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BracketMatchOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    if not tournament.pairings_public and not owns_tournament(tournament, user, db):
        return []
    return _build_bracket(tournament_id, db)


def _build_bracket(tournament_id: int, db: Session) -> list[BracketMatchOut]:
    rounds = db.scalars(
        select(Round)
        .where(Round.tournament_id == tournament_id, Round.phase.in_(["elimination", "topcut"]))
        .options(
            selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.assigned_judge),
        )
        .order_by(Round.number)
    ).all()
    matches: list[BracketMatchOut] = []
    for round_obj in rounds:
        for pairing in sorted(round_obj.pairings, key=lambda item: item.table_number):
            winner = None
            if pairing.result == "A":
                winner = pairing.player_a.player.display_name
            elif pairing.result == "B" and pairing.player_b:
                winner = pairing.player_b.player.display_name
            matches.append(
                BracketMatchOut(
                    pairing_id=pairing.id,
                    round_number=round_obj.number,
                    table_number=pairing.table_number,
                    player_a=pairing.player_a.player.display_name,
                    player_b=pairing.player_b.player.display_name if pairing.player_b else None,
                    match_wins_a=pairing.match_wins_a,
                    match_wins_b=pairing.match_wins_b,
                    winner=winner,
                )
            )
    return matches


@router.patch("/{tournament_id}/pairings/{pairing_id}/result", response_model=RoundOut)
def report_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    # Organizzatore proprietario o staff/judge invitato
    load_tournament_for_staff(tournament_id, user, db)
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_a)
            .selectinload(Registration.player),
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_b)
            .selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Partita non trovata")
    apply_pairing_result(tournament_id, pairing, payload, db)
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"standings:{tournament_id}")       # standings cambiano dopo ogni risultato
    cache_invalidate(f"result-reports:{tournament_id}")  # report map obsoleta
    cache_invalidate(f"my-pairings:{tournament_id}")     # card giocatori obsoleta
    return round_out(pairing.round)


# ── #39 Correzione risultato post-torneo + audit log ──────────
@router.patch("/{tournament_id}/pairings/{pairing_id}/correct", response_model=RoundOut)
def correct_pairing_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultIn,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Corregge il risultato di un tavolo anche a torneo concluso e ricalcola la
    classifica. L'azione viene tracciata nell'audit log (chi/quando/cosa)."""
    load_owned_tournament(tournament_id, organizer, db)
    pairing = db.scalar(
        select(Pairing).join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round).selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
            selectinload(Pairing.round).selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Partita non trovata")
    if not pairing.player_b_registration_id:
        raise HTTPException(status_code=409, detail="I BYE non si correggono")
    ensure_allowed_score(payload, pairing, db)
    old = f"{pairing.match_wins_a}-{pairing.match_wins_b}"
    pairing.match_wins_a = payload.match_wins_a
    pairing.match_wins_b = payload.match_wins_b
    pairing.draws = payload.draws
    pairing.result = "A" if payload.match_wins_a > payload.match_wins_b else ("B" if payload.match_wins_b > payload.match_wins_a else "D")
    new = f"{payload.match_wins_a}-{payload.match_wins_b}"
    write_audit(db, tournament_id, organizer.id, "correct_result",
                 f"Tavolo {pairing.table_number} round {pairing.round.number}: {old} → {new}")
    db.commit()
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"standings:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return round_out(pairing.round)


@router.get("/{tournament_id}/audit", response_model=list[AuditLogOut])
def list_audit(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[AuditLogOut]:
    load_owned_tournament(tournament_id, organizer, db)
    logs = db.scalars(
        select(AuditLog).where(AuditLog.tournament_id == tournament_id)
        .options(joinedload(AuditLog.editor)).order_by(AuditLog.created_at.desc())
    ).all()
    return [AuditLogOut(id=lg.id, action=lg.action, detail=lg.detail,
                        editor=(lg.editor.display_name if lg.editor else "?"),
                        created_at=lg.created_at) for lg in logs]


# ── #37 Gestione no-show: marca assenti e rigenera l'ultimo round ──
@router.post("/{tournament_id}/rounds/regenerate", response_model=RoundOut)
def regenerate_round(
    tournament_id: int,
    payload: RegenerateRoundIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Segna come ritirati i giocatori assenti (no-show) ed elimina+rigenera
    l'ultimo round (consentito solo se quel round non ha ancora risultati).
    Organizzatore o capojudge, come la generazione."""
    tournament, _ = load_tournament_for_head_judge(tournament_id, user, db)
    if tournament.status != TournamentStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Il torneo non è in corso")
    latest = db.scalar(
        select(Round).where(Round.tournament_id == tournament_id)
        .options(selectinload(Round.pairings)).order_by(Round.number.desc())
    )
    if not latest:
        raise HTTPException(status_code=409, detail="Nessun round da rigenerare")
    if any(p.result and p.player_b_registration_id for p in latest.pairings):
        raise HTTPException(status_code=409, detail="Il round ha già dei risultati: non rigenerabile")
    # Marca assenti come ritirati
    for rid in set(payload.drop_registration_ids):
        reg = db.get(Registration, rid)
        if reg and reg.tournament_id == tournament_id:
            reg.dropped = True
            db.add(reg)
    if payload.drop_registration_ids:
        write_audit(db, tournament_id, user.id, "no_show",
                     f"Segnati assenti: {len(set(payload.drop_registration_ids))} giocatori, round {latest.number} rigenerato")
    # Elimina il round e i suoi pairing, poi rigenera
    for p in list(latest.pairings):
        db.delete(p)
    db.delete(latest)
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"standings:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return create_round_for_tournament(tournament, db)


# ── #41 Statistiche meta (archetipi + win rate) ───────────────
def compute_meta_stats(tournament_id: int, db: Session) -> list[MetaStatRow]:
    """Ripartizione per archetipo: quanti l'hanno giocato e come è andata."""
    standings = calculate_standings(tournament_id, db)
    regs = db.scalars(select(Registration).where(Registration.tournament_id == tournament_id)).all()
    arch_by_reg = {r.id: (r.archetype.strip() or "Sconosciuto") for r in regs}
    agg: dict[str, dict] = {}
    for s in standings:
        arch = arch_by_reg.get(s.registration_id, "Sconosciuto")
        # calculate_standings scrive il record come "vittorie/sconfitte/pareggi":
        # leggerlo in un altro ordine gonfia il win rate (le sconfitte finivano
        # fra i pareggi e sparivano dal denominatore).
        try:
            w, ls, d = (int(x) for x in str(s.record).split("/"))
        except (ValueError, AttributeError):
            w = d = ls = 0
        a = agg.setdefault(arch, {"players": 0, "wins": 0, "draws": 0, "losses": 0})
        a["players"] += 1
        a["wins"] += w
        a["draws"] += d
        a["losses"] += ls
    rows = []
    for arch, a in agg.items():
        games = a["wins"] + a["losses"]
        rows.append(MetaStatRow(
            archetype=arch, players=a["players"], wins=a["wins"], draws=a["draws"], losses=a["losses"],
            win_rate=round(a["wins"] / games * 100, 1) if games else 0.0,
        ))
    rows.sort(key=lambda r: (-r.players, -r.win_rate))
    return rows


@router.get("/{tournament_id}/meta-stats", response_model=list[MetaStatRow])
def meta_stats(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[MetaStatRow]:
    """Metagame a torneo in corso: solo per chi lo organizza."""
    load_owned_tournament(tournament_id, organizer, db)
    return compute_meta_stats(tournament_id, db)


@router.get("/{tournament_id}/public-meta", response_model=list[MetaStatRow])
def public_meta_stats(tournament_id: int, db: Session = Depends(get_db)) -> list[MetaStatRow]:
    """Metagame di un torneo concluso, per la pagina coverage e lo storico.

    Vincolato alla classifica pubblica: gli archetipi compaiono già lì accanto
    ai nomi, quindi chi nasconde la classifica non se li vede uscire da qui.
    """
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    if tournament.status != TournamentStatus.COMPLETED or not tournament.standings_public:
        raise HTTPException(status_code=404, detail="Metagame non pubblico per questo torneo")
    return compute_meta_stats(tournament_id, db)


# ── #46 Bracket pubblico (SPA) ────────────────────────────────
@router.get("/{tournament_id}/public-bracket", response_model=list[BracketMatchOut])
def public_bracket(tournament_id: int, db: Session = Depends(get_db)) -> list[BracketMatchOut]:
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")
    if not tournament.pairings_public:
        return []
    return _build_bracket(tournament_id, db)


@router.patch("/{tournament_id}/pairings/{pairing_id}/player-result", response_model=RoundOut)
def report_player_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    pairing = load_player_pairing(tournament_id, pairing_id, user, db)
    ensure_allowed_score(payload, pairing, db)
    reporter_id = player_registration_id_for_pairing(pairing, user)
    existing = latest_open_report(pairing.id, db)
    if existing and existing.reporter_registration_id != reporter_id:
        raise HTTPException(status_code=409, detail="C'è un risultato dell'avversario da confermare o rifiutare")
    if existing and existing.reporter_registration_id == reporter_id:
        existing.match_wins_a = payload.match_wins_a
        existing.match_wins_b = payload.match_wins_b
        existing.draws = payload.draws
        existing.created_at = datetime.now(UTC)
        db.add(existing)
    else:
        db.add(
            PairingResultReport(
                pairing_id=pairing.id,
                reporter_registration_id=reporter_id,
                match_wins_a=payload.match_wins_a,
                match_wins_b=payload.match_wins_b,
                draws=payload.draws,
                status=ResultReportStatus.PENDING,
            )
        )
    db.commit()
    db.refresh(pairing.round)
    # Invalida PRIMA di ricostruire: così l'avversario vede subito il report e
    # gli compare la sezione "Conferma / Chiama Judge" (no attesa del TTL cache).
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"result-reports:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return round_out(pairing.round, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/pairings/{pairing_id}/player-result/confirm", response_model=RoundOut)
def confirm_player_result(
    tournament_id: int,
    pairing_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    pairing = load_player_pairing(tournament_id, pairing_id, user, db)
    reporter_id = player_registration_id_for_pairing(pairing, user)
    report = latest_open_report(pairing.id, db)
    if not report:
        raise HTTPException(status_code=404, detail="Non c'è nessun risultato da confermare")
    if report.reporter_registration_id == reporter_id:
        raise HTTPException(status_code=409, detail="Il risultato lo conferma l'avversario")
    apply_pairing_result(
        tournament_id,
        pairing,
        PairingResultIn(
            match_wins_a=report.match_wins_a,
            match_wins_b=report.match_wins_b,
            draws=report.draws,
        ),
        db,
    )
    report.status = ResultReportStatus.CONFIRMED
    report.resolved_at = datetime.now(UTC)
    db.add(report)
    db.commit()
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"standings:{tournament_id}")
    cache_invalidate(f"result-reports:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return round_out(pairing.round, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/pairings/{pairing_id}/player-result/reject", response_model=RoundOut)
def reject_player_result(
    tournament_id: int,
    pairing_id: int,
    payload: PairingResultRejectIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    pairing = load_player_pairing(tournament_id, pairing_id, user, db)
    reporter_id = player_registration_id_for_pairing(pairing, user)
    report = latest_open_report(pairing.id, db)
    if not report:
        raise HTTPException(status_code=404, detail="Non c'è nessun risultato da rifiutare")
    if report.reporter_registration_id == reporter_id:
        raise HTTPException(status_code=409, detail="Il risultato lo rifiuta l'avversario")
    report.status = ResultReportStatus.CONFLICT
    report.note = payload.note
    report.resolved_at = datetime.now(UTC)
    db.add(report)
    db.commit()
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"result-reports:{tournament_id}")
    cache_invalidate(f"my-pairings:{tournament_id}")
    return round_out(pairing.round, latest_result_reports(tournament_id, db))


@router.get("/{tournament_id}/public-results", response_model=PublicResultsOut)
def public_results(tournament_id: int, db: Session = Depends(get_db)) -> PublicResultsOut:
    """Risultati pubblici di un torneo (storico): vincitore, classifica e — se le
    liste sono pubbliche — le decklist. Nessuna autenticazione richiesta."""
    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")

    rows: list[PublicStandingRow] = []
    if tournament.standings_public:
        standings = calculate_standings(tournament_id, db)
        decks: dict[int, Registration] = {}
        if tournament.decklists_public:
            regs = db.scalars(
                select(Registration)
                .where(Registration.tournament_id == tournament_id)
                .options(selectinload(Registration.decklists))
            ).all()
            decks = {r.id: r for r in regs}
        for s in standings:
            reg = decks.get(s.registration_id)
            rows.append(PublicStandingRow(
                position=s.position, registration_id=s.registration_id, name=s.name,
                points=s.points, record=s.record,
                archetype=(reg.archetype if reg else "") or "",
                decklist=(reg.decklist.raw_text if reg and reg.decklist else None),
            ))
    return PublicResultsOut(
        tournament_id=tournament.id, name=tournament.name, format=tournament.format,
        starts_on=tournament.starts_on, start_time=tournament.start_time, status=tournament.status,
        standings_public=tournament.standings_public, decklists_public=tournament.decklists_public,
        standings=rows,
    )


@router.get("/{tournament_id}/public-display", response_model=PublicDisplayOut)
def public_display(tournament_id: int, db: Session = Depends(get_db)) -> PublicDisplayOut:
    """Dati per lo schermo pubblico in negozio (TV/proiettore) — nessuna autenticazione.

    Restituisce pairing del round corrente (se pairings_public), scadenza timer
    e standings (se standings_public). Cache 10s: regge il polling di più schermi.
    """
    from backend.app.core.cache import cache_get, cache_set
    cache_key = f"public-display:{tournament_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    tournament = db.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Torneo non trovato")

    latest_round = None
    pairings_out: list[PublicPairingOut] = []
    if tournament.pairings_public:
        latest_round = db.scalar(
            select(Round)
            .where(Round.tournament_id == tournament_id, Round.is_published == True)  # noqa: E712
            .options(
                selectinload(Round.pairings).selectinload(Pairing.player_a).selectinload(Registration.player),
                selectinload(Round.pairings).selectinload(Pairing.player_b).selectinload(Registration.player),
            selectinload(Round.pairings).selectinload(Pairing.assigned_judge),
            )
            .order_by(Round.number.desc())
        )
        if latest_round:
            base_end = latest_round.ends_at
            pairings_out = [
                PublicPairingOut(
                    table_number=p.table_number,
                    player_a=p.player_a.player.display_name,
                    player_b=p.player_b.player.display_name if p.player_b else None,
                    result=p.result,
                    extra_seconds=p.extra_seconds,
                    # Fine effettiva del tavolo = fine round + minuti extra concessi
                    ends_at=(base_end + timedelta(seconds=p.extra_seconds)) if base_end else None,
                )
                for p in sorted(latest_round.pairings, key=lambda x: x.table_number)
            ]

    standings = calculate_standings(tournament_id, db) if tournament.standings_public else []

    result = PublicDisplayOut(
        tournament_name=tournament.name,
        round_number=latest_round.number if latest_round else None,
        round_ends_at=latest_round.ends_at if latest_round else None,
        pairings=pairings_out,
        standings=standings[:16],   # top 16 bastano per lo schermo
    )
    cache_set(cache_key, result, ttl=10.0)
    return result


def _latest_round_or_404(tournament_id: int, db: Session) -> Round:
    rnd = db.scalar(
        select(Round)
        .where(Round.tournament_id == tournament_id)
        .order_by(Round.number.desc())
    )
    if not rnd:
        raise HTTPException(status_code=404, detail="Nessun round generato")
    return rnd


@router.post("/{tournament_id}/timer/restart", response_model=RoundOut)
def restart_round_timer(
    tournament_id: int,
    payload: TimerRestartIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """(Ri)avvia il timer dell'ultimo round: ends_at = ora + minuti. Organizer o staff."""
    ensure_tournament_live(load_tournament_for_staff(tournament_id, user, db))
    rnd = _latest_round_or_404(tournament_id, db)
    now = datetime.now(UTC)
    rnd.starts_at = now
    rnd.ends_at = now + timedelta(minutes=payload.minutes)
    db.commit()
    db.refresh(rnd)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(rnd, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/timer/stop", response_model=RoundOut)
def stop_round_timer(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Ferma il timer dell'ultimo round (ends_at = None). Organizer o staff."""
    load_tournament_for_staff(tournament_id, user, db)
    rnd = _latest_round_or_404(tournament_id, db)
    rnd.ends_at = None
    db.commit()
    db.refresh(rnd)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(rnd, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/timer/extend", response_model=RoundOut)
def extend_round_timer(
    tournament_id: int,
    payload: TimerExtendIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Aggiunge minuti alla scadenza dell'intero round corrente. Organizer o staff."""
    ensure_tournament_live(load_tournament_for_staff(tournament_id, user, db))
    rnd = _latest_round_or_404(tournament_id, db)
    base = rnd.ends_at or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    rnd.ends_at = base + timedelta(minutes=payload.minutes)
    db.commit()
    db.refresh(rnd)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(rnd, latest_result_reports(tournament_id, db))


@router.patch("/{tournament_id}/pairings/{pairing_id}/extend", response_model=RoundOut)
def extend_table_timer(
    tournament_id: int,
    pairing_id: int,
    payload: TableExtendIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Aggiunge minuti al singolo tavolo (es. ruling del judge). Organizer o staff."""
    ensure_tournament_live(load_tournament_for_staff(tournament_id, user, db))
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_a)
            .selectinload(Registration.player),
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_b)
            .selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Partita non trovata")
    pairing.extra_seconds = (pairing.extra_seconds or 0) + payload.minutes * 60
    db.commit()
    db.refresh(pairing.round)
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(pairing.round, latest_result_reports(tournament_id, db))


def load_player_pairing(tournament_id: int, pairing_id: int, user: User, db: Session) -> Pairing:
    pairing = db.scalar(
        select(Pairing)
        .join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_a)
            .selectinload(Registration.player),
            selectinload(Pairing.round)
            .selectinload(Round.pairings)
            .selectinload(Pairing.player_b)
            .selectinload(Registration.player),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Partita non trovata")
    participant_ids = {
        pairing.player_a.player_id,
        pairing.player_b.player_id if pairing.player_b else None,
    }
    if user.id not in participant_ids:
        raise HTTPException(status_code=403, detail="Non sei seduto a questo tavolo")
    if not pairing.round.is_published:
        raise HTTPException(status_code=409, detail="Gli abbinamenti non sono ancora pubblicati")
    if pairing.result:
        raise HTTPException(status_code=409, detail="Il risultato è già definitivo")
    if not pairing.player_b_registration_id:
        raise HTTPException(status_code=409, detail="Il risultato di un bye è automatico")
    return pairing


def player_registration_id_for_pairing(pairing: Pairing, user: User) -> int:
    if pairing.player_a.player_id == user.id:
        return pairing.player_a_registration_id
    if pairing.player_b and pairing.player_b.player_id == user.id:
        return pairing.player_b_registration_id
    raise HTTPException(status_code=403, detail="Non sei seduto a questo tavolo")


def latest_open_report(pairing_id: int, db: Session) -> PairingResultReport | None:
    return db.scalar(
        select(PairingResultReport)
        .where(
            PairingResultReport.pairing_id == pairing_id,
            PairingResultReport.status.in_([ResultReportStatus.PENDING, ResultReportStatus.CONFLICT]),
        )
        .order_by(PairingResultReport.created_at.desc(), PairingResultReport.id.desc())
    )


def latest_result_reports(tournament_id: int, db: Session) -> dict[int, dict]:
    """Restituisce {pairing_id: dict} con i dati del report più recente.

    Usa plain dict invece di oggetti SQLAlchemy per evitare DetachedInstanceError.
    Niente cache: con più worker Gunicorn la cache in-memory è per-processo e
    l'invalidazione non si propaga, così l'avversario non vedrebbe il report
    appena inserito. È una query piccola, la leggiamo sempre fresca.
    """
    reports = db.scalars(
        select(PairingResultReport)
        .join(Pairing)
        .join(Round)
        .where(Round.tournament_id == tournament_id)
        .options(
            selectinload(PairingResultReport.reporter).selectinload(Registration.player),
        )
        .order_by(PairingResultReport.created_at.asc(), PairingResultReport.id.asc())
    ).all()
    # Serializza subito — prima che la sessione si chiuda
    result: dict[int, dict] = {}
    for report in reports:
        reporter_name = ""
        if report.reporter and report.reporter.player:
            reporter_name = report.reporter.player.display_name
        result[report.pairing_id] = {
            "id": report.id,
            "status": report.status,
            "match_wins_a": report.match_wins_a,
            "match_wins_b": report.match_wins_b,
            "reporter_registration_id": report.reporter_registration_id,
            "reporter_name": reporter_name,
        }
    return result


def _load_pairing_for_staff(tournament_id: int, pairing_id: int, user: User, db: Session) -> Pairing:
    load_tournament_for_staff(tournament_id, user, db)
    pairing = db.scalar(
        select(Pairing).join(Round).where(
            Pairing.id == pairing_id, Round.tournament_id == tournament_id
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Tavolo non trovato")
    return pairing


@router.patch("/{tournament_id}/pairings/{pairing_id}/assign", response_model=RoundOut)
def assign_table(
    tournament_id: int,
    pairing_id: int,
    payload: TableAssignIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Assegna il tavolo a un judge, o lo libera con user_id nullo.

    A fine round serve sapere chi sta seguendo cosa: senza, due judge vanno
    allo stesso tavolo e un altro resta scoperto.
    """
    pairing = _load_pairing_for_staff(tournament_id, pairing_id, user, db)
    if payload.user_id is not None and not is_tournament_staff(tournament_id, payload.user_id, db):
        owner, store = db.execute(
            select(Tournament.organizer_id, Tournament.organization_id).where(Tournament.id == tournament_id)
        ).one()
        if payload.user_id != owner and not store_role(payload.user_id, store, db):
            raise HTTPException(status_code=422, detail="Il tavolo si assegna a chi è nello staff")
    pairing.assigned_judge_id = payload.user_id
    db.commit()
    from backend.app.core.cache import cache_invalidate
    cache_invalidate(f"public-display:{tournament_id}")
    return round_out(db.get(Round, pairing.round_id), latest_result_reports(tournament_id, db))


@router.patch("/{tournament_id}/pairings/{pairing_id}/status", response_model=RoundOut)
def set_table_status(
    tournament_id: int,
    pairing_id: int,
    payload: TableStatusIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Stato manuale del tavolo. Quello deducibile — risultato presente, tempo
    extra, referto in conflitto — resta dedotto dai dati, non si scrive qui."""
    pairing = _load_pairing_for_staff(tournament_id, pairing_id, user, db)
    pairing.table_status = payload.status
    db.commit()
    return round_out(db.get(Round, pairing.round_id), latest_result_reports(tournament_id, db))


def _deck_check_out(check: DeckCheck, rounds: dict[int, int]) -> DeckCheckOut:
    player = check.registration.player if check.registration else None
    return DeckCheckOut(
        id=check.id,
        registration_id=check.registration_id,
        player_name=player.display_name if player else "",
        round_number=rounds.get(check.round_id) if check.round_id else None,
        judge_name=check.judge.display_name if check.judge else "",
        result=check.result,
        note=check.note,
        created_at=check.created_at,
    )


@router.post("/{tournament_id}/deck-checks", response_model=DeckCheckOut, status_code=201)
def create_deck_check(
    tournament_id: int,
    payload: DeckCheckIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeckCheckOut:
    """Registra il controllo di una lista. Lo fa chiunque sia nello staff:
    il deck check è lavoro da judge, non da organizzatore."""
    tournament = load_tournament_for_staff(tournament_id, user, db)
    load_registration_for_tournament(tournament.id, payload.registration_id, db)
    latest = db.scalar(
        select(Round).where(Round.tournament_id == tournament_id).order_by(Round.number.desc())
    )
    check = DeckCheck(
        tournament_id=tournament_id,
        registration_id=payload.registration_id,
        round_id=latest.id if latest else None,
        judge_id=user.id,
        result=payload.result,
        note=payload.note.strip(),
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    rounds = {r.id: r.number for r in db.scalars(
        select(Round).where(Round.tournament_id == tournament_id)).all()}
    return _deck_check_out(check, rounds)


@router.get("/{tournament_id}/deck-checks", response_model=list[DeckCheckOut])
def list_deck_checks(
    tournament_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DeckCheckOut]:
    """Storico dei controlli. Visibile a tutto lo staff: sapere che un tavolo è
    già stato controllato evita di rifarlo e di perdere tempo di round."""
    load_tournament_for_staff(tournament_id, user, db)
    checks = db.scalars(
        select(DeckCheck)
        .where(DeckCheck.tournament_id == tournament_id)
        .options(
            joinedload(DeckCheck.registration).joinedload(Registration.player),
            joinedload(DeckCheck.judge),
        )
        .order_by(DeckCheck.created_at.desc())
    ).all()
    rounds = {r.id: r.number for r in db.scalars(
        select(Round).where(Round.tournament_id == tournament_id)).all()}
    return [_deck_check_out(c, rounds) for c in checks]


@router.post("/{tournament_id}/day2", response_model=list[Day2ConversionRow])
def set_day2(
    tournament_id: int,
    payload: Day2In,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[Day2ConversionRow]:
    """Segna chi passa alla seconda giornata. La lista sostituisce la precedente:
    rimandare l'elenco corretto ripara un import sbagliato senza azzerare a mano."""
    tournament = load_owned_tournament(tournament_id, organizer, db)
    registrations = db.scalars(
        select(Registration).where(Registration.tournament_id == tournament.id)
    ).all()
    wanted = set(payload.registration_ids)
    unknown = wanted - {r.id for r in registrations}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Iscrizioni non di questo torneo: {sorted(unknown)[:5]}",
        )
    for reg in registrations:
        reg.day2 = reg.id in wanted
    db.commit()
    return day2_conversion(tournament_id, db)


@router.get("/{tournament_id}/day2/conversion", response_model=list[Day2ConversionRow])
def day2_conversion_endpoint(
    tournament_id: int,
    organizer: User = Depends(require_organizer),
    db: Session = Depends(get_db),
) -> list[Day2ConversionRow]:
    load_owned_tournament(tournament_id, organizer, db)
    return day2_conversion(tournament_id, db)


def day2_conversion(tournament_id: int, db: Session) -> list[Day2ConversionRow]:
    """Quanti di ogni archetipo hanno passato il taglio. E la domanda che si fa
    la coverage: non quanti lo giocavano, ma quanti sono arrivati."""
    registrations = db.scalars(
        select(Registration).where(Registration.tournament_id == tournament_id)
    ).all()
    agg: dict[str, dict] = {}
    for reg in registrations:
        arch = (reg.archetype or "").strip() or "Sconosciuto"
        row = agg.setdefault(arch, {"players": 0, "day2": 0})
        row["players"] += 1
        if reg.day2:
            row["day2"] += 1
    rows = [
        Day2ConversionRow(
            archetype=arch,
            players=v["players"],
            day2=v["day2"],
            conversion=round(v["day2"] / v["players"] * 100, 1) if v["players"] else 0.0,
        )
        for arch, v in agg.items()
    ]
    rows.sort(key=lambda r: (-r.conversion, -r.players))
    return rows


@router.patch("/{tournament_id}/rounds/{round_id}/format", response_model=RoundOut)
def set_round_format(
    tournament_id: int,
    round_id: int,
    payload: RoundFormatIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Formato del segmento: draft ai primi turni, constructed dopo. Nullo
    significa "il formato del torneo", che resta il caso normale."""
    tournament, _ = load_tournament_for_head_judge(tournament_id, user, db)
    rnd = db.get(Round, round_id)
    if not rnd or rnd.tournament_id != tournament.id:
        raise HTTPException(status_code=404, detail="Round non trovato")
    rnd.format = (payload.format or "").strip() or None
    db.commit()
    db.refresh(rnd)
    return round_out(rnd, latest_result_reports(tournament_id, db))


@router.post("/{tournament_id}/pairings/{pairing_id}/tardiness", response_model=RoundOut)
def penalize_tardiness(
    tournament_id: int,
    pairing_id: int,
    payload: TardinessIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoundOut:
    """Chi non si presenta al tavolo, o arriva tardi. Con la sconfitta a
    tavolino l'avversario vince con il punteggio pieno del formato; con il game
    loss la partita si gioca e la penalità resta scritta. Chi non si è
    presentato si può anche ritirare dal torneo, così non viene più abbinato."""
    from backend.app.core.cache import cache_invalidate

    tournament = load_tournament_for_staff(tournament_id, user, db)
    pairing = db.scalar(
        select(Pairing).join(Round)
        .where(Pairing.id == pairing_id, Round.tournament_id == tournament_id)
        .options(selectinload(Pairing.round).selectinload(Round.pairings))
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Tavolo non trovato")
    if not pairing.player_b_registration_id:
        raise HTTPException(status_code=409, detail="Un bye non ha avversario")
    if payload.registration_id not in {pairing.player_a_registration_id, pairing.player_b_registration_id}:
        raise HTTPException(status_code=422, detail="Il giocatore non è a questo tavolo")
    if payload.penalty == "match_loss" and pairing.result:
        raise HTTPException(status_code=409, detail="Il tavolo ha già un risultato: correggi quello")
    registration = load_registration_for_tournament(tournament_id, payload.registration_id, db)
    number = pairing.round.number
    note = payload.note.strip() or (f"Non presentato al turno {number}" if payload.penalty == "match_loss"
                                    else f"In ritardo al turno {number}")
    db.add(Penalty(tournament_id=tournament.id, registration_id=registration.id, judge_id=user.id,
                   round_id=pairing.round_id, kind=payload.penalty, note=note, is_private=True))
    if payload.drop:
        registration.dropped = True
    write_audit(db, tournament.id, user.id, f"tardiness_{payload.penalty}",
                 f"{registration.player.display_name}, turno {number}: {note}" + (" (ritirato)" if payload.drop else ""))
    if payload.penalty == "match_loss":
        # Il punteggio pieno: 1-0 al meglio di 1 in svizzera, altrimenti 2-0.
        full = 1 if pairing.round.phase == "swiss" and tournament.best_of == 1 else 2
        late_is_a = registration.id == pairing.player_a_registration_id
        apply_pairing_result(tournament_id, pairing, PairingResultIn(
            match_wins_a=0 if late_is_a else full, match_wins_b=full if late_is_a else 0,
        ), db)
    else:
        db.commit()
    db.refresh(pairing.round)
    for key in ("standings", "result-reports", "my-pairings", "registrations", "public-display"):
        cache_invalidate(f"{key}:{tournament_id}")
    return round_out(pairing.round)
