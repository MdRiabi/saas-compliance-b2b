"""Require TOTP MFA for application administrators.

Revision ID: 6c2f8a1d9e40
Revises: a2c9029833d0
Create Date: 2026-11-12 16:45:00
"""

from alembic import op
import sqlalchemy as sa


revision = "6c2f8a1d9e40"
down_revision = "a2c9029833d0"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "mfa_secret" not in columns:
            batch.add_column(sa.Column("mfa_secret", sa.String(length=32), nullable=True))
        if "mfa_enabled" not in columns:
            batch.add_column(
                sa.Column(
                    "mfa_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        if "mfa_last_verified_step" not in columns:
            batch.add_column(
                sa.Column("mfa_last_verified_step", sa.Integer(), nullable=True)
            )


def downgrade():
    raise RuntimeError(
        "MFA cannot be downgraded automatically; disable it through the audited recovery procedure."
    )
