"""add generic analytics events

Revision ID: 20260705_0002
Revises: 20260705_0001
Create Date: 2026-07-05 00:00:00.000000+00:00
"""

from alembic import op

revision = "20260705_0002"
down_revision = "20260705_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists analytics_events (
          id uuid primary key,
          event_name text not null,
          event_category text not null,
          user_id text,
          anonymous_id text,
          session_id text,
          thread_id text,
          request_id text,
          trace_id text,
          client_request_id text,
          schema_version integer not null default 1,
          app_version text not null default '0.1.0',
          environment text not null default 'development',
          numeric_value double precision,
          unit text,
          properties_json text,
          created_at_epoch double precision not null
        );

        create index if not exists idx_analytics_events_created
          on analytics_events(created_at_epoch desc);

        create index if not exists idx_analytics_events_category_created
          on analytics_events(event_category, created_at_epoch desc);

        create index if not exists idx_analytics_events_request
          on analytics_events(request_id);

        create index if not exists idx_analytics_events_trace
          on analytics_events(trace_id);

        alter table analytics_events enable row level security;
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists analytics_events;")
