from __future__ import annotations

import argparse
import os

import psycopg
from psycopg import sql


ROLE_NAME = "agent_staging"
SCHEMA_NAME = "staging"
ADMIN_SCHEMA_NAME = "agent_eval_admin"
RESET_FUNCTION_NAME = "reset_staging_schema"


def provision(connection, password: str) -> None:
    if len(password) < 24:
        raise RuntimeError("STAGING_DB_PASSWORD must contain at least 24 characters")
    admin_name = connection.execute("SELECT current_user").fetchone()[0]
    database_name = connection.execute("SELECT current_database()").fetchone()[0]
    existing = connection.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE_NAME,)
    ).fetchone()
    role = sql.Identifier(ROLE_NAME)
    admin = sql.Identifier(admin_name)
    database = sql.Identifier(database_name)
    password_literal = sql.Literal(password)
    if existing:
        connection.execute(
            sql.SQL("ALTER ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
                role, password_literal
            )
        )
    else:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
                role, password_literal
            )
        )
    connection.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(role))
    connection.execute(
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role)
    )
    connection.execute(
        sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role)
    )
    # Supabase's managed `postgres` login is intentionally not a superuser.
    # PostgreSQL therefore requires it to be a member of the target owner role
    # while assigning schema ownership. The grant and revoke share this
    # transaction, so any failure rolls back the temporary membership too.
    connection.execute(sql.SQL("GRANT {} TO {}").format(role, admin))
    connection.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(
            sql.Identifier(SCHEMA_NAME), role
        )
    )
    # The reset function must own the schema so it can recreate it without
    # granting the PR role database-wide CREATE. Transfer ownership back to the
    # fixed admin identity before removing its temporary role membership.
    connection.execute(
        sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(
            sql.Identifier(SCHEMA_NAME), admin
        )
    )
    connection.execute(sql.SQL("REVOKE {} FROM {}").format(role, admin))
    connection.execute(
        sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(
            sql.Identifier(SCHEMA_NAME), role
        )
    )
    connection.execute(
        sql.SQL("REVOKE CREATE ON DATABASE {} FROM {}").format(database, role)
    )
    admin_schema = sql.Identifier(ADMIN_SCHEMA_NAME)
    reset_function = sql.Identifier(RESET_FUNCTION_NAME)
    connection.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(
            admin_schema, admin
        )
    )
    connection.execute(
        sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(admin_schema)
    )
    connection.execute(
        sql.SQL(
            """
            CREATE OR REPLACE FUNCTION {admin_schema}.{reset_function}()
            RETURNS void
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog
            AS $function$
            BEGIN
              DROP SCHEMA IF EXISTS {staging_schema} CASCADE;
              CREATE SCHEMA {staging_schema} AUTHORIZATION {admin};
              GRANT USAGE, CREATE ON SCHEMA {staging_schema} TO {role};
            END
            $function$
            """
        ).format(
            admin_schema=admin_schema,
            reset_function=reset_function,
            staging_schema=sql.Identifier(SCHEMA_NAME),
            admin=admin,
            role=role,
        )
    )
    connection.execute(
        sql.SQL("REVOKE ALL ON FUNCTION {}.{}() FROM PUBLIC").format(
            admin_schema, reset_function
        )
    )
    connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(admin_schema, role)
    )
    connection.execute(
        sql.SQL("GRANT EXECUTE ON FUNCTION {}.{}() TO {}").format(
            admin_schema, reset_function, role
        )
    )
    connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision the dedicated Supabase staging role"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Perform the one-time role/schema write"
    )
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit(
            "Dry run only. Re-run with --apply after reviewing this script and the recovery plan."
        )
    database_url = os.getenv("SUPABASE_ADMIN_DB_URL", "")
    password = os.getenv("STAGING_DB_PASSWORD", "")
    if not database_url:
        raise RuntimeError("SUPABASE_ADMIN_DB_URL is required")
    with psycopg.connect(database_url) as connection:
        provision(connection, password)


if __name__ == "__main__":
    main()
