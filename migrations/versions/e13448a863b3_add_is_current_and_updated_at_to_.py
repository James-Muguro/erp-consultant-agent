"""add is_current and updated_at to generated documents

Revision ID: e13448a863b3
Revises: 5ce7a828130c
Create Date: 2026-09-21 15:17:59.336310

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e13448a863b3'
down_revision: Union[str, Sequence[str], None] = '5ce7a828130c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add is_current. NOT NULL with a server-side default of TRUE, so
    #    every pre-existing row is initialized to TRUE. New rows without
    #    an explicit value also default to TRUE.
    # ------------------------------------------------------------------
    op.add_column(
        "generated_documents",
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # ------------------------------------------------------------------
    # 2. Add updated_at as nullable, backfill from created_at, then
    #    tighten to NOT NULL. Existing rows get updated_at = created_at
    #    (never now()).
    # ------------------------------------------------------------------
    op.add_column(
        "generated_documents",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE generated_documents "
        "SET updated_at = created_at "
        "WHERE updated_at IS NULL"
    )
    op.alter_column(
        "generated_documents",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # 3. Validate that no legacy row has a NULL logical identity field.
    #    Fail loudly instead of fabricating identity values.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        DECLARE
            null_identity_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO null_identity_count
            FROM generated_documents
            WHERE session_id IS NULL OR phase IS NULL OR label IS NULL;

            IF null_identity_count > 0 THEN
                RAISE EXCEPTION
                    'GeneratedDocument logical identity contains NULL '
                    'values in session_id, phase, or label';
            END IF;
        END $$;
        """
    )

    # ------------------------------------------------------------------
    # 4. Validate that no legacy identity group already has more than
    #    one is_current = TRUE row. If any group does, fail loudly with
    #    the required phrase before the unique index is created.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        DECLARE
            duplicate_group_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO duplicate_group_count
            FROM (
                SELECT session_id, phase, label
                FROM generated_documents
                GROUP BY session_id, phase, label
                HAVING SUM(CASE WHEN is_current THEN 1 ELSE 0 END) > 1
            ) AS dup_groups;

            IF duplicate_group_count > 0 THEN
                RAISE EXCEPTION
                    'duplicate GeneratedDocument logical identity: '
                    'multiple is_current = TRUE rows share the same '
                    '(session_id, phase, label)';
            END IF;
        END $$;
        """
    )

    # ------------------------------------------------------------------
    # 5. Non-unique index over the logical identity.
    # ------------------------------------------------------------------
    op.create_index(
        "ix_generated_documents_session_phase_label",
        "generated_documents",
        ["session_id", "phase", "label"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 6. Partial unique index enforcing AT MOST ONE current row per
    #    logical identity. Historical rows (is_current = FALSE) are
    #    exempt and may accumulate without limit.
    # ------------------------------------------------------------------
    op.create_index(
        "ix_generated_documents_session_phase_label_current",
        "generated_documents",
        ["session_id", "phase", "label"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generated_documents_session_phase_label_current",
        table_name="generated_documents",
    )
    op.drop_index(
        "ix_generated_documents_session_phase_label",
        table_name="generated_documents",
    )
    op.drop_column("generated_documents", "updated_at")
    op.drop_column("generated_documents", "is_current")