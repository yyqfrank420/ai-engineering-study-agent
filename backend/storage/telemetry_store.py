import json
import time
import uuid

from adapters.database_adapter import execute, fetchall
from storage.models import HttpRequestLogRow, HttpRequestLogWrite, LLMTelemetryRow, LLMTelemetryWrite


def _dump_metadata(metadata: dict | None) -> str | None:
    if not metadata:
        return None
    return json.dumps(metadata, sort_keys=True)


def _load_metadata(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _list_recent(table: str, columns: str, *, since_epoch: float, user_id: str | None = None) -> list[dict]:
    """Query recent rows from a telemetry table, optionally filtered by user."""
    where = "created_at_epoch >= ?"
    params: tuple = (since_epoch,)
    if user_id:
        where += " AND user_id = ?"
        params = (since_epoch, user_id)
    return fetchall(
        f"SELECT {columns} FROM {table} WHERE {where} ORDER BY created_at_epoch DESC",
        params,
    )


def record_http_request_log(
    *,
    method: str,
    path: str,
    status_code: int,
    latency_ms: int,
    user_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
    created_at_epoch: float | None = None,
) -> None:
    log = HttpRequestLogWrite.model_validate(
        {
            "method": method,
            "path": path,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "metadata": metadata,
            "created_at_epoch": time.time() if created_at_epoch is None else created_at_epoch,
        }
    )
    execute(
        """
        INSERT INTO http_request_logs (
            id, user_id, method, path, status_code, latency_ms,
            ip_address, user_agent, metadata_json, created_at_epoch
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            log.user_id,
            log.method,
            log.path,
            log.status_code,
            log.latency_ms,
            log.ip_address,
            log.user_agent,
            _dump_metadata(log.metadata),
            log.created_at_epoch,
        ),
    )


_HTTP_LOG_COLUMNS = (
    "id, user_id, method, path, status_code, latency_ms, "
    "ip_address, user_agent, metadata_json, created_at_epoch"
)


def list_recent_http_request_logs(*, since_epoch: float, user_id: str | None = None) -> list[dict]:
    rows = _list_recent("http_request_logs", _HTTP_LOG_COLUMNS, since_epoch=since_epoch, user_id=user_id)
    normalized: list[dict] = []
    for row in rows:
        row["metadata"] = _load_metadata(row.pop("metadata_json", None))
        normalized.append(HttpRequestLogRow.model_validate(row).model_dump())
    return normalized


def record_llm_telemetry(
    *,
    operation: str,
    provider: str,
    model: str,
    status: str,
    duration_ms: int,
    output_chars: int,
    used_fallback: bool,
    user_id: str | None = None,
    thread_id: str | None = None,
    error_type: str | None = None,
    metadata: dict | None = None,
    created_at_epoch: float | None = None,
) -> None:
    telemetry = LLMTelemetryWrite.model_validate(
        {
            "operation": operation,
            "provider": provider,
            "model": model,
            "status": status,
            "duration_ms": duration_ms,
            "output_chars": output_chars,
            "used_fallback": used_fallback,
            "user_id": user_id,
            "thread_id": thread_id,
            "error_type": error_type,
            "metadata": metadata,
            "created_at_epoch": time.time() if created_at_epoch is None else created_at_epoch,
        }
    )
    execute(
        """
        INSERT INTO llm_telemetry (
            id, user_id, thread_id, operation, provider, model, status,
            duration_ms, output_chars, used_fallback, error_type, metadata_json, created_at_epoch
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            telemetry.user_id,
            telemetry.thread_id,
            telemetry.operation,
            telemetry.provider,
            telemetry.model,
            telemetry.status,
            telemetry.duration_ms,
            telemetry.output_chars,
            telemetry.used_fallback,
            telemetry.error_type,
            _dump_metadata(telemetry.metadata),
            telemetry.created_at_epoch,
        ),
    )


_LLM_TELEMETRY_COLUMNS = (
    "id, user_id, thread_id, operation, provider, model, status, "
    "duration_ms, output_chars, used_fallback, error_type, metadata_json, created_at_epoch"
)


def list_recent_llm_telemetry(*, since_epoch: float, user_id: str | None = None) -> list[dict]:
    rows = _list_recent("llm_telemetry", _LLM_TELEMETRY_COLUMNS, since_epoch=since_epoch, user_id=user_id)
    normalized: list[dict] = []
    for row in rows:
        row["metadata"] = _load_metadata(row.pop("metadata_json", None))
        normalized.append(LLMTelemetryRow.model_validate(row).model_dump())
    return normalized
