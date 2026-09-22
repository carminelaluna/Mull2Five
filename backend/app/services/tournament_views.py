"""
tournament_views.py — Come un torneo, un'iscrizione o una distanza diventano
la risposta dell'API.

Stanno qui e non nel router perché li usano in tanti: la ricerca, la pagina di
un torneo, la regia, l'API pubblica.
"""
import math
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    Event,
    Organization,
    Registration,
    Round,
    Tournament,
    User,
)
from backend.app.schemas import (
    OrganizerRegistrationOut,
    RegistrationOut,
    TournamentOut,
)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distanza in chilometri fra due punti sulla sfera terrestre."""
    radius = 6371.0
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    )
    return 2 * radius * asin(sqrt(a))


def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """Il riquadro che contiene il cerchio: serve a scartare in SQL i tornei
    lontani prima di calcolare la distanza vera, che costa di più."""
    lat_span = radius_km / 111.0
    # Ai poli i meridiani si stringono: il grado di longitudine vale meno.
    lng_span = radius_km / max(111.0 * math.cos(math.radians(lat)), 1.0)
    return lat - lat_span, lat + lat_span, lng - lng_span, lng + lng_span


def filter_by_distance(
    tournaments: list[TournamentOut], lat: float, lng: float, radius_km: float | None, db: Session
) -> list[TournamentOut]:
    """Calcola la distanza e, se c'è un raggio, scarta chi ne sta fuori.

    Il conto si fa in Python: i tornei per tenant sono poche centinaia e SQLite
    non ha funzioni geospaziali. Un torneo senza coordinate proprie eredita quelle
    del negozio; se non le ha nessuno dei due resta fuori dalla ricerca per distanza.
    """
    org_coords = {
        o.slug: (o.latitude, o.longitude)
        for o in db.scalars(select(Organization)).all()
        if o.latitude is not None and o.longitude is not None
    }
    located: list[TournamentOut] = []
    for t in tournaments:
        coords = (t.latitude, t.longitude)
        if coords[0] is None or coords[1] is None:
            coords = org_coords.get(t.organization_slug, (None, None))
        if coords[0] is None or coords[1] is None:
            continue
        distance = haversine_km(lat, lng, coords[0], coords[1])
        if radius_km is not None and distance > radius_km:
            continue
        located.append(t.model_copy(update={"distance_km": round(distance, 1)}))
    located.sort(key=lambda t: t.distance_km or 0)
    return located


def tournament_out(tournament: Tournament, registered: int, db: Session) -> TournamentOut:
    """Serializza un torneo con negozio ed evento di appartenenza.

    Unico punto: prima l'arricchimento stava solo nell'helper della lista e il
    GET del singolo torneo rispondeva con event_slug nullo.
    """
    org = db.get(Organization, tournament.organization_id) if tournament.organization_id else None
    event = db.get(Event, tournament.event_id) if tournament.event_id else None
    organizer = db.get(User, tournament.organizer_id)
    location = tournament.location
    # La sede presta al torneo quello che non ha di suo: il luogo scritto e le
    # coordinate, così compare anche nella ricerca per distanza.
    inherited = {"venue": tournament.place}
    if location:
        inherited["location_name"] = location.name
        if tournament.latitude is None and location.latitude is not None:
            inherited["latitude"] = location.latitude
            inherited["longitude"] = location.longitude
    # I segmenti nascono dai round: dichiarare un formato su un turno significa
    # che per quella porzione serve una lista a parte.
    segments = db.scalars(
        select(Round.format)
        .where(Round.tournament_id == tournament.id, Round.format.is_not(None))
        .distinct()
    ).all()
    return TournamentOut.model_validate(tournament).model_copy(update={
        "registered_players": registered,
        "online_link": "",      # lo vedono solo iscritti e staff: vedi my_tournaments
        "organizer_name": organizer.display_name if organizer else None,
        **inherited,
        "organization_slug": org.slug if org else None,
        "organization_name": org.name if org else None,
        "event_slug": event.slug if event else None,
        "event_name": event.name if event else None,
        "decklist_formats": [""] + sorted(f for f in segments if f),
    })


def tournament_with_counts(stmt: Select[tuple[Tournament]], db: Session) -> list[TournamentOut]:
    """
    Ottimizzazione: unica query con LEFT JOIN invece di 2 query separate.
    La versione precedente eseguiva COUNT su tutte le iscrizioni (N+1 sotto carico).
    """
    count_subq = (
        select(
            Registration.tournament_id,
            func.count(Registration.id).label("cnt"),
        )
        .group_by(Registration.tournament_id)
        .subquery("reg_counts")
    )

    combined = (
        stmt.add_columns(func.coalesce(count_subq.c.cnt, 0).label("reg_count"))
        .outerjoin(count_subq, Tournament.id == count_subq.c.tournament_id)
    )

    rows = db.execute(combined).all()
    return [
        tournament_out(tournament, int(reg_count), db)
        for tournament, reg_count in rows
    ]


def registration_out(registration: Registration) -> RegistrationOut:
    return RegistrationOut(
        id=registration.id,
        tournament_id=registration.tournament_id,
        player_id=registration.player_id,
        archetype=registration.archetype,
        wizards_account=registration.wizards_account,
        checked_in=registration.checked_in,
        dropped=registration.dropped,
        waitlisted=registration.waitlisted,
        **_seating(registration),
        game_handle=registration.game_handle,
        online_link=registration.tournament.online_link if registration.tournament.is_online else "",
        player=registration.player,
        decklist_status=registration.decklist.status if registration.decklist else "missing",
        decklist_formats=sorted(d.format for d in registration.decklists),
        payment_status=registration.payment.status if registration.payment else "pending",
    )


def _seating(registration: Registration) -> dict:
    return {"pod": registration.pod, "pod_seat": registration.pod_seat, "fixed_table": registration.fixed_table,
            "team_id": registration.team_id, "team_seat": registration.team_seat,
            "team_name": registration.team.name if registration.team else None}


def organizer_registration_out(
    registration: Registration,
    tags: dict[int, list] | None = None,
    answers: dict[int, dict[int, str]] | None = None,
    prior: dict[int, int] | None = None,
) -> OrganizerRegistrationOut:
    base = registration_out(registration).model_dump()
    decklist = registration.decklist
    payment = registration.payment
    return OrganizerRegistrationOut(
        **base,
        player_email=registration.player.email,
        decklist_id=decklist.id if decklist else None,
        decklist_main_count=decklist.main_count if decklist else None,
        decklist_side_count=decklist.side_count if decklist else None,
        decklist_errors=decklist.validation_errors if decklist else "",
        decklist_raw_text=decklist.raw_text if decklist else "",
        payment_id=payment.id if payment else None,
        payment_provider=payment.provider if payment else None,
        decklist_revision_count=len(registration.decklist_revisions),
        tags=(tags or {}).get(registration.player_id, []),
        answers=(answers or {}).get(registration.id, {}),
        prize_note=registration.prize_note or "",
        prize_given_at=registration.prize_given_at,
        byes=registration.byes or 0,
        player_kind=registration.player.kind,
        prior_penalties=(prior or {}).get(registration.player_id, 0),
        guardian_name=registration.player.guardian.display_name if registration.player.guardian else None,
        guardian_email=registration.player.guardian.email if registration.player.guardian else None,
    )
