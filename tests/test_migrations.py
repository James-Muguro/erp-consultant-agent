"""
Migration cycle tests against a dedicated PostgreSQL database.

The dedicated database URL is read from MIGRATION_TEST_DATABASE_URL.
This is intentionally separate from the shared test DB used by the rest
of the suite, so `alembic downgrade base` cannot damage it.

If the env var is not set, the tests skip cleanly with an explanatory
message.

Requirements imposed on the environment:
  * MIGRATION_TEST_DATABASE_URL points at a PostgreSQL URL on the same
    server as DATABASE_URL (or a fresh empty DB is fine).
  * The database must be reachable and empty (or at least safe to
    downgrade to base).

Do NOT use this file against the shared test database.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

MIGRATION_ENV_VAR = "MIGRATION_TEST_DATABASE_URL"

REPO_ROOT = Path(__file__).resolve().parents[1]


def _url() -> str:
    return os.environ.get(MIGRATION_ENV_VAR, "").strip()


@pytest.fixture(scope="module")
def migration_url():
    url = _url()
    if not url:
        pytest.skip(
            f"{MIGRATION_ENV_VAR} is not set. Create a dedicated empty "
            "PostgreSQL database and export this variable to enable the "
            "migration cycle tests. The shared test database is "
            "deliberately not used."
        )
    if url == os.environ.get("DATABASE_URL", "").strip() and url:
        pytest.skip(
            f"{MIGRATION_ENV_VAR} matches DATABASE_URL. Refusing to run "
            "downgrade base against the shared database."
        )
    return url


def _alembic(args, url):
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    return subprocess.run(
        ["alembic", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


EXPECTED_TABLES = {
    "users", "sessions", "organizations", "organization_memberships",
    "user_roles", "generated_documents", "project_documents",
    "requirement_items", "process_steps", "solution_decisions",
    "test_case_records", "training_step_records", "project_issues",
    "review_actions", "trace_links", "attention_items",
    "erp_user_requests", "opportunities", "opportunity_requirements",
    "opportunity_documents", "opportunity_generated_documents",
    "firm_knowledge_entries", "session_user_artifact_grants",
    "session_stakeholder_submissions",
}


class TestMigrationCycle:
    def test_upgrade_head_and_verify_tables(self, migration_url):
        result = _alembic(["upgrade", "head"], migration_url)
        assert result.returncode == 0, (
            f"alembic upgrade head failed:\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

        engine = create_engine(migration_url)
        try:
            insp = inspect(engine)
            present = set(insp.get_table_names())
            missing = EXPECTED_TABLES - present
            assert not missing, f"missing tables after upgrade: {sorted(missing)}"
        finally:
            engine.dispose()

    def test_downgrade_base_clears_schema(self, migration_url):
        # Ensure we're at head first.
        up = _alembic(["upgrade", "head"], migration_url)
        assert up.returncode == 0, up.stderr

        result = _alembic(["downgrade", "base"], migration_url)
        assert result.returncode == 0, (
            f"alembic downgrade base failed:\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

        engine = create_engine(migration_url)
        try:
            insp = inspect(engine)
            remaining = set(insp.get_table_names()) - {"alembic_version"}
            assert not remaining, (
                f"tables survived downgrade base: {sorted(remaining)}"
            )
        finally:
            engine.dispose()