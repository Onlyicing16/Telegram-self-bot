"""
Global Debug Configuration — controls all tracing behavior.

Reads from env vars once at startup:
  DEBUG       — "true"/"false" master switch
  TRACE_LEVEL — OFF / ERROR / NORMAL / VERBOSE

When DEBUG=false or TRACE_LEVEL=OFF, all trace functions become no-ops
with zero overhead (early return, no allocations, no logging).

Level hierarchy:
  OFF     — nothing is traced (zero overhead)
  ERROR   — only errors and exceptions are traced
  NORMAL  — errors + start/finish of named steps (default when DEBUG=true)
  VERBOSE — everything, including per-RPC, per-query, background heartbeats

This module is imported by every other diagnostics module. It never
imports anything from the project — it is a leaf dependency.
"""
from __future__ import annotations

import os
from enum import IntEnum

class TraceLevel(IntEnum):
    OFF = 0
    ERROR = 1
    NORMAL = 2
    VERBOSE = 3

_LEVEL_MAP = {
    "off": TraceLevel.OFF,
    "error": TraceLevel.ERROR,
    "normal": TraceLevel.NORMAL,
    "verbose": TraceLevel.VERBOSE,
    "minimal": TraceLevel.NORMAL,
}

_debug_enabled: bool = False
_trace_level: TraceLevel = TraceLevel.OFF
_session_id: str = "-"


def init_config() -> None:
    """Read env vars and set the global config. Called once at startup."""
    global _debug_enabled, _trace_level, _session_id
    raw_debug = os.getenv("DEBUG", "false").lower().strip()
    _debug_enabled = raw_debug in ("true", "1", "yes", "on")

    raw_level = os.getenv("TRACE_LEVEL", "off" if not _debug_enabled else "normal").lower().strip()
    _trace_level = _LEVEL_MAP.get(raw_level, TraceLevel.OFF)

    if _debug_enabled and _trace_level == TraceLevel.OFF:
        _trace_level = TraceLevel.NORMAL

    import uuid
    _session_id = uuid.uuid4().hex[:12]


def reload_config() -> None:
    """Re-read env vars (for runtime level changes without restart)."""
    init_config()


def is_debug() -> bool:
    return _debug_enabled


def get_trace_level() -> TraceLevel:
    return _trace_level


def get_session_id() -> str:
    return _session_id


def should_trace(level: TraceLevel) -> bool:
    """Return True if the current config allows tracing at the given level."""
    if not _debug_enabled and _trace_level == TraceLevel.OFF:
        return False
    return _trace_level >= level


def should_trace_error() -> bool:
    return should_trace(TraceLevel.ERROR)


def should_trace_normal() -> bool:
    return should_trace(TraceLevel.NORMAL)


def should_trace_verbose() -> bool:
    return should_trace(TraceLevel.VERBOSE)


init_config()
