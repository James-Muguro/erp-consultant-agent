"""
ORM models for the persistence layer.

SessionRecord stores each project session as a JSON blob (`data`) alongside
a handful of indexed columns pulled out for querying - this mirrors the
existing SessionState.to_dict()/from_dict() shape exactly, so the migration
from file-based JSON to a database is a storage-location change, not a
schema redesign. A full relational schema (normalized conversation turns,
phase outputs, etc.) is worth doing once the UI/API need to query into
those pieces directly - not needed yet.

User is a stub for Stage 2 (authentication/multi-tenancy). It is not
referenced by any code path yet - it exists so Stage 2 can add a foreign
key from sessions to users without an awkward later migration.

Session ownership and deletion semantics: every table whose rows have no
lifecycle independent of the owning session declares
ON DELETE CASCADE on its sessions.session_id foreign key. This is the
schema-level guarantee that deleting a session does not fail with a
ForeignKeyViolation because a child row still references it, and it means
application code does not have to know every child table by name. Tables
whose rows have independent lifecycle (users, feedback rows retained for
analytics/user attribution) preserve their current behavior.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from src.db.base import Base, engine


def _json_type():
    """Use native JSONB on Postgres, a portable JSON column everywhere else
    (SQLite/others) - avoids importing a Postgres-only type on a SQLite
    engine."""
    if engine.dialect.name == "postgresql":
        return JSONB
    return JSON


def _utcnow():
    return datetime.now(timezone.utc)


# ============================================================================
# Sessions and identity
# ============================================================================
class SessionRecord(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True)
    # Nullable for backward compatibility with sessions created before Stage 2
    # (auth) existed. Every session created from this point on always sets it.
    # ON DELETE SET NULL matches the database constraint established by
    # migration 9ec08dd1761d, so a user deletion nulls this reference
    # rather than blocking the delete.
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    project_name = Column(String, index=True, nullable=False)
    module = Column(String, nullable=False)
    erp_system = Column(String, nullable=False)
    current_phase = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow, index=True,
    )
    # Soft delete: archived conversations are hidden from the default project
    # list but not destroyed. NULL = active. Set on DELETE /api/projects/{id}.
    archived_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # True for sessions auto-created from a plain question (no explicit
    # "start a project" intent) - lets the sidebar hide module/phase
    # metadata that was never meaningfully chosen for these. Sessions
    # created before this column existed default to False (real projects),
    # matching their actual origin at the time.
    is_casual = Column(
        Boolean, nullable=False, default=False,
        server_default=text("false"),
    )
    data = Column(_json_type()(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    profile_picture_url = Column(Text, nullable=True)
    hashed_password = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Feedback(Base):
    """User feedback on a single chat/phase interaction. Deliberately simple
    - a free-text comment plus an optional 1-5 rating - since there's no UI
    yet to drive anything richer (see Phase 4 in the roadmap)."""
    __tablename__ = "feedback"

    id = Column(String, primary_key=True)
    # ON DELETE SET NULL + nullable matches migration 9ec08dd1761d: a user
    # deletion nulls this reference rather than blocking the delete.
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    rating = Column(Integer, nullable=True)  # 1-5, optional
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


# ============================================================================
# Documents
# ============================================================================
class GeneratedDocument(Base):
    """Durable storage for generated documents (requirements, process
    maps, solution designs, test cases, training materials, etc).
    Documents were previously written only to local disk
    (output/documents/), which is wiped on every Render redeploy or
    free-tier idle-restart - this table is the fix. The actual file
    bytes live here; local disk is now only a transient scratch space
    used during generation, never the source of truth for downloads.

    Regeneration lifecycle: the platform's overarching principle is
    history-over-overwrite (see SolutionBaseline), so a regenerated
    document does not delete the prior row - the prior row has
    is_current flipped to False and remains queryable as history.
    `is_current` is therefore the single authoritative selector for the
    artifact a user should receive: download logic MUST filter on
    is_current = True for the given (session_id, phase, label). The
    composite index ix_generated_documents_session_phase_label backs
    that lookup. `updated_at` exists so a same-second regeneration has
    a deterministic ordering key if a full history is ever displayed.

    Logical artifact identity is (session_id, phase, label). This is
    derived from the existing callers, not invented here: `phase` is
    the document-type/phase identifier and `label` carries the
    instance (e.g. a process name for process-mapping phase, or the
    phase constant itself for singleton documents).

    The invariant "at most one current row per logical identity" is
    enforced at the database level by a partial unique index over
    (session_id, phase, label) WHERE is_current. Historical rows
    (is_current=False) are exempt, so a regenerated document coexists
    with its predecessors. The writer still flips the prior row's
    is_current to False before inserting the new current row (so the
    common sequential case succeeds without a conflict), and the
    database constraint is what guarantees safety when two concurrent
    regenerations race - one transaction will raise IntegrityError,
    which the writer must surface as a real persistence failure rather
    than swallow.

    Physical artifact cleanup (deleting bytes on disk for a row that
    has been superseded) is NOT this model's responsibility - see the
    storage layer. This model only tracks metadata and content bytes.
    """
    __tablename__ = "generated_documents"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    phase = Column(String, nullable=False)
    label = Column(String, nullable=False)
    # The authoritative artifact for a logical document. At most one
    # row per (session_id, phase, label) may have is_current=true;
    # the partial unique index below enforces this at the database
    # level. Regeneration flips the prior row to False and inserts a
    # new True row in the same transaction. server_default is provided
    # so the migration backfilling pre-existing rows is trivial.
    is_current = Column(
        Boolean, nullable=False, default=True,
        server_default=text("true"), index=True,
    )
    filename = Column(String, nullable=False)
    content_type = Column(
        String, nullable=False,
        default="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    # Set on every write. Populated for pre-existing rows by the
    # migration from created_at. Provides a deterministic tie-breaker
    # for same-second regenerations and a stable ordering key if the
    # full version history is ever rendered.
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        # Backs the "select the current artifact for this logical
        # document" query: WHERE session_id=? AND phase=? AND label=?
        # (AND is_current=true). The single-column session_id index
        # above remains for cross-phase scans.
        Index(
            "ix_generated_documents_session_phase_label",
            "session_id", "phase", "label",
        ),
        # Database-enforced invariant: at most one CURRENT row per
        # logical document identity (session_id, phase, label).
        # Historical rows (is_current=False) are exempt from the
        # constraint, so a regenerated document coexists with its
        # predecessors. This is what makes concurrent regenerations
        # safe: if two transactions both try to insert/keep a current
        # row for the same identity, one succeeds and the other raises
        # IntegrityError, which the writer must surface as a real
        # persistence failure rather than swallow.
        Index(
            "ix_generated_documents_session_phase_label_current",
            "session_id", "phase", "label",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class ProjectDocument(Base):
    """Metadata for a consultant-uploaded project document (distinct from
    GeneratedDocument above, which is AI-generated deliverables). The
    actual file bytes live in object storage (see
    src/storage/object_storage.py), not here and not on local disk -
    Render's disk is ephemeral, so this table only stores a pointer
    (storage_key) plus enough metadata to list, download, and delete the
    file. extracted_text_chars records how much text was pulled out and
    fed into project_memories (see src/tools/document_extractor.py) - 0
    means extraction found nothing usable (e.g. a scanned/image-only PDF),
    which the API surfaces so the consultant knows the upload succeeded
    but isn't yet searchable content.

    Session ownership: rows have no lifecycle independent of the owning
    session, so the sessions.session_id FK declares ON DELETE CASCADE.
    Deleting the DB row does not remove the object from external storage;
    that separation remains the responsibility of the storage layer.
    """
    __tablename__ = "project_documents"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # ON DELETE SET NULL + nullable matches migration 9ec08dd1761d: a user
    # deletion nulls this reference rather than blocking the delete.
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    filename = Column(String, nullable=False)
    storage_key = Column(String, nullable=False, unique=True)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    extracted_text_chars = Column(Integer, nullable=False, default=0)
    uploaded_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True,
    )


# ============================================================================
# Project memory
# ============================================================================
class ProjectMemory(Base):
    """Per-project agent knowledge: seeded templates, patterns the agents
    generate as they work, lessons learned at project completion, and
    (soon) extracted text from uploaded documents.

    Strictly scoped to session_id - this replaces the old global,
    file-based MemoryBank (src/memory/memory_bank.py), which had every
    project's "learned" content shared across ALL users and projects. That
    was fine for a single-tenant hackathon demo but is a real cross-tenant
    data leak once there's more than one user: one user's project details
    could surface in another user's agent-generated output. Every query
    against this table must filter by session_id - there is no
    cross-project read path, by design.

    Session ownership: rows have no lifecycle independent of the owning
    session, so the sessions.session_id FK declares ON DELETE CASCADE.
    Before this was set, PostgreSQL rejected the parent session delete
    with ForeignKeyViolation on project_memories_session_id_fkey, since
    the child rows still referenced the session at delete time.
    """
    __tablename__ = "project_memories"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    category = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    entry_metadata = Column(_json_type()(), nullable=True)
    # Stored as JSON (not a native array type) so this works identically on
    # SQLite (dev) and Postgres (prod) - consistent with the rest of this
    # file's approach to cross-dialect columns.
    tags = Column(_json_type()(), nullable=True)
    importance = Column(Float, nullable=False, default=1.0)
    access_count = Column(Integer, nullable=False, default=0)
    last_accessed = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


# ============================================================================
# Project intelligence - structured objects
# ============================================================================
class RequirementItemRecord(Base):
    """Structured, identifiable requirement objects - the 'requirements
    intelligence' layer. Coexists with the existing JSON blob stored on
    SessionState/SessionRecord; this table is what makes requirements
    queryable, reviewable, and traceable instead of only living inside a
    generated document.

    external_code holds the canonical model-reported ID (e.g. 'REQ-001'),
    which is what link_requirements() / resolve_requirement_codes() match
    on. Rationale and source are captured from the requirements schema's
    change-control fields; they were previously dropped by the sync layer.
    Non-functional requirements are stored under category='Non-functional'
    rather than a separate table - they share every other field shape.
    """
    __tablename__ = "requirement_items"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    lineage_id = Column(String, nullable=False, index=True)  # stable across all versions of "the same" requirement
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    category = Column(String, nullable=False)
    external_code = Column(String, nullable=True, index=True)  # model-assigned ID e.g. "REQ-001", for LLM-referenceable linking
    description = Column(Text, nullable=False)
    priority = Column(String, nullable=False, default="Medium")
    req_type = Column(String, nullable=False, default="Functional")
    acceptance_criteria = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="draft")  # draft, approved, rejected
    # Change-control fields. rationale explains why the requirement exists
    # (needed when scope is renegotiated); source names its origin
    # (stakeholder, regulation, existing-system limitation). Both optional -
    # a missing value is preferable to a fabricated one.
    rationale = Column(Text, nullable=True)
    source = Column(Text, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        # Two requirements in the same session must not share a model-facing
        # code - otherwise resolve_requirement_codes() picks an arbitrary
        # match and traceability becomes ambiguous. The ID normalizer in the
        # requirements schema is permissive (accepts REQ1, REQ_001, req-001
        # and normalizes them), so duplicates can theoretically arise from
        # sloppy model output; this constraint turns that into a loud insert
        # failure rather than a silent traceability bug.
        UniqueConstraint("session_id", "external_code",
                         name="uq_requirement_session_external_code"),
        # Database-enforced invariant: at most one CURRENT version per
        # lineage. Historical versions (is_current=False) are exempt and
        # may accumulate without limit. Established by migration
        # 8b69bcaa614c. The single-column lineage_id index from the
        # column declaration above remains for history lookups.
        Index(
            "ix_requirement_items_lineage_current",
            "lineage_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class ProcessStepRecord(Base):
    """Structural representation of business process steps, linkable back
    to the requirement(s) they implement.

    requirement_id (singular) is legacy: the domain is many-to-many and the
    canonical storage of step→requirement links is TraceLink (see
    project_intelligence.link_requirements). The column is retained for
    backward compatibility with any reader that expects it, but new code
    should use TraceLink.

    external_code carries the ProcessStep.id (STEP-NNN) so a re-sync can
    correlate with prior rows. Without it, every sync produced a fresh
    lineage with no external handle.
    """
    __tablename__ = "process_steps"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    lineage_id = Column(String, nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    process_name = Column(String, nullable=False)
    step_number = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    responsible_role = Column(String, nullable=True)
    # Extended step metadata from the process_map_schema. All optional - the
    # model is instructed to leave empty rather than invent when unknown.
    trigger = Column(Text, nullable=True)
    inputs = Column(_json_type()(), nullable=True)          # list[str]
    outputs = Column(_json_type()(), nullable=True)         # list[str]
    transaction = Column(String, nullable=True)
    exception_paths = Column(_json_type()(), nullable=True) # list[str]
    external_code = Column(String, nullable=True, index=True)
    requirement_id = Column(
        String, ForeignKey("requirement_items.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_process_steps_session_process", "session_id", "process_name"),
        # Same rationale as requirements: external_code must be unique per
        # session so resolve_process_step_external_code() resolves to a
        # single row.
        UniqueConstraint("session_id", "external_code",
                         name="uq_process_step_session_external_code"),
        # Database-enforced invariant: at most one CURRENT version per
        # lineage. Historical versions (is_current=False) are exempt.
        # Established by migration 598aff673b1b. The single-column
        # lineage_id index from the column declaration above remains
        # for history lookups.
        Index(
            "ix_process_steps_lineage_current",
            "lineage_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class SolutionDecision(Base):
    """ERP/module/config/customization/integration decisions as
    structured objects with rationale, linkable to the requirement(s)
    that drove them.

    requirement_id (singular) is legacy, as with ProcessStepRecord: the
    many-to-many mapping lives in TraceLink.

    classification (STANDARD / CONFIGURATION / EXTENSION) is populated for
    configuration decisions and lets downstream analysis count how many
    decisions actually are standard-first. complexity and lifecycle_impact
    are populated for customizations - the fields a steering committee
    actually asks about.
    """
    __tablename__ = "solution_decisions"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    lineage_id = Column(String, nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    stage = Column(String, nullable=False, default="proposed")  # proposed | actual - the platform's core distinction
    decision_type = Column(String, nullable=False)  # module_config, customization, integration, erp_selection
    component = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    # Standard-first ladder classification for configurations; NULL for
    # customizations (customizations ARE the bottom rung, self-evidently).
    classification = Column(String, nullable=True)
    # Customization governance fields.
    complexity = Column(String, nullable=True)          # Low | Medium | High
    lifecycle_impact = Column(Text, nullable=True)
    external_code = Column(String, nullable=True, index=True)
    requirement_id = Column(
        String, ForeignKey("requirement_items.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    status = Column(String, nullable=False, default="proposed")  # proposed, approved, rejected
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_solution_decisions_session_type", "session_id", "decision_type"),
        # Database-enforced invariant: at most one CURRENT version per
        # lineage. Historical versions (is_current=False) are exempt.
        # Established by migration 8b69bcaa614c. The single-column
        # lineage_id index from the column declaration above remains
        # for history lookups.
        Index(
            "ix_solution_decisions_lineage_current",
            "lineage_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class TestCaseRecord(Base):
    """Structured QA/UAT test cases, linkable to the requirements they
    validate.

    user_role, business_process, and acceptance_criteria are UAT-specific
    and populated only for UAT test cases; QA cases leave them NULL. These
    fields are what enable role-coverage and process-linkage reporting in
    the UAT agent's validator - without them, the agent's coverage signals
    have nothing to read.

    related_design_component is a free-form label linking a test back to a
    configuration, integration, or customization entry in the solution
    design. Distinct from the TraceLink-based requirement links, which use
    real foreign keys.

    DEFINED BEFORE ProjectIssue so its ForeignKey can be resolved at
    metadata-construction time. See module docstring.
    """
    __tablename__ = "test_case_records"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    test_type = Column(String, nullable=False)  # QA or UAT
    external_code = Column(String, nullable=True)  # e.g. "TC-001" or "TC-A1B2C3"
    scenario = Column(String, nullable=False)
    priority = Column(String, nullable=False, default="Medium")
    expected_result = Column(Text, nullable=True)
    # UAT-specific context. See class docstring.
    user_role = Column(String, nullable=True)
    business_process = Column(String, nullable=True)
    acceptance_criteria = Column(Text, nullable=True)
    related_design_component = Column(String, nullable=True)
    needs_retest = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        UniqueConstraint("session_id", "external_code",
                         name="uq_test_case_session_external_code"),
    )


class TrainingStepRecord(Base):
    """Structured training manual steps, linkable to the requirements they
    cover.

    role, verification, and prerequisites come from the training schema's
    per-step fields. Together with title and instructions they're what
    make a step usable: preconditions tell the user what must be in place,
    instructions tell them what to do, verification tells them how they
    know it worked. Previously only title/instructions were persisted, so
    the rest was silently lost.
    """
    __tablename__ = "training_step_records"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    external_code = Column(String, nullable=True, index=True)  # TSTEP-NNN
    title = Column(String, nullable=False)
    instructions = Column(Text, nullable=True)
    role = Column(String, nullable=True)
    verification = Column(Text, nullable=True)
    prerequisites = Column(_json_type()(), nullable=True)  # list[str]
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        UniqueConstraint("session_id", "external_code",
                         name="uq_training_step_session_external_code"),
    )


# ============================================================================
# Issues, reviews, traceability
# ============================================================================
class ProjectIssue(Base):
    """First-class exceptions: contradictions, missing info, coverage
    gaps, high-risk decisions - visible until a consultant resolves them,
    instead of being silently absorbed into an incomplete output.

    Also carries open_questions filed by the agent sync layer (issue_type
    'open_question'), so gaps surfaced by the agents have a landing spot.

    test_case_id references test_case_records - TestCaseRecord is declared
    above for FK resolution. See module docstring.
    """
    __tablename__ = "project_issues"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    issue_type = Column(String, nullable=False)
    # contradiction, missing_info, coverage_gap, high_risk_decision,
    # test_failure, requirement_changed, open_question
    severity = Column(String, nullable=False, default="medium")  # low, medium, high
    description = Column(Text, nullable=False)
    related_object_type = Column(String, nullable=True)
    related_object_id = Column(String, nullable=True)
    test_case_id = Column(
        String, ForeignKey("test_case_records.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    classification = Column(String, nullable=True)  # defect, unclear_requirement, changed_requirement, data_issue, integration_issue, environment_issue, other
    status = Column(String, nullable=False, default="open")  # open, resolved, dismissed
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_project_issues_session_status", "session_id", "status"),
        Index("ix_project_issues_session_type", "session_id", "issue_type"),
    )


class ReviewAction(Base):
    """Consultant corrections, approvals, rejections, overrides -
    captured as structured, queryable knowledge instead of being lost in
    chat history or hand-edited documents."""
    __tablename__ = "review_actions"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # ON DELETE SET NULL + nullable matches migration 9ec08dd1761d: a user
    # deletion nulls this reference rather than blocking the delete.
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    object_type = Column(String, nullable=False)  # requirement, solution_decision, process_step
    object_id = Column(String, nullable=False)
    action = Column(String, nullable=False)  # approved, rejected, corrected
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_review_actions_object", "object_type", "object_id"),
    )


class TraceLink(Base):
    """Generic traceability edge between any two project objects (e.g. a
    QA test case covering a requirement). One flexible table instead of a
    bespoke join table per object-type pair - powers coverage analysis
    and gap detection later without a schema change.

    Composite indexes on (target_type, target_id) and (source_type,
    source_id) are what keep coverage queries fast. Every call to
    get_coverage_gaps and get_project_health filters on target_type =
    'requirement' joined to target_id; without these, the query is a
    full scan.
    """
    __tablename__ = "trace_links"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_type = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    relationship = Column(String, nullable=False, default="covers")  # covers, derives_from, conflicts_with
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_trace_links_target", "target_type", "target_id"),
        Index("ix_trace_links_source", "source_type", "source_id"),
        Index("ix_trace_links_session_relationship", "session_id", "relationship"),
        # Prevent duplicate identical edges - project_intelligence can be
        # retried after a partial failure, and without this constraint a
        # retry would silently double a link and inflate coverage counts.
        UniqueConstraint(
            "session_id", "source_type", "source_id",
            "target_type", "target_id", "relationship",
            name="uq_trace_link_edge",
        ),
    )


# ============================================================================
# Baselines
# ============================================================================
class SolutionBaseline(Base):
    """A named, point-in-time snapshot of 'the solution actually delivered'
    - the brief's critical 'final validated solution' concept. Creating a
    new baseline never deletes an old one (is_active flips the prior one
    off) - full baseline history stays queryable, matching the platform's
    history-over-overwrite principle."""
    __tablename__ = "solution_baselines"

    id = Column(String, primary_key=True)
    session_id = Column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    label = Column(String, nullable=False)  # e.g. "Go-Live Baseline", "UAT Baseline"
    notes = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class SolutionBaselineItem(Base):
    """One (decision lineage -> specific version) pin within a baseline -
    the actual snapshot content."""
    __tablename__ = "solution_baseline_items"

    id = Column(String, primary_key=True)
    baseline_id = Column(
        String, ForeignKey("solution_baselines.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    solution_decision_id = Column(
        String, ForeignKey("solution_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )