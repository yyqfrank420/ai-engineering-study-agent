from __future__ import annotations

import argparse
import os
from pathlib import Path
# Migrations run as a fixed argument vector rather than through a shell.
import subprocess  # nosec B404
import sys
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
STAGING_SCHEMA = "staging"
ADVISORY_LOCK_KEY = "agent-staging-live-eval-v1"


def require_staging_schema(value: str | None) -> str:
    schema = (value or "").strip().lower()
    if schema != STAGING_SCHEMA:
        raise RuntimeError("staging reset is fail-closed and requires DB_SCHEMA=staging")
    return schema


def verify_public_isolation(connection) -> None:
    """Prove the staging login cannot read or mutate production application tables."""
    forbidden = (
        "SELECT * FROM public.profiles LIMIT 0",
        "UPDATE public.profiles SET email = email WHERE false",
    )
    unexpectedly_allowed: list[str] = []
    for statement in forbidden:
        try:
            connection.execute(statement)
        # Denial is the expected result of each isolation probe.
        except Exception:  # nosec B112
            continue
        unexpectedly_allowed.append(statement.split(" ", 1)[0])
    if unexpectedly_allowed:
        raise RuntimeError(
            "staging role unexpectedly has public-table privileges: "
            + ", ".join(unexpectedly_allowed)
        )


def provision_internal_identity(connection, email: str | None) -> str:
    normalized_email = (email or "").strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise RuntimeError("EVAL_EMAIL must identify the allowlisted shared Auth user")
    row = connection.execute(
        """
        INSERT INTO staging.profiles (id, email)
        SELECT id, email FROM auth.users WHERE lower(email) = lower(%s)
        ON CONFLICT(id) DO UPDATE
        SET email = excluded.email, updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (normalized_email,),
    ).fetchone()
    if not row:
        raise RuntimeError("the allowlisted evaluation identity does not exist in shared Supabase Auth")
    connection.commit()
    return str(row[0])


def reset_staging_schema(
    connection,
    run_migrations: Callable[[], None],
    *,
    eval_email: str | None,
) -> None:
    require_staging_schema(os.getenv("DB_SCHEMA"))
    connection.execute("SELECT pg_advisory_lock(hashtext(%s))", (ADVISORY_LOCK_KEY,))
    try:
        connection.execute("DROP SCHEMA IF EXISTS staging CASCADE")
        connection.execute("CREATE SCHEMA staging AUTHORIZATION CURRENT_USER")
        connection.commit()
        run_migrations()
        provision_internal_identity(connection, eval_email)
    finally:
        connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (ADVISORY_LOCK_KEY,))
        connection.commit()


def _migration_command() -> None:
    environment = os.environ.copy()
    environment["DB_SCHEMA"] = STAGING_SCHEMA
    # Fixed interpreter/module/arguments; no shell or operator-provided executable.
    subprocess.run(  # nosec B603
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def _connect():
    database_url = os.getenv("SUPABASE_DB_URL", "")
    if not database_url:
        raise RuntimeError("SUPABASE_DB_URL is required")
    import psycopg

    return psycopg.connect(database_url, autocommit=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset and verify the isolated staging application schema")
    parser.add_argument("command", choices=["reset", "verify-isolation"])
    args = parser.parse_args()
    require_staging_schema(os.getenv("DB_SCHEMA"))
    with _connect() as connection:
        verify_public_isolation(connection)
        if args.command == "reset":
            reset_staging_schema(
                connection,
                _migration_command,
                eval_email=os.getenv("EVAL_EMAIL"),
            )
        verify_public_isolation(connection)


if __name__ == "__main__":
    main()
