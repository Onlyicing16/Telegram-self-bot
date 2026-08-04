"""
Supabase-backed repository implementations (part 2).

Memory, Preferences, ProviderStats, Usage, and ToolHistory repos.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from backend.diagnostics_system import trace_step, trace_error
from backend.diagnostics_system.metrics import record_latency

from backend.ai.database.supabase_repos import _safe_execute
from backend.ai.database.memory_repository import MemoryRepository
from backend.ai.database.preferences_repository import PreferencesRecord, PreferencesRepository
from backend.ai.database.provider_stats_repository import ProviderStatsRecord, ProviderStatsRepository
from backend.ai.database.usage_repository import UsageRecord, UsageRepository
from backend.ai.database.tool_history_repository import ToolHistoryRecord, ToolHistoryRepository
from backend.ai.memory.types import MemoryEntry, MemoryQuery, MemoryTier, MemoryCategory

class SupabaseMemoryRepository(MemoryRepository):
    """Supabase-backed memory repository for long-term and permanent memory."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def save(self, entry: MemoryEntry) -> MemoryEntry:
        data = entry.as_dict()
        if data["id"] and data["id"].startswith("mem-"):
            del data["id"]
        if data.get("expires_at") is None:
            data["expires_at"] = None
        result = _safe_execute("memory_save", "ai_memories", "insert",
                               lambda: self._client.table("ai_memories").insert(data).execute())
        return entry

    def query(self, query: MemoryQuery) -> list[MemoryEntry]:
        q = self._client.table("ai_memories").select("*").eq("owner_id", query.owner_id)
        if query.tier:
            q = q.eq("tier", query.tier.value)
        if query.category:
            q = q.eq("category", query.category.value)
        if query.min_importance > 0:
            q = q.gte("importance", query.min_importance)
        q = q.or_(f"expires_at.is.null,expires_at.gt.{datetime.now(timezone.utc).isoformat()}")
        if query.query_text:
            q = q.ilike("content", f"%{query.query_text}%")
        q = q.order("importance", desc=True).limit(query.limit)
        result = _safe_execute("memory_query", "ai_memories", "select", lambda: q.execute())
        if result and result.data:
            return [self._row_to_entry(r) for r in result.data]
        return []

    def delete(self, entry_id: str) -> bool:
        result = _safe_execute("memory_delete", "ai_memories", "delete",
                               lambda: self._client.table("ai_memories")
                               .delete().eq("id", entry_id).execute())
        return bool(result and result.data)

    def delete_expired(self, tier: MemoryTier) -> int:
        now = datetime.now(timezone.utc).isoformat()
        result = _safe_execute("memory_delete_expired", "ai_memories", "delete",
                               lambda: self._client.table("ai_memories")
                               .delete().eq("tier", tier.value)
                               .lt("expires_at", now).execute())
        return len(result.data) if result and result.data else 0

    def count(self, owner_id: int, tier: MemoryTier | None = None) -> int:
        q = self._client.table("ai_memories").select("id", count="exact").eq("owner_id", owner_id)
        if tier:
            q = q.eq("tier", tier.value)
        result = _safe_execute("memory_count", "ai_memories", "select", lambda: q.execute())
        if result and hasattr(result, "count") and result.count is not None:
            return result.count
        return 0

    def _row_to_entry(self, row: dict[str, Any]) -> MemoryEntry:
        return MemoryEntry(
            id=str(row.get("id", "")),
            owner_id=row["owner_id"],
            tier=MemoryTier(row.get("tier", "long")),
            category=MemoryCategory(row.get("category", "summary")),
            content=row.get("content", ""),
            importance=row.get("importance", 0.5),
            created_at=row.get("created_at"),
            expires_at=row.get("expires_at"),
            metadata=row.get("metadata", {}),
        )


class SupabasePreferencesRepository(PreferencesRepository):
    """Supabase-backed preferences repository."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def get_or_create(self, owner_id: int) -> PreferencesRecord:
        existing = self.get(owner_id)
        if existing:
            return existing
        record = PreferencesRecord(owner_id=owner_id)
        data = record.as_dict()
        result = _safe_execute("preferences_create", "ai_preferences", "insert",
                               lambda: self._client.table("ai_preferences").insert(data).execute())
        return record

    def update(self, owner_id: int, updates: dict[str, Any]) -> PreferencesRecord | None:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = _safe_execute("preferences_update", "ai_preferences", "update",
                               lambda: self._client.table("ai_preferences")
                               .update(updates).eq("owner_id", owner_id).execute())
        if result and result.data:
            return self._row_to_record(result.data[0])
        return None

    def get(self, owner_id: int) -> PreferencesRecord | None:
        result = _safe_execute("preferences_get", "ai_preferences", "select",
                               lambda: self._client.table("ai_preferences")
                               .select("*").eq("owner_id", owner_id).maybe_single().execute())
        if result and result.data:
            return self._row_to_record(result.data)
        return None

    def _row_to_record(self, row: dict[str, Any]) -> PreferencesRecord:
        return PreferencesRecord(
            owner_id=row["owner_id"],
            language=row.get("language", "English"),
            personality=row.get("personality", "default"),
            response_style=row.get("response_style", "concise"),
            custom_instructions=row.get("custom_instructions", ""),
            auto_memory=row.get("auto_memory", True),
            auto_tools=row.get("auto_tools", True),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            metadata=row.get("metadata", {}),
        )


class SupabaseProviderStatsRepository(ProviderStatsRepository):
    """Supabase-backed provider statistics repository."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def get_or_create(self, provider_name: str, owner_id: int = 0) -> ProviderStatsRecord:
        existing = self.get(provider_name, owner_id)
        if existing:
            return existing
        record = ProviderStatsRecord(provider_name=provider_name, owner_id=owner_id)
        data = record.as_dict()
        if "id" in data:
            del data["id"]
        _safe_execute("provider_stats_create", "ai_provider_stats", "insert",
                      lambda: self._client.table("ai_provider_stats").insert(data).execute())
        return record

    def record_request(self, provider_name: str, owner_id: int = 0,
                       success: bool = True, prompt_tokens: int = 0,
                       completion_tokens: int = 0, latency_ms: float = 0.0) -> None:
        record = self.get_or_create(provider_name, owner_id)
        new_total = record.total_requests + 1
        new_success = record.successful_requests + (1 if success else 0)
        new_fail = record.failed_requests + (0 if success else 1)
        new_prompt = record.total_prompt_tokens + prompt_tokens
        new_completion = record.total_completion_tokens + completion_tokens
        new_avg = ((record.avg_latency_ms * record.total_requests) + latency_ms) / max(new_total, 1)
        now = datetime.now(timezone.utc).isoformat()
        updates = {
            "total_requests": new_total,
            "successful_requests": new_success,
            "failed_requests": new_fail,
            "total_prompt_tokens": new_prompt,
            "total_completion_tokens": new_completion,
            "avg_latency_ms": round(new_avg, 2),
            "last_request_at": now,
            "updated_at": now,
        }
        _safe_execute("provider_stats_update", "ai_provider_stats", "update",
                      lambda: self._client.table("ai_provider_stats")
                      .update(updates)
                      .eq("provider_name", provider_name)
                      .eq("owner_id", owner_id).execute())

    def get(self, provider_name: str, owner_id: int = 0) -> ProviderStatsRecord | None:
        result = _safe_execute("provider_stats_get", "ai_provider_stats", "select",
                               lambda: self._client.table("ai_provider_stats")
                               .select("*").eq("provider_name", provider_name)
                               .eq("owner_id", owner_id).maybe_single().execute())
        if result and result.data:
            return self._row_to_record(result.data)
        return None

    def list_all(self, owner_id: int = 0) -> list[ProviderStatsRecord]:
        result = _safe_execute("provider_stats_list", "ai_provider_stats", "select",
                               lambda: self._client.table("ai_provider_stats")
                               .select("*").eq("owner_id", owner_id).execute())
        if result and result.data:
            return [self._row_to_record(r) for r in result.data]
        return []

    def _row_to_record(self, row: dict[str, Any]) -> ProviderStatsRecord:
        return ProviderStatsRecord(
            provider_name=row["provider_name"],
            owner_id=row.get("owner_id", 0),
            total_requests=row.get("total_requests", 0),
            successful_requests=row.get("successful_requests", 0),
            failed_requests=row.get("failed_requests", 0),
            total_prompt_tokens=row.get("total_prompt_tokens", 0),
            total_completion_tokens=row.get("total_completion_tokens", 0),
            avg_latency_ms=row.get("avg_latency_ms", 0.0),
            last_request_at=row.get("last_request_at"),
            updated_at=row.get("updated_at"),
        )


class SupabaseUsageRepository(UsageRepository):
    """Supabase-backed usage repository."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, record: UsageRecord) -> UsageRecord:
        data = record.as_dict()
        if "id" in data and data["id"] is None:
            del data["id"]
        _safe_execute("usage_create", "ai_usage", "insert",
                      lambda: self._client.table("ai_usage").insert(data).execute())
        return record

    def total_tokens(self, owner_id: int) -> int:
        result = _safe_execute("usage_total", "ai_usage", "select",
                               lambda: self._client.table("ai_usage")
                               .select("total_tokens").eq("owner_id", owner_id).execute())
        if result and result.data:
            return sum(r.get("total_tokens", 0) for r in result.data)
        return 0

    def daily_tokens(self, owner_id: int, date: str) -> int:
        start = f"{date}T00:00:00+00:00"
        end = f"{date}T23:59:59+00:00"
        result = _safe_execute("usage_daily", "ai_usage", "select",
                               lambda: self._client.table("ai_usage")
                               .select("total_tokens").eq("owner_id", owner_id)
                               .gte("created_at", start).lte("created_at", end).execute())
        if result and result.data:
            return sum(r.get("total_tokens", 0) for r in result.data)
        return 0

    def recent(self, owner_id: int, limit: int = 50) -> list[UsageRecord]:
        result = _safe_execute("usage_recent", "ai_usage", "select",
                               lambda: self._client.table("ai_usage")
                               .select("*").eq("owner_id", owner_id)
                               .order("created_at", desc=True).limit(limit).execute())
        if result and result.data:
            return [self._row_to_record(r) for r in result.data]
        return []

    def _row_to_record(self, row: dict[str, Any]) -> UsageRecord:
        return UsageRecord(
            id=row.get("id"),
            owner_id=row["owner_id"],
            session_id=row.get("session_id", ""),
            provider=row.get("provider", ""),
            model=row.get("model", ""),
            prompt_tokens=row.get("prompt_tokens", 0),
            completion_tokens=row.get("completion_tokens", 0),
            total_tokens=row.get("total_tokens", 0),
            estimated_cost_usd=row.get("estimated_cost_usd", 0.0),
            latency_ms=row.get("latency_ms", 0.0),
            created_at=row.get("created_at"),
            metadata=row.get("metadata", {}),
        )


class SupabaseToolHistoryRepository(ToolHistoryRepository):
    """Supabase-backed tool history repository."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, record: ToolHistoryRecord) -> ToolHistoryRecord:
        data = record.as_dict()
        if "id" in data and data["id"] is None:
            del data["id"]
        _safe_execute("tool_history_create", "ai_tool_history", "insert",
                      lambda: self._client.table("ai_tool_history").insert(data).execute())
        return record

    def recent(self, owner_id: int, limit: int = 50) -> list[ToolHistoryRecord]:
        result = _safe_execute("tool_history_recent", "ai_tool_history", "select",
                               lambda: self._client.table("ai_tool_history")
                               .select("*").eq("owner_id", owner_id)
                               .order("created_at", desc=True).limit(limit).execute())
        if result and result.data:
            return [self._row_to_record(r) for r in result.data]
        return []

    def by_tool(self, owner_id: int, tool_name: str, limit: int = 20) -> list[ToolHistoryRecord]:
        result = _safe_execute("tool_history_by_tool", "ai_tool_history", "select",
                               lambda: self._client.table("ai_tool_history")
                               .select("*").eq("owner_id", owner_id)
                               .eq("tool_name", tool_name)
                               .order("created_at", desc=True).limit(limit).execute())
        if result and result.data:
            return [self._row_to_record(r) for r in result.data]
        return []

    def count(self, owner_id: int) -> int:
        result = _safe_execute("tool_history_count", "ai_tool_history", "select",
                               lambda: self._client.table("ai_tool_history")
                               .select("id", count="exact").eq("owner_id", owner_id).execute())
        if result and hasattr(result, "count") and result.count is not None:
            return result.count
        return 0

    def _row_to_record(self, row: dict[str, Any]) -> ToolHistoryRecord:
        return ToolHistoryRecord(
            id=row.get("id"),
            owner_id=row["owner_id"],
            session_id=row.get("session_id", ""),
            tool_name=row.get("tool_name", ""),
            arguments=row.get("arguments", {}),
            result_success=row.get("result_success", True),
            result_message=row.get("result_message", ""),
            result_data=row.get("result_data", {}),
            latency_ms=row.get("latency_ms", 0.0),
            created_at=row.get("created_at"),
        )
