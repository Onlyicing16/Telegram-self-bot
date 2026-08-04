"""
TraceContext — trace ID / request ID / correlation ID / session_id propagation.

Uses Python ``contextvars`` so trace context propagates correctly
across asyncio tasks without explicit threading. Each incoming event
gets a fresh TraceContext. Child operations inherit the parent's IDs.

Trace ID:       Groups all steps in one logical execution flow.
Request ID:     Unique per incoming event/request.
Session ID:     Unique per process restart (from debug_config).
Correlation ID: Links related traces across system boundaries (optional).
"""
from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.diagnostics_system.debug_config import get_session_id


@dataclass(frozen=True)
class TraceContext:
    """Immutable trace context propagated via contextvars."""

    trace_id: str
    request_id: str
    session_id: str = "-"
    correlation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_ctx: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "diagnostics_trace_ctx", default=None
)


def _short_uuid() -> str:
    return uuid.uuid4().hex[:12]


def new_trace(correlation_id: str | None = None, **extra: Any) -> TraceContext:
    """Create a fresh TraceContext and set it as the current context.

    Returns the new context so callers can store/restore it.
    """
    ctx = TraceContext(
        trace_id=_short_uuid(),
        request_id=_short_uuid(),
        session_id=get_session_id(),
        correlation_id=correlation_id,
        extra=dict(extra) if extra else {},
    )
    _ctx.set(ctx)
    return ctx


def new_request(correlation_id: str | None = None, **extra: Any) -> TraceContext:
    """Create a new request within the current trace (new request_id, same trace_id).

    If no trace context exists, creates a fresh trace.
    """
    parent = _ctx.get()
    if parent is not None:
        ctx = TraceContext(
            trace_id=parent.trace_id,
            request_id=_short_uuid(),
            session_id=parent.session_id,
            correlation_id=correlation_id or parent.correlation_id,
            extra={**parent.extra, **extra} if extra else parent.extra,
        )
    else:
        ctx = new_trace(correlation_id=correlation_id, **extra)
    _ctx.set(ctx)
    return ctx


def get_trace_context() -> TraceContext | None:
    """Return the current trace context, or None if no trace is active."""
    return _ctx.get()


def get_trace_id() -> str:
    ctx = _ctx.get()
    return ctx.trace_id if ctx else "-"


def get_request_id() -> str:
    ctx = _ctx.get()
    return ctx.request_id if ctx else "-"


def get_correlation_id() -> str | None:
    ctx = _ctx.get()
    return ctx.correlation_id if ctx else None


def set_trace_context(ctx: TraceContext) -> contextvars.Token[TraceContext | None]:
    """Explicitly set a trace context (e.g. restored from a parent task).

    Returns the token for restoration via reset_trace_context.
    """
    return _ctx.set(ctx)


def reset_trace_context(token: contextvars.Token[TraceContext | None]) -> None:
    """Reset trace context to a previous state."""
    _ctx.reset(token)
