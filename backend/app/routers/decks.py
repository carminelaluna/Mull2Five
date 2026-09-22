"""
Router liste — le liste salvate del giocatore, il controllo di una lista e la
ricerca carte per il costruttore.

Le regole e le carte vengono da services/decklists.py, un gioco alla volta: per
ora solo Magic. Per un gioco senza strumenti la ricerca risponde 501, il
controllo conta le carte senza giudicarle.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.limiter import limiter
from backend.app.db import get_db
from backend.app.games import GAMES, is_enabled
from backend.app.models import SavedDeck, User, now_utc
from backend.app.schemas import (
    CardLookupIn,
    CardOut,
    DeckValidateIn,
    DeckValidateOut,
    SavedDeckIn,
    SavedDeckOut,
)
from backend.app.security import get_current_user
from backend.app.services.decklists import (
    CARD_SOURCES,
    CardSource,
    validate_card_legality,
    validate_decklist,
)

router = APIRouter(tags=["decks"])

MAX_SAVED_DECKS = 200


def saved_deck_out(deck: SavedDeck) -> SavedDeckOut:
    validation = validate_decklist(deck.raw_text, deck.format, deck.game)
    return SavedDeckOut(
        id=deck.id, name=deck.name, game=deck.game, format=deck.format, archetype=deck.archetype,
        raw_text=deck.raw_text, main_count=validation.main_count, side_count=validation.side_count,
        errors=validation.errors if deck.raw_text.strip() else [], updated_at=deck.updated_at,
    )


def _own_deck(deck_id: int, user: User, db: Session) -> SavedDeck:
    deck = db.get(SavedDeck, deck_id)
    if not deck or deck.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    return deck


def _check_game(code: str) -> None:
    if code not in GAMES or not is_enabled(code):
        raise HTTPException(status_code=422, detail="Gioco non disponibile")


@router.get("/decks", response_model=list[SavedDeckOut])
def my_decks(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SavedDeckOut]:
    decks = db.scalars(
        select(SavedDeck).where(SavedDeck.owner_id == user.id)
        .order_by(SavedDeck.updated_at.desc(), SavedDeck.id.desc())
    ).all()
    return [saved_deck_out(deck) for deck in decks]


@router.post("/decks", response_model=SavedDeckOut, status_code=201)
def create_deck(
    payload: SavedDeckIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> SavedDeckOut:
    _check_game(payload.game)
    count = db.scalar(select(func.count(SavedDeck.id)).where(SavedDeck.owner_id == user.id)) or 0
    if count >= MAX_SAVED_DECKS:
        raise HTTPException(status_code=409, detail=f"Puoi salvare al massimo {MAX_SAVED_DECKS} liste.")
    deck = SavedDeck(owner_id=user.id, **payload.model_dump())
    db.add(deck)
    db.commit()
    db.refresh(deck)
    return saved_deck_out(deck)


@router.put("/decks/{deck_id}", response_model=SavedDeckOut)
def update_deck(
    deck_id: int, payload: SavedDeckIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> SavedDeckOut:
    deck = _own_deck(deck_id, user, db)
    _check_game(payload.game)
    for field, value in payload.model_dump().items():
        setattr(deck, field, value)
    deck.updated_at = now_utc()
    db.commit()
    db.refresh(deck)
    return saved_deck_out(deck)


@router.delete("/decks/{deck_id}", status_code=204)
def delete_deck(deck_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    db.delete(_own_deck(deck_id, user, db))
    db.commit()
    return Response(status_code=204)


@router.post("/decks/validate", response_model=DeckValidateOut)
@limiter.limit("60/minute")
def check_deck(request: Request, payload: DeckValidateIn, user: User = Depends(get_current_user)) -> DeckValidateOut:
    """Le regole del formato; con legality=true anche le carte bandite o non legali."""
    validation = validate_decklist(payload.raw_text, payload.format, payload.game)
    errors = validation.errors[:]
    if payload.legality and validation.main_count + validation.side_count:
        errors.extend(validate_card_legality(payload.raw_text, payload.format, payload.game))
    return DeckValidateOut(
        main_count=validation.main_count, side_count=validation.side_count,
        status="invalid" if errors else "valid", errors=errors,
    )


def _card_source(game: str) -> CardSource:
    source = CARD_SOURCES.get(game)
    if not source:
        raise HTTPException(status_code=501, detail="Ricerca carte non ancora disponibile per questo gioco")
    return source


@router.get("/cards/search")
@limiter.limit("120/minute")
def search_cards(
    request: Request,
    q: str = Query(default="", max_length=80),
    game: str = Query(default="mtg", max_length=20),
    user: User = Depends(get_current_user),
) -> dict[str, list[str]]:
    """I nomi di carta che iniziano (o quasi) con q, per l'autocompletamento."""
    source = _card_source(game)
    query = q.strip()
    if len(query) < 2:
        return {"names": []}
    try:
        return {"names": source.search(query)}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Ricerca carte non disponibile: riprova più tardi") from exc


@router.post("/cards/lookup", response_model=list[CardOut])
@limiter.limit("60/minute")
def lookup_cards(request: Request, payload: CardLookupIn, user: User = Depends(get_current_user)) -> list[dict]:
    """Costo, tipo e immagine delle carte di una lista: il costruttore le raggruppa per tipo."""
    source = _card_source(payload.game)
    names = [name.strip() for name in dict.fromkeys(payload.names) if name.strip()]
    if not names:
        return []
    try:
        return source.lookup(names)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Carte non disponibili: riprova più tardi") from exc
