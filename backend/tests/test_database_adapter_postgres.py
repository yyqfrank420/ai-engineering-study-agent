import pytest

from config import settings


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakePostgresConnection:
    def __init__(self, *, tables=None, rls=None, policies=None):
        self.tables = tables or []
        self.rls = rls or []
        self.policies = policies or []
        self.queries = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if "FROM pg_tables" in query:
            return _Cursor([{"tablename": table} for table in self.tables])
        if "FROM pg_class" in query:
            return _Cursor([{"table_name": table} for table in self.rls])
        if "FROM pg_policies" in query:
            return _Cursor([
                {"tablename": table, "policyname": policy}
                for table, policies in self.policies.items()
                for policy in policies
            ])
        return _Cursor([])

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_postgres_connect_commits_and_adapts_placeholders(monkeypatch):
    import adapters.database_adapter as db

    conn = _FakePostgresConnection()
    monkeypatch.setattr(settings, "supabase_db_url", "postgresql://db")
    monkeypatch.setattr(db.psycopg, "connect", lambda url: conn)

    with db._connect() as opened:
        assert opened is conn
        assert db._adapt_query("SELECT ?") == "SELECT %s"

    assert conn.committed is True
    assert conn.closed is True


def test_postgres_connect_rolls_back_on_error(monkeypatch):
    import adapters.database_adapter as db

    conn = _FakePostgresConnection()
    monkeypatch.setattr(settings, "supabase_db_url", "postgresql://db")
    monkeypatch.setattr(db.psycopg, "connect", lambda url: conn)

    with pytest.raises(RuntimeError, match="boom"):
        with db._connect():
            raise RuntimeError("boom")

    assert conn.rolled_back is True
    assert conn.closed is True


def test_validate_postgres_schema_success_and_failure(monkeypatch):
    import adapters.database_adapter as db

    tables = list(db.POSTGRES_REQUIRED_TABLES)
    policies = {table: set(required) for table, required in db.POSTGRES_REQUIRED_POLICIES.items()}
    db._validate_postgres_schema(_FakePostgresConnection(tables=tables, rls=tables, policies=policies))

    with pytest.raises(RuntimeError) as exc_info:
        db._validate_postgres_schema(
            _FakePostgresConnection(
                tables=["profiles"],
                rls=[],
                policies={"profiles": {"profiles_select_own"}},
            )
        )

    message = str(exc_info.value)
    assert "missing tables" in message
    assert "RLS disabled" in message
    assert "missing policies" in message
