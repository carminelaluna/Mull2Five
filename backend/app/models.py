from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class UserRole(StrEnum):
    PLAYER = "player"
    ORGANIZER = "organizer"
    ADMIN = "admin"


class TournamentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TournamentStructure(StrEnum):
    SWISS = "swiss"
    SINGLE_ELIMINATION = "single_elimination"
    SWISS_TOPCUT = "swiss_topcut"


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


class ResultReportStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"


def now_utc() -> datetime:
    return datetime.now(UTC)


class Organization(Base):
    """Tenant: il negozio/organizzazione che ospita i tornei. Ogni organizer e
    torneo appartiene a un'organizzazione; il listing pubblico può essere filtrato
    per tenant (header X-Manabind-Org o slug). Esiste sempre un'org di default."""
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    user: Mapped[User] = relationship(back_populates="push_subscriptions")


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

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
    rules_enforcement_level: Mapped[str] = mapped_column(String(40), default="Competitive")
    venue: Mapped[str] = mapped_column(String(180), default="")
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
    decklist_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    organizer: Mapped[User] = relationship(back_populates="tournaments")
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
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    tournament: Mapped[Tournament] = relationship(back_populates="registrations")
    player: Mapped[User] = relationship(back_populates="registrations")
    decklist: Mapped["Decklist"] = relationship(back_populates="registration", uselist=False)
    decklist_revisions: Mapped[list["DecklistRevision"]] = relationship(back_populates="registration")
    payment: Mapped["Payment"] = relationship(back_populates="registration", uselist=False)


class Decklist(Base):
    __tablename__ = "decklists"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(
        ForeignKey("registrations.id", ondelete="CASCADE"), unique=True
    )
    raw_text: Mapped[str] = mapped_column(Text)
    main_count: Mapped[int] = mapped_column(Integer, default=0)
    side_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=DecklistStatus.SUBMITTED)
    validation_errors: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    registration: Mapped[Registration] = relationship(back_populates="decklist")


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

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
    refund_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    registration: Mapped[Registration] = relationship(back_populates="payment")


class Round(Base):
    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("tournament_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(32), default="swiss")
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

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

    round: Mapped[Round] = relationship(back_populates="pairings")
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    tournament: Mapped[Tournament] = relationship(back_populates="announcements")
    author: Mapped[User] = relationship()


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    registration: Mapped[Registration] = relationship()
    judge: Mapped[User] = relationship()
    round: Mapped[Round | None] = relationship()


class Season(Base):
    """Stagione del negozio: raggruppa tornei e somma i punti per la leaderboard."""
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    organizer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    points_win: Mapped[int] = mapped_column(Integer, default=3)
    points_draw: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    organizer: Mapped[User] = relationship()
    tournaments: Mapped[list[Tournament]] = relationship()


class TournamentStaff(Base):
    """Staff/judge invitato su un singolo torneo: può inserire risultati e penalità,
    non può eliminare il torneo né vedere i pagamenti."""
    __tablename__ = "tournament_staff"
    __table_args__ = (UniqueConstraint("tournament_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    editor: Mapped[User] = relationship()


class InviteCode(Base):
    __tablename__ = "invite_codes"
    __table_args__ = (UniqueConstraint("tournament_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(80))
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    tournament: Mapped[Tournament] = relationship(back_populates="invite_codes")
