"""
Production Diagnostic & Trace System — public API.

This package provides:
  - TraceContext: trace_id / request_id / correlation_id propagation
  - Structured logging (machine-readable JSON to stdout)
  - Performance metrics collection
  - Batched Supabase persistence with retention

All existing trace/diagnostic infrastructure (backend.diagnostics,
backend.runtime.tracer, backend.health) continues to work unchanged.
This system ADDS structured trace persistence on top.

Usage::

    from backend.diagnostics_system import trace_step, trace_error, measure

    with measure("service", "save_service", "execute_save") as m:
        result = await save_service.execute_save(...)
        m.set_context(save_code=result)
        # on exit: trace_step records started→finished with duration

    try:
        ...
    except Exception as exc:
        trace_error("service", "save_service", "execute_save", exc)
        raise
"""
from backend.diagnostics_system.trace_context import (
    TraceContext,
    new_trace,
    new_request,
    get_trace_context,
    get_trace_id,
    get_request_id,
    get_correlation_id,
)
from backend.diagnostics_system.structured_logger import (
    structured_log,
    log_trace_event,
    log_error_event,
)
from backend.diagnostics_system.metrics import (
    record_metric,
    record_latency,
    get_metrics_snapshot,
)
from backend.diagnostics_system.batch_writer import (
    flush_traces,
    flush_metrics,
    start_batch_writer,
    stop_batch_writer,
    set_db_client,
)
from backend.diagnostics_system.instrument import (
    measure,
    trace_step,
    trace_error,
    trace_background,
    TraceTimer,
)

__all__ = [
    "TraceContext",
    "new_trace",
    "new_request",
    "get_trace_context",
    "get_trace_id",
    "get_request_id",
    "get_correlation_id",
    "structured_log",
    "log_trace_event",
    "log_error_event",
    "record_metric",
    "record_latency",
    "get_metrics_snapshot",
    "flush_traces",
    "flush_metrics",
    "start_batch_writer",
    "stop_batch_writer",
    "set_db_client",
    "measure",
    "trace_step",
    "trace_error",
    "trace_background",
    "TraceTimer",
]
