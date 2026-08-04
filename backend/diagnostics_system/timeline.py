"""
Execution Timeline — builds a per-request ordered trace of every step.

Each incoming event gets a Timeline. Steps are added as execution flows
through Router -> Handler -> Service -> AI -> Provider -> DB -> Telegram.
On completion (or error), the timeline is available for inspection
via the web API or structured log.

Design:
  - Timeline lives in a contextvar, auto-propagated via asyncio tasks.
  - Each step records: layer, module, function, start, end, duration, status.
  - When DEBUG=false, Timeline is a no-op stub — zero allocations.
  - Timeline is capped at _MAX_STEPS to prevent memory growth.
"""
from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field
from typing import Any

from backend.diagnostics_system.debug_config import should_trace_normal, should_trace_verbose, TraceLevel

_MAX_STEPS = 100


@dataclass
class TimelineStep:
    layer: str
    module: str
    function: str
    event: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "pending"
    error_type: str | None = None
    error_message: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Timeline:
    trace_id: str
    request_id: str
    session_id: str
    steps: list[TimelineStep] = field(default_factory=list)
    _current_step: TimelineStep | None = field(default=None, repr=False)

    def step(self, layer: str, module: str, function: str, event: str = "step", **context: Any) -> TimelineStep:
        if len(self.steps) >= _MAX_STEPS:
            return TimelineStep("overflow", "", "", "", 0.0)
        s = TimelineStep(
            layer=layer, module=module, function=function, event=event,
            start_time=time.perf_counter(), context=dict(context) if context else {},
        )
        self.steps.append(s)
        self._current_step = s
        return s

    def finish_step(self, step: TimelineStep, status: str = "success", **context: Any) -> None:
        step.end_time = time.perf_counter()
        step.duration_ms = (step.end_time - step.start_time) * 1000
        step.status = status
        if context:
            step.context.update(context)

    def fail_step(self, step: TimelineStep, exc: BaseException, **context: Any) -> None:
        step.end_time = time.perf_counter()
        step.duration_ms = (step.end_time - step.start_time) * 1000
        step.status = "failure"
        step.error_type = type(exc).__name__
        step.error_message = str(exc)[:500]
        if context:
            step.context.update(context)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "step_count": len(self.steps),
            "steps": [
                {
                    "layer": s.layer,
                    "module": s.module,
                    "function": s.function,
                    "event": s.event,
                    "duration_ms": round(s.duration_ms, 2),
                    "status": s.status,
                    "error_type": s.error_type,
                    "error_message": s.error_message,
                    "context": s.context if s.context else None,
                }
                for s in self.steps
            ],
        }

    def summary(self) -> dict[str, Any]:
        ok = sum(1 for s in self.steps if s.status == "success")
        fail = sum(1 for s in self.steps if s.status == "failure")
        total_ms = sum(s.duration_ms for s in self.steps)
        return {
            "trace_id": self.trace_id,
            "step_count": len(self.steps),
            "succeeded": ok,
            "failed": fail,
            "total_duration_ms": round(total_ms, 2),
        }


_timeline_ctx: contextvars.ContextVar[Timeline | None] = contextvars.ContextVar(
    "diagnostics_timeline", default=None
)


class _NullTimeline(Timeline):
    """No-op timeline used when DEBUG=false — zero allocations."""
    def __init__(self) -> None:
        super().__init__(trace_id="-", request_id="-", session_id="-")

    def step(self, layer: str, module: str, function: str, event: str = "step", **context: Any) -> TimelineStep:
        return TimelineStep("", "", "", "", 0.0)

    def finish_step(self, step: TimelineStep, status: str = "success", **context: Any) -> None:
        pass

    def fail_step(self, step: TimelineStep, exc: BaseException, **context: Any) -> None:
        pass

    def to_dict(self) -> dict[str, Any]:
        return {"trace_id": "-", "step_count": 0, "steps": []}

    def summary(self) -> dict[str, Any]:
        return {"trace_id": "-", "step_count": 0, "succeeded": 0, "failed": 0, "total_duration_ms": 0.0}


_NULL = _NullTimeline()


def get_timeline() -> Timeline:
    """Return the current timeline, or a no-op stub if none."""
    tl = _timeline_ctx.get()
    return tl if tl is not None else _NULL


def set_timeline(tl: Timeline) -> contextvars.Token[Timeline | None]:
    return _timeline_ctx.set(tl)


def reset_timeline(token: contextvars.Token[Timeline | None]) -> None:
    _timeline_ctx.reset(token)


def new_timeline(trace_id: str, request_id: str, session_id: str) -> Timeline:
    """Create a new Timeline and set it as current. Returns the timeline."""
    if not should_trace_normal():
        return _NULL
    tl = Timeline(trace_id=trace_id, request_id=request_id, session_id=session_id)
    _timeline_ctx.set(tl)
    return tl
