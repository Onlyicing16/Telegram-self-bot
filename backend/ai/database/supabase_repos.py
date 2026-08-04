"""
Supabase-backed repository implementations.

Each class wraps the Supabase REST API for a specific AI table.
All calls go through the service-role key (bypasses RLS).
On any error, the operation logs a warning and returns a safe default
(empty list, None, or zero) — never raises.

All methods are synchronous because the Supabase Python client is
synchronous. Callers wrap them in ``asyncio.to_thread()``.

Tracing: every operation emits a ``trace_step`` with table, operation,
duration, and affected-row count. Errors emit ``trace_error``.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.diagnostics_system import trace_step, trace_error
from backend.diagnostics_system.metrics import record_latency

from backend.ai.database.session_repository import SessionRecord, SessionRepository
from backend.ai.database.message_repository import MessageRecord, MessageRepository
from backend.ai.database.memory_repository import MemoryRepository
from backend.ai.database.preferences_repository import PreferencesRecord, PreferencesRepository
from backend.ai.database.provider_stats_repository import ProviderStatsRecord, ProviderStatsRepository
from backend.ai.database.usage_repository import UsageRecord, UsageRepository
from backend.ai.database.tool_history_repository import ToolHistoryRecord, ToolHistoryRepository

from backend.ai.memory.types import MemoryEntry, MemoryQuery, MemoryTier, MemoryCategory

logger = logging.getLogger(__name__)


def _get_client() -> Any:
    """Get the Supabase client from env vars. Returns None if unavailable."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def _safe_execute(label: str, table: str, operation: str, fn: Any) -> Any:
    """Execute a Supabase call with tracing and error handling."""
    t0 = time.perf_counter()
    try:
        result = fn()
        duration = (time.perf_counter() - t0) * 1000
        record_latency("db_latency", t0, table=table, operation=operation)
        count = len(result.data) if hasattr(result, "data") and result.data else 0
        trace_step("database", "ai_repo", operation,
                   function=label, status="success",
                   table=table, operation=operation,
                   duration_ms=round(duration, 2), affected_rows=count)
        return result
    except Exception as exc:
        duration = (time.perf_counter() - t0) * 1000
        trace_error("database", "ai_repo", label, exc,
                    table=table, operation=operation, duration_ms=round(duration, 2))
        logger.warning("Supabase AI repo error in %s (%s.%s): %s", label, table, operation, exc)
        return None


class SupabaseSessionRepository(SessionRepository):
    """Supabase-backed session repository."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, record: SessionRecord) -> SessionRecord:
        data = record.as_dict()
        result = _safe_execute("session_create", "ai_sessions", "insert",
                               lambda: self._client.table("ai_sessions").insert(data).execute())
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        result = _safe_execute("session_get", "ai_sessions", "select",
                               lambda: self._client.table("ai_sessions")
                               .select("*").eq("session_id", session_id).maybe_single().execute())
        if result and result.data:
            return self._row_to_record(result.data)
        return None

    def update(self, session_id: str, updates: dict[str, Any]) -> SessionRecord | None:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = _safe_execute("session_update", "ai_sessions", "update",
                               lambda: self._client.table("ai_sessions")
                               .update(updates).eq("session_id", session_id).execute())
        if result and result.data:
            return self._row_to_record(result.data[0])
        return None

    def list_sessions(self, owner_id: int, limit: int = 50) -> list[SessionRecord]:
        result = _safe_execute("session_list", "ai_sessions", "select",
                               lambda: self._client.table("ai_sessions")
                               .select("*").eq("owner_id", owner_id)
                               .order("updated_at", desc=True).limit(limit).execute())
        if result and result.data:
            return [self._row_to_record(r) for r in result.data]
        return []

    def delete(self, session_id: str) -> bool:
        result = _safe_execute("session_delete", "ai_sessions", "delete",
                               lambda: self._client.table("ai_sessions")
                               .delete().eq("session_id", session_id).execute())
        return bool(result and result.data)

    def _row_to_record(self, row: dict[str, Any]) -> SessionRecord:
        return SessionRecord(
            session_id=row["session_id"],
            owner_id=row["owner_id"],
            provider=row.get("provider", "dummy"),
            model=row.get("model", "dummy-1"),
            status=row.get("status", "active"),
            total_tokens=row.get("total_tokens", 0),
            message_count=row.get("message_count", 0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            metadata=row.get("metadata", {}),
        )


class SupabaseMessageRepository(MessageRepository):
    """Supabase-backed message repository."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, record: MessageRecord) -> MessageRecord:
        data = record.as_dict()
        if "id" in data and data["id"] is None:
            del data["id"]
        result = _safe_execute("message_create", "ai_messages", "insert",
                               lambda: self._client.table("ai_messages").insert(data).execute())
        return record

    def list_messages(self, session_id: str, limit: int = 100) -> list[MessageRecord]:
        result = _safe_execute("message_list", "ai_messages", "select",
                               lambda: self._client.table("ai_messages")
                               .select("*").eq("session_id", session_id)
                               .order("created_at", desc=False).limit(limit).execute())
        if result and result.data:
            return [self._row_to_record(r) for r in result.data]
        return []

    def delete_session_messages(self, session_id: str) -> int:
        result = _safe_execute("message_delete", "ai_messages", "delete",
                               lambda: self._client.table("ai_messages")
                               .delete().eq("session_id", session_id).execute())
        return len(result.data) if result and result.data else 0

    def count(self, session_id: str) -> int:
        result = _safe_execute("message_count", "ai_messages", "select",
                               lambda: self._client.table("ai_messages")
                               .select("id", count="exact").eq("session_id", session_id).execute())
        if result and hasattr(result, "count") and result.count is not None:
            return result.count
        return 0

    def _row_to_record(self, row: dict[str, Any]) -> MessageRecord:
        return MessageRecord(
            id=row.get("id"),
            session_id=row["session_id"],
            owner_id=row["owner_id"],
            role=row.get("role", "user"),
            content=row.get("content", ""),
            token_count=row.get("token_count", 0),
            tool_calls=row.get("tool_calls", []),
            provider=row.get("provider", ""),
            model=row.get("model", ""),
            created_at=row.get("created_at"),
            metadata=row.get("metadata", {}),
        )
