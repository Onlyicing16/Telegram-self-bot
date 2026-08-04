"""
Automatic Exception Context Enrichment.

When an exception occurs, this module automatically attaches:
  - trace_id, request_id, session_id
  - current command, chat_id, msg_id, user_id
  - current handler, service, provider
  - stack trace, error type, root cause
  - retry count (if applicable)

The context is gathered from contextvars (TraceContext + ExceptionContext)
so it propagates automatically through asyncio without manual parameter
passing.

Usage in exception handlers::

    from backend.diagnostics_system.exc_context import enrich_exception, get_exc_context

    try:
        ...
    except Exception as exc:
        ctx = get_exc_context(exc, command="save", chat_id=123, ...)
        # ctx is a dict with all auto-gathered fields
"""
from __future__ import annotations

import contextvars
import traceback as tb_module
from typing import Any

from backend.diagnostics_system.debug_config import should_trace_error, get_session_id
from backend.diagnostics_system.trace_context import get_trace_id, get_request_id, get_correlation_id

_exc_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "diagnostics_exc_context", default={}
)


def set_exc_context(**kwargs: Any) -> contextvars.Token[dict[str, Any]]:
    """Set exception context fields. Returns a token for restoration."""
    current = _exc_ctx.get()
    merged = {**current, **kwargs}
    return _exc_ctx.set(merged)


def reset_exc_context(token: contextvars.Token[dict[str, Any]]) -> None:
    _exc_ctx.reset(token)


def update_exc_context(**kwargs: Any) -> None:
    """Update exception context fields in-place (no token needed)."""
    current = dict(_exc_ctx.get())
    current.update(kwargs)
    _exc_ctx.set(current)


def clear_exc_context() -> None:
    _exc_ctx.set({})


def get_exc_context(exc: BaseException | None = None, **extra: Any) -> dict[str, Any]:
    """Build a full exception context dict.

    Gathers from:
      - contextvars (trace IDs, current handler/service/provider/command)
      - the exception itself (type, message, stack trace)
      - extra kwargs passed by the caller
    """
    ctx: dict[str, Any] = {}

    ctx["trace_id"] = get_trace_id()
    ctx["request_id"] = get_request_id()
    ctx["session_id"] = get_session_id()
    cid = get_correlation_id()
    if cid:
        ctx["correlation_id"] = cid

    auto = _exc_ctx.get()
    for k, v in auto.items():
        if v is not None:
            ctx[k] = v

    if exc is not None:
        ctx["error_type"] = type(exc).__name__
        ctx["error_message"] = str(exc)[:500]
        ctx["stack_trace"] = "".join(
            tb_module.format_exception(type(exc), exc, exc.__traceback__)
        )[:2000]
        cause = exc.__cause__
        if cause is not None:
            ctx["root_cause_type"] = type(cause).__name__
            ctx["root_cause_message"] = str(cause)[:300]

    for k, v in extra.items():
        if v is not None:
            ctx[k] = v

    return ctx


class exc_context_scope:
    """Context manager that sets exception context fields and restores on exit."""

    __slots__ = ("_kwargs", "_token")

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._token: contextvars.Token[dict[str, Any]] | None = None

    def __enter__(self) -> "exc_context_scope":
        self._token = set_exc_context(**self._kwargs)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if self._token is not None:
            reset_exc_context(self._token)
        return False
