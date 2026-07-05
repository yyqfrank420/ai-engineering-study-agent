from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StorageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductAnalyticsEventWrite(StorageModel):
    anonymous_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    user_id: str | None = None
    properties: dict[str, Any] | None = None
    created_at_epoch: float = Field(ge=0)


class ProductAnalyticsEventRow(StorageModel):
    id: str = Field(min_length=1)
    user_id: str | None = None
    anonymous_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at_epoch: float = Field(ge=0)


class HttpRequestLogWrite(StorageModel):
    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    status_code: int = Field(ge=100, le=599)
    latency_ms: int = Field(ge=0)
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    metadata: dict[str, Any] | None = None
    created_at_epoch: float = Field(ge=0)


class HttpRequestLogRow(StorageModel):
    id: str = Field(min_length=1)
    user_id: str | None = None
    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    status_code: int = Field(ge=100, le=599)
    latency_ms: int = Field(ge=0)
    ip_address: str | None = None
    user_agent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at_epoch: float = Field(ge=0)


class LLMTelemetryWrite(StorageModel):
    operation: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    status: str = Field(min_length=1)
    duration_ms: int = Field(ge=0)
    output_chars: int = Field(ge=0)
    used_fallback: bool
    user_id: str | None = None
    thread_id: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] | None = None
    created_at_epoch: float = Field(ge=0)


class LLMTelemetryRow(StorageModel):
    id: str = Field(min_length=1)
    user_id: str | None = None
    thread_id: str | None = None
    operation: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    status: str = Field(min_length=1)
    duration_ms: int = Field(ge=0)
    output_chars: int = Field(ge=0)
    used_fallback: bool
    error_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at_epoch: float = Field(ge=0)


class AnalyticsEventWrite(StorageModel):
    event_name: str = Field(min_length=1, max_length=120)
    event_category: str = Field(min_length=1, max_length=80)
    user_id: str | None = None
    anonymous_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = None
    thread_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    client_request_id: str | None = None
    schema_version: int = Field(default=1, ge=1)
    app_version: str = Field(default="0.1.0", min_length=1, max_length=40)
    environment: str = Field(default="development", min_length=1, max_length=80)
    numeric_value: float | None = None
    unit: str | None = Field(default=None, max_length=40)
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at_epoch: float = Field(ge=0)


class AnalyticsEventRow(AnalyticsEventWrite):
    id: str = Field(min_length=1)
