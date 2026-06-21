"""
添加邮箱配置表

Revision ID: 20260226_0007
Revises: 20260226_0006
Create Date: 2026-02-26

@author ScholarMind Team
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260226_0007"
down_revision = "20260226_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    添加邮箱配置表
    """

    # 创建邮箱配置表
    op.create_table(
        "email_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("smtp_server", sa.String(256), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sender_email", sa.String(256), nullable=False),
        sa.Column("sender_name", sa.String(128), nullable=False, server_default="ScholarMind"),
        sa.Column("username", sa.String(256), nullable=False),
        sa.Column("password", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """
    移除邮箱配置表
    """
    op.drop_table("email_configs")
