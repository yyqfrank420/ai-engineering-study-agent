from __future__ import annotations

import argparse
import os

import psycopg
from psycopg import sql


ROLE_NAME = "agent_staging"
SCHEMA_NAME = "staging"


def provision(connection, password: str) -> None:
    if len(password) < 24:
        raise RuntimeError("STAGING_DB_PASSWORD must contain at least 24 characters")
    existing = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE_NAME,)).fetchone()
    role = sql.Identifier(ROLE_NAME)
    password_literal = sql.Literal(password)
    if existing:
        connection.execute(
            sql.SQL("ALTER ROLE {} LOGIN NOINHERIT PASSWORD {}").format(role, password_literal)
        )
    else:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}").format(role, password_literal)
        )
    connection.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(role))
    connection.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
    connection.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role))
    # Preserve the production FK shape and seed only the allowlisted test user.
    # No other Auth columns and no production application tables are readable.
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA auth TO {}").format(role))
    connection.execute(
        sql.SQL("GRANT SELECT (id, email), REFERENCES (id) ON auth.users TO {}").format(role)
    )
    connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(sql.Identifier(SCHEMA_NAME), role))
    connection.execute(sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(sql.Identifier(SCHEMA_NAME), role))
    connection.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(sql.Identifier(SCHEMA_NAME), role))
    connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision the dedicated Supabase staging role")
    parser.add_argument("--apply", action="store_true", help="Perform the one-time role/schema write")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("Dry run only. Re-run with --apply after reviewing this script and the recovery plan.")
    database_url = os.getenv("SUPABASE_ADMIN_DB_URL", "")
    password = os.getenv("STAGING_DB_PASSWORD", "")
    if not database_url:
        raise RuntimeError("SUPABASE_ADMIN_DB_URL is required")
    with psycopg.connect(database_url) as connection:
        provision(connection, password)


if __name__ == "__main__":
    main()
