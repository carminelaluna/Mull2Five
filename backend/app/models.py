from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base, UtcDateTime


class UserRole(StrEnum):
    PLAYER = "player"
    ORGANIZER = "organizer"
    ADMIN = "admin"


class StaffRole(StrEnum):
    """Incarico sul singolo torneo, indipendente dal ruolo dell'account: lo stesso
    utente può essere capojudge a un torneo, judge a un altro e giocatore a un terzo."""
    HEAD_JUDGE = "head_judge"
    JUDGE = "judge"


class StoreRole(StrEnum):
    """Ruolo nello staff del negozio. Il titolare decide chi ne fa parte; gli
    organizzatori creano e gestiscono tutti i tornei del negozio."""
    OWNER = "owner"
    ORGANIZER = "organizer"


class TournamentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    """Tassonomia con cui il giocatore filtra: risponde a "che serata e?", non
    a "che formato si gioca?" (quello resta il campo format)."""
    LOCALS = "locals"
    PRERELEASE = "prerelease"
    RCQ = "rcq"
    STORE_CHAMPIONSHIP = "store_championship"
    PREMIER = "premier"
    OTHER = "other"


class RulesEnforcementLevel(StrEnum):
    REGULAR = "Regular"
    COMPETITIVE = "Competitive"
    PROFESSIONAL = "Professional"


class TournamentStructure(StrEnum):
    SWISS = "swiss"
    SINGLE_ELIMINATION = "single_elimination"
    SWISS_TOPCUT = "swiss_topcut"
    # Si raccolgono iscrizioni, pagamenti e presenze, senza turni né classifica:
    # una serata casual, un draft tra amici, una presentazione.
    REGISTRATION_ONLY = "registration_only"


class RegistrationMode(StrEnum):
    OPEN = "open"
    INVITE_ONLY = "invite_only"
    CLOSED = "closed"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    REFUND_REQUESTED = "refund_requested"


class DecklistStatus(StrEnum):
    MISSING = "missing"
    SUBMITTED = "submitted"
    VALID = "valid"
    INVALID = "invalid"


class TableStatus(StrEnum):
    """Stato che il judge imposta a mano sul tavolo. Quello che si puo dedurre
    dai dati (risultato presente, tempo extra, referto in conflitto) resta
    dedotto: qui ci va solo cio che il software non puo sapere da solo."""
    PLAYING = "playing"
    CALLED = "called"        # chiamato a referto
    ATTENTION = "attention"  # richiede un judge


class DeckCheckResult(StrEnum):
    OK = "ok"
    MINOR = "minor"          # discrepanza lieve, lista corretta
    MAJOR = "major"          # errore che comporta penalita
    NOT_FOUND = "not_found"  # lista non consegnata


class ResultReportStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"


DECKLIST_LOCK_MINUTES = 30   # default: liste chiuse 30 minuti prima dell'inizio


def now_utc() -> datetime:
    return datetime.now(UTC)


class Event(Base):
    """Contenitore di tornei che si svolgono insieme: un weekend con main event
    e side event, una convention. Chi ha un ruolo qui ce l'ha su tutti i tornei
    dentro, cosi lo staff si nomina una volta sola per tutto il fine settimana."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organizer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    venue: Mapped[str] = mapped_column(String(180), default="", server_default="")
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    organizer: Mapped["User"] = relationship()
    tournaments: Mapped[list["Tournament"]] = relationship(back_populates="event")


class EventStaff(Base):
    """Staff nominato sull'intero evento. Vale su ogni torneo che contiene:
    a un weekend non si rinomina lo stesso capojudge dieci volte."""
    __tablename__ = "event_staff"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default=StaffRole.JUDGE)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    user: Mapped["User"] = relationship()
    event: Mapped[Event] = relationship()


class Organization(Base):
    """Tenant: il negozio/organizzazione che ospita i tornei. Ogni organizer e
    torneo appartiene a un'organizzazione; il listing pubblico può essere filtrato
    per tenant (header X-Mull2Five-Org o slug). Esiste sempre un'org di default."""
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Profilo pubblico del negozio: senza questi la pagina store non ha nulla da dire.
    # server_default perché la riga di default nasce da una INSERT grezza in db.py.
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    city: Mapped[str] = mapped_column(String(120), default="", server_default="")
    address: Mapped[str] = mapped_column(String(240), default="", server_default="")
    website: Mapped[str] = mapped_column(String(240), default="", server_default="")
    logo_url: Mapped[str] = mapped_column(String(400), default="", server_default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)


class Location(Base):
    """Una sede del negozio: dove si gioca. Un negozio con due punti vendita, o che
    affitta una sala per gli eventi grandi, ne ha più d'una; il torneo sceglie la
    sua e ne eredita indirizzo e coordinate (per la ricerca per distanza)."""
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(240), default="", server_default="")
    city: Mapped[str] = mapped_column(String(120), default="", server_default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Accessibilità, parcheggio, piano: quello che serve sapere prima di arrivare.
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    @property
    def label(self) -> str:
        """Come si scrive la sede sotto il nome del torneo."""
        return ", ".join(part for part in (self.name, self.address, self.city) if part)


class StoreMember(Base):
    """Chi lavora per il negozio: più account sugli stessi tornei."""
    __tablename__ = "store_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default=StoreRole.ORGANIZER)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    user: Mapped["User"] = relationship()


class Suspension(Base):
    """Un giocatore escluso dagli eventi di un negozio: il motivo e fino a quando.
    Non si cancella: revocarla lascia scritto chi l'ha tolta e quando."""
    __tablename__ = "suspensions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    # Vuota: vale finché qualcuno non la revoca.
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)
    lifted_at: Mapped[datetime | None] = mapped_column(UtcDateTime(timezone=True), nullable=True)
    lifted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])

    def is_active(self, today: date) -> bool:
        return self.lifted_at is None and (self.ends_on is None or self.ends_on >= today)


class TournamentSeries(Base):
    """Tornei che si ripetono (il venerdì sera, il primo sabato del mese): ogni
    data resta un torneo a sé, la serie serve a crearli e a modificarli insieme."""
    __tablename__ = "tournament_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    frequency: Mapped[str] = mapped_column(String(20))
    organizer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)


class RegistrationField(Base):
    """Una domanda in più all'iscrizione, decisa dall'organizzatore: la taglia
    della maglietta, l'archetipo del mazzo, "accetto il regolamento"."""
    __tablename__ = "registration_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20), default="text")    # text | choice | checkbox
    # Le scelte possibili, una per riga (solo per "choice").
    options: Mapped[str] = mapped_column(Text, default="", server_default="")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def option_list(self) -> list[str]:
        return [line for line in self.options.splitlines() if line.strip()]


class RegistrationAnswer(Base):
    __tablename__ = "registration_answers"
    __table_args__ = (UniqueConstraint("registration_id", "field_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(
        ForeignKey("registrations.id", ondelete="CASCADE"), index=True
    )
    field_id: Mapped[int] = mapped_column(ForeignKey("registration_fields.id", ondelete="CASCADE"))
    value: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(32), default=UserRole.PLAYER)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="user")
    tournaments: Mapped[list["Tournament"]] = relationship(back_populates="organizer")
    registrations: Mapped[list["Registration"]] = relationship(back_populates="player")
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(back_populates="user")


class PushSubscription(Base):
    """Subscription Web Push (browser) di un utente per le notifiche di torneo."""
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    user: Mapped[User] = relationship(back_populates="push_subscriptions")


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    user: Mapped[User] = relationship(back_populates="oauth_accounts")


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    organizer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(180), index=True)
    format: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(40), default=EventType.LOCALS, index=True)
    # Il gioco decide formati, spareggi e regole di mazzo: vedi backend/app/games.py.
    game: Mapped[str] = mapped_column(String(20), default="mtg", server_default="mtg", index=True)
    # Match in svizzera al meglio di 1, 2 o 3 (i playoff sono sempre al meglio di 3).
    best_of: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    # Spento, il pulsante della patta intenzionale sparisce; le patte a tempo restano.
    allow_intentional_draws: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    rules_enforcement_level: Mapped[str] = mapped_column(String(40), default="Competitive")
    venue: Mapped[str] = mapped_column(String(180), default="")
    # Coordinate del luogo: se assenti vale la posizione del negozio.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    starts_on: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM"
    capacity: Mapped[int] = mapped_column(Integer)
    entry_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(32), default=TournamentStatus.DRAFT)
    structure: Mapped[str] = mapped_column(String(32), default=TournamentStructure.SWISS)
    swiss_rounds: Mapped[int] = mapped_column(Integer, default=0)
    top_cut_size: Mapped[int] = mapped_column(Integer, default=8)
    decklist_required: Mapped[bool] = mapped_column(Boolean, default=True)
    decklist_deadline: Mapped[datetime | None] = mapped_column(UtcDateTime(timezone=True), nullable=True)
    check_in_required: Mapped[bool] = mapped_column(Boolean, default=False)
    self_check_in_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    late_registration_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    registration_mode: Mapped[str] = mapped_column(String(32), default=RegistrationMode.OPEN)
    pairings_public: Mapped[bool] = mapped_column(Boolean, default=False)
    standings_public: Mapped[bool] = mapped_column(Boolean, default=True)
    decklists_public: Mapped[bool] = mapped_column(Boolean, default=False)
    round_timer_minutes: Mapped[int] = mapped_column(Integer, default=50)
    refund_policy: Mapped[str] = mapped_column(Text, default="")
    invite_code_required: Mapped[bool] = mapped_column(Boolean, default=False)
    email_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    legal_validation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # Metodi di pagamento accettati per l'iscrizione
    pay_at_event: Mapped[bool] = mapped_column(Boolean, default=True)   # al banco, in loco
    pay_stripe: Mapped[bool] = mapped_column(Boolean, default=False)    # online via Stripe
    pay_paypal: Mapped[bool] = mapped_column(Boolean, default=False)    # online via PayPal
    season_id: Mapped[int | None] = mapped_column(
        ForeignKey("seasons.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament_series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    location: Mapped["Location | None"] = relationship()

    @property
    def place(self) -> str:
        """Dove si gioca: il luogo scritto a mano vince, altrimenti la sede scelta."""
        return self.venue or (self.location.label if self.location else "")

    @property
    def starts_at(self) -> datetime | None:
        """Data e ora di inizio. None senza un orario valido: la sola data non
        basta a dire quando si comincia."""
        if not self.start_time:
            return None
        try:
            hh, mm = (int(part) for part in self.start_time.split(":"))
        except (ValueError, TypeError):
            return None
        return datetime.combine(self.starts_on, time(hh, mm), tzinfo=UTC)

    @property
    def decklist_locks_at(self) -> datetime | None:
        """Istante in cui le liste si chiudono: la deadline esplicita, altrimenti 30
        minuti prima dell'orario di inizio. None se l'organizzatore non ha fissato
        nulla — in quel caso a chiudere è solo l'avvio del torneo."""
        if self.decklist_deadline:
            deadline = self.decklist_deadline
            return deadline if deadline.tzinfo else deadline.replace(tzinfo=UTC)
        start = self.starts_at
        return start - timedelta(minutes=DECKLIST_LOCK_MINUTES) if start else None

    @property
    def decklist_locked(self) -> bool:
        """A torneo avviato o concluso le liste sono sempre chiuse."""
        if self.status in {TournamentStatus.RUNNING, TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}:
            return True
        locks_at = self.decklist_locks_at
        return bool(locks_at and datetime.now(UTC) > locks_at)

    organizer: Mapped[User] = relationship(back_populates="tournaments")
    event: Mapped[Event | None] = relationship(back_populates="tournaments")
    registrations: Mapped[list["Registration"]] = relationship(back_populates="tournament")
    rounds: Mapped[list["Round"]] = relationship(back_populates="tournament")
    announcements: Mapped[list["Announcement"]] = relationship(back_populates="tournament")
    invite_codes: Mapped[list["InviteCode"]] = relationship(back_populates="tournament")


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (UniqueConstraint("tournament_id", "player_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    player_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    archetype: Mapped[str] = mapped_column(String(120), default="")
    wizards_account: Mapped[str] = mapped_column(String(80), default="")
    checked_in: Mapped[bool] = mapped_column(Boolean, default=False)
    dropped: Mapped[bool] = mapped_column(Boolean, default=False)
    waitlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted_at: Mapped[datetime | None] = mapped_column(UtcDateTime(timezone=True), nullable=True)
    day2: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    tournament: Mapped[Tournament] = relationship(back_populates="registrations")
    player: Mapped[User] = relationship(back_populates="registrations")
    decklists: Mapped[list["Decklist"]] = relationship(
        back_populates="registration", cascade="all, delete-orphan"
    )

    @property
    def decklist(self) -> "Decklist | None":
        """La lista principale. Tutto il codice che non sa nulla di segmenti
        continua a leggere `registration.decklist` e trova quella giusta."""
        return next((d for d in self.decklists if not d.format), None)

    def decklist_for(self, fmt: str) -> "Decklist | None":
        return next((d for d in self.decklists if d.format == (fmt or "")), None)
    decklist_revisions: Mapped[list["DecklistRevision"]] = relationship(back_populates="registration")
    payment: Mapped["Payment"] = relationship(back_populates="registration", uselist=False)


class Decklist(Base):
    """Una lista per segmento di formato.

    `format` vuoto e la lista principale, il caso normale di un torneo a formato
    unico. In un evento misto ce n'e una per porzione ("Booster Draft", "Modern").
    Vuoto e non NULL di proposito: in SQL NULL != NULL, quindi con NULL il vincolo
    di unicita non impedirebbe due liste principali sulla stessa iscrizione.
    """
    __tablename__ = "decklists"
    __table_args__ = (UniqueConstraint("registration_id", "format"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(
        ForeignKey("registrations.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(80), default="", server_default="")
    raw_text: Mapped[str] = mapped_column(Text)
    main_count: Mapped[int] = mapped_column(Integer, default=0)
    side_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=DecklistStatus.SUBMITTED)
    validation_errors: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    registration: Mapped[Registration] = relationship(back_populates="decklists")


class DecklistRevision(Base):
    __tablename__ = "decklist_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"))
    edited_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    raw_text: Mapped[str] = mapped_column(Text)
    main_count: Mapped[int] = mapped_column(Integer, default=0)
    side_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=DecklistStatus.SUBMITTED)
    validation_errors: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    registration: Mapped[Registration] = relationship(back_populates="decklist_revisions")
    edited_by: Mapped[User] = relationship()


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(
        ForeignKey("registrations.id", ondelete="CASCADE"), unique=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default=PaymentStatus.PENDING)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    provider_checkout_id: Mapped[str] = mapped_column(String(255), default="")
    provider_payment_id: Mapped[str] = mapped_column(String(255), default="")
    checkout_url: Mapped[str] = mapped_column(Text, default="")
    refund_reason: Mapped[str] = mapped_column(Text, default="")
    refund_requested_at: Mapped[datetime | None] = mapped_column(UtcDateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)
    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime(timezone=True), nullable=True)

    registration: Mapped[Registration] = relationship(back_populates="payment")


class Round(Base):
    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("tournament_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(32), default="swiss")
    # Segmento a formato diverso (draft ai primi turni, constructed dopo).
    # Nullo significa: il formato del torneo.
    format: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(UtcDateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(UtcDateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    tournament: Mapped[Tournament] = relationship(back_populates="rounds")
    pairings: Mapped[list["Pairing"]] = relationship(back_populates="round")


class Pairing(Base):
    __tablename__ = "pairings"

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"))
    table_number: Mapped[int] = mapped_column(Integer)
    player_a_registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"))
    player_b_registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id"), nullable=True)
    result: Mapped[str] = mapped_column(String(20), default="")
    match_wins_a: Mapped[int] = mapped_column(Integer, default=0)
    match_wins_b: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    # Secondi extra concessi a questo tavolo (es. ruling del judge): si sommano
    # alla scadenza del round per ottenere la fine effettiva del singolo tavolo.
    extra_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # Chi segue questo tavolo a fine round: il team vede la sala coperta a
    # colpo d'occhio invece di chiedersi chi sta guardando cosa.
    assigned_judge_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    table_status: Mapped[str] = mapped_column(
        String(20), default=TableStatus.PLAYING, server_default="playing"
    )

    round: Mapped[Round] = relationship(back_populates="pairings")
    assigned_judge: Mapped["User | None"] = relationship(foreign_keys=[assigned_judge_id])
    player_a: Mapped[Registration] = relationship(foreign_keys=[player_a_registration_id])
    player_b: Mapped[Registration | None] = relationship(foreign_keys=[player_b_registration_id])


class PairingResultReport(Base):
    __tablename__ = "pairing_result_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    pairing_id: Mapped[int] = mapped_column(ForeignKey("pairings.id", ondelete="CASCADE"))
    reporter_registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"))
    match_wins_a: Mapped[int] = mapped_column(Integer, default=0)
    match_wins_b: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=ResultReportStatus.PENDING)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime(timezone=True), nullable=True)

    pairing: Mapped[Pairing] = relationship()
    reporter: Mapped[Registration] = relationship()


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    send_email: Mapped[bool] = mapped_column(Boolean, default=False)
    # Mirato o no: e questo a decidere chi legge, non il numero di destinatari.
    # Un annuncio mandato a un tag che nessuno porta ha zero destinatari e resta
    # privato; se lo si deducesse dalle righe, diventerebbe pubblico.
    targeted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # I nomi dei tag destinatari, congelati al momento dell'invio. E una riga di
    # storia, non una chiave: se il tag viene rinominato o cancellato, resta
    # scritto a chi era stato mandato.
    audience: Mapped[str] = mapped_column(String(240), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    tournament: Mapped[Tournament] = relationship(back_populates="announcements")
    author: Mapped[User] = relationship()
    recipients: Mapped[list["AnnouncementRecipient"]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan"
    )


class AnnouncementRecipient(Base):
    """Chi doveva ricevere un annuncio mirato. Esiste solo per gli annunci con
    destinatari scelti: senza righe, l'annuncio e per tutti gli iscritti, e chi si
    iscrive dopo lo vede comunque.

    La platea si fissa all'invio invece di ricalcolarla dai tag a ogni lettura,
    altrimenti togliere un tag nasconderebbe a un giocatore un messaggio che ha
    gia ricevuto per email, e cancellarlo renderebbe pubblico un annuncio che
    pubblico non era."""
    __tablename__ = "announcement_recipients"
    __table_args__ = (UniqueConstraint("announcement_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    announcement: Mapped[Announcement] = relationship(back_populates="recipients")


class Penalty(Base):
    __tablename__ = "penalties"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"))
    judge_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    round_id: Mapped[int | None] = mapped_column(ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), default="warning")
    note: Mapped[str] = mapped_column(Text, default="")
    is_private: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    registration: Mapped[Registration] = relationship()
    judge: Mapped[User] = relationship()
    round: Mapped[Round | None] = relationship()


class DeckCheck(Base):
    """Esito di un controllo lista. Sopravvive alla rigenerazione di un round:
    e un atto del torneo, non uno stato del turno."""
    __tablename__ = "deck_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"), index=True)
    round_id: Mapped[int | None] = mapped_column(ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True)
    judge_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    result: Mapped[str] = mapped_column(String(20), default=DeckCheckResult.OK)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    registration: Mapped[Registration] = relationship()
    judge: Mapped[User] = relationship()


class Season(Base):
    """Circuito del negozio: raggruppa tornei e somma i punti per la leaderboard.

    Nato come "stagione" interna, ha ora una pagina pubblica propria (slug) con
    periodo, descrizione e soglia di qualificazione.
    """
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    organizer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str | None] = mapped_column(String(120), unique=True, index=True, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    points_win: Mapped[int] = mapped_column(Integer, default=3)
    points_draw: Mapped[int] = mapped_column(Integer, default=1)
    # Punti bonus a chi vince il torneo, e soglia sopra cui si e qualificati.
    points_participation: Mapped[int] = mapped_column(Integer, default=0)
    points_champion_bonus: Mapped[int] = mapped_column(Integer, default=0)
    qualification_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    organizer: Mapped[User] = relationship()
    tournaments: Mapped[list[Tournament]] = relationship()


class PlayerTag(Base):
    """Etichetta che il negozio applica ai propri giocatori (es. "Commander",
    "Nuovo", "Judge"): serve a filtrare gli iscritti e a mandare annunci mirati."""
    __tablename__ = "player_tags"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(9), default="#d8b465")
    description: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    assignments: Mapped[list["PlayerTagAssignment"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )


class PlayerTagAssignment(Base):
    """Un tag su un giocatore. L'etichetta vale dentro il negozio che l'ha creata:
    lo stesso utente puo essere "Habitue" da un tenant e sconosciuto da un altro."""
    __tablename__ = "player_tag_assignments"
    __table_args__ = (UniqueConstraint("tag_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("player_tags.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assigned_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    tag: Mapped[PlayerTag] = relationship(back_populates="assignments")
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class TournamentStaff(Base):
    """Staff giudicante di un singolo torneo. Sia il capojudge sia il judge possono
    inserire risultati, dare penalità ed estendere il tempo di un tavolo; nessuno dei
    due può eliminare il torneo o vedere i pagamenti (restano a load_owned_tournament).
    In più il capojudge nomina e rimuove i judge sotto di lui: è l'organizzatore a
    nominare lui, e ce n'è al massimo uno per torneo."""
    __tablename__ = "tournament_staff"
    __table_args__ = (UniqueConstraint("tournament_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32), default=StaffRole.JUDGE)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    user: Mapped[User] = relationship()
    tournament: Mapped[Tournament] = relationship()


class AuditLog(Base):
    """Traccia azioni sensibili dell'organizzatore (es. correzione risultati a
    torneo concluso): chi, quando, cosa."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    editor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    editor: Mapped[User] = relationship()


class InviteCode(Base):
    __tablename__ = "invite_codes"
    __table_args__ = (UniqueConstraint("tournament_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(80))
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(timezone=True), default=now_utc)

    tournament: Mapped[Tournament] = relationship(back_populates="invite_codes")
