"""Give persisted messages a database-owned total order.

Revision ID: 20260912_0007
Revises: 20260816_0006
Create Date: 2026-09-12
"""

from alembic import op

revision = "20260912_0007"
down_revision = "20260816_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("set local statement_timeout = '60s'")
    # Keep old writers blocked until the backfill and automatic default become
    # visible together. A timeout rolls back this entire bounded migration.
    op.execute("lock table chat_messages in access exclusive mode")
    op.execute("alter table chat_messages add column message_sequence bigint")
    op.execute(
        """
        with historical_turns as (
          select id, thread_id, user_id, role, client_request_id,
            case when client_request_id is null then created_at
              else min(created_at) over (partition by user_id, thread_id, client_request_id)
            end as turn_created_at
          from chat_messages
        ), ordered_messages as (
          select id, row_number() over (
            order by turn_created_at, thread_id, user_id,
              client_request_id is null, coalesce(client_request_id, id::text),
              case role when 'user' then 0 else 1 end, id
          ) as ordinal
          from historical_turns
        )
        update chat_messages as message
        set message_sequence = ordered_messages.ordinal
        from ordered_messages where message.id = ordered_messages.id
        """
    )
    op.execute("alter table chat_messages alter column message_sequence set not null")
    op.execute(
        "alter table chat_messages alter column message_sequence "
        "add generated always as identity (cache 1 no cycle)"
    )
    op.execute(
        """
        select setval(
          pg_get_serial_sequence('chat_messages', 'message_sequence'),
          coalesce(max(message_sequence), 1), max(message_sequence) is not null
        ) from chat_messages
        """
    )
    # These indexes share the bounded transaction so failed deployment cannot
    # leave readers on a partially installed ordering contract.
    op.execute(
        "create unique index uq_chat_messages_sequence "
        "on chat_messages(message_sequence)"
    )
    op.execute(
        "create index idx_chat_messages_thread_sequence "
        "on chat_messages(thread_id, message_sequence)"
    )


def downgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("set local statement_timeout = '60s'")
    op.execute("alter table chat_messages drop column message_sequence")
