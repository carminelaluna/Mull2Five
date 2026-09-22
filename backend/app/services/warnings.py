"""
Avvisi per chi organizza: cose che il sistema accetta ma che quasi sempre sono
una svista. Non bloccano niente, perche l'organizzatore puo avere le sue ragioni,
ma vanno dette prima che le scopra un giocatore al banco.

Due livelli:
- "warn": qualcosa andra storto se nessuno interviene (un pagamento che fallira,
  una tappa che in calendario sta fuori dalla manifestazione).
- "info": una nota. Resta dentro il torneo e non entra nel contatore della lista
  eventi, altrimenti i badge si accenderebbero ovunque e si smetterebbe di leggerli.

Un solo posto per le regole: il back-office legge da qui sia il contatore sulle
schede sia la striscia dentro il torneo.
"""
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.clock import local_today, local_zone
from backend.app.core.config import get_settings
from backend.app.games import OFFICIAL_EVENT_TYPES, get_game
from backend.app.models import (
    Decklist,
    Event,
    EventStaff,
    Organization,
    Registration,
    RulesEnforcementLevel,
    StaffRole,
    Suspension,
    Tournament,
    TournamentStaff,
    TournamentStatus,
    TournamentStructure,
    User,
)
from backend.app.schemas import WarningOut

# Quando le liste mancanti diventano un problema: una settimana prima e normale
# che manchino, due giorni prima bisogna sollecitare.
MISSING_DECKLISTS_WINDOW = timedelta(hours=48)

NOT_STARTED = {TournamentStatus.DRAFT, TournamentStatus.PUBLISHED}
CLOSED = {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}
REL_WITH_HEAD_JUDGE = {RulesEnforcementLevel.COMPETITIVE, RulesEnforcementLevel.PROFESSIONAL}


def _d(value: date) -> str:
    return value.strftime("%d/%m")


def event_end(event: Event) -> date:
    """Ultimo giorno della manifestazione: senza data di fine, dura un giorno."""
    return event.ends_on or event.starts_on


def outside_period(tournament: Tournament, event: Event) -> bool:
    return not (event.starts_on <= tournament.starts_on <= event_end(event))


def _period_label(event: Event) -> str:
    end = event_end(event)
    return _d(event.starts_on) if end == event.starts_on else f"{_d(event.starts_on)} → {_d(end)}"


@dataclass
class WarningContext:
    """I dati che le regole leggono, caricati una volta per tutti i tornei: la
    lista eventi ne mostra decine e non deve fare una query per scheda."""
    events: dict[int, Event] = field(default_factory=dict)
    # tournament_id -> (iscritti attivi, quanti senza lista principale)
    decklists: dict[int, tuple[int, int]] = field(default_factory=dict)
    head_judge_tournaments: set[int] = field(default_factory=set)
    head_judge_events: set[int] = field(default_factory=set)
    # tournament_id -> nomi degli iscritti sospesi dal negozio
    suspended: dict[int, list[str]] = field(default_factory=dict)
    # tournament_id -> nomi di chi non ha dato l'ID all'editore (solo eventi ufficiali)
    missing_ids: dict[int, list[str]] = field(default_factory=dict)
    # I negozi dei tornei: servono a sapere dove vanno gli incassi online.
    stores: dict[int, Organization] = field(default_factory=dict)


def build_context(tournaments: list[Tournament], db: Session) -> WarningContext:
    ctx = WarningContext()
    ids = [t.id for t in tournaments]
    if not ids:
        return ctx

    event_ids = {t.event_id for t in tournaments if t.event_id}
    if event_ids:
        ctx.events = {e.id: e for e in db.scalars(select(Event).where(Event.id.in_(event_ids)))}
        ctx.head_judge_events = set(db.scalars(
            select(EventStaff.event_id).where(
                EventStaff.event_id.in_(event_ids), EventStaff.role == StaffRole.HEAD_JUDGE
            )
        ))
    ctx.head_judge_tournaments = set(db.scalars(
        select(TournamentStaff.tournament_id).where(
            TournamentStaff.tournament_id.in_(ids), TournamentStaff.role == StaffRole.HEAD_JUDGE
        )
    ))

    # Chi ha lasciato o aspetta in lista d'attesa non deve una lista: non gioca.
    with_main_list = select(Decklist.registration_id).where(Decklist.format == "")
    rows = db.execute(
        select(
            Registration.tournament_id,
            func.count(Registration.id),
            func.sum(case((Registration.id.not_in(with_main_list), 1), else_=0)),
        )
        .where(
            Registration.tournament_id.in_(ids),
            Registration.dropped.is_(False),
            Registration.waitlisted.is_(False),
        )
        .group_by(Registration.tournament_id)
    ).all()
    ctx.decklists = {tid: (int(total), int(missing or 0)) for tid, total, missing in rows}

    today = local_today()
    suspended = db.execute(
        select(Registration.tournament_id, User.display_name)
        .join(User, User.id == Registration.player_id)
        .join(Tournament, Tournament.id == Registration.tournament_id)
        .join(Suspension, (Suspension.user_id == Registration.player_id)
              & (Suspension.organization_id == Tournament.organization_id))
        .where(
            Registration.tournament_id.in_(ids),
            Registration.dropped.is_(False),
            Suspension.lifted_at.is_(None),
            or_(Suspension.ends_on.is_(None), Suspension.ends_on >= today),
        )
        .order_by(User.display_name)
    ).all()
    for tid, name in suspended:
        ctx.suspended.setdefault(tid, []).append(name)

    store_ids = {t.organization_id for t in tournaments if t.organization_id}
    if store_ids:
        ctx.stores = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(store_ids)))}

    official = [t.id for t in tournaments if t.event_type in OFFICIAL_EVENT_TYPES or t.invites]
    if official:
        missing = db.execute(
            select(Registration.tournament_id, User.display_name)
            .join(User, User.id == Registration.player_id)
            .where(
                Registration.tournament_id.in_(official),
                Registration.dropped.is_(False),
                Registration.waitlisted.is_(False),
                func.trim(Registration.wizards_account) == "",
            )
            .order_by(User.display_name)
        ).all()
        for tid, name in missing:
            ctx.missing_ids.setdefault(tid, []).append(name)
    return ctx


def tournament_warnings(
    tournament: Tournament, ctx: WarningContext, now: datetime | None = None
) -> list[WarningOut]:
    """Gli avvisi di un torneo ancora aperto. Uno concluso o annullato non ne ha:
    non c'e piu niente da correggere."""
    if tournament.status in CLOSED:
        return []
    now = now or datetime.now(UTC)
    settings = get_settings()
    not_started = tournament.status in NOT_STARTED
    out: list[WarningOut] = []

    def add(code: str, level: str, message: str) -> None:
        out.append(WarningOut(code=code, level=level, message=message, tournament_id=tournament.id))

    event = ctx.events.get(tournament.event_id) if tournament.event_id else None
    if event and outside_period(tournament, event):
        add("outside_event_period", "warn",
            f"Si gioca il {_d(tournament.starts_on)}, fuori dal periodo di «{event.name}» "
            f"({_period_label(event)}). Nel programma pubblico compare lo stesso.")

    registration_only = tournament.structure == TournamentStructure.REGISTRATION_ONLY
    if not_started and tournament.starts_on < now.astimezone(local_zone()).date():
        add("missed_start", "warn",
            f"L'evento c'è stato il {_d(tournament.starts_on)}: chiudilo per metterlo nello storico."
            if registration_only else
            f"Doveva iniziare il {_d(tournament.starts_on)} e non è mai partito: "
            "avvialo, oppure chiudilo se non si è giocato.")

    if not_started and tournament.entry_fee_cents > 0:
        broken = []
        if tournament.pay_stripe and not settings.stripe_secret_key:
            broken.append("Stripe")
        if tournament.pay_paypal and not (settings.paypal_client_id and settings.paypal_client_secret):
            broken.append("PayPal")
        if broken:
            fallback = ("I giocatori potranno pagare solo al banco." if tournament.pay_at_event
                        else "Nessuno potrà pagare l'iscrizione.")
            add("online_payment_unavailable", "warn",
                f"{' e '.join(broken)} è attivo sul torneo, ma il server non ne ha le "
                f"credenziali: il pagamento online fallirà. {fallback}")

    starts_at = tournament.starts_at
    deadline = tournament.decklist_deadline
    if not_started and deadline:
        deadline = deadline if deadline.tzinfo else deadline.replace(tzinfo=UTC)
        late = deadline > starts_at if starts_at else deadline.date() > tournament.starts_on
        if late:
            add("decklist_deadline_after_start", "warn",
                f"La scadenza delle liste ({deadline:%d/%m %H:%M}) è dopo l'inizio del torneo. "
                "All'avvio le liste si chiudono comunque: ai giocatori stai mostrando "
                "una scadenza che non vale.")

    store = ctx.stores.get(tournament.organization_id)
    if (not_started and tournament.entry_fee_cents > 0 and tournament.pay_stripe and settings.stripe_secret_key
            and store and not store.is_default and not (store.stripe_account_id and store.stripe_charges_enabled)):
        add("store_stripe_not_connected", "info",
            "I pagamenti con carta arrivano al conto della piattaforma: collega Stripe "
            "dalla sezione Negozio perché arrivino al tuo.")

    total, missing = ctx.decklists.get(tournament.id, (0, 0))
    if not_started and tournament.decklist_required and missing:
        reference = starts_at or datetime.combine(tournament.starts_on, time(0), tzinfo=local_zone())
        if now >= reference - MISSING_DECKLISTS_WINDOW:
            add("missing_decklists", "warn",
                f"{missing} iscritti su {total} non hanno ancora caricato la lista.")

    names = ctx.suspended.get(tournament.id)
    if names:
        one = len(names) == 1
        add("suspended_players", "warn",
            f"{'Iscritto sospeso' if one else 'Iscritti sospesi'} dagli eventi del negozio: "
            f"{', '.join(names)}. {'Toglilo' if one else 'Toglili'} dal torneo o revoca la sospensione.")

    names = ctx.missing_ids.get(tournament.id)
    if names:
        label = get_game(tournament.game).publisher_id_label or "ID dell'editore"
        shown = ", ".join(names[:5]) + (f" e altri {len(names) - 5}" if len(names) > 5 else "")
        add("missing_publisher_ids", "warn",
            f"{len(names)} {'iscritto' if len(names) == 1 else 'iscritti'} senza {label}: {shown}. "
            "In un evento ufficiale serve a tutti: risultati e inviti arrivano lì.")

    if (
        not registration_only
        and tournament.rules_enforcement_level in REL_WITH_HEAD_JUDGE
        and tournament.id not in ctx.head_judge_tournaments
        and tournament.event_id not in ctx.head_judge_events
    ):
        add("no_head_judge", "info",
            f"Nessun capojudge nominato. A REL {tournament.rules_enforcement_level} di "
            "solito ce n'è uno: lo nomini dalla scheda Staff.")

    if tournament.email_notifications_enabled and not settings.smtp_host:
        add("email_unavailable", "info",
            "Le notifiche email sono attive, ma il server non ha un SMTP configurato: "
            "non parte nessuna email.")

    return out


def event_warnings(event: Event, stages: list[Tournament]) -> list[WarningOut]:
    """Avvisi della manifestazione nel suo insieme. `stages` sono le tappe non
    annullate, concluse comprese: stanno ancora nel programma pubblico."""
    out: list[WarningOut] = []
    if event.ends_on and event.ends_on < event.starts_on:
        out.append(WarningOut(
            code="period_inverted", level="warn",
            message=f"Finisce il {_d(event.ends_on)}, prima di cominciare ({_d(event.starts_on)}).",
        ))
        # Con il periodo rovesciato ogni tappa risulterebbe fuori: basta questo.
        return out
    for stage in stages:
        if outside_period(stage, event):
            out.append(WarningOut(
                code="stage_outside_period", level="warn", tournament_id=stage.id,
                message=f"«{stage.name}» si gioca il {_d(stage.starts_on)}, fuori dal "
                        f"periodo ({_period_label(event)}).",
            ))
    if event.is_public and not stages:
        out.append(WarningOut(
            code="public_without_stages", level="info",
            message="La pagina pubblica è online, ma il programma è vuoto: aggiungi le tappe.",
        ))
    return out
