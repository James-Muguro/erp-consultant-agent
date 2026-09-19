"""
Database engine and session factory.

Defaults to a local SQLite file (output/erp_agent.db) so the app runs with
zero external setup in development and CI. Set DATABASE_URL to a real
Postgres DSN (e.g. postgresql+psycopg2://user:pass@host:5432/dbname) in
production - no code changes required, SQLAlchemy handles both dialects
through the same engine/session interface.

Notes on this revision:

  * Schema-drift detection for local SQLite. create_all() only creates
    missing tables; it never adds columns to existing ones. A developer
    whose local DB predates a model change would otherwise see opaque
    "no such column" errors from the first query that touches the new
    column. _check_sqlite_schema_drift() compares Base.metadata to the
    actual DB and logs a clear warning naming the missing columns and
    the remedy. The check is derived from the models, so it can't go
    stale as models gain or lose columns.

  * Startup diagnostic. One INFO line at import time describing the
    dialect, URL (password redacted), and pool sizing. Matches the
    boot-time logging pattern used elsewhere (see
    src/tools/knowledge/__init__.py, src/orchestrator_api.py).

  * Pool sizing for Postgres is explicit and settings-overridable.
    SQLAlchemy's default (pool_size=5, max_overflow=10 = 15 total
    connections) is tight for a multi-worker deployment running agent
    phases concurrently. SQLite ignores these because its pool model
    does not accept them.

  * expire_on_commit is documented rather than changed. SQLAlchemy's
    default is True, meaning ORM objects are expired after commit and
    attribute access reloads them from the DB. The codebase's pattern
    (return IDs, not ORM objects, from mutation functions) works with
    either setting; flipping it globally would be a silent behavior
    change across the app, so it stays at the default with a note.

  * The targeted SQLite ALTERs are wrapped in try/except so an odd
    local-DB state (locked file, corrupt table) cannot take boot down.
    The drift warning still fires, so the operator sees what happened.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

Base = declarative_base()


# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------
_is_sqlite = settings.database_url.startswith("sqlite")

_connect_args: dict = {}
if _is_sqlite:
    # Allow the same connection to be used across threads - the app
    # guards concurrent writes with its own lock (see session_manager.py);
    # SQLite's default same-thread check would otherwise reject that.
    _connect_args = {"check_same_thread": False}
    # Ensure the directory for the sqlite file exists before connecting.
    db_path = settings.database_url.replace("sqlite:///", "", 1)
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


_engine_kwargs: dict = {
    "connect_args": _connect_args,
    "future": True,
    # Recycle pooled connections to avoid "server closed the connection
    # unexpectedly" against Neon / serverless Postgres, which drop idle
    # connections. Checks liveness before handing out a pooled connection
    # instead of failing whichever request happens to get a dead one.
    "pool_pre_ping": True,
}

if not _is_sqlite:
    # Explicit pool sizing for Postgres and other server-class engines.
    # Overridable via settings for deployments with different concurrency
    # profiles. Defaults chosen for a small multi-worker deployment where
    # several agent phases can issue DB queries in parallel.
    _engine_kwargs["pool_size"] = int(getattr(settings, "db_pool_size", 10) or 10)
    _engine_kwargs["max_overflow"] = int(
        getattr(settings, "db_max_overflow", 20) or 20
    )
    # Recycle connections well before typical proxy/LB idle timeouts.
    _engine_kwargs["pool_recycle"] = int(
        getattr(settings, "db_pool_recycle_seconds", 1800) or 1800
    )

engine = create_engine(settings.database_url, **_engine_kwargs)

# expire_on_commit left at SQLAlchemy's default (True). See module
# docstring for the reasoning; changing it here would be a behavior
# change across every data-access path in the app.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


if engine.dialect.name == "sqlite":
    # SQLite ignores foreign keys unless explicitly told to enforce them -
    # without this, FK bugs like broken cascading deletes pass silently in
    # local/test runs and only surface in production against real Postgres.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ---------------------------------------------------------------------------
# Schema reconciliation and drift detection
# ---------------------------------------------------------------------------
def _check_sqlite_schema_drift() -> List[Tuple[str, List[str]]]:
    """Return a list of (table_name, missing_columns) for every model
    table that exists in the DB but is missing one or more columns
    declared on the model.

    Only meaningful for SQLite (the local dev / CI default), where
    create_all() can't add columns to existing tables. On Postgres,
    schema changes go through Alembic; a drift there is a deployment
    problem to catch in CI, not at boot.

    Derived from Base.metadata, so it stays in sync as models gain or
    lose columns. Read-only — it never modifies the DB."""
    if engine.dialect.name != "sqlite":
        return []

    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
    except Exception as e:  # noqa: BLE001 - inspecting a broken DB must not crash boot
        logger.warning("Could not inspect SQLite schema for drift: %s", e)
        return []

    drift: List[Tuple[str, List[str]]] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            # create_all() will create it fresh; no drift to report.
            continue
        try:
            existing_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not inspect table %s: %s", table_name, e)
            continue
        model_columns = {column.name for column in table.columns}
        missing = model_columns - existing_columns
        if missing:
            drift.append((table_name, sorted(missing)))

    return drift


def _apply_targeted_sqlite_column_fixes() -> None:
    """Additive ALTERs for the two historical columns that predate the
    general drift detector. Kept narrow on purpose — this is not a
    general-purpose migration tool (Alembic is). It exists so a
    developer's local DB survives the common profile-migration case
    without a manual delete.

    Wrapped in try/except: a locked or corrupt local DB must not take
    boot down. If the ALTERs can't run, the drift warning below will
    still fire."""
    try:
        inspector = inspect(engine)
        if "users" not in set(inspector.get_table_names()):
            return

        columns = {column["name"] for column in inspector.get_columns("users")}
        with engine.begin() as connection:
            if "name" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN name VARCHAR")
                )
            if "profile_picture_url" not in columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN profile_picture_url TEXT")
                )
    except Exception as e:  # noqa: BLE001
        logger.debug("Targeted SQLite column fixes skipped: %s", e)


def init_db() -> None:
    """Create missing tables and apply additive SQLite compatibility fixes.
    Safe to call on every startup; it never drops existing data.

    On SQLite, also detects schema drift between the models and an
    existing local database (columns declared on models but missing
    from the DB) and logs a clear warning with the exact remedy.
    create_all() cannot add columns to existing tables; without this
    warning, the first query touching a missing column fails with an
    opaque 'no such column' error."""
    from src.db import models  # noqa: F401  (registers models on Base.metadata)

    Base.metadata.create_all(bind=engine)

    if engine.dialect.name == "sqlite":
        _apply_targeted_sqlite_column_fixes()

        drift = _check_sqlite_schema_drift()
        if drift:
            # Build a readable one-line summary:
            # "table1 (col, col), table2 (col)"
            summary = "; ".join(
                f"{table}({', '.join(columns)})"
                for table, columns in drift
            )
            logger.warning(
                "Local SQLite database is missing columns declared on the "
                "models. Alembic migrations are the intended path on "
                "Postgres; for SQLite, either delete the local DB file "
                "(recommended for dev) or run the equivalent ALTER TABLE "
                "statements. Missing: %s",
                summary,
            )


# ---------------------------------------------------------------------------
# Startup diagnostic
# ---------------------------------------------------------------------------
def _log_engine_configuration() -> None:
    """One INFO line describing the effective engine configuration, so
    an operator can confirm what the process connected to without
    querying the DB. Matches the boot-time diagnostic pattern used
    elsewhere in the codebase."""
    try:
        url_safe = engine.url.render_as_string(hide_password=True)
        info: dict = {
            "dialect": engine.dialect.name,
            "url": url_safe,
        }
        pool = getattr(engine, "pool", None)
        if pool is not None and engine.dialect.name != "sqlite":
            info["pool_size"] = getattr(pool, "size", None)
            info["max_overflow"] = getattr(pool, "_max_overflow", None)
        logger.info("Database engine initialized: %s", info)
    except Exception as e:  # noqa: BLE001 - diagnostic must not break import
        logger.debug("Could not summarize engine configuration: %s", e)


_log_engine_configuration()