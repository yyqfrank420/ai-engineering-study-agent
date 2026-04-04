import json
import time
import uuid

from adapters.database_adapter import execute, fetchall


def _dump_metadata(metadata: dict | None) -> str | None:
    if not metadata:
        return None
    return json.dumps(metadata, sort_keys=True)


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
            user_id,
            method,
            path,
            status_code,
            latency_ms,
            ip_address,
            user_agent,
            _dump_metadata(metadata),
            created_at_epoch or time.time(),
        ),
    )


def list_recent_http_request_logs(*, since_epoch: float, user_id: str | None = None) -> list[dict]:
    if user_id:
        return fetchall(
            """
            SELECT id, user_id, method, path, status_code, latency_ms,
                   ip_address, user_agent, metadata_json, created_at_epoch
            FROM http_request_logs
            WHERE created_at_epoch >= ? AND user_id = ?
            ORDER BY created_at_epoch DESC
            """,
            (since_epoch, user_id),
        )

    return fetchall(
        """
        SELECT id, user_id, method, path, status_code, latency_ms,
               ip_address, user_agent, metadata_json, created_at_epoch
        FROM http_request_logs
        WHERE created_at_epoch >= ?
        ORDER BY created_at_epoch DESC
        """,
        (since_epoch,),
    )


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
            user_id,
            thread_id,
            operation,
            provider,
            model,
            status,
            duration_ms,
            output_chars,
            used_fallback,
            error_type,
            _dump_metadata(metadata),
            created_at_epoch or time.time(),
        ),
    )


def list_recent_llm_telemetry(*, since_epoch: float, user_id: str | None = None) -> list[dict]:
    if user_id:
        return fetchall(
            """
            SELECT id, user_id, thread_id, operation, provider, model, status,
                   duration_ms, output_chars, used_fallback, error_type, metadata_json, created_at_epoch
            FROM llm_telemetry
            WHERE created_at_epoch >= ? AND user_id = ?
            ORDER BY created_at_epoch DESC
            """,
            (since_epoch, user_id),
        )

    return fetchall(
        """
        SELECT id, user_id, thread_id, operation, provider, model, status,
               duration_ms, output_chars, used_fallback, error_type, metadata_json, created_at_epoch
        FROM llm_telemetry
        WHERE created_at_epoch >= ?
        ORDER BY created_at_epoch DESC
        """,
        (since_epoch,),
    )
