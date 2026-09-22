"""Unified regression suite for the history-over-overwrite versioning
contract across every structured project-intelligence entity that
declares lineage_id / version / is_current:

  * RequirementItemRecord
  * ProcessStepRecord
  * SolutionDecision

PostgreSQL is required. The module skips cleanly on any other dialect.

Nothing here mocks SessionLocal, SQLAlchemy queries, db.commit, the
partial unique indexes, or the synchronizers. Every assertion is against
a row PostgreSQL actually wrote.

The synchronizers own their own SessionLocal()-managed transaction via
_db_session(). The test adapter methods accept a `db` argument so test
call sites do not need to change, but they do not forward `db` to the
real service — the service creates and commits its own session. Fixtures
that create User and SessionRecord rows therefore must commit before the
service runs; a flush() is not visible to the service's separate
transaction.
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from src.db.base import engine
from src.db.models import (
    ProcessStepRecord,
    RequirementItemRecord,
    SessionRecord,
    SolutionDecision,
    TraceLink,
    User,
)
from src.services import project_intelligence as pi


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
def _resolve_session_local():
    for mod_name in ("src.db.base", "src.db.session", "src.db.database", "src.db"):
        try:
            mod = __import__(mod_name, fromlist=["SessionLocal"])
        except Exception:
            continue
        factory = getattr(mod, "SessionLocal", None)
        if factory is not None:
            return factory
    return sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False,
    )


SessionLocal = _resolve_session_local()

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Unified versioning regression suite requires PostgreSQL.",
)

PREFIX = "univer-test"


def _new_id(label: str) -> str:
    return f"{PREFIX}-{label}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def cleanup_registry():
    sessions_created: list[str] = []
    users_created: list[str] = []
    yield sessions_created, users_created

    s = SessionLocal()
    try:
        if sessions_created:
            s.query(TraceLink).filter(
                TraceLink.session_id.in_(sessions_created)
            ).delete(synchronize_session=False)
            s.query(RequirementItemRecord).filter(
                RequirementItemRecord.session_id.in_(sessions_created)
            ).delete(synchronize_session=False)
            s.query(ProcessStepRecord).filter(
                ProcessStepRecord.session_id.in_(sessions_created)
            ).delete(synchronize_session=False)
            s.query(SolutionDecision).filter(
                SolutionDecision.session_id.in_(sessions_created)
            ).delete(synchronize_session=False)
            s.query(SessionRecord).filter(
                SessionRecord.session_id.in_(sessions_created)
            ).delete(synchronize_session=False)
        if users_created:
            s.query(User).filter(
                User.id.in_(users_created)
            ).delete(synchronize_session=False)
        s.commit()
    finally:
        s.close()


@pytest.fixture
def db(cleanup_registry):
    s = SessionLocal()
    try:
        yield s
    finally:
        try:
            s.rollback()
        finally:
            s.close()


@pytest.fixture
def make_user(db, cleanup_registry):
    _, users_created = cleanup_registry

    def _make() -> str:
        uid = _new_id("user")
        db.add(User(id=uid, email=f"{uid}@example.test", hashed_password="x"))
        # The synchronizers open their own session; a flush() would be
        # invisible to it. Commit so the service's session sees this row.
        db.commit()
        users_created.append(uid)
        return uid

    return _make


@pytest.fixture
def make_session(db, cleanup_registry, make_user):
    sessions_created, _ = cleanup_registry

    def _make(user_id: str | None = None) -> str:
        if user_id is None:
            user_id = make_user()
        sid = _new_id("session")
        db.add(SessionRecord(
            session_id=sid,
            user_id=user_id,
            project_name="verification",
            module="Finance",
            erp_system="Dynamics",
            current_phase="requirements",
            data={},
        ))
        # Commit so the FK from RequirementItemRecord / ProcessStepRecord /
        # SolutionDecision to sessions.session_id resolves in the
        # synchronizer's own transaction.
        db.commit()
        sessions_created.append(sid)
        return sid

    return _make


# ---------------------------------------------------------------------------
# Entity specs (uniform shape over three entities)
# ---------------------------------------------------------------------------
class RequirementSpec:
    model = RequirementItemRecord
    bucket_key = "functional_requirements"

    @staticmethod
    def build_row(session_id, external_code, description, *, lineage_id, version,
                  is_current, extra=None):
        return RequirementItemRecord(
            id=_new_id("row"),
            session_id=session_id,
            lineage_id=lineage_id,
            version=version,
            is_current=is_current,
            category="Functional",
            external_code=external_code,
            description=description,
            priority="Medium",
            req_type="Functional",
            status="draft",
            **(extra or {}),
        )

    @staticmethod
    def payload(external_code, description, **kw):
        return {
            "id": external_code,
            "external_code": external_code,
            "code": external_code,
            "description": description,
            "priority": kw.get("priority", "Medium"),
            "type": kw.get("req_type", "Functional"),
            "req_type": kw.get("req_type", "Functional"),
            "acceptance_criteria": kw.get("acceptance_criteria"),
            "rationale": kw.get("rationale"),
            "source": kw.get("source"),
        }

    @staticmethod
    def structured(*payloads, bucket=None):
        bucket = bucket or RequirementSpec.bucket_key
        return {
            "functional_requirements": [],
            "non_functional_requirements": [],
            "technical_requirements": [],
            "integration_requirements": [],
            "reporting_requirements": [],
            bucket: list(payloads),
        }

    @staticmethod
    def sync(db, session_id, structured):
        # The real service owns its own SessionLocal()-managed transaction
        # via _db_session(). The `db` argument is accepted so test call
        # sites do not need to change, but is intentionally not forwarded.
        return pi.sync_requirements_from_structured(session_id, structured)


class ProcessStepSpec:
    model = ProcessStepRecord

    @staticmethod
    def build_row(session_id, external_code, description, *, lineage_id, version,
                  is_current, extra=None):
        return ProcessStepRecord(
            id=_new_id("row"),
            session_id=session_id,
            lineage_id=lineage_id,
            version=version,
            is_current=is_current,
            process_name="Order to Cash",
            step_number=1,
            name="Create Sales Order",
            description=description,
            external_code=external_code,
            **(extra or {}),
        )

    @staticmethod
    def payload(external_code, description, **kw):
        return {
            "id": external_code,
            "external_code": external_code,
            "step_number": kw.get("step_number", 1),
            "name": kw.get("name", "Create Sales Order"),
            "description": description,
            "process_name": kw.get("process_name", "Order to Cash"),
        }

    @staticmethod
    def structured(*payloads):
        # The real service reads structured_process["steps"]. Nothing else.
        return {"steps": list(payloads)}

    @staticmethod
    def sync(db, session_id, structured):
        # The real service owns its own SessionLocal()-managed transaction.
        # `process_name` is a required positional on the real signature;
        # it is derived from the first step payload, which the spec's
        # payload() helper always populates. Falls back to the fixture
        # default only when the caller supplied no steps.
        steps = structured.get("steps", []) or []
        process_name = "Order to Cash"
        if steps and isinstance(steps[0], dict):
            process_name = steps[0].get("process_name") or process_name
        return pi.sync_process_steps_from_structured(
            session_id, process_name, structured,
        )


class SolutionDecisionSpec:
    model = SolutionDecision

    @staticmethod
    def build_row(session_id, external_code, description, *, lineage_id, version,
                  is_current, extra=None):
        return SolutionDecision(
            id=_new_id("row"),
            session_id=session_id,
            lineage_id=lineage_id,
            version=version,
            is_current=is_current,
            stage="proposed",
            decision_type="module_config",
            description=description,
            external_code=external_code,
            status="proposed",
            **(extra or {}),
        )

    @staticmethod
    def payload(external_code, description, **kw):
        return {
            "id": external_code,
            "external_code": external_code,
            "decision_type": kw.get("decision_type", "module_config"),
            "description": description,
            "rationale": kw.get("rationale"),
            "stage": kw.get("stage", "proposed"),
            "status": kw.get("status", "proposed"),
        }

    @staticmethod
    def structured(*payloads):
        # The real service reads structured_design["configurations"] and,
        # for other real branches, ["customizations"] and ["integrations"].
        # Generic versioning tests exercise the configurations branch only.
        return {"configurations": list(payloads)}

    @staticmethod
    def sync(db, session_id, structured):
        # The real service owns its own SessionLocal()-managed transaction.
        return pi.sync_solution_decisions_from_structured(session_id, structured)


ALL_SPECS = [RequirementSpec, ProcessStepSpec, SolutionDecisionSpec]


def _rows(db, spec, session_id, external_code):
    return (
        db.query(spec.model)
        .filter(
            spec.model.session_id == session_id,
            spec.model.external_code == external_code,
        )
        .order_by(spec.model.version.asc())
        .all()
    )


def _current_rows(db, spec, session_id, external_code):
    return (
        db.query(spec.model)
        .filter(
            spec.model.session_id == session_id,
            spec.model.external_code == external_code,
            spec.model.is_current.is_(True),
        )
        .all()
    )


# ===========================================================================
# Service-level tests (parametrized per entity)
# ===========================================================================

@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_first_insert_creates_version_1(db, make_session, spec):
    sid = make_session()
    code = _new_id("code")
    spec.sync(db, sid, spec.structured(spec.payload(code, "Original content")))
    db.commit()

    rows = _rows(db, spec, sid, code)
    assert len(rows) == 1
    r = rows[0]
    assert r.external_code == code
    assert r.version == 1
    assert r.is_current is True
    assert r.lineage_id, "lineage_id must be populated on first insert"
    assert r.description == "Original content"


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_regeneration_creates_version_2_and_preserves_v1(db, make_session, spec):
    sid = make_session()
    code = _new_id("code")
    spec.sync(db, sid, spec.structured(spec.payload(code, "Original content")))
    db.commit()

    v1_before = _rows(db, spec, sid, code)[0]
    v1_id = v1_before.id
    v1_lineage = v1_before.lineage_id
    v1_created = v1_before.created_at

    spec.sync(db, sid, spec.structured(spec.payload(code, "Updated content")))
    db.commit()

    rows = _rows(db, spec, sid, code)
    assert len(rows) == 2
    v1, v2 = rows[0], rows[1]

    # Historical preservation
    assert v1.id == v1_id
    assert v1.version == 1
    assert v1.is_current is False
    assert v1.external_code == code
    assert v1.lineage_id == v1_lineage
    assert v1.created_at == v1_created
    assert v1.description == "Original content"

    # New current
    assert v2.id != v1.id
    assert v2.version == 2
    assert v2.is_current is True
    assert v2.external_code == code
    assert v2.lineage_id == v1.lineage_id
    assert v2.description == "Updated content"


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_second_regeneration_creates_version_3(db, make_session, spec):
    sid = make_session()
    code = _new_id("code")
    for desc in ("Original content", "Updated content", "Third revision"):
        spec.sync(db, sid, spec.structured(spec.payload(code, desc)))
        db.commit()

    rows = _rows(db, spec, sid, code)
    assert [r.version for r in rows] == [1, 2, 3]
    assert {r.lineage_id for r in rows} == {rows[0].lineage_id}
    assert {r.external_code for r in rows} == {code}
    assert [r.is_current for r in rows] == [False, False, True]
    assert rows[0].description == "Original content"
    assert rows[1].description == "Updated content"
    assert rows[2].description == "Third revision"
    assert len(_current_rows(db, spec, sid, code)) == 1


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_lineage_id_remains_stable_across_versions(db, make_session, spec):
    sid = make_session()
    code = _new_id("code")
    for desc in ("v1", "v2", "v3"):
        spec.sync(db, sid, spec.structured(spec.payload(code, desc)))
        db.commit()
    lineages = {r.lineage_id for r in _rows(db, spec, sid, code)}
    assert len(lineages) == 1
    assert next(iter(lineages))


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_external_code_remains_stable_across_versions(db, make_session, spec):
    sid = make_session()
    code = _new_id("code")
    for desc in ("v1", "v2", "v3"):
        spec.sync(db, sid, spec.structured(spec.payload(code, desc)))
        db.commit()
    codes = {r.external_code for r in _rows(db, spec, sid, code)}
    assert codes == {code}


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_exactly_one_current_row_after_each_regeneration(db, make_session, spec):
    sid = make_session()
    code = _new_id("code")
    for desc in ("v1", "v2", "v3"):
        spec.sync(db, sid, spec.structured(spec.payload(code, desc)))
        db.commit()
        assert len(_current_rows(db, spec, sid, code)) == 1
    historical = [r for r in _rows(db, spec, sid, code) if not r.is_current]
    assert all(r.is_current is False for r in historical)
    assert len(historical) == 2


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_different_sessions_remain_isolated(db, make_session, spec):
    sid_a = make_session()
    sid_b = make_session()
    code = _new_id("code")

    spec.sync(db, sid_a, spec.structured(spec.payload(code, "A original")))
    spec.sync(db, sid_b, spec.structured(spec.payload(code, "B original")))
    db.commit()

    b_before = _rows(db, spec, sid_b, code)[0]
    b_id, b_lineage, b_created = b_before.id, b_before.lineage_id, b_before.created_at

    spec.sync(db, sid_a, spec.structured(spec.payload(code, "A updated")))
    db.commit()

    a_rows = _rows(db, spec, sid_a, code)
    assert [r.version for r in a_rows] == [1, 2]
    assert [r.is_current for r in a_rows] == [False, True]

    b_after = _rows(db, spec, sid_b, code)[0]
    assert b_after.id == b_id
    assert b_after.lineage_id == b_lineage
    assert b_after.created_at == b_created
    assert b_after.version == 1
    assert b_after.is_current is True
    assert b_after.description == "B original"
    assert a_rows[0].lineage_id != b_after.lineage_id


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_distinct_external_codes_create_independent_lineages(db, make_session, spec):
    sid = make_session()
    c1 = _new_id("code-A")
    c2 = _new_id("code-B")
    spec.sync(db, sid, spec.structured(
        spec.payload(c1, "First"),
        spec.payload(c2, "Second"),
    ))
    db.commit()

    r1 = _rows(db, spec, sid, c1)
    r2 = _rows(db, spec, sid, c2)
    assert len(r1) == 1 and len(r2) == 1
    assert r1[0].version == 1 and r2[0].version == 1
    assert r1[0].is_current is True and r2[0].is_current is True
    assert r1[0].lineage_id != r2[0].lineage_id


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_historical_duplicates_are_legal(db, make_session, spec):
    sid = make_session()
    code = _new_id("code")
    spec.sync(db, sid, spec.structured(spec.payload(code, "v1")))
    db.commit()
    # If a full-table unique constraint on external_code survived, this
    # regeneration would raise IntegrityError at commit.
    spec.sync(db, sid, spec.structured(spec.payload(code, "v2")))
    db.commit()
    rows = _rows(db, spec, sid, code)
    assert len(rows) == 2
    assert rows[0].external_code == rows[1].external_code == code


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_version_numbers_do_not_reset(db, make_session, spec):
    """Next version = max(existing version) + 1, never row count + 1."""
    sid = make_session()
    code = _new_id("code")
    for desc in ("v1", "v2", "v3"):
        spec.sync(db, sid, spec.structured(spec.payload(code, desc)))
        db.commit()
    existing = [r.version for r in _rows(db, spec, sid, code)]
    assert existing == [1, 2, 3]
    expected_next = max(existing) + 1

    spec.sync(db, sid, spec.structured(spec.payload(code, "v4")))
    db.commit()

    rows = _rows(db, spec, sid, code)
    assert [r.version for r in rows] == [1, 2, 3, expected_next]
    assert rows[-1].version == 4
    assert rows[-1].is_current is True
    assert rows[-1].description == "v4"
    assert len(_current_rows(db, spec, sid, code)) == 1


# ---------------------------------------------------------------------------
# Requirement buckets: same versioning contract across every bucket
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bucket", [
    "functional_requirements",
    "non_functional_requirements",
    "technical_requirements",
    "integration_requirements",
    "reporting_requirements",
])
def test_all_requirement_buckets_use_same_versioning_contract(db, make_session, bucket):
    sid = make_session()
    code = _new_id("code")
    RequirementSpec.sync(
        db, sid, RequirementSpec.structured(
            RequirementSpec.payload(code, "First"),
            bucket=bucket,
        )
    )
    db.commit()
    RequirementSpec.sync(
        db, sid, RequirementSpec.structured(
            RequirementSpec.payload(code, "Second"),
            bucket=bucket,
        )
    )
    db.commit()

    rows = _rows(db, RequirementSpec, sid, code)
    assert len(rows) == 2
    assert rows[0].version == 1 and rows[1].version == 2
    assert rows[0].is_current is False and rows[1].is_current is True
    assert rows[0].lineage_id == rows[1].lineage_id
    assert rows[0].external_code == rows[1].external_code == code
    assert len(_current_rows(db, RequirementSpec, sid, code)) == 1


# ---------------------------------------------------------------------------
# Process step isolation: distinct step identities must not collapse
# ---------------------------------------------------------------------------
def test_process_steps_distinct_identities_do_not_collapse(db, make_session):
    sid = make_session()
    c1 = _new_id("step-A")
    c2 = _new_id("step-B")
    ProcessStepSpec.sync(db, sid, ProcessStepSpec.structured(
        ProcessStepSpec.payload(c1, "Step A", step_number=1),
        ProcessStepSpec.payload(c2, "Step B", step_number=2),
    ))
    db.commit()
    a = _rows(db, ProcessStepSpec, sid, c1)
    b = _rows(db, ProcessStepSpec, sid, c2)
    assert len(a) == 1 and len(b) == 1
    assert a[0].lineage_id != b[0].lineage_id
    assert a[0].external_code == c1
    assert b[0].external_code == c2


# ---------------------------------------------------------------------------
# Solution decision isolation: distinct decisions must not collapse
# ---------------------------------------------------------------------------
def test_solution_decisions_distinct_identities_do_not_collapse(db, make_session):
    sid = make_session()
    c1 = _new_id("dec-A")
    c2 = _new_id("dec-B")
    SolutionDecisionSpec.sync(db, sid, SolutionDecisionSpec.structured(
        SolutionDecisionSpec.payload(c1, "Decision A", decision_type="module_config"),
        SolutionDecisionSpec.payload(c2, "Decision B", decision_type="integration"),
    ))
    db.commit()
    a = _rows(db, SolutionDecisionSpec, sid, c1)
    b = _rows(db, SolutionDecisionSpec, sid, c2)
    assert len(a) == 1 and len(b) == 1
    assert a[0].lineage_id != b[0].lineage_id


# ===========================================================================
# Cross-entity tests
# ===========================================================================
def test_requirement_regeneration_does_not_affect_process_step(db, make_session):
    sid = make_session()
    req_code = _new_id("req")
    step_code = _new_id("step")

    RequirementSpec.sync(db, sid, RequirementSpec.structured(
        RequirementSpec.payload(req_code, "Original req"),
    ))
    ProcessStepSpec.sync(db, sid, ProcessStepSpec.structured(
        ProcessStepSpec.payload(step_code, "Step stays"),
    ))
    db.commit()

    step_before = _rows(db, ProcessStepSpec, sid, step_code)[0]
    step_id = step_before.id
    step_lineage = step_before.lineage_id

    RequirementSpec.sync(db, sid, RequirementSpec.structured(
        RequirementSpec.payload(req_code, "Updated req"),
    ))
    db.commit()

    step_after = _rows(db, ProcessStepSpec, sid, step_code)[0]
    assert step_after.id == step_id
    assert step_after.lineage_id == step_lineage
    assert step_after.version == 1
    assert step_after.is_current is True
    assert step_after.description == "Step stays"


def test_tracelink_to_historical_requirement_version_remains_valid(db, make_session):
    """TraceLink points at a physical row id. When a requirement is
    regenerated, the historical row must remain addressable by its
    original physical id, so existing trace links are not orphaned."""
    sid = make_session()
    code = _new_id("req")

    RequirementSpec.sync(db, sid, RequirementSpec.structured(
        RequirementSpec.payload(code, "Original req"),
    ))
    db.commit()
    v1 = _rows(db, RequirementSpec, sid, code)[0]
    v1_id = v1.id

    # Simulate a design component trace link pointing at the physical v1 row.
    tl_id = _new_id("tl")
    db.add(TraceLink(
        id=tl_id,
        session_id=sid,
        source_type="solution_decision",
        source_id=_new_id("dec"),
        target_type="requirement",
        target_id=v1_id,
        relationship="covers",
    ))
    db.commit()

    RequirementSpec.sync(db, sid, RequirementSpec.structured(
        RequirementSpec.payload(code, "Updated req"),
    ))
    db.commit()

    # Historical row is still queryable by its original id.
    historical = (
        db.query(RequirementItemRecord)
        .filter(RequirementItemRecord.id == v1_id)
        .one()
    )
    assert historical.version == 1
    assert historical.is_current is False

    # Trace link still resolves.
    link = db.query(TraceLink).filter(TraceLink.id == tl_id).one()
    assert link.target_id == v1_id


# ===========================================================================
# Schema-level tests
# ===========================================================================
@pytest.mark.parametrize("spec, old_constraint", [
    (RequirementSpec, "uq_requirement_session_external_code"),
    (ProcessStepSpec, "uq_process_step_session_external_code"),
    (SolutionDecisionSpec, None),  # no prior full constraint existed
], ids=lambda x: getattr(x, "__name__", str(x)))
def test_partial_unique_current_index_exists(db, spec, old_constraint):
    table = spec.model.__tablename__
    index_name = f"ix_{table}_session_external_code_current"
    with engine.connect() as conn:
        row = conn.execute(text(
            """
            SELECT indexdef FROM pg_indexes
            WHERE tablename = :t AND indexname = :i
            """
        ), {"t": table, "i": index_name}).fetchone()
    assert row is not None, f"missing partial unique index {index_name} on {table}"
    ddl = row[0].lower()
    assert "unique" in ddl
    assert "session_id" in ddl
    assert "external_code" in ddl
    assert "is_current" in ddl


def test_old_full_constraint_uq_requirement_is_gone(db):
    with engine.connect() as conn:
        row = conn.execute(text(
            """
            SELECT conname FROM pg_constraint
            WHERE conname = 'uq_requirement_session_external_code'
              AND conrelid = 'requirement_items'::regclass
            """
        )).fetchone()
    assert row is None


def test_old_full_constraint_uq_process_step_is_gone(db):
    with engine.connect() as conn:
        row = conn.execute(text(
            """
            SELECT conname FROM pg_constraint
            WHERE conname = 'uq_process_step_session_external_code'
              AND conrelid = 'process_steps'::regclass
            """
        )).fetchone()
    assert row is None


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_database_rejects_two_current_rows(db, make_session, spec):
    """Direct-insert schema test: the partial unique index refuses a
    second is_current=True row for the same (session_id, external_code)."""
    sid = make_session()
    code = _new_id("dup")
    db.add(spec.build_row(
        sid, code, "first current",
        lineage_id=_new_id("lin"), version=1, is_current=True,
    ))
    db.commit()

    db.add(spec.build_row(
        sid, code, "second current (must be rejected)",
        lineage_id=_new_id("lin"), version=2, is_current=True,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    current = _current_rows(db, spec, sid, code)
    assert len(current) == 1
    assert current[0].version == 1


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_database_permits_historical_duplicates(db, make_session, spec):
    """One historical (is_current=False) and one current row for the same
    identity both persist. This is the database-level proof that history
    coexists with the current marker."""
    sid = make_session()
    code = _new_id("hist")
    db.add(spec.build_row(
        sid, code, "historical",
        lineage_id=_new_id("lin"), version=1, is_current=False,
    ))
    db.add(spec.build_row(
        sid, code, "current",
        lineage_id=_new_id("lin"), version=2, is_current=True,
    ))
    db.commit()

    rows = _rows(db, spec, sid, code)
    assert len(rows) == 2
    assert [r.version for r in rows] == [1, 2]
    assert rows[0].is_current is False and rows[1].is_current is True


# ===========================================================================
# Concurrency tests
# ===========================================================================
@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.model.__name__)
def test_concurrent_regeneration_leaves_at_most_one_current(db, make_session, spec):
    sid = make_session()
    code = _new_id("race")
    spec.sync(db, sid, spec.structured(spec.payload(code, "baseline")))
    db.commit()
    assert len(_current_rows(db, spec, sid, code)) == 1

    barrier = threading.Barrier(2, timeout=15)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker(desc: str) -> None:
        # The synchronizer owns its own SessionLocal()-managed transaction.
        # The worker's `local` session is retained only for the outer
        # commit/rollback calls, which are no-ops with respect to the
        # synchronizer's internal session. The race is between the two
        # synchronizer transactions, not between these outer sessions.
        local = SessionLocal()
        try:
            barrier.wait()
            try:
                spec.sync(local, sid, spec.structured(spec.payload(code, desc)))
                local.commit()
                outcome = {"status": "ok", "desc": desc}
            except (IntegrityError, DBAPIError) as exc:
                local.rollback()
                outcome = {"status": "integrity_error", "exc_type": type(exc).__name__}
            except Exception as exc:
                local.rollback()
                outcome = {"status": "other_error", "exc_type": type(exc).__name__}
        finally:
            local.close()
        with results_lock:
            results.append(outcome)

    t1 = threading.Thread(target=worker, args=("concurrent-A",), daemon=True)
    t2 = threading.Thread(target=worker, args=("concurrent-B",), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert not t1.is_alive(), "worker A did not finish"
    assert not t2.is_alive(), "worker B did not finish"

    check = SessionLocal()
    try:
        current = (
            check.query(spec.model)
            .filter(
                spec.model.session_id == sid,
                spec.model.external_code == code,
                spec.model.is_current.is_(True),
            )
            .all()
        )
    finally:
        check.close()

    assert len(current) <= 1
    statuses = sorted(r["status"] for r in results)
    assert "ok" in statuses
    assert all(s in {"ok", "integrity_error"} for s in statuses), results
    if statuses == ["ok", "ok"]:
        assert len(current) == 1


# ===========================================================================
# Rollback / atomicity tests
# ===========================================================================
@pytest.mark.parametrize("spec, poison_setter", [
    (RequirementSpec, lambda p: p.update(description=None)),
    (ProcessStepSpec, lambda p: p.update(name=None)),
    (SolutionDecisionSpec, lambda p: p.update(description=None)),
], ids=lambda x: getattr(x, "__name__", str(x)))
def test_failed_regeneration_rolls_back(db, make_session, spec, poison_setter):
    """A regeneration whose persistence step fails must leave the prior
    current row intact: same id, version, content, created_at, is_current.

    The synchronizer owns its own SessionLocal()-managed transaction via
    _db_session(). It commits on success and rolls back on failure before
    re-raising. The fixture's `db.rollback()` below only clears any
    snapshot the test's own session is holding; it does not and cannot
    undo the service's transaction, which has already been resolved by
    the time the exception reaches this frame.
    """
    sid = make_session()
    code = _new_id("poison")
    spec.sync(db, sid, spec.structured(spec.payload(code, "original content")))
    db.commit()

    v1_before = _rows(db, spec, sid, code)[0]
    v1_id, v1_lineage, v1_created = v1_before.id, v1_before.lineage_id, v1_before.created_at

    poison = spec.payload(code, "should not persist")
    poison_setter(poison)

    with pytest.raises(Exception):
        spec.sync(db, sid, spec.structured(poison))
        db.commit()

    db.rollback()

    rows = _rows(db, spec, sid, code)
    assert len(rows) == 1
    r = rows[0]
    assert r.id == v1_id
    assert r.lineage_id == v1_lineage
    assert r.created_at == v1_created
    assert r.version == 1
    assert r.is_current is True
    assert r.description == "original content"
    assert len(_current_rows(db, spec, sid, code)) == 1