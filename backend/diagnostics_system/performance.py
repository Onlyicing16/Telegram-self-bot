"""
Performance Metrics Aggregation — computes averages and system stats.

Maintains rolling windows of latency samples per category and provides
a snapshot endpoint for the web API. All collection respects the debug
config — when OFF, snapshots return zeros with zero overhead.

Categories tracked:
  - handler_duration
  - db_latency
  - ai_latency
  - telegram_latency
  - tool_execution
  - prompt_build
  - memory_retrieval
  - background_task

System stats:
  - running background tasks (count)
  - memory usage (RSS estimate)
  - CPU estimate (from process time)
  - queue sizes (trace/metric buffers)
"""
from __future__ import annotations

import os
import time
from collections import deque
from typing import Any

from backend.diagnostics_system.debug_config import is_debug
from backend.diagnostics_system.metrics import get_metrics_snapshot

_WINDOW = 100

_latency_windows: dict[str, deque] = {}
_error_counts: dict[str, int] = {}
_total_counts: dict[str, int] = {}


def record_sample(category: str, duration_ms: float, error: bool = False) -> None:
    """Record a latency sample for a category."""
    if not is_debug():
        return
    w = _latency_windows.get(category)
    if w is None:
        w = deque(maxlen=_WINDOW)
        _latency_windows[category] = w
    w.append(duration_ms)
    _total_counts[category] = _total_counts.get(category, 0) + 1
    if error:
        _error_counts[category] = _error_counts.get(category, 0) + 1


def _avg(window: deque) -> float:
    if not window:
        return 0.0
    return round(sum(window) / len(window), 2)


def _p95(window: deque) -> float:
    if not window:
        return 0.0
    sorted_vals = sorted(window)
    idx = int(len(sorted_vals) * 0.95)
    return round(sorted_vals[min(idx, len(sorted_vals) - 1)], 2)


def _memory_rss_kb() -> int:
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        return 0


def _cpu_time() -> float:
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF)
        return round(r.ru_utime + r.ru_stime, 2)
    except Exception:
        return 0.0


def _task_count() -> int:
    try:
        import asyncio
        return len(asyncio.all_tasks())
    except Exception:
        return 0


def get_performance_snapshot() -> dict[str, Any]:
    """Return a complete performance snapshot for the web API."""
    categories = [
        "handler_duration", "db_latency", "ai_latency", "telegram_latency",
        "tool_execution", "prompt_build", "memory_retrieval", "background_task",
    ]

    latencies: dict[str, Any] = {}
    for cat in categories:
        w = _latency_windows.get(cat)
        if w and len(w) > 0:
            latencies[cat] = {
                "avg_ms": _avg(w),
                "p95_ms": _p95(w),
                "samples": len(w),
                "total_calls": _total_counts.get(cat, 0),
                "errors": _error_counts.get(cat, 0),
            }
        else:
            latencies[cat] = {
                "avg_ms": 0.0, "p95_ms": 0.0, "samples": 0,
                "total_calls": _total_counts.get(cat, 0),
                "errors": _error_counts.get(cat, 0),
            }

    from backend.diagnostics_system.batch_writer import _trace_buffer, _metrics_buffer
    from backend.diagnostics_system.debug_config import get_trace_level, get_session_id

    return {
        "session_id": get_session_id(),
        "debug_enabled": is_debug(),
        "trace_level": get_trace_level().name,
        "latencies": latencies,
        "system": {
            "memory_rss_kb": _memory_rss_kb(),
            "cpu_time_s": _cpu_time(),
            "async_tasks": _task_count(),
            "trace_buffer_size": len(_trace_buffer),
            "metrics_buffer_size": len(_metrics_buffer),
        },
        "timestamp": time.time(),
    }
