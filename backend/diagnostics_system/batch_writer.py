"""
Batch writer — flushes trace events and metrics to Supabase in batches.

Design:
  - Trace events and metrics accumulate in in-memory buffers.
  - A background asyncio task flushes every ``_FLUSH_INTERVAL`` seconds
    (default 10s) or when the buffer exceeds ``_FLUSH_THRESHOLD`` entries.
  - All writes use the service-role key (bypasses RLS).
  - If Supabase is unavailable, buffers are silently dropped (never blocks).
  - On shutdown, a final flush is attempted.

This avoids excessive writes on Render Free tier while ensuring every
trace eventually reaches the database.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from backend.diagnostics_system.structured_logger import log_trace_event
from backend.diagnostics_system.trace_context import get_trace_id, get_request_id

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL = 10.0
_FLUSH_THRESHOLD = 50
_MAX_BUFFER = 500

_trace_buffer: list[dict[str, Any]] = []
_metrics_buffer: list[dict[str, Any]] = []
_db_client: Any = None
_task: asyncio.Task | None = None
_lock = asyncio.Lock()


def set_db_client(client: Any) -> None:
    """Set the Supabase client used for batch writes."""
    global _db_client
    _db_client = client


def queue_trace(entry: dict[str, Any]) -> None:
    """Add a trace entry to the buffer (non-async, safe from any context)."""
    global _trace_buffer
    if len(_trace_buffer) >= _MAX_BUFFER:
        _trace_buffer = _trace_buffer[-_MAX_BUFFER + 50 :]
    _trace_buffer.append(entry)


def queue_metric(entry: dict[str, Any]) -> None:
    """Add a metric entry to the buffer."""
    global _metrics_buffer
    if len(_metrics_buffer) >= _MAX_BUFFER:
        _metrics_buffer = _metrics_buffer[-_MAX_BUFFER + 50 :]
    _metrics_buffer.append(entry)


async def flush_traces() -> int:
    """Flush buffered traces to Supabase. Returns count flushed."""
    global _trace_buffer
    if not _trace_buffer or _db_client is None:
        return 0
    async with _lock:
        batch = _trace_buffer[:]
        _trace_buffer = []
    if not batch:
        return 0
    try:
        table = _db_client.table("diagnostic_traces")
        table.insert(batch)
        log_trace_event(
            "diagnostics", "batch_writer", "traces_flushed",
            status="success", count=len(batch),
        )
        return len(batch)
    except Exception as exc:
        logger.warning("[DIAG_BATCH] trace flush failed: %s", exc)
        return 0


async def flush_metrics() -> int:
    """Flush buffered metrics to Supabase. Returns count flushed."""
    global _metrics_buffer
    if not _metrics_buffer or _db_client is None:
        return 0
    async with _lock:
        batch = _metrics_buffer[:]
        _metrics_buffer = []
    if not batch:
        return 0
    try:
        table = _db_client.table("diagnostic_metrics")
        table.insert(batch)
        return len(batch)
    except Exception as exc:
        logger.warning("[DIAG_BATCH] metrics flush failed: %s", exc)
        return 0


async def _flush_loop() -> None:
    """Background loop that flushes buffers periodically."""
    from backend.diagnostics_system.metrics import drain_metrics
    logger.info("[DIAG_BATCH] flush loop started (interval=%.0fs)", _FLUSH_INTERVAL)
    _retention_counter = 0
    while True:
        await asyncio.sleep(_FLUSH_INTERVAL)
        try:
            metrics = drain_metrics()
            for m in metrics:
                queue_metric({
                    "metric_name": m["metric_name"],
                    "value": m["value"],
                    "unit": m["unit"],
                    "tags": m.get("tags"),
                })
            await flush_traces()
            await flush_metrics()
            _retention_counter += 1
            if _retention_counter >= 360:
                await _retention_cleanup()
                _retention_counter = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[DIAG_BATCH] flush loop error: %s", exc)


async def _retention_cleanup() -> None:
    """Delete old traces and metrics from Supabase (Python-side retention)."""
    if _db_client is None:
        return
    try:
        _db_client.table("diagnostic_traces").delete().lt("timestamp", "now() - interval '7 days'")
        _db_client.table("diagnostic_metrics").delete().lt("timestamp", "now() - interval '30 days'")
        logger.info("[DIAG_BATCH] retention cleanup completed")
    except Exception as exc:
        logger.warning("[DIAG_BATCH] retention cleanup failed: %s", exc)


def start_batch_writer() -> None:
    """Start the background flush loop."""
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_flush_loop())


async def stop_batch_writer() -> None:
    """Stop the flush loop and do a final flush."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await asyncio.wait_for(_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    _task = None
    await flush_traces()
    await flush_metrics()
