"""reconcile production schema with ORM model

Revision ID: 7392e627e855
Revises: e13448a863b3
Create Date: 2026-09-21 16:09:55.166735

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7392e627e855'
down_revision: Union[str, Sequence[str], None] = 'e13448a863b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Duplicate-data validators. Each raises before its corresponding unique
# constraint is created so failures are explicit and pre-emptive rather
# than opaque PostgreSQL duplicate-key errors. None of them mutate data.
# ---------------------------------------------------------------------------
def _raise_if_duplicate_requirement_external_code() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM requirement_items
                WHERE external_code IS NOT NULL
                GROUP BY session_id, external_code
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'duplicate requirement external_code';
            END IF;
        END $$;
    """)


def _raise_if_duplicate_test_case_external_code() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM test_case_records
                WHERE external_code IS NOT NULL
                GROUP BY session_id, external_code
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'duplicate test case external_code';
            END IF;
        END $$;
    """)


def _raise_if_duplicate_trace_link_edge() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM trace_links
                GROUP BY session_id, source_type, source_id,
                         target_type, target_id, relationship
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'duplicate trace link edge';
            END IF;
        END $$;
    """)


def upgrade() -> None:
    """Upgrade schema."""

    # ------------------------------------------------------------------
    # 1. GeneratedDocument: add the single-column is_current index.
    #    The composite identity index and the partial unique current-row
    #    index were already created by migration e13448a863b3 and are
    #    left untouched.
    # ------------------------------------------------------------------
    op.create_index(
        "ix_generated_documents_is_current",
        "generated_documents",
        ["is_current"],
    )

    # ------------------------------------------------------------------
    # 2. process_steps: add extended step metadata + external_code.
    #    existing rows receive NULL for the new nullable columns, so the
    #    new unique constraint cannot conflict with legacy data.
    # ------------------------------------------------------------------
    op.add_column("process_steps", sa.Column("trigger", sa.Text(), nullable=True))
    op.add_column(
        "process_steps",
        sa.Column("inputs", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "process_steps",
        sa.Column("outputs", postgresql.JSONB(), nullable=True),
    )
    op.add_column("process_steps", sa.Column("transaction", sa.String(), nullable=True))
    op.add_column(
        "process_steps",
        sa.Column("exception_paths", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "process_steps",
        sa.Column("external_code", sa.String(), nullable=True),
    )

    op.create_index(
        "ix_process_steps_external_code",
        "process_steps",
        ["external_code"],
    )
    op.create_index(
        "ix_process_steps_lineage_id",
        "process_steps",
        ["lineage_id"],
    )
    op.create_index(
        "ix_process_steps_session_process",
        "process_steps",
        ["session_id", "process_name"],
    )
    op.create_unique_constraint(
        "uq_process_step_session_external_code",
        "process_steps",
        ["session_id", "external_code"],
    )

    # ------------------------------------------------------------------
    # 3. project_issues: add updated_at (backfill from created_at), then
    #    the two session-scoped indexes.
    # ------------------------------------------------------------------
    op.add_column(
        "project_issues",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE project_issues "
        "SET updated_at = created_at "
        "WHERE updated_at IS NULL"
    )
    op.alter_column(
        "project_issues",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_index(
        "ix_project_issues_session_status",
        "project_issues",
        ["session_id", "status"],
    )
    op.create_index(
        "ix_project_issues_session_type",
        "project_issues",
        ["session_id", "issue_type"],
    )

    # ------------------------------------------------------------------
    # 4. project_memories:
    #    a. Align session_id FK with the ORM contract by dropping the
    #       existing FK and recreating it with ON DELETE CASCADE,
    #       preserving the existing constraint name.
    #    b. Convert JSON -> JSONB, preserving values.
    # ------------------------------------------------------------------
    op.drop_constraint(
        "project_memories_session_id_fkey",
        "project_memories",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "project_memories_session_id_fkey",
        "project_memories",
        "sessions",
        ["session_id"],
        ["session_id"],
        ondelete="CASCADE",
    )

    op.execute(
        "ALTER TABLE project_memories "
        "ALTER COLUMN entry_metadata TYPE jsonb "
        "USING entry_metadata::jsonb"
    )
    op.execute(
        "ALTER TABLE project_memories "
        "ALTER COLUMN tags TYPE jsonb "
        "USING tags::jsonb"
    )

    # ------------------------------------------------------------------
    # 5. requirement_items: add source, lineage_id index, and validate
    #    legacy external_code uniqueness before creating the constraint.
    # ------------------------------------------------------------------
    op.add_column(
        "requirement_items",
        sa.Column("source", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_requirement_items_lineage_id",
        "requirement_items",
        ["lineage_id"],
    )
    _raise_if_duplicate_requirement_external_code()
    op.create_unique_constraint(
        "uq_requirement_session_external_code",
        "requirement_items",
        ["session_id", "external_code"],
    )

    # ------------------------------------------------------------------
    # 6. review_actions: object index.
    # ------------------------------------------------------------------
    op.create_index(
        "ix_review_actions_object",
        "review_actions",
        ["object_type", "object_id"],
    )

    # ------------------------------------------------------------------
    # 7. sessions: convert data JSON -> JSONB, preserving values.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE sessions "
        "ALTER COLUMN data TYPE jsonb "
        "USING data::jsonb"
    )

    # ------------------------------------------------------------------
    # 8. solution_decisions: add governance columns and indexes. The
    #    current ORM does NOT declare a unique constraint on external_code
    #    for this table, so none is created here.
    # ------------------------------------------------------------------
    op.add_column(
        "solution_decisions",
        sa.Column("classification", sa.String(), nullable=True),
    )
    op.add_column(
        "solution_decisions",
        sa.Column("complexity", sa.String(), nullable=True),
    )
    op.add_column(
        "solution_decisions",
        sa.Column("lifecycle_impact", sa.Text(), nullable=True),
    )
    op.add_column(
        "solution_decisions",
        sa.Column("external_code", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_solution_decisions_external_code",
        "solution_decisions",
        ["external_code"],
    )
    op.create_index(
        "ix_solution_decisions_lineage_id",
        "solution_decisions",
        ["lineage_id"],
    )
    op.create_index(
        "ix_solution_decisions_session_type",
        "solution_decisions",
        ["session_id", "decision_type"],
    )

    # ------------------------------------------------------------------
    # 9. test_case_records: add UAT-specific columns and updated_at
    #    (backfilled from created_at), then validate legacy external_code
    #    uniqueness before creating the constraint.
    # ------------------------------------------------------------------
    op.add_column(
        "test_case_records",
        sa.Column("user_role", sa.String(), nullable=True),
    )
    op.add_column(
        "test_case_records",
        sa.Column("business_process", sa.String(), nullable=True),
    )
    op.add_column(
        "test_case_records",
        sa.Column("acceptance_criteria", sa.Text(), nullable=True),
    )
    op.add_column(
        "test_case_records",
        sa.Column("related_design_component", sa.String(), nullable=True),
    )
    op.add_column(
        "test_case_records",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE test_case_records "
        "SET updated_at = created_at "
        "WHERE updated_at IS NULL"
    )
    op.alter_column(
        "test_case_records",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    _raise_if_duplicate_test_case_external_code()
    op.create_unique_constraint(
        "uq_test_case_session_external_code",
        "test_case_records",
        ["session_id", "external_code"],
    )

    # ------------------------------------------------------------------
    # 10. trace_links: indexes and the unique edge constraint, with a
    #     pre-emptive duplicate check before the constraint is created.
    # ------------------------------------------------------------------
    op.create_index(
        "ix_trace_links_session_relationship",
        "trace_links",
        ["session_id", "relationship"],
    )
    op.create_index(
        "ix_trace_links_source",
        "trace_links",
        ["source_type", "source_id"],
    )
    op.create_index(
        "ix_trace_links_target",
        "trace_links",
        ["target_type", "target_id"],
    )
    _raise_if_duplicate_trace_link_edge()
    op.create_unique_constraint(
        "uq_trace_link_edge",
        "trace_links",
        [
            "session_id", "source_type", "source_id",
            "target_type", "target_id", "relationship",
        ],
    )

    # ------------------------------------------------------------------
    # 11. training_step_records: add step-context columns and updated_at
    #     (backfilled from created_at), then the external_code index and
    #     unique constraint. external_code is newly added nullable, so
    #     existing rows receive NULL and do not conflict.
    # ------------------------------------------------------------------
    op.add_column(
        "training_step_records",
        sa.Column("external_code", sa.String(), nullable=True),
    )
    op.add_column(
        "training_step_records",
        sa.Column("role", sa.String(), nullable=True),
    )
    op.add_column(
        "training_step_records",
        sa.Column("verification", sa.Text(), nullable=True),
    )
    op.add_column(
        "training_step_records",
        sa.Column("prerequisites", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "training_step_records",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE training_step_records "
        "SET updated_at = created_at "
        "WHERE updated_at IS NULL"
    )
    op.alter_column(
        "training_step_records",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_index(
        "ix_training_step_records_external_code",
        "training_step_records",
        ["external_code"],
    )
    op.create_unique_constraint(
        "uq_training_step_session_external_code",
        "training_step_records",
        ["session_id", "external_code"],
    )


def downgrade() -> None:
    """Downgrade schema."""

    # 11. training_step_records
    op.drop_constraint(
        "uq_training_step_session_external_code",
        "training_step_records",
        type_="unique",
    )
    op.drop_index(
        "ix_training_step_records_external_code",
        table_name="training_step_records",
    )
    op.drop_column("training_step_records", "updated_at")
    op.drop_column("training_step_records", "prerequisites")
    op.drop_column("training_step_records", "verification")
    op.drop_column("training_step_records", "role")
    op.drop_column("training_step_records", "external_code")

    # 10. trace_links
    op.drop_constraint("uq_trace_link_edge", "trace_links", type_="unique")
    op.drop_index("ix_trace_links_target", table_name="trace_links")
    op.drop_index("ix_trace_links_source", table_name="trace_links")
    op.drop_index(
        "ix_trace_links_session_relationship", table_name="trace_links",
    )

    # 9. test_case_records
    op.drop_constraint(
        "uq_test_case_session_external_code",
        "test_case_records",
        type_="unique",
    )
    op.drop_column("test_case_records", "updated_at")
    op.drop_column("test_case_records", "related_design_component")
    op.drop_column("test_case_records", "acceptance_criteria")
    op.drop_column("test_case_records", "business_process")
    op.drop_column("test_case_records", "user_role")

    # 8. solution_decisions
    op.drop_index(
        "ix_solution_decisions_session_type",
        table_name="solution_decisions",
    )
    op.drop_index(
        "ix_solution_decisions_lineage_id",
        table_name="solution_decisions",
    )
    op.drop_index(
        "ix_solution_decisions_external_code",
        table_name="solution_decisions",
    )
    op.drop_column("solution_decisions", "external_code")
    op.drop_column("solution_decisions", "lifecycle_impact")
    op.drop_column("solution_decisions", "complexity")
    op.drop_column("solution_decisions", "classification")

    # 7. sessions.data JSONB -> JSON
    op.execute(
        "ALTER TABLE sessions "
        "ALTER COLUMN data TYPE json "
        "USING data::json"
    )

    # 6. review_actions
    op.drop_index("ix_review_actions_object", table_name="review_actions")

    # 5. requirement_items
    op.drop_constraint(
        "uq_requirement_session_external_code",
        "requirement_items",
        type_="unique",
    )
    op.drop_index(
        "ix_requirement_items_lineage_id",
        table_name="requirement_items",
    )
    op.drop_column("requirement_items", "source")

    # 4. project_memories: reverse JSONB -> JSON, then restore the
    #    session_id FK without ON DELETE CASCADE.
    op.execute(
        "ALTER TABLE project_memories "
        "ALTER COLUMN tags TYPE json "
        "USING tags::json"
    )
    op.execute(
        "ALTER TABLE project_memories "
        "ALTER COLUMN entry_metadata TYPE json "
        "USING entry_metadata::json"
    )
    op.drop_constraint(
        "project_memories_session_id_fkey",
        "project_memories",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "project_memories_session_id_fkey",
        "project_memories",
        "sessions",
        ["session_id"],
        ["session_id"],
    )

    # 3. project_issues
    op.drop_index(
        "ix_project_issues_session_type", table_name="project_issues",
    )
    op.drop_index(
        "ix_project_issues_session_status", table_name="project_issues",
    )
    op.drop_column("project_issues", "updated_at")

    # 2. process_steps
    op.drop_constraint(
        "uq_process_step_session_external_code",
        "process_steps",
        type_="unique",
    )
    op.drop_index(
        "ix_process_steps_session_process", table_name="process_steps",
    )
    op.drop_index(
        "ix_process_steps_lineage_id", table_name="process_steps",
    )
    op.drop_index(
        "ix_process_steps_external_code", table_name="process_steps",
    )
    op.drop_column("process_steps", "external_code")
    op.drop_column("process_steps", "exception_paths")
    op.drop_column("process_steps", "transaction")
    op.drop_column("process_steps", "outputs")
    op.drop_column("process_steps", "inputs")
    op.drop_column("process_steps", "trigger")

    # 1. GeneratedDocument
    op.drop_index(
        "ix_generated_documents_is_current",
        table_name="generated_documents",
    )