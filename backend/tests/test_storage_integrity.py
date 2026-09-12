import json
from concurrent.futures import ThreadPoolExecutor

from adapters.database_adapter import execute, init_db
from storage import (
    analytics_event_store,
    product_analytics_store,
    runtime_state_store,
    telemetry_store,
)
from storage.profile_store import upsert_profile
from storage.rate_limit_store import RateLimitDimension, reserve_rate_limit
from storage.retention import prune_expired_observability_data
from storage.thread_store import (
    create_thread,
    get_completed_turn,
    get_graph,
    get_graph_artifact,
    get_thread,
    persist_turn,
    save_graph,
)
from storage.message_store import get_messages


def test_runtime_state_request_events_and_pruning(temp_data_dir):
    init_db()
    upsert_profile("user-1", "friend@example.com")

    runtime_state_store.record_request_event("user-1", "chat", created_at_epoch=10)
    runtime_state_store.record_request_event("user-1", "chat", created_at_epoch=20)
    runtime_state_store.record_request_event("user-1", "node", created_at_epoch=30)

    assert [
        row["created_at_epoch"]
        for row in runtime_state_store.get_recent_request_events(
            "user-1", "chat", since_epoch=15
        )
    ] == [20]

    runtime_state_store.prune_request_events(older_than_epoch=25)

    assert (
        runtime_state_store.get_recent_request_events("user-1", "chat", since_epoch=0)
        == []
    )
    assert (
        len(
            runtime_state_store.get_recent_request_events(
                "user-1", "node", since_epoch=0
            )
        )
        == 1
    )


def test_rate_limit_reservations_are_atomic_and_expire(temp_data_dir):
    init_db()
    dimensions = (
        RateLimitDimension(
            scope="otp-verify-email",
            identifier="friend@example.com",
            event_type="otp_verify_email",
            limit=1,
            window_s=10,
        ),
    )

    assert reserve_rate_limit(dimensions, created_at_epoch=100)
    assert reserve_rate_limit(dimensions, created_at_epoch=101) is None
    assert reserve_rate_limit(dimensions, created_at_epoch=101, bypass_limits=True)
    assert reserve_rate_limit(dimensions, created_at_epoch=111) is not None


def test_concurrent_rate_limit_reservations_admit_only_one(temp_data_dir):
    init_db()
    dimensions = (
        RateLimitDimension(
            scope="internal-login-ip",
            identifier="127.0.0.1",
            event_type="internal_login_failure",
            limit=1,
            window_s=60,
        ),
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        reservations = list(
            executor.map(
                lambda _: reserve_rate_limit(dimensions, created_at_epoch=100),
                range(4),
            )
        )

    assert sum(reservation is not None for reservation in reservations) == 1


def test_persist_turn_commits_messages_metadata_and_graph_together(temp_data_dir):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    graph = {"nodes": [{"id": "n1"}], "edges": []}

    assert (
        persist_turn(
            "user-1",
            thread["id"],
            title="RAG",
            user_content="Explain RAG",
            assistant_content="Retrieval-augmented generation…",
            graph_data=graph,
        )
        is True
    )

    assert [message["role"] for message in get_messages("user-1", thread["id"])] == [
        "user",
        "assistant",
    ]
    assert get_thread("user-1", thread["id"])["title"] == "RAG"
    assert get_graph("user-1", thread["id"]) == graph


def test_persist_turn_commits_server_only_graph_contract_with_graph(temp_data_dir):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    graph = {"version": "graph-v1", "nodes": [{"id": "n1"}], "edges": []}
    contract = {"graph_version": "graph-v1", "required_node_ids": ["n1"]}

    assert (
        persist_turn(
            "user-1",
            thread["id"],
            title="RAG",
            user_content="Explain RAG",
            assistant_content="Retrieval-augmented generation…",
            graph_data=graph,
            graph_contract=contract,
        )
        is True
    )

    assert get_graph_artifact("user-1", thread["id"]) == (graph, contract)
    assert "graph_contract" not in get_thread("user-1", thread["id"])


def test_persist_turn_rejects_mismatched_contract_without_partial_turn(temp_data_dir):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")

    try:
        persist_turn(
            "user-1",
            thread["id"],
            title="RAG",
            user_content="Explain RAG",
            assistant_content="Retrieval-augmented generation…",
            graph_data={"version": "graph-v1", "nodes": [], "edges": []},
            graph_contract={"graph_version": "graph-v2"},
        )
    except ValueError as exc:
        assert str(exc) == "graph_contract.graph_version must match graph_data.version"
    else:
        raise AssertionError("persist_turn() should reject a mismatched graph contract")

    assert get_messages("user-1", thread["id"]) == []
    assert get_graph_artifact("user-1", thread["id"]) == (None, None)


def test_get_graph_artifact_discards_invalid_contract_version_and_preserves_graph(
    temp_data_dir,
):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    graph = {"version": "graph-v1", "nodes": [{"id": "n1"}], "edges": []}
    assert persist_turn(
        "user-1",
        thread["id"],
        title="RAG",
        user_content="Explain RAG",
        assistant_content="Retrieval-augmented generation…",
        graph_data=graph,
    )

    invalid_contracts = (
        {"required_node_ids": ["n1"]},
        {"graph_version": "   ", "required_node_ids": ["n1"]},
        {"graph_version": "graph-v2", "required_node_ids": ["n1"]},
    )
    for contract in invalid_contracts:
        execute(
            "UPDATE chat_threads SET graph_contract = ? WHERE id = ? AND user_id = ?",
            (json.dumps(contract), thread["id"], "user-1"),
        )
        assert get_graph_artifact("user-1", thread["id"]) == (graph, None)


def test_legacy_graph_and_view_state_write_preserve_contract_compatibility(
    temp_data_dir,
):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    graph = {"version": "graph-v1", "nodes": [{"id": "n1"}], "edges": []}
    contract = {"graph_version": "graph-v1", "required_node_ids": ["n1"]}
    assert persist_turn(
        "user-1",
        thread["id"],
        title="RAG",
        user_content="Explain RAG",
        assistant_content="Retrieval-augmented generation…",
        graph_data=graph,
        graph_contract=contract,
    )

    updated_view_state = {"viewport": {"x": 1, "y": 2, "k": 1}}
    assert save_graph(
        "user-1",
        thread["id"],
        {"version": "graph-v1", "view_state": updated_view_state},
    )
    assert get_graph_artifact("user-1", thread["id"]) == (
        {**graph, "view_state": updated_view_state},
        contract,
    )

    assert persist_turn(
        "user-1",
        thread["id"],
        title="Legacy graph",
        user_content="Explain legacy graph",
        assistant_content="Legacy answer",
        graph_data={"version": "graph-v2", "nodes": [], "edges": []},
    )
    assert get_graph_artifact("user-1", thread["id"])[1] is None


def test_persist_turn_deduplicates_completed_client_request(temp_data_dir):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")

    first = persist_turn(
        "user-1",
        thread["id"],
        title="Original",
        user_content="Explain RAG",
        assistant_content="Original answer",
        graph_data=None,
        client_request_id="client-turn-1",
    )
    retry = persist_turn(
        "user-1",
        thread["id"],
        title="Retry must not overwrite",
        user_content="Explain RAG",
        assistant_content="Different retry output",
        graph_data=None,
        client_request_id="client-turn-1",
    )

    assert first is True
    assert retry is True
    assert [message["content"] for message in get_messages("user-1", thread["id"])] == [
        "Explain RAG",
        "Original answer",
    ]
    assert get_thread("user-1", thread["id"])["title"] == "Original"
    assert get_completed_turn("user-1", thread["id"], "client-turn-1") == {
        "user_content": "Explain RAG",
        "assistant_content": "Original answer",
    }
    assert get_completed_turn("user-1", thread["id"], "unknown") is None


def test_runtime_state_search_tool_expiry_and_delete(temp_data_dir, monkeypatch):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    thread = create_thread("user-1")
    thread_id = thread["id"]
    monkeypatch.setattr(runtime_state_store.time, "time", lambda: 100.0)

    runtime_state_store.create_search_tool_request(
        "req-1",
        "user-1",
        thread_id,
        expires_at_epoch=110,
    )
    assert (
        runtime_state_store.mark_search_tool_requested("req-1", "user-1", thread_id)
        is True
    )
    assert (
        runtime_state_store.is_search_tool_requested("req-1", "user-1", thread_id)
        is True
    )

    runtime_state_store.delete_search_tool_request("req-1")
    assert (
        runtime_state_store.is_search_tool_requested("req-1", "user-1", thread_id)
        is False
    )

    runtime_state_store.create_search_tool_request(
        "req-expired",
        "user-1",
        thread_id,
        expires_at_epoch=99,
    )
    assert (
        runtime_state_store.mark_search_tool_requested(
            "req-expired", "user-1", thread_id
        )
        is False
    )
    runtime_state_store.prune_search_tool_requests(older_than_epoch=100)
    assert (
        runtime_state_store.is_search_tool_requested("req-expired", "user-1", thread_id)
        is False
    )


def test_runtime_state_active_stream_limits_release_and_prune(
    temp_data_dir, monkeypatch
):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    monkeypatch.setattr(runtime_state_store.time, "time", lambda: 100.0)

    unlimited = runtime_state_store.try_acquire_active_stream(
        "user-1", "chat", limit=0, ttl_s=10
    )
    assert unlimited

    first = runtime_state_store.try_acquire_active_stream(
        "user-1", "chat", limit=1, ttl_s=10
    )
    assert first
    assert (
        runtime_state_store.try_acquire_active_stream(
            "user-1", "chat", limit=1, ttl_s=10
        )
        is None
    )

    runtime_state_store.release_active_stream(first)
    second = runtime_state_store.try_acquire_active_stream(
        "user-1", "chat", limit=1, ttl_s=10
    )
    assert second

    monkeypatch.setattr(runtime_state_store.time, "time", lambda: 200.0)
    runtime_state_store.prune_active_streams(older_than_epoch=200)
    assert runtime_state_store.try_acquire_active_stream(
        "user-1", "chat", limit=1, ttl_s=10
    )

    runtime_state_store.release_active_stream(None)


def test_runtime_state_scopes_active_stream_exclusivity(temp_data_dir, monkeypatch):
    init_db()
    upsert_profile("user-1", "friend@example.com")
    monkeypatch.setattr(runtime_state_store.time, "time", lambda: 100.0)

    first = runtime_state_store.try_acquire_active_stream(
        "user-1", "chat", limit=1, ttl_s=60, scope_id="thread-1"
    )
    assert first
    assert (
        runtime_state_store.try_acquire_active_stream(
            "user-1", "chat", limit=1, ttl_s=60, scope_id="thread-1"
        )
        is None
    )
    second = runtime_state_store.try_acquire_active_stream(
        "user-1", "chat", limit=1, ttl_s=60, scope_id="thread-2"
    )
    assert second

    runtime_state_store.release_active_stream(first)
    runtime_state_store.release_active_stream(second)


def test_product_analytics_round_trips_properties_and_ignores_bad_json(temp_data_dir):
    init_db()
    upsert_profile("user-1", "friend@example.com")

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

    http_rows = telemetry_store.list_recent_http_request_logs(
        since_epoch=0, user_id="user-1"
    )
    llm_rows = telemetry_store.list_recent_llm_telemetry(
        since_epoch=0, user_id="user-1"
    )

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
        (
            "bad-metadata",
            "user-1",
            "GET",
            "/health",
            200,
            1,
            None,
            None,
            '"not-dict"',
            10,
        ),
    )

    assert (
        telemetry_store.list_recent_http_request_logs(since_epoch=0)[0]["metadata"]
        == {}
    )


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


def test_generic_analytics_events_round_trip_shape_metrics(temp_data_dir):
    init_db()

    analytics_event_store.record_analytics_event(
        event_name="stream_first_token",
        event_category="stream",
        user_id="user-1",
        session_id="thread-1",
        thread_id="thread-1",
        request_id="request-1",
        trace_id="trace-1",
        client_request_id="client-1",
        numeric_value=321,
        unit="ms",
        properties={"output_type": "chat_response", "nested": {"ok": True}},
        created_at_epoch=20,
    )

    rows = analytics_event_store.list_recent_analytics_events(since_epoch=0)

    assert len(rows) == 1
    assert rows[0]["event_name"] == "stream_first_token"
    assert rows[0]["event_category"] == "stream"
    assert rows[0]["numeric_value"] == 321
    assert rows[0]["properties"] == {
        "output_type": "chat_response",
        "nested": {"ok": True},
    }


def test_observability_retention_prunes_old_rows_atomically(temp_data_dir):
    init_db()
    telemetry_store.record_http_request_log(
        method="GET", path="/old", status_code=200, latency_ms=1, created_at_epoch=10
    )
    telemetry_store.record_llm_telemetry(
        operation="route",
        provider="anthropic",
        model="claude",
        status="success",
        duration_ms=1,
        output_chars=1,
        used_fallback=False,
        created_at_epoch=10,
    )
    analytics_event_store.record_analytics_event(
        event_name="old", event_category="test", created_at_epoch=10
    )
    product_analytics_store.record_product_analytics_event(
        anonymous_id="anon", event_type="old", created_at_epoch=10
    )
    analytics_event_store.record_analytics_event(
        event_name="new", event_category="test", created_at_epoch=30
    )

    prune_expired_observability_data(older_than_epoch=20)

    assert telemetry_store.list_recent_http_request_logs(since_epoch=0) == []
    assert telemetry_store.list_recent_llm_telemetry(since_epoch=0) == []
    assert (
        product_analytics_store.list_recent_product_analytics_events(since_epoch=0)
        == []
    )
    assert [
        row["event_name"]
        for row in analytics_event_store.list_recent_analytics_events(since_epoch=0)
    ] == ["new"]
