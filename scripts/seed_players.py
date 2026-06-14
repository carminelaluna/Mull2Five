from backend.app.db import SessionLocal, create_all
from backend.app.models import User, UserRole
from backend.app.security import hash_password


def player_name(index: int) -> str:
    letters = []
    for power in (26**3, 26**2, 26, 1):
        value, index = divmod(index, power)
        letters.append(chr(ord("A") + value))
    return "".join(letters)


def main() -> None:
    create_all()
    password_hash = hash_password("test")
    created = 0
    skipped = 0

    with SessionLocal() as db:
        existing = {email for (email,) in db.query(User.email).all()}
        for index in range(1024):
            name = player_name(index)
            email = f"{name.lower()}@test.it"
            if email in existing:
                skipped += 1
                continue
            db.add(
                User(
                    email=email,
                    display_name=name,
                    role=UserRole.PLAYER,
                    password_hash=password_hash,
                )
            )
            created += 1
        db.commit()

    print(f"Seed completato: {created} creati, {skipped} gia presenti.")


if __name__ == "__main__":
    main()
