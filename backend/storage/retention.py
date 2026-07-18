from adapters.database_adapter import _adapt_query, _connect


_RETENTION_QUERIES = (
    "DELETE FROM product_analytics_events WHERE created_at_epoch < ?",
    "DELETE FROM http_request_logs WHERE created_at_epoch < ?",
    "DELETE FROM llm_telemetry WHERE created_at_epoch < ?",
    "DELETE FROM analytics_events WHERE created_at_epoch < ?",
)


def prune_expired_observability_data(*, older_than_epoch: float) -> None:
    """Apply the configured observability retention window in one transaction."""
    with _connect() as conn:
        for query in _RETENTION_QUERIES:
            conn.execute(
                _adapt_query(query),
                (older_than_epoch,),
            )
