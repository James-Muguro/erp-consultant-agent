"""
Database engine and session factory.

Defaults to a local SQLite file (output/erp_agent.db) so the app runs with
zero external setup in development and CI. Set DATABASE_URL to a real
Postgres DSN (e.g. postgresql+psycopg2://user:pass@host:5432/dbname) in
production - no code changes required, SQLAlchemy handles both dialects
through the same engine/session interface.
"""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config.settings import settings

Base = declarative_base()

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    # Allow the same connection to be used across threads - the app already
    # guards writes with its own lock (see session_manager.py); SQLite's
    # default same-thread check would otherwise reject that.
    _connect_args = {"check_same_thread": False}
    # Ensure the directory for the sqlite file exists before connecting.
    db_path = settings.database_url.replace("sqlite:///", "", 1)
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create all tables that don't already exist. Safe to call on every
    startup - idempotent, and never drops or alters existing tables."""
    from src.db import models  # noqa: F401  (registers models on Base.metadata)
    Base.metadata.create_all(bind=engine)
