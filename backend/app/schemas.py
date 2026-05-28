from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=8)
    role: str = "player"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    role: str

    model_config = {"from_attributes": True}


class TournamentCreate(BaseModel):
    name: str = Field(min_length=3, max_length=180)
    format: str
    rules_enforcement_level: str = "Competitive"
    venue: str = ""
    starts_on: date
    capacity: int = Field(gt=1)
    entry_fee_cents: int = Field(ge=0)
    currency: str = "EUR"
    status: str = "published"
    structure: str = Field(default="swiss", pattern="^(swiss|single_elimination|swiss_topcut)$")
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
    round_timer_minutes: int = Field(default=50, ge=1, le=120)
    refund_policy: str = ""
    email_notifications_enabled: bool = False
    legal_validation_enabled: bool = False
    description: str = ""


class TournamentOut(BaseModel):
    id: int
    organizer_id: int
    name: str
    format: str
    rules_enforcement_level: str
    venue: str
    starts_on: date
    capacity: int
    entry_fee_cents: int
    currency: str
    status: str
    structure: str
    swiss_rounds: int
    top_cut_size: int
    decklist_required: bool
    decklist_deadline: datetime | None
    check_in_required: bool
    self_check_in_enabled: bool
    late_registration_enabled: bool
    registration_mode: str
    pairings_public: bool
    standings_public: bool
    round_timer_minutes: int
    refund_policy: str
    email_notifications_enabled: bool
    legal_validation_enabled: bool
    description: str
    registered_players: int = 0

    model_config = {"from_attributes": True}


class RegistrationCreate(BaseModel):
    wizards_account: str = ""


class RegistrationOut(BaseModel):
    id: int
    tournament_id: int
    player_id: int
    archetype: str
    wizards_account: str
    checked_in: bool
    dropped: bool
    player: UserOut
    decklist_status: str = "missing"
    payment_status: str = "pending"

    model_config = {"from_attributes": True}


class OrganizerRegistrationOut(RegistrationOut):
    player_email: EmailStr
    decklist_id: int | None = None
    decklist_main_count: int | None = None
    decklist_side_count: int | None = None
    decklist_errors: str = ""
    decklist_raw_text: str = ""
    payment_id: int | None = None
    payment_provider: str | None = None
    decklist_revision_count: int = 0


class TournamentControlsIn(BaseModel):
    pairings_public: bool | None = None
    standings_public: bool | None = None
    decklist_deadline: datetime | None = None
    self_check_in_enabled: bool | None = None
    late_registration_enabled: bool | None = None
    registration_mode: str | None = Field(default=None, pattern="^(open|closed)$")
    round_timer_minutes: int | None = Field(default=None, ge=1, le=120)
    refund_policy: str | None = None
    email_notifications_enabled: bool | None = None
    legal_validation_enabled: bool | None = None


class ManualPairingIn(BaseModel):
    table_number: int = Field(gt=0)
    player_a_registration_id: int
    player_b_registration_id: int | None = None


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    body: str = Field(min_length=2)
    send_email: bool = False


class AnnouncementOut(BaseModel):
    id: int
    tournament_id: int
    title: str
    body: str
    send_email: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PenaltyCreate(BaseModel):
    registration_id: int
    round_id: int | None = None
    kind: str = Field(default="warning", pattern="^(warning|game_loss|match_loss|disqualification|note)$")
    note: str = ""
    is_private: bool = True


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


class DecklistOut(BaseModel):
    id: int
    registration_id: int
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


class RoundOut(BaseModel):
    id: int
    tournament_id: int
    number: int
    phase: str
    is_published: bool
    starts_at: datetime | None
    ends_at: datetime | None
    pairings: list[PairingOut]


class PairingResultIn(BaseModel):
    match_wins_a: int = Field(ge=0, le=2)
    match_wins_b: int = Field(ge=0, le=2)
    draws: int = Field(default=0, ge=0, le=0)


class StandingOut(BaseModel):
    position: int
    registration_id: int
    name: str
    pod: int = 1
    points: int
    record: str
    match_win_percentage: float
    opponent_match_win_percentage: float
    game_win_percentage: float
    opponent_game_win_percentage: float
