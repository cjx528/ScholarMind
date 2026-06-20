"""add agent pending action table

Revision ID: 5ae0d73c1013
Revises: 20260311_0010_add_schedule_frequency
Create Date: 2026-03-12 01:32:59.424095
"""

from alembic import op
import sqlalchemy as sa


revision = "5ae0d73c1013"
down_revision = "20260311_0010_add_schedule_frequency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_pending_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_args", sa.JSON(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=64), nullable=True),
        sa.Column("conversation_state", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_pending_actions_conversation_id"),
        "agent_pending_actions",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_pending_actions_paper_id"),
        "agent_pending_actions",
        ["paper_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_agent_pending_actions_paper_id"),
        table_name="agent_pending_actions",
    )
    op.drop_index(
        op.f("ix_agent_pending_actions_conversation_id"),
        table_name="agent_pending_actions",
    )
    op.drop_table("agent_pending_actions")
