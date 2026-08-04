"""
Structured logger — machine-readable JSON to stdout.

Every log line is a JSON object with consistent fields so Render log
aggregation and grep can parse them uniformly. This complements the
existing ``backend.runtime.tracer`` (which uses a grep-friendly
``[TRACE]`` text format) — both can coexist without conflict.

Fields:
  - timestamp (ISO 8601 UTC)
  - trace_id
  - request_id
  - correlation_id
  - level (INFO/WARN/ERROR)
  - layer
  - module
  - function
  - event
  - status
  - duration_ms
  - message
  - context (JSON object of safe extra fields)
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from backend.diagnostics_system.trace_context import (
    get_correlation_id,
    get_request_id,
    get_trace_id,
)

_logger = logging.getLogger("backend.diagnostics")


def structured_log(
    level: int,
    layer: str,
    module: str,
    event: str,
    *,
    function: str | None = None,
    status: str = "info",
    duration_ms: float | None = None,
    message: str | None = None,
    **context: Any,
) -> None:
    """Emit a structured JSON log line to stdout."""
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": get_trace_id(),
        "request_id": get_request_id(),
        "level": logging.getLevelName(level),
        "layer": layer,
        "module": module,
        "event": event,
        "status": status,
    }
    if get_correlation_id():
        record["correlation_id"] = get_correlation_id()
    if function:
        record["function"] = function
    if duration_ms is not None:
        record["duration_ms"] = round(duration_ms, 2)
    if message:
        record["message"] = message
    if context:
        safe: dict[str, Any] = {}
        for k, v in context.items():
            if v is None:
                continue
            try:
                json.dumps(v)
                safe[k] = v
            except (TypeError, ValueError):
                safe[k] = str(v)
        if safe:
            record["context"] = safe

    line = json.dumps(record, default=str, separators=(",", ":"))
    _logger.log(level, line)


def log_trace_event(
    layer: str,
    module: str,
    event: str,
    *,
    function: str | None = None,
    status: str = "success",
    duration_ms: float | None = None,
    message: str | None = None,
    **context: Any,
) -> None:
    """Log a trace event at INFO level."""
    structured_log(
        logging.INFO,
        layer,
        module,
        event,
        function=function,
        status=status,
        duration_ms=duration_ms,
        message=message,
        **context,
    )


def log_error_event(
    layer: str,
    module: str,
    event: str,
    *,
    function: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    stack_trace: str | None = None,
    duration_ms: float | None = None,
    **context: Any,
) -> None:
    """Log an error event at ERROR level."""
    ctx: dict[str, Any] = dict(context)
    if error_type:
        ctx["error_type"] = error_type
    if error_message:
        ctx["error_message"] = error_message
    if stack_trace:
        ctx["stack_trace"] = stack_trace
    structured_log(
        logging.ERROR,
        layer,
        module,
        event,
        function=function,
        status="failure",
        duration_ms=duration_ms,
        message=error_message,
        **ctx,
    )
