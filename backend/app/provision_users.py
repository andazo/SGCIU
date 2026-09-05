from __future__ import annotations

import os

from sqlalchemy import select

from app.auth import AuthService
from app.db import SessionLocal
from app.models import User

INITIAL_USERS = (
    ("policia.flores", "police", "AUTH_BOOTSTRAP_POLICE_PASSWORD"),
    ("administrativo.flores", "administrative", "AUTH_BOOTSTRAP_ADMINISTRATIVE_PASSWORD"),
)


def provision_users() -> list[str]:
    created: list[str] = []
    with SessionLocal() as db:
        service = AuthService(db)
        for username, role, password_variable in INITIAL_USERS:
            password = os.getenv(password_variable)
            if not password:
                raise RuntimeError(f"Falta el secreto {password_variable}.")
            existing = db.scalar(select(User).where(User.username == username))
            if existing is not None:
                if existing.role != role:
                    raise RuntimeError(f"El usuario {username} tiene un rol incompatible.")
                if not existing.is_active:
                    existing.is_active = True
                    db.commit()
                continue
            service.create_user(username, password, role)
            created.append(username)
    return created


if __name__ == "__main__":
    users = provision_users()
    print(f"Usuarios creados: {', '.join(users) if users else 'ninguno; ya existían'}")
