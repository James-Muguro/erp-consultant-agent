"""add opportunity / TOR workflow tables

Revision ID: f6b3c1d8e7a4
Revises: e5a2b9c3d1f7
Create Date: 2026-09-26 16:00:00.000000

Phase 2.5 Step 3 (D1). Adds the pre-award container (Opportunity), the
TOR requirements staging buffer, the two pre-award document tables, and
the firm-knowledge store. All tables are new; no existing schema is
altered.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'f6b3c1d8e7a4'
down_revision: Union[str, Sequence[str], None] = 'e5a2b9c3d1f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=True),
        sa.Column("owner_user_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("assigned_consultant_user_id", sa.String(), nullable=True),
        sa.Column("converted_session_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("won_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_consultant_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["converted_session_id"], ["sessions.session_id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("converted_session_id"),
        sa.CheckConstraint(
            "status IN ('draft', 'tor_finalized', 'won', 'lost', 'archived')",
            name="ck_opportunities_status",
        ),
    )
    op.create_index(
        "ix_opportunities_organization_id", "opportunities", ["organization_id"],
    )
    op.create_index(
        "ix_opportunities_created_by_user_id", "opportunities", ["created_by_user_id"],
    )
    op.create_index(
        "ix_opportunities_owner_user_id", "opportunities", ["owner_user_id"],
    )
    op.create_index(
        "ix_opportunities_assigned_consultant_user_id",
        "opportunities", ["assigned_consultant_user_id"],
    )
    op.create_index(
        "ix_opportunities_org_status",
        "opportunities", ["organization_id", "status"],
    )
    op.create_index(
        "ix_opportunities_owner", "opportunities", ["owner_user_id"],
    )

    op.create_table(
        "opportunity_requirements",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("opportunity_id", sa.String(), nullable=False),
        sa.Column("external_code", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "priority", sa.String(), nullable=False,
            server_default=sa.text("'Medium'"),
        ),
        sa.Column(
            "req_type", sa.String(), nullable=False,
            server_default=sa.text("'Functional'"),
        ),
        sa.Column("acceptance_criteria", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("importance", sa.String(), nullable=True),
        sa.Column("fit_response", sa.String(), nullable=True),
        sa.Column("fit_response_ai", sa.String(), nullable=True),
        sa.Column("fit_response_comment", sa.Text(), nullable=True),
        sa.Column("fit_response_ai_comment", sa.Text(), nullable=True),
        sa.Column(
            "ai_draft_status", sa.String(), nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opportunity_id", "external_code",
            name="uq_opportunity_requirements_opp_code",
        ),
        sa.CheckConstraint(
            "fit_response IS NULL OR fit_response IN "
            "('meets_out_of_the_box', 'requires_customization', 'not_supported')",
            name="ck_opportunity_requirements_fit_response",
        ),
        sa.CheckConstraint(
            "ai_draft_status IN ('pending', 'drafted', 'finalized')",
            name="ck_opportunity_requirements_ai_draft_status",
        ),
    )
    op.create_index(
        "ix_opportunity_requirements_opportunity_id",
        "opportunity_requirements", ["opportunity_id"],
    )
    op.create_index(
        "ix_opportunity_requirements_external_code",
        "opportunity_requirements", ["external_code"],
    )
    op.create_index(
        "ix_opportunity_requirements_opp_status",
        "opportunity_requirements", ["opportunity_id", "ai_draft_status"],
    )

    op.create_table(
        "opportunity_documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("opportunity_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "extracted_text_chars", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("source_format", sa.String(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_opportunity_documents_opportunity_id",
        "opportunity_documents", ["opportunity_id"],
    )
    op.create_index(
        "ix_opportunity_documents_user_id", "opportunity_documents", ["user_id"],
    )
    op.create_index(
        "ix_opportunity_documents_uploaded_at",
        "opportunity_documents", ["uploaded_at"],
    )

    op.create_table(
        "opportunity_generated_documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("opportunity_id", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column(
            "is_current", sa.Boolean(), nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_opportunity_generated_documents_opportunity_id",
        "opportunity_generated_documents", ["opportunity_id"],
    )
    op.create_index(
        "ix_opportunity_generated_documents_is_current",
        "opportunity_generated_documents", ["is_current"],
    )
    op.create_index(
        "ix_opportunity_generated_documents_opp_phase_label",
        "opportunity_generated_documents",
        ["opportunity_id", "phase", "label"],
    )
    op.create_index(
        "ix_opportunity_generated_documents_opp_phase_label_current",
        "opportunity_generated_documents",
        ["opportunity_id", "phase", "label"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )

    op.create_table(
        "firm_knowledge_entries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("source_opportunity_id", sa.String(), nullable=True),
        sa.Column("source_external_code", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("requirement_text", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("response_kind", sa.String(), nullable=True),
        sa.Column("importance", sa.String(), nullable=True),
        sa.Column("erp_system", sa.String(), nullable=True),
        sa.Column("tags", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_session_id"], ["sessions.session_id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_opportunity_id"], ["opportunities.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_opportunity_id", "source_external_code",
            name="uq_firm_knowledge_source",
        ),
    )
    op.create_index(
        "ix_firm_knowledge_entries_organization_id",
        "firm_knowledge_entries", ["organization_id"],
    )
    op.create_index(
        "ix_firm_knowledge_entries_created_at",
        "firm_knowledge_entries", ["created_at"],
    )
    op.create_index(
        "ix_firm_knowledge_org_type",
        "firm_knowledge_entries", ["organization_id", "source_type"],
    )
    op.create_index(
        "ix_firm_knowledge_org_erp",
        "firm_knowledge_entries", ["organization_id", "erp_system"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_firm_knowledge_org_erp", table_name="firm_knowledge_entries",
    )
    op.drop_index(
        "ix_firm_knowledge_org_type", table_name="firm_knowledge_entries",
    )
    op.drop_index(
        "ix_firm_knowledge_entries_created_at", table_name="firm_knowledge_entries",
    )
    op.drop_index(
        "ix_firm_knowledge_entries_organization_id",
        table_name="firm_knowledge_entries",
    )
    op.drop_table("firm_knowledge_entries")

    op.drop_index(
        "ix_opportunity_generated_documents_opp_phase_label_current",
        table_name="opportunity_generated_documents",
    )
    op.drop_index(
        "ix_opportunity_generated_documents_opp_phase_label",
        table_name="opportunity_generated_documents",
    )
    op.drop_index(
        "ix_opportunity_generated_documents_is_current",
        table_name="opportunity_generated_documents",
    )
    op.drop_index(
        "ix_opportunity_generated_documents_opportunity_id",
        table_name="opportunity_generated_documents",
    )
    op.drop_table("opportunity_generated_documents")

    op.drop_index(
        "ix_opportunity_documents_uploaded_at", table_name="opportunity_documents",
    )
    op.drop_index(
        "ix_opportunity_documents_user_id", table_name="opportunity_documents",
    )
    op.drop_index(
        "ix_opportunity_documents_opportunity_id",
        table_name="opportunity_documents",
    )
    op.drop_table("opportunity_documents")

    op.drop_index(
        "ix_opportunity_requirements_opp_status",
        table_name="opportunity_requirements",
    )
    op.drop_index(
        "ix_opportunity_requirements_external_code",
        table_name="opportunity_requirements",
    )
    op.drop_index(
        "ix_opportunity_requirements_opportunity_id",
        table_name="opportunity_requirements",
    )
    op.drop_table("opportunity_requirements")

    op.drop_index("ix_opportunities_owner", table_name="opportunities")
    op.drop_index("ix_opportunities_org_status", table_name="opportunities")
    op.drop_index(
        "ix_opportunities_assigned_consultant_user_id",
        table_name="opportunities",
    )
    op.drop_index("ix_opportunities_owner_user_id", table_name="opportunities")
    op.drop_index(
        "ix_opportunities_created_by_user_id", table_name="opportunities",
    )
    op.drop_index("ix_opportunities_organization_id", table_name="opportunities")
    op.drop_table("opportunities")