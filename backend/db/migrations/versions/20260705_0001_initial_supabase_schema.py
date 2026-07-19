"""initial Supabase schema

Revision ID: 20260705_0001
Revises:
Create Date: 2026-07-05 00:00:00.000000+00:00
"""

import os

from alembic import op

revision = "20260705_0001"
down_revision = None
branch_labels = None
depends_on = None

ALLOWED_SCHEMAS = {"public", "staging"}


def _identity_constraints() -> tuple[str, str]:
    """Keep production Auth integrity without granting staging access to Auth."""
    schema = os.environ.get("DB_SCHEMA", "public").strip().lower()
    if schema not in ALLOWED_SCHEMAS:
        raise RuntimeError("DB_SCHEMA must be either 'public' or 'staging'")
    if schema == "staging":
        return (
            "id uuid primary key",
            "nullif(current_setting('request.jwt.claim.sub', true), '')::uuid",
        )
    return (
        "id uuid primary key references auth.users(id) on delete cascade",
        "auth.uid()",
    )


def upgrade() -> None:
    profile_identity, request_user_id = _identity_constraints()
    op.execute(
        f"""
        create table if not exists profiles (
          {profile_identity},
          email text not null unique,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );

        create table if not exists chat_threads (
          id uuid primary key,
          user_id uuid not null references profiles(id) on delete cascade,
          title text not null default 'New chat',
          graph_data jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          last_seen_at timestamptz not null default now()
        );

        create table if not exists chat_messages (
          id uuid primary key,
          thread_id uuid not null references chat_threads(id) on delete cascade,
          user_id uuid not null references profiles(id) on delete cascade,
          role text not null check (role in ('user', 'assistant')),
          content text not null,
          created_at timestamptz not null default now()
        );

        create table if not exists request_events (
          id uuid primary key,
          user_id uuid not null references profiles(id) on delete cascade,
          event_type text not null,
          created_at_epoch double precision not null
        );

        create table if not exists product_analytics_events (
          id uuid primary key,
          user_id uuid references profiles(id) on delete cascade,
          anonymous_id text not null,
          event_type text not null,
          properties_json text,
          created_at_epoch double precision not null
        );

        create table if not exists search_tool_requests (
          request_id uuid primary key,
          user_id uuid not null references profiles(id) on delete cascade,
          thread_id uuid not null references chat_threads(id) on delete cascade,
          requested boolean not null default false,
          created_at_epoch double precision not null,
          expires_at_epoch double precision not null
        );

        create table if not exists active_streams (
          id uuid primary key,
          user_id uuid not null references profiles(id) on delete cascade,
          stream_type text not null,
          created_at_epoch double precision not null,
          expires_at_epoch double precision not null
        );

        create table if not exists http_request_logs (
          id uuid primary key,
          user_id uuid,
          method text not null,
          path text not null,
          status_code integer not null,
          latency_ms integer not null,
          ip_address text,
          user_agent text,
          metadata_json text,
          created_at_epoch double precision not null
        );

        create table if not exists llm_telemetry (
          id uuid primary key,
          user_id uuid,
          thread_id uuid,
          operation text not null,
          provider text not null,
          model text not null,
          status text not null,
          duration_ms integer not null,
          output_chars integer not null,
          used_fallback boolean not null default false,
          error_type text,
          metadata_json text,
          created_at_epoch double precision not null
        );

        create index if not exists idx_chat_threads_user_last_seen
          on chat_threads(user_id, last_seen_at desc);

        create index if not exists idx_chat_messages_thread_created
          on chat_messages(thread_id, created_at desc);

        create index if not exists idx_request_events_user_type_created
          on request_events(user_id, event_type, created_at_epoch desc);

        create index if not exists idx_product_analytics_events_created
          on product_analytics_events(created_at_epoch desc);

        create index if not exists idx_product_analytics_events_type_created
          on product_analytics_events(event_type, created_at_epoch desc);

        create index if not exists idx_product_analytics_events_actor_created
          on product_analytics_events(anonymous_id, created_at_epoch desc);

        create index if not exists idx_search_tool_requests_user_thread
          on search_tool_requests(user_id, thread_id);

        create index if not exists idx_active_streams_user_type
          on active_streams(user_id, stream_type, expires_at_epoch desc);

        create index if not exists idx_http_request_logs_created
          on http_request_logs(created_at_epoch desc);

        create index if not exists idx_http_request_logs_user_created
          on http_request_logs(user_id, created_at_epoch desc);

        create index if not exists idx_llm_telemetry_created
          on llm_telemetry(created_at_epoch desc);

        create index if not exists idx_llm_telemetry_user_created
          on llm_telemetry(user_id, created_at_epoch desc);

        alter table profiles enable row level security;
        alter table chat_threads enable row level security;
        alter table chat_messages enable row level security;
        alter table request_events enable row level security;
        alter table product_analytics_events enable row level security;
        alter table search_tool_requests enable row level security;
        alter table active_streams enable row level security;
        alter table http_request_logs enable row level security;
        alter table llm_telemetry enable row level security;

        drop policy if exists "profiles_select_own" on profiles;
        create policy "profiles_select_own" on profiles
        for select using ({request_user_id} = id);

        drop policy if exists "profiles_update_own" on profiles;
        create policy "profiles_update_own" on profiles
        for update using ({request_user_id} = id);

        drop policy if exists "threads_all_own" on chat_threads;
        create policy "threads_all_own" on chat_threads
        for all using ({request_user_id} = user_id) with check ({request_user_id} = user_id);

        drop policy if exists "messages_all_own" on chat_messages;
        create policy "messages_all_own" on chat_messages
        for all using ({request_user_id} = user_id) with check ({request_user_id} = user_id);

        drop policy if exists "active_streams_all_own" on active_streams;
        create policy "active_streams_all_own" on active_streams
        for all using ({request_user_id} = user_id) with check ({request_user_id} = user_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop policy if exists "active_streams_all_own" on active_streams;
        drop policy if exists "messages_all_own" on chat_messages;
        drop policy if exists "threads_all_own" on chat_threads;
        drop policy if exists "profiles_update_own" on profiles;
        drop policy if exists "profiles_select_own" on profiles;

        drop table if exists llm_telemetry;
        drop table if exists http_request_logs;
        drop table if exists active_streams;
        drop table if exists search_tool_requests;
        drop table if exists product_analytics_events;
        drop table if exists request_events;
        drop table if exists chat_messages;
        drop table if exists chat_threads;
        drop table if exists profiles;
        """
    )
