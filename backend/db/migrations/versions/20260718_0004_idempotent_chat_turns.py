"""make completed chat turns idempotent

Revision ID: 20260718_0004
Revises: 20260718_0003
Create Date: 2026-07-18 00:04:00.000000+00:00
"""

from alembic import op

revision = "20260718_0004"
down_revision = "20260718_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute(
        "alter table chat_messages "
        "add column if not exists client_request_id text"
    )
    with op.get_context().autocommit_block():
        op.execute("set lock_timeout = '5s'")
        op.execute(
            """
            create unique index concurrently if not exists uq_chat_messages_client_turn_role
            on chat_messages(user_id, thread_id, client_request_id, role)
            where client_request_id is not null
            """
        )
        op.execute("reset lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("set lock_timeout = '5s'")
        op.execute(
            "drop index concurrently if exists uq_chat_messages_client_turn_role"
        )
        op.execute("reset lock_timeout")
    op.execute("set local lock_timeout = '5s'")
    op.execute(
        "alter table chat_messages drop column if exists client_request_id"
    )
