import importlib
from pathlib import Path
import uuid

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
        "SELECT agent_eval_admin.reset_staging_schema()",
        """
        INSERT INTO staging.profiles (id, email)
        VALUES (%s, %s)
        ON CONFLICT(id) DO UPDATE
        SET email = excluded.email, updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        "SELECT pg_advisory_unlock(hashtext(%s))",
    ]
    assert migrations == ["ran"]
    user_id, email = connection.statements[2][1]
    assert isinstance(user_id, uuid.UUID)
    assert email == "eval@example.com"


def test_staging_identity_provisioning_requires_an_explicit_internal_user():
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


def test_initial_migration_keeps_managed_auth_out_of_staging(monkeypatch):
    initial = importlib.import_module(
        "db.migrations.versions.20260705_0001_initial_supabase_schema"
    )

    monkeypatch.setenv("DB_SCHEMA", "staging")
    profile_identity, request_user_id = initial._identity_constraints()
    assert "auth.users" not in profile_identity
    assert "auth." not in request_user_id
    assert "request.jwt.claim.sub" in request_user_id

    monkeypatch.setenv("DB_SCHEMA", "public")
    profile_identity, request_user_id = initial._identity_constraints()
    assert "references auth.users(id)" in profile_identity
    assert request_user_id == "auth.uid()"


def test_initial_migration_rejects_arbitrary_schema(monkeypatch):
    initial = importlib.import_module(
        "db.migrations.versions.20260705_0001_initial_supabase_schema"
    )
    monkeypatch.setenv("DB_SCHEMA", "attacker_controlled")

    with pytest.raises(RuntimeError, match="public.*staging"):
        initial._identity_constraints()
