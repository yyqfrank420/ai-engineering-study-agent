from adapters.database_adapter import execute, init_db
from storage import product_analytics_store, runtime_state_store, telemetry_store


def test_runtime_state_request_events_and_pruning(temp_data_dir):
    init_db()

    runtime_state_store.record_request_event("user-1", "chat", created_at_epoch=10)
    runtime_state_store.record_request_event("user-1", "chat", created_at_epoch=20)
    runtime_state_store.record_request_event("user-1", "node", created_at_epoch=30)

    assert [row["created_at_epoch"] for row in runtime_state_store.get_recent_request_events("user-1", "chat", since_epoch=15)] == [20]

    runtime_state_store.prune_request_events(older_than_epoch=25)

    assert runtime_state_store.get_recent_request_events("user-1", "chat", since_epoch=0) == []
    assert len(runtime_state_store.get_recent_request_events("user-1", "node", since_epoch=0)) == 1


def test_runtime_state_search_tool_expiry_and_delete(temp_data_dir, monkeypatch):
    init_db()
    monkeypatch.setattr(runtime_state_store.time, "time", lambda: 100.0)

    runtime_state_store.create_search_tool_request(
        "req-1",
        "user-1",
        "thread-1",
        expires_at_epoch=110,
    )
    assert runtime_state_store.mark_search_tool_requested("req-1", "user-1", "thread-1") is True
    assert runtime_state_store.is_search_tool_requested("req-1", "user-1", "thread-1") is True

    runtime_state_store.delete_search_tool_request("req-1")
    assert runtime_state_store.is_search_tool_requested("req-1", "user-1", "thread-1") is False

    runtime_state_store.create_search_tool_request(
        "req-expired",
        "user-1",
        "thread-1",
        expires_at_epoch=99,
    )
    assert runtime_state_store.mark_search_tool_requested("req-expired", "user-1", "thread-1") is False
    runtime_state_store.prune_search_tool_requests(older_than_epoch=100)
    assert runtime_state_store.is_search_tool_requested("req-expired", "user-1", "thread-1") is False


def test_runtime_state_active_stream_limits_release_and_prune(temp_data_dir, monkeypatch):
    init_db()
    monkeypatch.setattr(runtime_state_store.time, "time", lambda: 100.0)

    unlimited = runtime_state_store.try_acquire_active_stream("user-1", "chat", limit=0, ttl_s=10)
    assert unlimited

    first = runtime_state_store.try_acquire_active_stream("user-1", "chat", limit=1, ttl_s=10)
    assert first
    assert runtime_state_store.try_acquire_active_stream("user-1", "chat", limit=1, ttl_s=10) is None

    runtime_state_store.release_active_stream(first)
    second = runtime_state_store.try_acquire_active_stream("user-1", "chat", limit=1, ttl_s=10)
    assert second

    monkeypatch.setattr(runtime_state_store.time, "time", lambda: 200.0)
    runtime_state_store.prune_active_streams(older_than_epoch=200)
    assert runtime_state_store.try_acquire_active_stream("user-1", "chat", limit=1, ttl_s=10)

    runtime_state_store.release_active_stream(None)


def test_product_analytics_round_trips_properties_and_ignores_bad_json(temp_data_dir):
    init_db()

    product_analytics_store.record_product_analytics_event(
        anonymous_id="anon-1",
        user_id="user-1",
        event_type="chat_sent",
        properties={"thread_id": "thread-1", "nested": {"ok": True}},
        created_at_epoch=20,
    )
    execute(
        """
        INSERT INTO product_analytics_events (
            id, user_id, anonymous_id, event_type, properties_json, created_at_epoch
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("bad-json", None, "anon-2", "auth_viewed", "[1,2,3]", 30),
    )
    execute(
        """
        INSERT INTO product_analytics_events (
            id, user_id, anonymous_id, event_type, properties_json, created_at_epoch
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("malformed-json", None, "anon-3", "auth_viewed", "{bad", 40),
    )
    product_analytics_store.record_product_analytics_event(
        anonymous_id="anon-4",
        event_type="auth_viewed",
        properties=None,
        created_at_epoch=50,
    )

    rows = product_analytics_store.list_recent_product_analytics_events(since_epoch=0)

    assert rows[0]["properties"] == {}
    assert rows[1]["properties"] == {}
    assert rows[2]["properties"] == {}
    assert rows[3]["properties"] == {"thread_id": "thread-1", "nested": {"ok": True}}


def test_product_analytics_rejects_invalid_event_shape(temp_data_dir):
    init_db()

    try:
        product_analytics_store.record_product_analytics_event(
            anonymous_id="",
            event_type="chat_sent",
            created_at_epoch=20,
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("analytics events should require a non-empty anonymous_id")

    assert "anonymous_id" in message


def test_telemetry_logs_round_trip_metadata_and_filter_by_user(temp_data_dir):
    init_db()

    telemetry_store.record_http_request_log(
        method="POST",
        path="/api/chat",
        status_code=200,
        latency_ms=123,
        user_id="user-1",
        metadata={"request_id": "req-1"},
        created_at_epoch=20,
    )
    telemetry_store.record_http_request_log(
        method="GET",
        path="/health",
        status_code=200,
        latency_ms=5,
        user_id="user-2",
        metadata=None,
        created_at_epoch=30,
    )
    telemetry_store.record_llm_telemetry(
        operation="synthesis",
        provider="anthropic",
        model="claude",
        status="success",
        duration_ms=500,
        output_chars=42,
        used_fallback=False,
        user_id="user-1",
        thread_id="thread-1",
        metadata={"trace_id": "trace-1"},
        created_at_epoch=40,
    )

    http_rows = telemetry_store.list_recent_http_request_logs(since_epoch=0, user_id="user-1")
    llm_rows = telemetry_store.list_recent_llm_telemetry(since_epoch=0, user_id="user-1")

    assert len(http_rows) == 1
    assert http_rows[0]["metadata"] == {"request_id": "req-1"}
    assert len(llm_rows) == 1
    assert llm_rows[0]["metadata"] == {"trace_id": "trace-1"}
    assert llm_rows[0]["used_fallback"] in {False, 0}


def test_telemetry_ignores_non_dict_metadata(temp_data_dir):
    init_db()
    execute(
        """
        INSERT INTO http_request_logs (
            id, user_id, method, path, status_code, latency_ms,
            ip_address, user_agent, metadata_json, created_at_epoch
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("bad-metadata", "user-1", "GET", "/health", 200, 1, None, None, '"not-dict"', 10),
    )

    assert telemetry_store.list_recent_http_request_logs(since_epoch=0)[0]["metadata"] == {}


def test_telemetry_rejects_invalid_numeric_fields(temp_data_dir):
    init_db()

    try:
        telemetry_store.record_llm_telemetry(
            operation="synthesis",
            provider="anthropic",
            model="claude",
            status="success",
            duration_ms=-1,
            output_chars=42,
            used_fallback=False,
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("LLM telemetry should reject negative durations")

    assert "duration_ms" in message
