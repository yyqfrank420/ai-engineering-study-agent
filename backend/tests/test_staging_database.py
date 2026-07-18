from pathlib import Path

import pytest
from pydantic import ValidationError

from config import Settings
from scripts.staging_database import (
    provision_internal_identity,
    require_staging_schema,
    reset_staging_schema,
    verify_public_isolation,
)


class FakeConnection:
    def __init__(self, *, public_access: bool = False):
        self.public_access = public_access
        self.statements = []
        self.commits = 0

    def execute(self, statement, params=()):
        self.statements.append((statement, params))
        if "public.profiles" in statement and not self.public_access:
            raise PermissionError("permission denied")
        return self

    def commit(self):
        self.commits += 1

    def fetchone(self):
        return ("auth-user-id",)


def test_db_schema_configuration_is_allowlisted():
    assert Settings(db_schema="public").db_schema == "public"
    assert Settings(db_schema="staging").db_schema == "staging"
    with pytest.raises(ValidationError):
        Settings(db_schema="customer_supplied")


def test_staging_reset_rejects_every_other_schema():
    assert require_staging_schema("staging") == "staging"
    for unsafe in (None, "", "public", "other", "staging; drop schema public"):
        with pytest.raises(RuntimeError, match="requires DB_SCHEMA=staging"):
            require_staging_schema(unsafe)


def test_staging_reset_uses_constant_target_and_holds_advisory_lock(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA", "staging")
    connection = FakeConnection()
    migrations = []

    reset_staging_schema(
        connection,
        lambda: migrations.append("ran"),
        eval_email="EVAL@example.com",
    )

    statements = [statement for statement, _params in connection.statements]
    assert statements == [
        "SELECT pg_advisory_lock(hashtext(%s))",
        "DROP SCHEMA IF EXISTS staging CASCADE",
        "CREATE SCHEMA staging AUTHORIZATION CURRENT_USER",
        """
        INSERT INTO staging.profiles (id, email)
        SELECT id, email FROM auth.users WHERE lower(email) = lower(%s)
        ON CONFLICT(id) DO UPDATE
        SET email = excluded.email, updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        "SELECT pg_advisory_unlock(hashtext(%s))",
    ]
    assert migrations == ["ran"]
    assert connection.statements[3][1] == ("eval@example.com",)


def test_staging_identity_provisioning_requires_an_explicit_shared_auth_user():
    connection = FakeConnection()
    for invalid in (None, "", "not-an-email"):
        with pytest.raises(RuntimeError, match="EVAL_EMAIL"):
            provision_internal_identity(connection, invalid)


def test_isolation_probe_rejects_any_public_access():
    verify_public_isolation(FakeConnection(public_access=False))

    with pytest.raises(RuntimeError, match="public-table privileges"):
        verify_public_isolation(FakeConnection(public_access=True))


def test_migrations_do_not_hardcode_the_production_schema():
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("backend/db/migrations/versions").glob("*.py")
    )

    assert "public." not in migration_text
