from adapters import database_adapter
from adapters.database_adapter import init_db
from config import settings


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, *, tables, rls_tables, policies):
        self._tables = tables
        self._rls_tables = rls_tables
        self._policies = policies
        self.queries: list[str] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, query, params=()):
        del params
        self.queries.append(query)
        normalized = " ".join(query.lower().split())
        if "from pg_tables" in normalized:
            return _FakeCursor([{"tablename": name} for name in self._tables])
        if "from pg_class as c" in normalized:
            return _FakeCursor([{"table_name": name} for name in self._rls_tables])
        if "from pg_policies" in normalized:
            return _FakeCursor(
                [
                    {"tablename": table_name, "policyname": policy_name}
                    for table_name, policy_names in self._policies.items()
                    for policy_name in policy_names
                ]
            )
        raise AssertionError(f"Unexpected query: {query}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _patch_postgres_connection(monkeypatch, conn):
    monkeypatch.setattr(settings, "supabase_db_url", "postgresql://example")
    monkeypatch.setattr(database_adapter.psycopg, "connect", lambda *args, **kwargs: conn)


def test_init_db_in_postgres_mode_validates_schema_without_creating_tables(monkeypatch):
    policies = {table_name: set(policy_names) for table_name, policy_names in database_adapter.POSTGRES_REQUIRED_POLICIES.items()}
    conn = _FakeConnection(
        tables=set(database_adapter.POSTGRES_REQUIRED_TABLES),
        rls_tables=set(database_adapter.POSTGRES_REQUIRED_TABLES),
        policies=policies,
    )
    _patch_postgres_connection(monkeypatch, conn)

    init_db()

    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True
    assert all("create table" not in query.lower() for query in conn.queries)


def test_init_db_in_postgres_mode_fails_when_rls_is_missing(monkeypatch):
    policies = {table_name: set(policy_names) for table_name, policy_names in database_adapter.POSTGRES_REQUIRED_POLICIES.items()}
    conn = _FakeConnection(
        tables=set(database_adapter.POSTGRES_REQUIRED_TABLES),
        rls_tables={"profiles", "chat_threads", "chat_messages"},
        policies=policies,
    )
    _patch_postgres_connection(monkeypatch, conn)

    try:
        init_db()
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("init_db() should fail when required Postgres RLS is missing")

    assert "RLS disabled" in message
    assert "request_events" in message
    assert conn.committed is False
    assert conn.rolled_back is True
    assert conn.closed is True
