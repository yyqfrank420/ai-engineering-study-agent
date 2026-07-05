from __future__ import annotations

import json
import time
import uuid
from typing import Any

from adapters.database_adapter import execute, fetchall
from config import settings
from storage.models import AnalyticsEventRow, AnalyticsEventWrite


def _dump_properties(properties: dict[str, Any] | None) -> str | None:
    if not properties:
        return None
    return json.dumps(properties, sort_keys=True)


def _load_properties(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def record_analytics_event(
    *,
    event_name: str,
    event_category: str,
    user_id: str | None = None,
    anonymous_id: str | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    client_request_id: str | None = None,
    schema_version: int | None = None,
    app_version: str = "0.1.0",
    environment: str | None = None,
    numeric_value: float | None = None,
    unit: str | None = None,
    properties: dict[str, Any] | None = None,
    created_at_epoch: float | None = None,
) -> None:
    event = AnalyticsEventWrite.model_validate(
        {
            "event_name": event_name,
            "event_category": event_category,
            "user_id": user_id,
            "anonymous_id": anonymous_id,
            "session_id": session_id,
            "thread_id": thread_id,
            "request_id": request_id,
            "trace_id": trace_id,
            "client_request_id": client_request_id,
            "schema_version": schema_version or settings.analytics_event_schema_version,
            "app_version": app_version,
            "environment": environment or settings.otel_environment,
            "numeric_value": numeric_value,
            "unit": unit,
            "properties": properties or {},
            "created_at_epoch": time.time() if created_at_epoch is None else created_at_epoch,
        }
    )
    execute(
        """
        INSERT INTO analytics_events (
            id, event_name, event_category, user_id, anonymous_id, session_id,
            thread_id, request_id, trace_id, client_request_id, schema_version,
            app_version, environment, numeric_value, unit, properties_json, created_at_epoch
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            event.event_name,
            event.event_category,
            event.user_id,
            event.anonymous_id,
            event.session_id,
            event.thread_id,
            event.request_id,
            event.trace_id,
            event.client_request_id,
            event.schema_version,
            event.app_version,
            event.environment,
            event.numeric_value,
            event.unit,
            _dump_properties(event.properties),
            event.created_at_epoch,
        ),
    )


def list_recent_analytics_events(*, since_epoch: float, event_category: str | None = None) -> list[dict[str, Any]]:
    where = "created_at_epoch >= ?"
    params: tuple[Any, ...] = (since_epoch,)
    if event_category:
        where += " AND event_category = ?"
        params = (since_epoch, event_category)

    rows = fetchall(
        f"""
        SELECT id, event_name, event_category, user_id, anonymous_id, session_id,
               thread_id, request_id, trace_id, client_request_id, schema_version,
               app_version, environment, numeric_value, unit, properties_json, created_at_epoch
        FROM analytics_events
        WHERE {where}
        ORDER BY created_at_epoch DESC
        """,
        params,
    )
    normalized: list[dict[str, Any]] = []
    for row in rows:
        row["properties"] = _load_properties(row.pop("properties_json", None))
        normalized.append(AnalyticsEventRow.model_validate(row).model_dump())
    return normalized
