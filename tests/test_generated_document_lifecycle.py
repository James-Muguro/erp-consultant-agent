"""Lifecycle contract tests for GeneratedDocument.

These tests exercise the real PostgreSQL schema and the real ORM model:

  * src/db/models.py               -- GeneratedDocument
  * src/tools/document_generator.py -- _persist_to_db (writer path)
  * src/orchestrator_api.py         -- current-row selection query

PostgreSQL is the production database, so these tests target PostgreSQL
only. They do NOT use SQLite, they do NOT mock the database, and they do
NOT define a replacement model.

Every test creates its own uniquely-prefixed session/document rows,
commits them, and cleans them up on teardown. Tests do not depend on each
other's execution order, on real user data, or on pre-existing rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Thread

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.db.base import SessionLocal, engine
from src.db.models import GeneratedDocument, SessionRecord, User

# ---------------------------------------------------------------------------
# Module-level guard: PostgreSQL only.
# ---------------------------------------------------------------------------
if engine.dialect.name != "postgresql":
    pytest.skip(
        "GeneratedDocument lifecycle tests target PostgreSQL only",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Test data prefix. Every row this module creates carries this prefix so
# cleanup can target only test data. Fresh per pytest session.
# ---------------------------------------------------------------------------
_TEST_PREFIX = f"test-gd-{uuid.uuid4().hex[:8]}"


def _mk_session(db, tag: str) -> str:
    """Create a User + SessionRecord pair and return the session_id."""
    user_id = f"{_TEST_PREFIX}-user-{tag}-{uuid.uuid4().hex[:8]}"
    session_id = f"{_TEST_PREFIX}-sess-{tag}-{uuid.uuid4().hex[:8]}"

    db.add(User(
        id=user_id,
        email=f"{user_id}@test.invalid",
        hashed_password="x",
    ))
    db.flush()

    db.add(SessionRecord(
        session_id=session_id,
        user_id=user_id,
        project_name="lifecycle-test",
        module="FI",
        erp_system="SAP S/4HANA",
        current_phase="requirements_gathering",
        data={},
    ))
    db.flush()
    return session_id


def _mk_doc(
    db,
    session_id: str,
    phase: str,
    label: str,
    *,
    is_current: bool,
    content: bytes = b"payload",
    filename: str | None = None,
) -> str:
    """Insert one GeneratedDocument row and return its id."""
    doc_id = f"{_TEST_PREFIX}-doc-{uuid.uuid4().hex}"
    db.add(GeneratedDocument(
        id=doc_id,
        session_id=session_id,
        phase=phase,
        label=label,
        is_current=is_current,
        filename=filename or f"{doc_id}.docx",
        content=content,
    ))
    db.flush()
    return doc_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _wipe_test_rows() -> None:
    """Delete every row this module could have created. Ordered to avoid
    FK violations (documents -> sessions -> users)."""
    s = SessionLocal()
    try:
        s.execute(
            text("DELETE FROM generated_documents WHERE session_id LIKE :p"),
            {"p": f"{_TEST_PREFIX}%"},
        )
        s.execute(
            text("DELETE FROM sessions WHERE session_id LIKE :p"),
            {"p": f"{_TEST_PREFIX}%"},
        )
        s.execute(
            text("DELETE FROM users WHERE id LIKE :p"),
            {"p": f"{_TEST_PREFIX}%"},
        )
        s.commit()
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _isolate_test_data():
    """Guarantee a clean slate before and after each test, regardless of
    whether the test committed or rolled back."""
    _wipe_test_rows()
    try:
        yield
    finally:
        _wipe_test_rows()


@pytest.fixture
def db():
    """Fresh ORM session for the test. Closed in teardown."""
    session = SessionLocal()
    try:
        yield session
    finally:
        try:
            session.rollback()
        except Exception:
            pass
        session.close()


# ---------------------------------------------------------------------------
# 1. Same logical document regeneration keeps history, leaves one current.
# ---------------------------------------------------------------------------
def test_regenerated_logical_document_keeps_history_and_one_current(db):
    session_id = _mk_session(db, "regen")
    phase, label = "qa_testing", "regenerated"

    # Generation 1.
    gen1_id = _mk_doc(
        db, session_id, phase, label, is_current=True, content=b"v1",
    )
    db.commit()
    gen1_created_at = db.get(GeneratedDocument, gen1_id).created_at

    # Generation 2: mirror the writer's transaction shape --
    # flip prior current to False, insert new current.
    db.query(GeneratedDocument).filter(
        GeneratedDocument.session_id == session_id,
        GeneratedDocument.phase == phase,
        GeneratedDocument.label == label,
        GeneratedDocument.is_current.is_(True),
    ).update(
        {"is_current": False, "updated_at": datetime.now(timezone.utc)},
        synchronize_session=False,
    )
    gen2_id = _mk_doc(
        db, session_id, phase, label, is_current=True, content=b"v2",
    )
    db.commit()

    # Assertions.
    rows = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == phase,
            GeneratedDocument.label == label,
        )
        .all()
    )
    assert len(rows) >= 2, "historical row must not be deleted"
    current = [r for r in rows if r.is_current]
    historical = [r for r in rows if not r.is_current]
    assert len(current) == 1, "exactly one current row"
    assert len(historical) >= 1, "at least one historical row"

    assert current[0].id == gen2_id, "newer generation is current"
    prior = db.get(GeneratedDocument, gen1_id)
    assert prior.is_current is False
    assert prior.created_at == gen1_created_at, "created_at must be preserved"
    assert prior.content == b"v1", "historical content must be preserved"


# ---------------------------------------------------------------------------
# 2. Distinct labels within one phase have independent current rows.
# ---------------------------------------------------------------------------
def test_distinct_labels_within_phase_have_independent_current_rows(db):
    session_id = _mk_session(db, "labels")

    a = _mk_doc(db, session_id, "qa_testing", "qa_report",
                is_current=True, content=b"r")
    b = _mk_doc(db, session_id, "qa_testing", "qa_traceability",
                is_current=True, content=b"t")
    db.commit()

    # Both identities have exactly one current row.
    for label, doc_id in (("qa_report", a), ("qa_traceability", b)):
        current = (
            db.query(GeneratedDocument)
            .filter(
                GeneratedDocument.session_id == session_id,
                GeneratedDocument.phase == "qa_testing",
                GeneratedDocument.label == label,
                GeneratedDocument.is_current.is_(True),
            )
            .all()
        )
        assert len(current) == 1
        assert current[0].id == doc_id

    # Regenerate qa_report; qa_traceability must be unaffected.
    db.query(GeneratedDocument).filter(
        GeneratedDocument.id == a,
    ).update({"is_current": False}, synchronize_session=False)
    _mk_doc(db, session_id, "qa_testing", "qa_report",
            is_current=True, content=b"r2")
    db.commit()

    trace = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == "qa_testing",
            GeneratedDocument.label == "qa_traceability",
            GeneratedDocument.is_current.is_(True),
        )
        .one()
    )
    assert trace.id == b, "unrelated label's current row must be unchanged"


# ---------------------------------------------------------------------------
# 3. Same phase+label are isolated by session.
# ---------------------------------------------------------------------------
def test_same_phase_and_label_are_isolated_by_session(db):
    sess_a = _mk_session(db, "iso-a")
    sess_b = _mk_session(db, "iso-b")

    a_id = _mk_doc(db, sess_a, "training", "user_manual_ap",
                   is_current=True, content=b"a")
    b_id = _mk_doc(db, sess_b, "training", "user_manual_ap",
                   is_current=True, content=b"b")
    db.commit()

    a_current = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == sess_a,
            GeneratedDocument.phase == "training",
            GeneratedDocument.label == "user_manual_ap",
            GeneratedDocument.is_current.is_(True),
        )
        .one()
    )
    assert a_current.id == a_id
    assert a_current.id != b_id

    # Regenerating in session A must not touch session B.
    db.query(GeneratedDocument).filter(
        GeneratedDocument.id == a_id,
    ).update({"is_current": False}, synchronize_session=False)
    _mk_doc(db, sess_a, "training", "user_manual_ap",
            is_current=True, content=b"a2")
    db.commit()

    b_still_current = db.get(GeneratedDocument, b_id)
    assert b_still_current.is_current is True
    assert b_still_current.session_id == sess_b


# ---------------------------------------------------------------------------
# 4. Current selection query returns the is_current row, and that row has
#    the newest updated_at for the logical identity.
#
#    This mirrors the exact predicate the download endpoint uses:
#        session_id + phase + label + is_current = True
#    It additionally proves the diagnostic ordering contract that the
#    selected current row is the one with the newest updated_at among the
#    rows of that logical identity. Timestamps are set explicitly so the
#    assertion does not depend on execution timing.
# ---------------------------------------------------------------------------
def test_current_selection_prefers_is_current_row(db):
    session_id = _mk_session(db, "selection")
    phase, label = "requirements_gathering", "requirements"

    # Explicit, deterministic, timezone-aware UTC timestamps. The stale
    # row is strictly older than the current row.
    older = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    newer = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert newer > older

    old_id = _mk_doc(db, session_id, phase, label,
                     is_current=False, content=b"old")
    new_id = _mk_doc(db, session_id, phase, label,
                     is_current=True, content=b"new")

    # Pin deterministic timestamps on both rows, bypassing the auto
    # default so ordering is not accidental.
    db.query(GeneratedDocument).filter(
        GeneratedDocument.id == old_id,
    ).update(
        {"created_at": older, "updated_at": older},
        synchronize_session=False,
    )
    db.query(GeneratedDocument).filter(
        GeneratedDocument.id == new_id,
    ).update(
        {"created_at": newer, "updated_at": newer},
        synchronize_session=False,
    )
    db.commit()
    db.expire_all()

    # The exact query the download endpoint uses: no ORDER BY, no
    # substitution of created_at or id for is_current.
    selected = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == phase,
            GeneratedDocument.label == label,
            GeneratedDocument.is_current.is_(True),
        )
        .limit(2)
        .all()
    )

    # 1. Exactly one current row is selected.
    assert len(selected) == 1
    row = selected[0]

    # 2. Selected row has is_current=True.
    assert row.is_current is True

    # 3. Selected row is the expected current generation.
    assert row.id == new_id

    # 4. Selected row has the newest updated_at for the identity.
    all_rows = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == phase,
            GeneratedDocument.label == label,
        )
        .all()
    )
    newest_updated_at = max(r.updated_at for r in all_rows)
    assert row.updated_at == newest_updated_at
    assert row.updated_at == newer

    # 5. Stale row is not selected.
    assert row.id != old_id


# ---------------------------------------------------------------------------
# 5. Stale row retains original content, filename, created_at.
# ---------------------------------------------------------------------------
def test_stale_row_retains_original_content_and_created_at(db):
    session_id = _mk_session(db, "stale")
    phase, label = "solution_design", "solution_design"

    old_id = _mk_doc(
        db, session_id, phase, label,
        is_current=True, content=b"original-bytes",
        filename="original.docx",
    )
    db.commit()
    old = db.get(GeneratedDocument, old_id)
    original_created_at = old.created_at
    original_filename = old.filename

    # Regenerate: flip prior, insert new current.
    db.query(GeneratedDocument).filter(
        GeneratedDocument.id == old_id,
    ).update(
        {"is_current": False, "updated_at": datetime.now(timezone.utc)},
        synchronize_session=False,
    )
    _mk_doc(db, session_id, phase, label,
            is_current=True, content=b"new-bytes",
            filename="new.docx")
    db.commit()

    db.expire_all()
    prior = db.get(GeneratedDocument, old_id)
    assert prior.is_current is False
    assert prior.content == b"original-bytes"
    assert prior.filename == original_filename
    assert prior.created_at == original_created_at


# ---------------------------------------------------------------------------
# 6. Concurrent regeneration -> at most one current row.
# ---------------------------------------------------------------------------
def test_concurrent_regeneration_allows_at_most_one_current_row():
    setup = SessionLocal()
    try:
        session_id = _mk_session(setup, "concurrent")
        setup.commit()
    finally:
        setup.close()

    phase, label = "qa_testing", "concurrent_identity"
    barrier = Barrier(2)
    results: dict[str, str] = {}

    def worker(tag: str) -> None:
        s = SessionLocal()
        try:
            doc = GeneratedDocument(
                id=f"{_TEST_PREFIX}-doc-{tag}-{uuid.uuid4().hex}",
                session_id=session_id,
                phase=phase,
                label=label,
                is_current=True,
                filename=f"{tag}.docx",
                content=b"x",
            )
            # Line both transactions up on the barrier so the INSERTs
            # race against the same partial unique index.
            barrier.wait(timeout=10)
            s.add(doc)
            s.commit()
            results[tag] = "committed"
        except IntegrityError:
            try:
                s.rollback()
            except Exception:
                pass
            results[tag] = "integrity_error"
        except Exception as e:  # noqa: BLE001
            try:
                s.rollback()
            except Exception:
                pass
            results[tag] = f"other:{type(e).__name__}"
        finally:
            s.close()

    threads = [
        Thread(target=worker, args=(f"t{i}",), daemon=True) for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    verify = SessionLocal()
    try:
        current_rows = (
            verify.query(GeneratedDocument)
            .filter(
                GeneratedDocument.session_id == session_id,
                GeneratedDocument.phase == phase,
                GeneratedDocument.label == label,
                GeneratedDocument.is_current.is_(True),
            )
            .all()
        )
    finally:
        verify.close()

    # Core invariant.
    assert len(current_rows) <= 1, (
        f"partial unique index failed to enforce at-most-one current row; "
        f"found {len(current_rows)}"
    )
    # At least one transaction must have succeeded.
    assert "committed" in results.values(), (
        f"expected at least one commit; worker outcomes: {results}"
    )
    # The conflicting transaction must have surfaced an IntegrityError --
    # not silently produced a duplicate current row.
    if len(current_rows) == 1:
        assert "integrity_error" in results.values() or sum(
            1 for v in results.values() if v == "committed"
        ) == 2, (
            "expected the losing transaction to raise IntegrityError; "
            f"worker outcomes: {results}"
        )


# ---------------------------------------------------------------------------
# 7. Different sessions may both hold a current row for same phase+label.
# ---------------------------------------------------------------------------
def test_different_sessions_allow_same_phase_and_label_as_current(db):
    a = _mk_session(db, "cross-a")
    b = _mk_session(db, "cross-b")

    _mk_doc(db, a, "training", "user_manual_shared",
            is_current=True, content=b"a")
    _mk_doc(db, b, "training", "user_manual_shared",
            is_current=True, content=b"b")
    # No IntegrityError expected.
    db.commit()

    count = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.phase == "training",
            GeneratedDocument.label == "user_manual_shared",
            GeneratedDocument.is_current.is_(True),
            GeneratedDocument.session_id.in_([a, b]),
        )
        .count()
    )
    assert count == 2


# ---------------------------------------------------------------------------
# 8. Multiple historical rows are exempt from the uniqueness check.
# ---------------------------------------------------------------------------
def test_historical_rows_are_exempt_from_current_uniqueness(db):
    session_id = _mk_session(db, "history")
    phase, label = "process_mapping", "process_x"

    for _ in range(5):
        _mk_doc(db, session_id, phase, label,
                is_current=False, content=b"h")
    # No IntegrityError expected.
    db.commit()

    count = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.phase == phase,
            GeneratedDocument.label == label,
            GeneratedDocument.is_current.is_(False),
        )
        .count()
    )
    assert count == 5


# ---------------------------------------------------------------------------
# 9. Partial unique index exists with the correct shape.
# ---------------------------------------------------------------------------
def test_current_partial_unique_index_exists():
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = ANY (current_schemas(false))
              AND tablename = 'generated_documents'
              AND indexname = 'ix_generated_documents_session_phase_label_current'
        """)).fetchone()

    assert row is not None, (
        "ix_generated_documents_session_phase_label_current is missing; "
        "the GeneratedDocument lifecycle migration has not been applied"
    )
    idx = row[0].lower()

    assert "unique" in idx
    assert "session_id" in idx
    assert "phase" in idx
    assert "label" in idx
    assert "is_current" in idx
    assert "where" in idx


# ---------------------------------------------------------------------------
# 10. Lifecycle columns exist and are NOT NULL.
# ---------------------------------------------------------------------------
def test_generated_document_lifecycle_columns_exist():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT column_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'generated_documents'
              AND column_name IN ('is_current', 'updated_at')
        """)).fetchall()

    by_name = {r[0]: r for r in rows}
    assert "is_current" in by_name, "is_current column missing"
    assert "updated_at" in by_name, "updated_at column missing"

    assert by_name["is_current"][1] == "NO", "is_current must be NOT NULL"
    assert by_name["updated_at"][1] == "NO", "updated_at must be NOT NULL"


# ---------------------------------------------------------------------------
# 11. Real writer path: _persist_to_db flips prior current and inserts new.
# ---------------------------------------------------------------------------
def test_persist_to_db_writes_current_row_and_flips_prior(tmp_path: Path):
    from src.tools.document_generator import doc_generator

    setup = SessionLocal()
    try:
        session_id = _mk_session(setup, "writer")
        setup.commit()
    finally:
        setup.close()

    payload_1 = tmp_path / "gen1.bin"
    payload_1.write_bytes(b"first generation")
    payload_2 = tmp_path / "gen2.bin"
    payload_2.write_bytes(b"second generation")

    phase, label = "requirements_gathering", "requirements"

    doc_generator._persist_to_db(session_id, phase, label, str(payload_1))
    doc_generator._persist_to_db(session_id, phase, label, str(payload_2))

    verify = SessionLocal()
    try:
        rows = (
            verify.query(GeneratedDocument)
            .filter(
                GeneratedDocument.session_id == session_id,
                GeneratedDocument.phase == phase,
                GeneratedDocument.label == label,
            )
            .all()
        )
    finally:
        verify.close()

    assert len(rows) == 2
    current = [r for r in rows if r.is_current]
    historical = [r for r in rows if not r.is_current]
    assert len(current) == 1, "writer must leave exactly one current row"
    assert len(historical) == 1
    assert current[0].content == b"second generation"
    assert historical[0].content == b"first generation"