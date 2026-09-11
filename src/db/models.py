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
"""
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean, Integer, LargeBinary, Float
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

class SessionRecord(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True)
    # Nullable for backward compatibility with sessions created before Stage 2
    # (auth) existed. Every session created from this point on always sets it.
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    project_name = Column(String, index=True, nullable=False)
    module = Column(String, nullable=False)
    erp_system = Column(String, nullable=False)
    current_phase = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc), index=True)
    # Soft delete: archived conversations are hidden from the default project
    # list but not destroyed. NULL = active. Set on DELETE /api/projects/{id}.
    archived_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # True for sessions auto-created from a plain question (no explicit
    # "start a project" intent) - lets the sidebar hide module/phase
    # metadata that was never meaningfully chosen for these. Sessions
    # created before this column existed default to False (real projects),
    # matching their actual origin at the time.
    is_casual = Column(Boolean, nullable=False, default=False, server_default="false")
    data = Column(_json_type()(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    profile_picture_url = Column(Text, nullable=True)
    hashed_password = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc))


class Feedback(Base):
    """User feedback on a single chat/phase interaction. Deliberately simple
    - a free-text comment plus an optional 1-5 rating - since there's no UI
    yet to drive anything richer (see Phase 4 in the roadmap)."""
    __tablename__ = "feedback"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=True, index=True)
    rating = Column(Integer, nullable=True)  # 1-5, optional
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc))

class GeneratedDocument(Base):
    """Durable storage for generated documents (requirements, process
    maps, solution designs, test cases, training materials, etc).
    Documents were previously written only to local disk
    (output/documents/), which is wiped on every Render redeploy or
    free-tier idle-restart - this table is the fix. The actual file
    bytes live here; local disk is now only a transient scratch space
    used during generation, never the source of truth for downloads."""
    __tablename__ = "generated_documents"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    phase = Column(String, nullable=False)
    label = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False,
                           default="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc))

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
    """
    __tablename__ = "project_memories"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
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
    created_at = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc), index=True)

import uuid as _uuid_intel


class RequirementItemRecord(Base):
    """Structured, identifiable requirement objects - the 'requirements
    intelligence' layer. Coexists with the existing JSON blob stored on
    SessionState/SessionRecord; this table is what makes requirements
    queryable, reviewable, and traceable instead of only living inside a
    generated document."""
    __tablename__ = "requirement_items"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    category = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(String, nullable=False, default="Medium")
    req_type = Column(String, nullable=False, default="Functional")
    acceptance_criteria = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="draft")  # draft, approved, rejected
    source_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))


class ProcessStepRecord(Base):
    """Structural representation of business process steps, linkable back
    to the requirement(s) they implement."""
    __tablename__ = "process_steps"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    process_name = Column(String, nullable=False)
    step_number = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    responsible_role = Column(String, nullable=True)
    requirement_id = Column(String, ForeignKey("requirement_items.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SolutionDecision(Base):
    """ERP/module/config/customization/integration decisions as
    structured objects with rationale, linkable to the requirement(s)
    that drove them."""
    __tablename__ = "solution_decisions"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    decision_type = Column(String, nullable=False)  # module_config, customization, integration, erp_selection
    component = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    requirement_id = Column(String, ForeignKey("requirement_items.id"), nullable=True, index=True)
    status = Column(String, nullable=False, default="proposed")  # proposed, approved, rejected
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class ProjectIssue(Base):
    """First-class exceptions: contradictions, missing info, coverage
    gaps, high-risk decisions - visible until a consultant resolves them,
    instead of being silently absorbed into an incomplete output."""
    __tablename__ = "project_issues"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    issue_type = Column(String, nullable=False)  # contradiction, missing_info, coverage_gap, high_risk_decision
    severity = Column(String, nullable=False, default="medium")  # low, medium, high
    description = Column(Text, nullable=False)
    related_object_type = Column(String, nullable=True)
    related_object_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="open")  # open, resolved, dismissed
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class ReviewAction(Base):
    """Consultant corrections, approvals, rejections, overrides -
    captured as structured, queryable knowledge instead of being lost in
    chat history or hand-edited documents."""
    __tablename__ = "review_actions"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    object_type = Column(String, nullable=False)  # requirement, solution_decision, process_step
    object_id = Column(String, nullable=False)
    action = Column(String, nullable=False)  # approved, rejected, corrected
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class TraceLink(Base):
    """Generic traceability edge between any two project objects (e.g. a
    QA test case covering a requirement). One flexible table instead of a
    bespoke join table per object-type pair - powers coverage analysis
    and gap detection later without a schema change."""
    __tablename__ = "trace_links"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    source_type = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    relationship = Column(String, nullable=False, default="covers")  # covers, derives_from, conflicts_with
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))