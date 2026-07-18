from uuid import uuid4

from storage.models import (
    AnalyticsEventRow,
    HttpRequestLogRow,
    LLMTelemetryRow,
    ProductAnalyticsEventRow,
)


def test_storage_rows_normalize_postgres_uuid_values_to_strings():
    event_id = uuid4()
    user_id = uuid4()
    thread_id = uuid4()

    product = ProductAnalyticsEventRow.model_validate(
        {
            "id": event_id,
            "user_id": user_id,
            "anonymous_id": "anon-1",
            "event_type": "chat_sent",
            "properties": {},
            "created_at_epoch": 1,
        }
    )
    http = HttpRequestLogRow.model_validate(
        {
            "id": event_id,
            "user_id": user_id,
            "method": "GET",
            "path": "/api/prepare",
            "status_code": 200,
            "latency_ms": 10,
            "metadata": {},
            "created_at_epoch": 1,
        }
    )
    llm = LLMTelemetryRow.model_validate(
        {
            "id": event_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "operation": "synthesis",
            "provider": "anthropic",
            "model": "claude",
            "status": "ok",
            "duration_ms": 10,
            "output_chars": 20,
            "used_fallback": False,
            "metadata": {},
            "created_at_epoch": 1,
        }
    )
    analytics = AnalyticsEventRow.model_validate(
        {
            "id": event_id,
            "event_name": "request_completed",
            "event_category": "request",
            "schema_version": 1,
            "app_version": "0.1.0",
            "environment": "production",
            "properties": {},
            "created_at_epoch": 1,
        }
    )

    assert product.id == str(event_id)
    assert product.user_id == str(user_id)
    assert http.id == str(event_id)
    assert http.user_id == str(user_id)
    assert llm.id == str(event_id)
    assert llm.user_id == str(user_id)
    assert llm.thread_id == str(thread_id)
    assert analytics.id == str(event_id)
