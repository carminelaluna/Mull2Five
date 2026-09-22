"""
audit.py — Il registro delle modifiche di un torneo.

Chi ha cambiato cosa: correzioni di risultati, impostazioni toccate a torneo
iniziato, iscritti tolti perché non hanno pagato. Lo leggono i router e la
scheda "Registro" del back-office.
"""
from sqlalchemy.orm import Session

from backend.app.models import AuditLog


def write_audit(db: Session, tournament_id: int, editor_id: int, action: str, detail: str) -> None:
    db.add(AuditLog(tournament_id=tournament_id, editor_id=editor_id, action=action, detail=detail))
