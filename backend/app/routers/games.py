"""
Router giochi — l'elenco dei giochi supportati, per il frontend.

Formati, formato dei match e sistema di spareggi vivono in backend/app/games.py:
il frontend li legge da qui invece di tenerne una copia.
"""
from fastapi import APIRouter

from backend.app.games import games_catalog

router = APIRouter(prefix="/games", tags=["games"])


@router.get("")
def list_games() -> list[dict]:
    return games_catalog()
