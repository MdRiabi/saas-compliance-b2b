"""Extend audit log records

Revision ID: a2c9029833d0
Revises:
Create Date: 2026-11-12 02:01:35.705199

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2c9029833d0'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "audit_log" not in inspector.get_table_names():
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=True),
            sa.Column("user_email", sa.String(length=120), nullable=True),
            sa.Column("action", sa.String(length=255), nullable=False),
            sa.Column("resource_type", sa.String(length=80), nullable=True),
            sa.Column("resource_id", sa.String(length=128), nullable=True),
            sa.Column("result", sa.String(length=20), nullable=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
        return

    columns = {column["name"]: column for column in inspector.get_columns("audit_log")}
    indexes = {index["name"] for index in inspector.get_indexes("audit_log")}
    if "timestamp" in columns and columns["timestamp"]["nullable"]:
        op.execute(
            sa.text(
                "UPDATE audit_log SET timestamp = CURRENT_TIMESTAMP WHERE timestamp IS NULL"
            )
        )
    with op.batch_alter_table("audit_log") as batch:
        for name, column_type in (
            ("resource_type", sa.String(length=80)),
            ("resource_id", sa.String(length=128)),
            ("result", sa.String(length=20)),
        ):
            if name not in columns:
                batch.add_column(sa.Column(name, column_type, nullable=True))
        if "tenant_id" in columns and not columns["tenant_id"]["nullable"]:
            batch.alter_column("tenant_id", existing_type=sa.String(length=64), nullable=True)
        if "user_email" in columns and not columns["user_email"]["nullable"]:
            batch.alter_column("user_email", existing_type=sa.String(length=120), nullable=True)
        if "timestamp" in columns and columns["timestamp"]["nullable"]:
            batch.alter_column(
                "timestamp",
                existing_type=sa.DateTime(),
                nullable=False,
            )

    if (
        connection.dialect.name == "postgresql"
        and "timestamp" in columns
        and not getattr(columns["timestamp"]["type"], "timezone", False)
    ):
        op.execute(
            "ALTER TABLE audit_log ALTER COLUMN timestamp TYPE TIMESTAMP WITH TIME ZONE "
            "USING timestamp AT TIME ZONE 'UTC'"
        )
    op.execute(
        sa.text("UPDATE audit_log SET result = 'success' WHERE result IS NULL")
    )
    if "ix_audit_log_tenant_id" not in indexes:
        op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])


def downgrade():
    raise RuntimeError(
        "Audit log fields cannot be removed without discarding records; restore from a backup instead."
    )
