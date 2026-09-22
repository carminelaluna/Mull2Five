from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=8)
    role: str = "player"
    # Il modulo chiede di confermare l'età minima: False blocca la registrazione.
    age_confirmed: bool | None = None


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=160)


class ProfileOut(BaseModel):
    id: int
    display_name: str
    created_at: datetime
    registrations: int = 0


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str          # str, non EmailStr: la validazione serve solo in input, non in output
    display_name: str
    role: str

    model_config = {"from_attributes": True}


class TournamentCreate(BaseModel):
    name: str = Field(min_length=3, max_length=180)
    format: str
    game: str = "mtg"
    # 1: individuale; 2 o 3: a squadre.
    team_size: int = Field(default=1, ge=1, le=3)
    # Una delle sedi del negozio: il torneo ne eredita indirizzo e coordinate.
    location_id: int | None = None
    # Vuoto: quello del regolamento del gioco (One Piece al meglio di 1, gli altri di 3).
    best_of: int | None = Field(default=None, ge=1, le=3)
    allow_intentional_draws: bool = True
    event_type: Literal["locals", "prerelease", "rcq", "store_championship", "premier", "other"] = "locals"
    rules_enforcement_level: str = "Competitive"
    venue: str = ""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    starts_on: date
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    capacity: int = Field(gt=1)
    entry_fee_cents: int = Field(ge=0)
    currency: str = "EUR"
    status: str = "published"
    structure: str = Field(default="swiss", pattern="^(swiss|single_elimination|swiss_topcut|registration_only)$")
    swiss_rounds: int = Field(default=0, ge=0)
    top_cut_size: int = Field(default=8, ge=2)
    decklist_required: bool = True
    decklist_deadline: datetime | None = None
    check_in_required: bool = False
    self_check_in_enabled: bool = False
    late_registration_enabled: bool = False
    registration_mode: str = Field(default="open", pattern="^(open|closed)$")
    pairings_public: bool = False
    standings_public: bool = True
    decklists_public: bool = False
    round_timer_minutes: int = Field(default=50, ge=1, le=120)
    refund_policy: str = ""
    email_notifications_enabled: bool = False
    legal_validation_enabled: bool = False
    description: str = ""
    pay_at_event: bool = True
    pay_stripe: bool = False
    pay_paypal: bool = False
    sanction_id: str = Field(default="", max_length=60)
    # Vuoto: uno in un RCQ (l'invito al Regional Championship), nessuno negli altri.
    invites: int | None = Field(default=None, ge=0, le=64)
    is_online: bool = False
    online_platform: str = Field(default="", max_length=30)
    online_link: str = Field(default="", max_length=300, pattern=r"^(https://\S+)?$")

    @model_validator(mode="after")
    def _game_and_match_format(self):
        from backend.app.games import GAMES, is_enabled

        if not is_enabled(self.game):
            raise ValueError(f"Gioco non disponibile: {self.game}")
        if self.best_of is None:
            self.best_of = GAMES[self.game].default_best_of
        return self

    @model_validator(mode="after")
    def _invites(self):
        if self.invites is None:
            self.invites = 1 if self.event_type == "rcq" else 0
        self.sanction_id = self.sanction_id.strip()
        return self

    @model_validator(mode="after")
    def _online_platform(self):
        from backend.app.games import online_platform

        if not self.is_online:
            self.online_platform, self.online_link = "", ""
        elif not online_platform(self.game, self.online_platform):
            raise ValueError("Scegli dove si gioca il torneo online")
        return self

    @model_validator(mode="after")
    def _teams_play_swiss(self):
        if self.team_size > 1 and self.structure != "swiss":
            raise ValueError("I tornei a squadre si giocano in svizzera")
        return self

    @model_validator(mode="after")
    def _require_payment_method(self):
        # Almeno un metodo di pagamento deve essere abilitato alla creazione
        if not (self.pay_at_event or self.pay_stripe or self.pay_paypal):
            raise ValueError("Seleziona almeno un metodo di pagamento (al banco, Stripe o PayPal).")
        return self


class RepeatIn(BaseModel):
    """Ripetere un torneo: quanto spesso, e quante volte oppure fino a quando."""
    frequency: Literal["weekly", "biweekly", "monthly"]
    count: int | None = Field(default=None, ge=1, le=52)
    until: date | None = None

    @model_validator(mode="after")
    def _how_long(self) -> RepeatIn:
        if (self.count is None) == (self.until is None):
            raise ValueError("Indica quante volte oppure fino a quando")
        return self


class RepeatPreviewOut(BaseModel):
    dates: list[date]
    # Date in cui la serie ha già un torneo: non si creano due volte.
    already_there: list[date] = []


class TournamentUpdate(BaseModel):
    """Modifiche dalla scheda Impostazioni. I campi non inviati restano com'erano."""
    name: str | None = Field(default=None, min_length=3, max_length=180)
    # 0 toglie la sede; null la lascia com'è.
    location_id: int | None = Field(default=None, ge=0)
    team_size: int | None = Field(default=None, ge=1, le=3)
    format: str | None = Field(default=None, min_length=1, max_length=80)
    game: str | None = None
    best_of: int | None = Field(default=None, ge=1, le=3)
    allow_intentional_draws: bool | None = None
    event_type: Literal["locals", "prerelease", "rcq", "store_championship", "premier", "other"] | None = None
    rules_enforcement_level: str | None = Field(default=None, max_length=40)
    venue: str | None = Field(default=None, max_length=180)
    description: str | None = None
    refund_policy: str | None = None
    starts_on: date | None = None
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    capacity: int | None = Field(default=None, gt=1)
    entry_fee_cents: int | None = Field(default=None, ge=0)
    pay_at_event: bool | None = None
    pay_stripe: bool | None = None
    pay_paypal: bool | None = None
    structure: str | None = Field(default=None, pattern="^(swiss|single_elimination|swiss_topcut|registration_only)$")
    swiss_rounds: int | None = Field(default=None, ge=0)
    top_cut_size: int | None = Field(default=None, ge=2)
    decklist_required: bool | None = None
    check_in_required: bool | None = None
    round_timer_minutes: int | None = Field(default=None, ge=1, le=120)
    email_notifications_enabled: bool | None = None
    sanction_id: str | None = Field(default=None, max_length=60)
    invites: int | None = Field(default=None, ge=0, le=64)
    is_online: bool | None = None
    online_platform: str | None = Field(default=None, max_length=30)
    online_link: str | None = Field(default=None, max_length=300, pattern=r"^(https://\S+)?$")


class TournamentOut(BaseModel):
    id: int
    organizer_id: int
    name: str
    format: str
    game: str = "mtg"
    best_of: int = 3
    allow_intentional_draws: bool = True
    # Chi organizza, come persona: il negozio (organization_name) non basta a
    # sapere a chi rivolgersi.
    organizer_name: str | None = None
    location_id: int | None = None
    location_name: str | None = None
    # Solo in /tournaments/mine: chi chiama lo gestisce (suo, o del suo negozio),
    # non ci arbitra soltanto.
    can_manage: bool = False
    series_id: int | None = None
    pod_size: int = 0
    team_size: int = 1
    # Solo nella risposta di una modifica estesa alla serie.
    series_updated: int | None = None
    series_skipped: list[str] = []
    event_type: str = "locals"
    rules_enforcement_level: str
    venue: str
    latitude: float | None = None
    longitude: float | None = None
    # Popolato solo dalla ricerca per distanza.
    distance_km: float | None = None
    event_slug: str | None = None
    event_name: str | None = None
    organization_slug: str | None = None
    organization_name: str | None = None
    starts_on: date
    start_time: str | None = None
    capacity: int
    entry_fee_cents: int
    currency: str
    status: str
    structure: str
    swiss_rounds: int
    top_cut_size: int
    decklist_required: bool
    decklist_deadline: datetime | None
    # Calcolati dal modello: il giocatore deve sapere entro quando può modificare.
    decklist_locks_at: datetime | None = None
    decklist_locked: bool = False
    # I segmenti per cui serve una lista: "" e la principale, poi i formati
    # dichiarati sui round. Un torneo a formato unico ha solo [""].
    decklist_formats: list[str] = [""]
    check_in_required: bool
    self_check_in_enabled: bool
    late_registration_enabled: bool
    registration_mode: str
    pairings_public: bool
    standings_public: bool
    decklists_public: bool = False
    round_timer_minutes: int
    refund_policy: str
    email_notifications_enabled: bool
    legal_validation_enabled: bool
    description: str
    pay_at_event: bool = True
    pay_stripe: bool = False
    pay_paypal: bool = False
    registered_players: int = 0
    sanction_id: str = ""
    invites: int = 0
    is_online: bool = False
    online_platform: str = ""
    # Solo per chi è iscritto o nello staff (/tournaments/mine): altrove è vuoto.
    online_link: str = ""

    model_config = {"from_attributes": True}


class RegistrationCreate(BaseModel):
    wizards_account: str = ""
    # Nei tornei online: il nome in gioco (l'Arena ID su MTG Arena).
    game_handle: str = Field(default="", max_length=80)
    # Le risposte alle domande del torneo, per id della domanda.
    answers: dict[int, str | bool] = {}


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TeamSeatIn(BaseModel):
    registration_id: int | None = None   # null libera il posto


class TeamMemberOut(BaseModel):
    registration_id: int
    name: str
    seat: int


class TeamOut(BaseModel):
    id: int
    name: str
    members: list[TeamMemberOut]
    complete: bool


class TeamStandingOut(BaseModel):
    position: int
    team_id: int
    name: str
    points: int
    record: str
    opponent_match_win_percentage: float
    seat_wins: int


class FixedTableIn(BaseModel):
    table: int | None = Field(default=None, ge=1, le=500)   # null toglie il tavolo fisso


class PodsIn(BaseModel):
    pod_size: int = Field(default=8, ge=4, le=12)


class PodSeatOut(BaseModel):
    registration_id: int
    name: str
    seat: int


class PodOut(BaseModel):
    pod: int
    players: list[PodSeatOut]


class ByesIn(BaseModel):
    byes: int = Field(ge=0, le=3)


class TardinessIn(BaseModel):
    """Chi non si presenta al tavolo o arriva tardi. match_loss: l'avversario
    vince a tavolino; game_loss: la partita si gioca, la penalità resta scritta."""
    registration_id: int
    penalty: Literal["game_loss", "match_loss"] = "match_loss"
    # Chi non si è presentato si può anche ritirare dal torneo.
    drop: bool = False
    note: str = Field(default="", max_length=500)


class PrizeIn(BaseModel):
    """Premio consegnato (given) o annullato; note dice cosa: "3 buste", "20 € di credito"."""
    given: bool
    note: str = Field(default="", max_length=240)


class DropUnpaidOut(BaseModel):
    # Chi viene tolto (o verrebbe tolto, in anteprima), e quanti salgono dalla lista d'attesa.
    dropped: list[str]
    promoted: int = 0


class ImportIn(BaseModel):
    """Una lista di giocatori da iscrivere, così come esce da un foglio di calcolo."""
    csv_text: str = Field(min_length=1, max_length=200_000)
    # Tutti come pagati al banco, oltre a chi lo è già segnato nel file.
    mark_paid: bool = False
    # Vero: dice solo cosa succederebbe, riga per riga.
    dry_run: bool = True


class ImportRowOut(BaseModel):
    line: int
    email: str
    name: str
    outcome: Literal["added", "waitlisted", "already", "error"]
    detail: str = ""


class ImportOut(BaseModel):
    rows: list[ImportRowOut]
    added: int
    waitlisted: int
    skipped: int


class RegistrationFieldIn(BaseModel):
    id: int | None = None       # presente: la domanda esiste già e tiene le sue risposte
    label: str = Field(min_length=1, max_length=160)
    kind: Literal["text", "choice", "checkbox"] = "text"
    options: list[str] = []
    required: bool = False

    @model_validator(mode="after")
    def _choices(self) -> RegistrationFieldIn:
        self.options = [o.strip() for o in self.options if o.strip()]
        if self.kind == "choice" and len(self.options) < 2:
            raise ValueError(f"«{self.label}»: servono almeno due scelte")
        return self


class RegistrationFieldOut(BaseModel):
    id: int
    label: str
    kind: str
    options: list[str]
    required: bool
    position: int


class WalkInIn(BaseModel):
    """Iscrizione 'al banco' creata dall'organizzatore per un giocatore presente.
    Senza email il giocatore è un ospite: gioca, ma non ha un account."""
    email: EmailStr | None = None
    display_name: str = Field(min_length=2, max_length=160)
    wizards_account: str = ""
    mark_paid: bool = True
    answers: dict[int, str | bool] = {}


class TimerRestartIn(BaseModel):
    minutes: int = Field(default=50, ge=1, le=180)


class TimerExtendIn(BaseModel):
    minutes: int = Field(ge=1, le=120)


class TableExtendIn(BaseModel):
    minutes: int = Field(ge=1, le=120)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class SeasonCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    points_win: int = 3
    points_draw: int = 1


class SeasonOut(BaseModel):
    id: int
    name: str
    slug: str | None = None
    description: str = ""
    starts_on: date | None = None
    ends_on: date | None = None
    points_win: int
    points_draw: int
    points_participation: int = 0
    points_champion_bonus: int = 0
    qualification_threshold: int | None = None
    is_public: bool = True
    is_active: bool
    tournament_count: int = 0
    organization_slug: str | None = None

    model_config = {"from_attributes": True}


class SeasonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    points_win: int | None = Field(default=None, ge=0, le=100)
    points_draw: int | None = Field(default=None, ge=0, le=100)
    points_participation: int | None = Field(default=None, ge=0, le=100)
    points_champion_bonus: int | None = Field(default=None, ge=0, le=100)
    qualification_threshold: int | None = Field(default=None, ge=0)
    is_public: bool | None = None


class SeriesPublicOut(BaseModel):
    season: SeasonOut
    tournaments: list[TournamentOut] = []
    leaderboard: list[LeaderboardRowOut] = []


class PlayerTagIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default="#d8b465", pattern=r"^#[0-9a-fA-F]{6}$")
    description: str = Field(default="", max_length=240)


class PlayerTagOut(BaseModel):
    id: int
    name: str
    color: str
    description: str = ""
    player_count: int = 0

    model_config = {"from_attributes": True}


class TagAssignIn(BaseModel):
    """Assegnazione singola o in blocco: la UI manda sempre una lista."""
    user_ids: list[int] = Field(min_length=1, max_length=500)


class LeaderboardRowOut(BaseModel):
    position: int
    player_name: str
    points: int
    wins: int
    draws: int
    losses: int
    tournaments_played: int


class StaffIn(BaseModel):
    email: EmailStr
    role: Literal["head_judge", "judge"] = "judge"


class StaffRoleIn(BaseModel):
    role: Literal["head_judge", "judge"]


class StaffOut(BaseModel):
    id: int
    user_id: int
    display_name: str
    email: str
    role: str


class TournamentRoleOut(BaseModel):
    """Che cosa sei su questo torneo: serve alla UI per decidere cosa mostrare."""
    role: Literal["organizer", "head_judge", "judge", "player", "none"]
    can_manage_judges: bool


class PlayerHistoryRowOut(BaseModel):
    tournament_id: int
    tournament_name: str
    starts_on: date
    format: str
    status: str
    placement: int | None = None
    record: str = ""
    points: int = 0
    event_type: str = "locals"
    # Ha chiuso fra i qualificati di un programma ufficiale (l'invito di un RCQ).
    invited: bool = False


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


class VapidKeyOut(BaseModel):
    public_key: str | None = None
    enabled: bool = False


class EventCreate(BaseModel):
    name: str = Field(min_length=3, max_length=180)
    description: str = ""
    venue: str = ""
    starts_on: date
    ends_on: date | None = None
    is_public: bool = True


class EventUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=180)
    description: str | None = None
    venue: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    is_public: bool | None = None


class EventOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str = ""
    venue: str = ""
    starts_on: date
    ends_on: date | None = None
    is_public: bool = True
    organization_slug: str | None = None
    tournament_count: int = 0

    model_config = {"from_attributes": True}


class WarningOut(BaseModel):
    """Qualcosa che il sistema accetta ma che quasi sempre e una svista.
    `warn` va risolto, `info` e una nota: solo i primi contano nei badge."""
    code: str
    level: str = Field(pattern="^(warn|info)$")
    message: str
    tournament_id: int | None = None


class EventOwnerOut(EventOut):
    """La manifestazione vista da chi la organizza. Gli avvisi stanno qui e non
    su EventOut, che e anche la risposta pubblica: cosi non possono uscire."""
    warnings: list[WarningOut] = []


class EventPublicOut(BaseModel):
    event: EventOut
    tournaments: list[TournamentOut] = []


class Day2In(BaseModel):
    """Chi passa alla seconda giornata. La lista sostituisce quella precedente:
    ripetere la chiamata con l'elenco giusto corregge un import sbagliato."""
    registration_ids: list[int] = Field(max_length=2000)


class Day2ConversionRow(BaseModel):
    archetype: str
    players: int
    day2: int
    conversion: float


class OrganizationOut(BaseModel):
    id: int
    slug: str
    name: str
    is_default: bool = False
    description: str = ""
    city: str = ""
    address: str = ""
    website: str = ""
    logo_url: str = ""
    latitude: float | None = None
    longitude: float | None = None
    is_premium: bool = False
    upcoming_count: int = 0
    past_count: int = 0
    distance_km: float | None = None
    # Solo in /organizations/mine: il ruolo di chi chiama nello staff.
    my_role: str | None = None

    model_config = {"from_attributes": True}


class StoreCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    city: str = Field(default="", max_length=120)


class StoreMembershipOut(BaseModel):
    slug: str
    name: str
    role: str
    current: bool = False


class StoreMemberIn(BaseModel):
    email: EmailStr
    role: Literal["owner", "organizer"] = "organizer"


class StoreMemberRoleIn(BaseModel):
    role: Literal["owner", "organizer"]


class SuspensionIn(BaseModel):
    """Il giocatore si indica con l'email del suo account o, dalla lista iscritti, con l'id."""
    email: EmailStr | None = None
    user_id: int | None = None
    reason: str = Field(min_length=3, max_length=500)
    ends_on: date | None = None

    @model_validator(mode="after")
    def _someone(self) -> SuspensionIn:
        if not self.email and not self.user_id:
            raise ValueError("Indica il giocatore: email o id")
        return self


class SuspensionOut(BaseModel):
    id: int
    user_id: int
    display_name: str
    email: str
    reason: str
    ends_on: date | None = None
    created_at: datetime
    created_by_name: str | None = None
    lifted_at: datetime | None = None
    active: bool


class StoreMemberOut(BaseModel):
    user_id: int
    display_name: str
    email: str
    role: str
    created_at: datetime


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    city: str | None = None
    address: str | None = None
    website: str | None = None
    logo_url: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class LocationIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(default="", max_length=240)
    city: str = Field(default="", max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: str = ""


class LocationOut(LocationIn):
    id: int
    organization_id: int
    label: str = ""

    model_config = {"from_attributes": True}


class StoreProfileOut(BaseModel):
    """Pagina pubblica del negozio: anagrafica piu cosa c'e in calendario."""
    organization: OrganizationOut
    locations: list[LocationOut] = []
    upcoming: list[TournamentOut] = []
    past: list[TournamentOut] = []


class PublicStandingRow(BaseModel):
    position: int
    registration_id: int
    name: str
    points: int
    record: str
    archetype: str = ""
    decklist: str | None = None   # raw_text, solo se le liste sono pubbliche


class PublicResultsOut(BaseModel):
    tournament_id: int
    name: str
    format: str
    starts_on: date
    start_time: str | None = None
    status: str
    standings_public: bool
    decklists_public: bool
    standings: list[PublicStandingRow] = []


class OrganizedTournamentRow(BaseModel):
    tournament_id: int
    name: str
    format: str
    starts_on: date
    status: str
    registered_players: int = 0


class PlayerPublicProfileOut(BaseModel):
    display_name: str
    email: str
    role: str = "player"
    tournaments_played: int = 0
    total_points: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    rows: list[PlayerHistoryRowOut] = []
    organized: list[OrganizedTournamentRow] = []


class AuditLogOut(BaseModel):
    id: int
    action: str
    detail: str
    editor: str
    created_at: datetime


class MetaStatRow(BaseModel):
    archetype: str
    players: int
    wins: int
    draws: int
    losses: int
    win_rate: float


class RegenerateRoundIn(BaseModel):
    drop_registration_ids: list[int] = []


class TournamentReportOut(BaseModel):
    tournament_id: int
    tournament_name: str
    starts_on: date
    format: str
    registrations: int
    paid_count: int
    revenue_cents: int
    currency: str


class PublicPairingOut(BaseModel):
    table_number: int
    player_a: str
    player_b: str | None
    result: str
    extra_seconds: int = 0
    ends_at: datetime | None = None   # fine effettiva del tavolo (round + extra)


class PublicDisplayOut(BaseModel):
    tournament_name: str
    round_number: int | None
    round_ends_at: datetime | None
    pairings: list[PublicPairingOut] = []
    standings: list[StandingOut] = []


class RegistrationOut(BaseModel):
    id: int
    tournament_id: int
    player_id: int
    archetype: str
    wizards_account: str
    checked_in: bool
    dropped: bool
    waitlisted: bool = False
    day2: bool = False
    player: UserOut
    decklist_status: str = "missing"
    # Segmenti gia consegnati: "" e la lista principale.
    decklist_formats: list[str] = []
    payment_status: str = "pending"
    # Pod di draft, posto al tavolo del draft e tavolo fisso, se ci sono.
    pod: int | None = None
    pod_seat: int | None = None
    fixed_table: int | None = None
    team_id: int | None = None
    team_name: str | None = None
    team_seat: int | None = None
    game_handle: str = ""
    # Il link della stanza del torneo online: l'iscritto lo trova qui.
    online_link: str = ""

    model_config = {"from_attributes": True}


class PublisherIdIn(BaseModel):
    publisher_id: str = Field(max_length=80)


class OfficialReportRowOut(BaseModel):
    position: int
    registration_id: int
    name: str
    publisher_id: str
    record: str
    points: int
    invited: bool


class OfficialReportOut(BaseModel):
    """Quello che l'editore chiede di un evento ufficiale: chi ha giocato, con che
    ID, come è finita e chi ha l'invito."""
    tournament_id: int
    name: str
    format: str
    starts_on: date
    status: str
    event_type: str
    sanction_id: str
    sanction_label: str
    publisher_id_label: str
    players: int
    rounds: int
    invites: int
    rows: list[OfficialReportRowOut]
    missing_ids: list[str]


class GameHandleIn(BaseModel):
    game_handle: str = Field(max_length=80)


class OrganizerRegistrationOut(RegistrationOut):
    player_email: str   # str, non EmailStr: output, non input
    decklist_id: int | None = None
    decklist_main_count: int | None = None
    decklist_side_count: int | None = None
    decklist_errors: str = ""
    decklist_raw_text: str = ""
    payment_id: int | None = None
    payment_provider: str | None = None
    decklist_revision_count: int = 0
    tags: list[PlayerTagOut] = []
    # Le risposte alle domande del torneo, per id della domanda.
    answers: dict[int, str] = {}
    prize_note: str = ""
    prize_given_at: datetime | None = None
    byes: int = 0
    # account | profile (un minore, gestito da un genitore) | guest (senza account)
    player_kind: str = "account"
    # Penalità prese negli altri tornei (senza le note): un judge vede i recidivi.
    prior_penalties: int = 0
    guardian_name: str | None = None
    guardian_email: str | None = None


class TournamentControlsIn(BaseModel):
    pairings_public: bool | None = None
    standings_public: bool | None = None
    decklists_public: bool | None = None
    decklist_deadline: datetime | None = None
    self_check_in_enabled: bool | None = None
    late_registration_enabled: bool | None = None
    registration_mode: str | None = Field(default=None, pattern="^(open|closed)$")
    round_timer_minutes: int | None = Field(default=None, ge=1, le=120)
    email_notifications_enabled: bool | None = None
    refund_policy: str | None = None
    email_notifications_enabled: bool | None = None
    legal_validation_enabled: bool | None = None


class TableAssignIn(BaseModel):
    """user_id nullo libera il tavolo."""
    user_id: int | None = None


class TableStatusIn(BaseModel):
    status: Literal["playing", "called", "attention"]


class DeckCheckIn(BaseModel):
    registration_id: int
    result: Literal["ok", "minor", "major", "not_found"] = "ok"
    note: str = Field(default="", max_length=500)


class DeckCheckOut(BaseModel):
    id: int
    registration_id: int
    player_name: str = ""
    round_number: int | None = None
    judge_name: str = ""
    result: str
    note: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class ManualPairingIn(BaseModel):
    table_number: int = Field(gt=0)
    player_a_registration_id: int
    player_b_registration_id: int | None = None


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    body: str = Field(min_length=2)
    send_email: bool = False
    # Lista vuota: a tutti gli iscritti. Con dei tag, solo a chi ne porta almeno uno.
    tag_ids: list[int] = Field(default_factory=list)


class AnnouncementOut(BaseModel):
    id: int
    tournament_id: int
    title: str
    body: str
    send_email: bool
    targeted: bool = False
    audience: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class AnnouncementAudienceOut(BaseModel):
    """Quanti leggeranno un annuncio, prima di scriverlo: mandare a un
    sottoinsieme senza sapere quanto e grande e un errore facile."""
    recipients: int
    total: int
    label: str
    # Se "Invia anche via email" partira davvero: "ok", "tournament_off" (spenta
    # sul torneo, si accende da qui) o "no_smtp" (manca il server di posta).
    email_status: str = "ok"


class PenaltyCreate(BaseModel):
    registration_id: int
    round_id: int | None = None
    kind: str = Field(default="warning", pattern="^(warning|game_loss|match_loss|disqualification|note)$")
    note: str = ""
    is_private: bool = True


class PenaltyHistoryOut(BaseModel):
    """Una penalità del giocatore in un altro torneo, per chi lo arbitra ora."""
    tournament_id: int
    tournament_name: str
    starts_on: date
    store_name: str | None = None
    round_number: int | None = None
    kind: str
    note: str
    judge_name: str | None = None
    created_at: datetime


class PenaltyOut(BaseModel):
    id: int
    tournament_id: int
    registration_id: int
    judge_id: int
    round_id: int | None
    kind: str
    note: str
    is_private: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class InviteCodeCreate(BaseModel):
    code: str = Field(min_length=3, max_length=80)
    max_uses: int = Field(default=1, ge=1)


class InviteCodeOut(BaseModel):
    id: int
    tournament_id: int
    code: str
    max_uses: int
    used_count: int

    model_config = {"from_attributes": True}


class RefundRequestIn(BaseModel):
    reason: str = ""


class RefundDecisionIn(BaseModel):
    approve: bool = True


class PlayerCardOut(BaseModel):
    registration: RegistrationOut
    payment: PaymentOut | None = None
    decklist: DecklistOut | None = None
    pairings: list[PairingOut]
    penalties: list[PenaltyOut]


class BracketMatchOut(BaseModel):
    pairing_id: int
    round_number: int
    table_number: int
    player_a: str
    player_b: str | None
    match_wins_a: int = 0
    match_wins_b: int = 0
    winner: str | None


class DecklistCreate(BaseModel):
    raw_text: str = Field(min_length=5)
    archetype: str = ""
    # Vuoto = lista principale. Valorizzato sui segmenti di un evento misto.
    format: str = Field(default="", max_length=80)


class SavedDeckIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    game: str = Field(default="mtg", max_length=20)
    format: str = Field(default="", max_length=80)
    archetype: str = Field(default="", max_length=120)
    raw_text: str = Field(default="", max_length=20_000)

    @field_validator("name", "format", "archetype")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class SavedDeckOut(BaseModel):
    id: int
    name: str
    game: str
    format: str
    archetype: str
    raw_text: str
    main_count: int
    side_count: int
    # Le regole del formato, senza rete: la legalità delle carte si chiede a parte.
    errors: list[str]
    updated_at: datetime


class DeckValidateIn(BaseModel):
    raw_text: str = Field(default="", max_length=20_000)
    game: str = Field(default="mtg", max_length=20)
    format: str = Field(default="", max_length=80)
    # Chiede a Scryfall se le carte sono legali nel formato (serve la rete).
    legality: bool = False


class DeckValidateOut(BaseModel):
    main_count: int
    side_count: int
    status: str
    errors: list[str]


class CardLookupIn(BaseModel):
    game: str = Field(default="mtg", max_length=20)
    names: list[str] = Field(default_factory=list, max_length=250)


class CardOut(BaseModel):
    query: str
    found: bool
    name: str
    mana_cost: str
    type_line: str
    category: str
    image: str


class ArchiveDeckOut(BaseModel):
    """Una lista dell'archivio pubblico: chi l'ha giocata, dove e come è andata."""
    decklist_id: int
    registration_id: int
    tournament_id: int
    tournament_name: str
    starts_on: date
    store_name: str | None = None
    store_slug: str | None = None
    format: str
    position: int
    players: int
    player_name: str
    archetype: str
    record: str
    points: int
    main_count: int
    side_count: int


class ArchiveDeckDetailOut(ArchiveDeckOut):
    raw_text: str


class ArchivePageOut(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[ArchiveDeckOut]


class ArchetypeShareOut(BaseModel):
    archetype: str
    lists: int
    share: float        # percentuale delle liste
    top8: int
    wins: int


class CardShareOut(BaseModel):
    name: str
    lists: int
    share: float        # percentuale delle liste che la giocano
    copies: float       # copie in media, main e sideboard insieme


class ArchiveMetaOut(BaseModel):
    total_lists: int
    archetypes: list[ArchetypeShareOut]
    top_cards: list[CardShareOut]


class DecklistOut(BaseModel):
    id: int
    registration_id: int
    format: str = ""
    # Il giocatore deve poter rileggere la propria lista per correggerla e vederla.
    raw_text: str = ""
    main_count: int
    side_count: int
    status: str
    validation_errors: str
    submitted_at: datetime

    model_config = {"from_attributes": True}


class CheckoutCreate(BaseModel):
    provider: str = Field(pattern="^(stripe|paypal)$")


class PaymentOut(BaseModel):
    id: int
    provider: str
    status: str
    amount_cents: int
    currency: str
    checkout_url: str
    refund_reason: str = ""

    model_config = {"from_attributes": True}


class SandboxPaymentOut(BaseModel):
    id: int
    status: str


class PairingOut(BaseModel):
    id: int
    table_number: int
    player_a: str
    player_a_registration_id: int
    player_b: str | None = None
    player_b_registration_id: int | None = None
    result: str = ""
    match_wins_a: int = 0
    match_wins_b: int = 0
    draws: int = 0
    extra_seconds: int = 0
    assigned_judge_id: int | None = None
    assigned_judge_name: str = ""
    table_status: str = "playing"
    report_id: int | None = None
    report_status: str = ""
    report_score: str = ""
    report_reporter_registration_id: int | None = None
    report_reporter_name: str = ""
    # I nomi in gioco dei due giocatori: solo nei propri abbinamenti di un torneo online.
    player_a_handle: str = ""
    player_b_handle: str = ""


class RoundFormatIn(BaseModel):
    format: str | None = Field(default=None, max_length=80)


class RoundOut(BaseModel):
    id: int
    tournament_id: int
    number: int
    phase: str
    # Nullo = il formato del torneo. Valorizzato sui segmenti a formato diverso.
    format: str | None = None
    is_published: bool
    starts_at: datetime | None
    ends_at: datetime | None
    pairings: list[PairingOut]


class PairingResultIn(BaseModel):
    match_wins_a: int = Field(ge=0, le=2)
    match_wins_b: int = Field(ge=0, le=2)
    draws: int = Field(default=0, ge=0, le=0)


class PairingResultRejectIn(BaseModel):
    note: str = ""


class StandingOut(BaseModel):
    position: int
    registration_id: int
    name: str
    pod: int = 1
    points: int
    record: str
    match_win_percentage: float
    opponent_match_win_percentage: float
    # Non tutti i giochi le usano: One Piece e Pokémon non guardano i giochi.
    game_win_percentage: float = 0.0
    opponent_game_win_percentage: float = 0.0
    opponent_opponent_win_percentage: float = 0.0   # solo Pokémon


# Risolve la forward reference "StandingOut" usata in PublicDisplayOut
PublicDisplayOut.model_rebuild()
