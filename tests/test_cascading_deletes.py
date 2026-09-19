"""
Regression tests for cascading deletes.

A session's child rows must be removed by FK cascade when the session
is deleted. This is only meaningful if FK enforcement is actually
active — SQLite defaults to enforcement OFF, so the app's engine
configuration must explicitly enable it (see src/db/base.py).

Two things are tested:

  1. That FK enforcement is on (test_foreign_key_enforcement_is_active).
     A focused, diagnostic check for the SQLite PRAGMA. If this fails,
     every other test in this file will also fail — with a clearer
     error message here than from the cascade assertions.

  2. That deleting a session actually cascades to the tables whose
     rows reference it via session_id (test_deleting_session_cascades_*).
     Covers requirements, process steps, solution decisions, test
     cases, training steps, project issues, and trace links. Review
     actions are not covered here — they require a real User row (FK
     to users.id) and thus a heavier fixture than the rest of this file
     needs. A separate test with a user fixture would close that gap.

The cascade relies on each table declaring
ForeignKey("sessions.session_id", ondelete="CASCADE"). Tables without
that declaration rely on explicit cleanup in
DbSessionService.delete_session instead, which is a different mechanism
and is out of scope for this file.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from src.db.base import engine as db_engine
from src.memory import agent_memory
from src.services import project_intelligence


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def cascade_session():
    """Create a session, yield its id, and delete it on teardown.

    Deletion is attempted regardless of whether the test body already
    deleted the session — delete_session is idempotent (returns False
    on an already-deleted session), so a double-delete in teardown is
    safe. This guarantees cleanup even when an assertion fails mid-test."""
    session_id = agent_memory.create_project(
        project_name="Cascade Test",
        module="General",
    )
    try:
        yield session_id
    finally:
        try:
            agent_memory.session_service.delete_session(session_id)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# FK enforcement check
# ---------------------------------------------------------------------------
def test_foreign_key_enforcement_is_active():
    """If this fails on SQLite, cascading deletes silently leave
    orphaned rows behind — delete_session returns True but the child
    tables still contain rows pointing at the deleted session.

    Postgres and other server-side engines enforce FKs unconditionally
    by default, so the PRAGMA check is SQLite-specific. On other engines
    the test is skipped rather than failed, since there's nothing to
    configure."""
    if db_engine.dialect.name != "sqlite":
        pytest.skip(
            f"{db_engine.dialect.name} enforces foreign keys by default"
        )

    with db_engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()

    assert result == 1, (
        "PRAGMA foreign_keys is OFF for SQLite. Cascading deletes on "
        "delete_session are silently non-functional. See src/db/base.py — "
        "the engine needs an event listener that runs `PRAGMA foreign_keys=ON` "
        "for every new connection."
    )


# ---------------------------------------------------------------------------
# Cascade behavior
# ---------------------------------------------------------------------------
def test_deleting_session_cascades_to_project_intelligence_tables(cascade_session):
    """Create rows across every project_intelligence table that has a
    session_id FK with ON DELETE CASCADE, delete the session, and verify
    every one of those tables is now empty for that session.

    This is the core regression test. It would have caught the original
    Stage 0 bug where SQLite's default FK enforcement (OFF) silently
    allowed orphaned rows to persist after a session delete."""
    session_id = cascade_session

    # Populate every table that cascades via session_id.
    req_ids = project_intelligence.sync_requirements_from_structured(session_id, {
        "functional_requirements": {
            "Finance": [{"id": "REQ-001", "description": "Test req"}],
        },
    })
    step_ids = project_intelligence.sync_process_steps_from_structured(
        session_id,
        "Test Process",
        {"steps": [{"number": 1, "name": "Step 1"}]},
    )
    project_intelligence.sync_solution_decisions_from_structured(session_id, {
        "configurations": [{"component": "Test config"}],
    })
    project_intelligence.sync_test_cases_from_structured(session_id, "QA", [
        {"id": "TC-001", "scenario": "Test scenario"},
    ])
    project_intelligence.sync_training_steps_from_structured(session_id, {
        "user_manual": {"steps": [{"title": "Test step", "instructions": "Do it"}]},
    })
    project_intelligence.create_issue(session_id, "missing_info", "Test issue")

    # A trace link between two real objects. Using a real step ID (rather
    # than a fake one) is required by the current implementation of
    # add_trace_link, which validates that both endpoints belong to the
    # session.
    project_intelligence.add_trace_link(
        session_id, "process_step", step_ids[0], "requirement", req_ids[0],
    )

    # Sanity check: the rows we're about to lose exist now. Without this,
    # a bug that made the sync functions silently produce no rows would
    # make the post-delete assertions vacuously true.
    assert len(project_intelligence.get_requirements(session_id)) == 1
    assert len(project_intelligence.get_process_steps(session_id)) == 1
    assert len(project_intelligence.get_solution_decisions(session_id)) == 1
    assert len(project_intelligence.get_test_cases(session_id)) == 1
    assert len(project_intelligence.get_training_steps(session_id)) == 1
    assert len(project_intelligence.get_issues(session_id, status=None)) == 1

    deleted = agent_memory.session_service.delete_session(session_id)
    assert deleted is True

    # Every cascading table must be empty for the deleted session.
    assert project_intelligence.get_requirements(session_id) == []
    assert project_intelligence.get_process_steps(session_id) == []
    assert project_intelligence.get_solution_decisions(session_id) == []
    assert project_intelligence.get_test_cases(session_id) == []
    assert project_intelligence.get_training_steps(session_id) == []
    assert project_intelligence.get_issues(session_id, status=None) == []


def test_deleting_session_cascades_trace_links(cascade_session):
    """TraceLink has no public get_* accessor in project_intelligence,
    so this test queries the DB directly. TraceLink's only FK is
    session_id — source_id and target_id are plain strings — so the
    cascade is purely session-scoped."""
    from src.db.base import SessionLocal
    from src.db.models import TraceLink

    session_id = cascade_session

    req_ids = project_intelligence.sync_requirements_from_structured(session_id, {
        "functional_requirements": {
            "Finance": [{"id": "REQ-001", "description": "Test req"}],
        },
    })
    link_id = project_intelligence.add_trace_link(
        session_id, "requirement", req_ids[0], "requirement", req_ids[0],
        relationship="conflicts_with",
    )

    db = SessionLocal()
    try:
        assert db.query(TraceLink).filter(TraceLink.id == link_id).count() == 1
    finally:
        db.close()

    assert agent_memory.session_service.delete_session(session_id) is True

    db = SessionLocal()
    try:
        assert db.query(TraceLink).filter(TraceLink.session_id == session_id).count() == 0
    finally:
        db.close()


def test_delete_session_is_idempotent_and_returns_false_for_missing():
    """Deleting a session twice, or deleting an unknown session id,
    returns False rather than raising. Some callers (project teardown,
    account deletion) call delete_session without checking whether the
    session still exists first, so the idempotent behavior is
    load-bearing."""
    # A fresh session, deleted once.
    session_id = agent_memory.create_project(
        project_name="Idempotent Delete Test",
        module="General",
    )
    assert agent_memory.session_service.delete_session(session_id) is True
    assert agent_memory.session_service.delete_session(session_id) is False

    # A session that never existed.
    assert agent_memory.session_service.delete_session(
        f"does-not-exist-{uuid.uuid4().hex}"
    ) is False


def test_deleted_session_is_not_returned_by_get_session(cascade_session):
    """After deletion, get_session must return None — otherwise a caller
    holding a stale session_id could continue operating on a session
    whose child rows are gone."""
    session_id = cascade_session
    assert agent_memory.session_service.get_session(session_id) is not None

    agent_memory.session_service.delete_session(session_id)

    assert agent_memory.session_service.get_session(session_id) is None