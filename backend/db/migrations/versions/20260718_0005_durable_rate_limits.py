"""store request rate limits in shared durable state

Revision ID: 20260718_0005
Revises: 20260718_0004
Create Date: 2026-07-18 00:05:00.000000+00:00
"""

from alembic import op

revision = "20260718_0005"
down_revision = "20260718_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute(
        """
        create table if not exists rate_limit_events (
          id uuid primary key,
          key_hash text not null,
          event_type text not null,
          created_at_epoch double precision not null,
          expires_at_epoch double precision not null
        )
        """
    )
    op.execute("alter table rate_limit_events enable row level security")

    with op.get_context().autocommit_block():
        op.execute("set lock_timeout = '5s'")
        op.execute(
            """
            create index concurrently if not exists idx_rate_limit_key_type_expiry
            on rate_limit_events(key_hash, event_type, expires_at_epoch desc)
            """
        )
        op.execute(
            """
            create index concurrently if not exists idx_rate_limit_expiry
            on rate_limit_events(expires_at_epoch)
            """
        )
        op.execute("reset lock_timeout")


def downgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("drop table if exists rate_limit_events")
