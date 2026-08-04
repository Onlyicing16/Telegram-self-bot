"""
Performance metrics collection.

Collects latency, count, and size metrics from every layer. Metrics
are accumulated in memory and flushed to Supabase in batches by the
batch_writer module. This is lightweight — no per-call database writes.

Metric types:
  - Latency: telethon_rpc, supabase_query, provider_response,
    memory_retrieval, prompt_build, tool_execution, background_task
  - Count:  handler_invoked, tool_called, save_executed, delete_executed
  - Size:   buffer_bytes, message_length
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

from backend.diagnostics_system.structured_logger import log_trace_event
from backend.diagnostics_system.trace_context import get_trace_id, get_request_id

_MAX_RING = 200
_metrics_ring: deque = deque(maxlen=_MAX_RING)


def record_metric(
    metric_name: str,
    value: float,
    unit: str = "ms",
    **tags: Any,
) -> None:
    """Record a metric and add it to the in-memory ring buffer.

    The batch_writer will flush this to Supabase periodically.
    """
    entry = {
        "metric_name": metric_name,
        "value": round(value, 3),
        "unit": unit,
        "tags": {k: str(v) for k, v in tags.items() if v is not None} if tags else None,
        "trace_id": get_trace_id(),
        "request_id": get_request_id(),
    }
    _metrics_ring.append(entry)


def record_latency(
    metric_name: str,
    start_time: float,
    **tags: Any,
) -> float:
    """Record latency from a start_time (time.perf_counter()) and return ms.

    Usage::

        t0 = time.perf_counter()
        result = await some_call()
        record_latency("telethon_rpc", t0, function="send_message")
    """
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    record_metric(metric_name, elapsed_ms, unit="ms", **tags)
    return elapsed_ms


def get_metrics_snapshot() -> list[dict[str, Any]]:
    """Return all buffered metrics (does not clear the buffer)."""
    return list(_metrics_ring)


def drain_metrics() -> list[dict[str, Any]]:
    """Return all buffered metrics and clear the buffer.

    Called by the batch_writer when flushing to Supabase.
    """
    items = list(_metrics_ring)
    _metrics_ring.clear()
    return items


def get_metric_names() -> list[str]:
    """Return unique metric names in the ring."""
    return list({e["metric_name"] for e in _metrics_ring})
