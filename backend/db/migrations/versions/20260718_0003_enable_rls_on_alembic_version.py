"""enable RLS on Alembic version table

Revision ID: 20260718_0003
Revises: 20260705_0002
Create Date: 2026-07-18 00:00:00.000000+00:00
"""

from alembic import op

revision = "20260718_0003"
down_revision = "20260705_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table alembic_version enable row level security;")


def downgrade() -> None:
    op.execute("alter table alembic_version disable row level security;")
