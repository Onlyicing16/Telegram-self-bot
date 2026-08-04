"""
Instrumentation helpers — decorators and context managers.

This module provides the primary API that every other module uses to
add diagnostics without changing their logic:

  - ``measure()``: context manager that records start/finish/duration
  - ``trace_step()``: record a single trace step (fire-and-forget)
  - ``trace_error()``: record an error with full exception details
  - ``trace_background()``: decorator for background task lifecycle tracking
  - ``TraceTimer``: low-level timer for manual start/stop

All functions respect the global debug config. When TRACE_LEVEL=OFF,
they are no-ops with zero overhead (no allocations, no logging, no
database writes).

When tracing is enabled, each call also:
  - Adds a step to the current Timeline (if one exists)
  - Records a performance sample
  - Queues the trace for batched Supabase persistence
"""
from __future__ import annotations

import functools
import logging
import time
import traceback as tb_module
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from backend.diagnostics_system.debug_config import (
    should_trace_error,
    should_trace_normal,
    should_trace_verbose,
)
from backend.diagnostics_system.trace_context import (
    TraceContext,
    get_correlation_id,
    get_request_id,
    get_trace_context,
    get_trace_id,
    new_trace,
    set_trace_context,
    reset_trace_context,
)
from backend.diagnostics_system.structured_logger import (
    log_error_event,
    log_trace_event,
)
from backend.diagnostics_system.metrics import record_latency
from backend.diagnostics_system.batch_writer import queue_trace
from backend.diagnostics_system.timeline import get_timeline
from backend.diagnostics_system.performance import record_sample

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)


def _safe_context(context: dict[str, Any]) -> dict[str, Any]:
    """Filter context to JSON-serializable values."""
    import json
    safe: dict[str, Any] = {}
    for k, v in context.items():
        if v is None:
            continue
        try:
            json.dumps(v)
            safe[k] = v
        except (TypeError, ValueError):
            safe[k] = str(v)
    return safe


class TraceTimer:
    """Manual timer for measuring duration.

    Usage::

        timer = TraceTimer("service", "save_service", "execute_save")
        timer.start()
        result = await some_call()
        timer.finish(status="success", message=result)
    """

    __slots__ = ("_layer", "_module", "_function", "_start", "_ctx")

    def __init__(self, layer: str, module: str, function: str) -> None:
        self._layer = layer
        self._module = module
        self._function = function
        self._start: float = 0.0
        self._ctx: TraceContext | None = None

    def start(self, **context: Any) -> None:
        if not should_trace_normal():
            return
        self._start = time.perf_counter()
        self._ctx = get_trace_context()
        log_trace_event(
            self._layer, self._module, "started",
            function=self._function,
            status="started",
            **context,
        )
        self._queue("started", "started", 0.0, None, context)

    def finish(self, status: str = "success", message: str | None = None, **context: Any) -> float:
        duration_ms = (time.perf_counter() - self._start) * 1000 if self._start else 0.0
        if not should_trace_normal():
            return duration_ms
        log_trace_event(
            self._layer, self._module, "finished",
            function=self._function,
            status=status,
            duration_ms=duration_ms,
            message=message,
            **context,
        )
        record_latency(
            f"{self._layer}_duration",
            self._start if self._start else time.perf_counter(),
            module=self._module,
            function=self._function,
        )
        record_sample(f"{self._layer}_duration", duration_ms, error=(status == "failure"))
        self._queue("finished", status, duration_ms, message, context)
        return duration_ms

    def fail(self, exc: BaseException, **context: Any) -> float:
        duration_ms = (time.perf_counter() - self._start) * 1000 if self._start else 0.0
        if not should_trace_error():
            return duration_ms
        error_type = type(exc).__name__
        error_message = str(exc)[:500]
        stack = "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))[:2000]
        log_error_event(
            self._layer, self._module, "error",
            function=self._function,
            error_type=error_type,
            error_message=error_message,
            stack_trace=stack,
            duration_ms=duration_ms,
            **context,
        )
        record_sample(f"{self._layer}_duration", duration_ms, error=True)
        self._queue("error", "failure", duration_ms, error_message, context,
                     error_type=error_type, error_message=error_message, stack_trace=stack)
        return duration_ms

    def _queue(self, event: str, status: str, duration_ms: float,
               message: str | None, context: dict[str, Any],
               error_type: str | None = None, error_message: str | None = None,
               stack_trace: str | None = None) -> None:
        if not should_trace_normal():
            return
        entry: dict[str, Any] = {
            "trace_id": get_trace_id(),
            "request_id": get_request_id(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "layer": self._layer,
            "module": self._module,
            "function": self._function,
            "event": event,
            "status": status,
            "duration_ms": round(duration_ms, 2),
        }
        cid = get_correlation_id()
        if cid:
            entry["correlation_id"] = cid
        if message:
            entry["message"] = message[:500]
        if error_type:
            entry["error_type"] = error_type
        if error_message:
            entry["error_message"] = error_message[:500]
        if stack_trace:
            entry["stack_trace"] = stack_trace[:2000]
        safe_ctx = _safe_context(context)
        if safe_ctx:
            entry["context"] = safe_ctx
        queue_trace(entry)


class measure:
    """Context manager for tracing a code block's execution.

    Automatically records start, finish (or error), and duration.
    Does NOT suppress exceptions — they propagate to the caller.

    Usage::

        with measure("service", "save_service", "execute_save") as m:
            result = await save(...)
            m.set_context(save_code=result)
    """

    __slots__ = ("_timer", "_context", "_layer", "_module", "_function")

    def __init__(self, layer: str, module: str, function: str, **context: Any) -> None:
        self._timer = TraceTimer(layer, module, function)
        self._context: dict[str, Any] = dict(context)
        self._layer = layer
        self._module = module
        self._function = function

    def set_context(self, **kwargs: Any) -> None:
        self._context.update(kwargs)

    def __enter__(self) -> "measure":
        self._timer.start(**self._context)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if exc_type is not None and exc_val is not None:
            if isinstance(exc_val, BaseException):
                self._timer.fail(exc_val, **self._context)
            return False
        self._timer.finish(status="success", **self._context)
        return False


def trace_step(
    layer: str,
    module: str,
    event: str,
    *,
    function: str | None = None,
    status: str = "success",
    duration_ms: float | None = None,
    message: str | None = None,
    verbose: bool = False,
    **context: Any,
) -> None:
    """Record a single trace step (fire-and-forget).

    The ``verbose`` flag marks events that only appear at VERBOSE level.
    """
    if verbose:
        if not should_trace_verbose():
            return
    elif status == "failure" or status == "error":
        if not should_trace_error():
            return
    else:
        if not should_trace_normal():
            return

    log_trace_event(
        layer, module, event,
        function=function,
        status=status,
        duration_ms=duration_ms,
        message=message,
        verbose=verbose,
        **context,
    )
    entry: dict[str, Any] = {
        "trace_id": get_trace_id(),
        "request_id": get_request_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "layer": layer,
        "module": module,
        "function": function,
        "event": event,
        "status": status,
    }
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 2)
    if message:
        entry["message"] = message[:500]
    cid = get_correlation_id()
    if cid:
        entry["correlation_id"] = cid
    safe_ctx = _safe_context(context)
    if safe_ctx:
        entry["context"] = safe_ctx
    queue_trace(entry)


def trace_error(
    layer: str,
    module: str,
    function: str,
    exc: BaseException,
    **context: Any,
) -> None:
    """Record an error with full exception details (fire-and-forget)."""
    if not should_trace_error():
        return
    error_type = type(exc).__name__
    error_message = str(exc)[:500]
    stack = "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))[:2000]
    log_error_event(
        layer, module, "error",
        function=function,
        error_type=error_type,
        error_message=error_message,
        stack_trace=stack,
        **context,
    )
    entry: dict[str, Any] = {
        "trace_id": get_trace_id(),
        "request_id": get_request_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "layer": layer,
        "module": module,
        "function": function,
        "event": "error",
        "status": "failure",
        "error_type": error_type,
        "error_message": error_message,
        "stack_trace": stack,
    }
    cid = get_correlation_id()
    if cid:
        entry["correlation_id"] = cid
    safe_ctx = _safe_context(context)
    if safe_ctx:
        entry["context"] = safe_ctx
    queue_trace(entry)


def trace_background(task_name: str) -> Callable[[F], F]:
    """Decorator for background task lifecycle tracking.

    Tracks: started, running, sleeping, retrying, stopped, restarted,
    exception, cancelled.

    Usage::

        @trace_background("bio_cron")
        async def _cron_loop():
            while True:
                ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            trace_step("background", task_name, "started", function=func.__name__, status="started")
            attempts = 0
            while True:
                try:
                    trace_step("background", task_name, "running",
                               function=func.__name__, status="running", attempt=attempts)
                    result = await func(*args, **kwargs)
                    trace_step("background", task_name, "stopped",
                               function=func.__name__, status="stopped")
                    return result
                except asyncio.CancelledError:
                    trace_step("background", task_name, "cancelled",
                               function=func.__name__, status="cancelled")
                    raise
                except Exception as exc:
                    attempts += 1
                    trace_error("background", task_name, func.__name__, exc,
                                attempt=attempts, retry_count=attempts)
                    trace_step("background", task_name, "retrying",
                               function=func.__name__, status="retrying", attempt=attempts)
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator


import asyncio  # needed by trace_background wrapper
