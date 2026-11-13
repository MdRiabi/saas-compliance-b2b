"""Create application tables missing from the original migration history.

Revision ID: d7f4a8c21b90
Revises: 6c2f8a1d9e40
Create Date: 2026-11-13 02:50:00
"""

from alembic import op
import sqlalchemy as sa


revision = "d7f4a8c21b90"
down_revision = "6c2f8a1d9e40"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())

    if "tenants" not in tables:
        op.create_table(
            "tenants",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        tables.add("tenants")

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(length=120), nullable=False),
            sa.Column("password_hash", sa.String(length=256), nullable=False),
            sa.Column("role", sa.String(length=50), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("mfa_secret", sa.String(length=32), nullable=True),
            sa.Column(
                "mfa_enabled",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column("mfa_last_verified_step", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
        tables.add("users")

    if "rgpd_audit" not in tables:
        op.create_table(
            "rgpd_audit",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("company_name", sa.String(length=120), nullable=False),
            sa.Column("data_processing_name", sa.String(length=200), nullable=False),
            sa.Column("data_category", sa.String(length=100), nullable=True),
            sa.Column("compliance_score", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=True),
            sa.Column("recommendations", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        tables.add("rgpd_audit")
    if "ix_rgpd_audit_tenant_id" not in {
        index["name"] for index in sa.inspect(connection).get_indexes("rgpd_audit")
    }:
        op.create_index("ix_rgpd_audit_tenant_id", "rgpd_audit", ["tenant_id"])

    if "iso27001_control" not in tables:
        op.create_table(
            "iso27001_control",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("company_name", sa.String(length=120), nullable=False),
            sa.Column("control_domain", sa.String(length=150), nullable=False),
            sa.Column("control_title", sa.String(length=200), nullable=False),
            sa.Column("implementation_status", sa.String(length=50), nullable=True),
            sa.Column("evidence_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        tables.add("iso27001_control")
    if "ix_iso27001_control_tenant_id" not in {
        index["name"] for index in sa.inspect(connection).get_indexes("iso27001_control")
    }:
        op.create_index(
            "ix_iso27001_control_tenant_id",
            "iso27001_control",
            ["tenant_id"],
        )


def downgrade():
    raise RuntimeError(
        "Application tables may contain tenant data; restore from a backup instead."
    )
