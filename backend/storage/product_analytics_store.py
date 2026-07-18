import json
import time
import uuid
from typing import Any

from adapters.database_adapter import execute, fetchall
from config import settings
from storage.models import ProductAnalyticsEventRow, ProductAnalyticsEventWrite


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


def record_product_analytics_event(
    *,
    anonymous_id: str,
    event_type: str,
    user_id: str | None = None,
    properties: dict[str, Any] | None = None,
    created_at_epoch: float | None = None,
) -> None:
    event = ProductAnalyticsEventWrite.model_validate(
        {
            "anonymous_id": anonymous_id,
            "event_type": event_type,
            "user_id": user_id,
            "properties": properties,
            "created_at_epoch": time.time() if created_at_epoch is None else created_at_epoch,
        }
    )
    execute(
        """
        INSERT INTO product_analytics_events (
            id, user_id, anonymous_id, event_type, properties_json, created_at_epoch
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            event.user_id,
            event.anonymous_id,
            event.event_type,
            _dump_properties(event.properties),
            event.created_at_epoch,
        ),
    )


def list_recent_product_analytics_events(*, since_epoch: float) -> list[dict[str, Any]]:
    rows = fetchall(
        """
        SELECT id, user_id, anonymous_id, event_type, properties_json, created_at_epoch
        FROM product_analytics_events
        WHERE created_at_epoch >= ?
        ORDER BY created_at_epoch DESC
        LIMIT ?
        """,
        (since_epoch, settings.dashboard_query_max_rows),
    )
    normalized: list[dict[str, Any]] = []
    for row in rows:
        row["properties"] = _load_properties(row.pop("properties_json", None))
        normalized.append(ProductAnalyticsEventRow.model_validate(row).model_dump())
    return normalized
