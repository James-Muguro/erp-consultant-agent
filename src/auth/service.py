"""
User account operations against the `users` table. Kept as plain functions
taking a SQLAlchemy Session rather than a class, matching the lightweight
style of the rest of the codebase (see src/tools/*.py).
"""
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from src.auth.security import hash_password, verify_password
from src.db.models import User


class EmailAlreadyRegistered(Exception):
    pass


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.get(User, user_id)


def create_user(db: Session, email: str, password: str) -> User:
    email = email.lower()
    if get_user_by_email(db, email):
        raise EmailAlreadyRegistered(f"{email} is already registered")

    user = User(
        id=uuid.uuid4().hex,
        email=email,
        hashed_password=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def update_profile(db: Session, user: User, name: Optional[str], profile_picture_url: Optional[str]) -> User:
    user.name = name.strip() if name else None
    user.profile_picture_url = profile_picture_url.strip() if profile_picture_url else None
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> bool:
    if not verify_password(current_password, user.hashed_password):
        return False
    user.hashed_password = hash_password(new_password)
    db.commit()
    return True
