"""store server-only graph contracts with persisted graphs

Revision ID: 20260816_0006
Revises: 20260718_0005
Create Date: 2026-08-16 00:06:00.000000+00:00
"""

from alembic import op

revision = "20260816_0006"
down_revision = "20260718_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("alter table chat_threads add column if not exists graph_contract jsonb")
    op.execute(
        """
        do $$
        begin
          if not exists (
            select 1 from pg_constraint
            where conname = 'graph_contract_version_matches_graph'
              and conrelid = 'chat_threads'::regclass
          ) then
            alter table chat_threads
            add constraint graph_contract_version_matches_graph
            check (
              graph_contract is null
              or (
                jsonb_typeof(graph_contract) = 'object'
                and graph_data is not null
                and jsonb_typeof(graph_data) = 'object'
                and graph_contract ? 'graph_version'
                and graph_data ? 'version'
                and nullif(btrim(graph_contract ->> 'graph_version'), '') is not null
                and graph_contract ->> 'graph_version' = graph_data ->> 'version'
              )
            ) not valid;
          end if;
        end
        $$
        """
    )
    op.execute(
        "alter table chat_threads validate constraint graph_contract_version_matches_graph"
    )


def downgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute(
        "alter table chat_threads drop constraint if exists graph_contract_version_matches_graph"
    )
    op.execute("alter table chat_threads drop column if exists graph_contract")
