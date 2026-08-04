"""
AI Persistence Service — bridges the runtime conversation layer and
the Supabase repository layer.

This service is called by the Engine Dispatcher to persist:
  - Session state (create/update)
  - Conversation messages (user + assistant)
  - Token usage records
  - Provider statistics

All operations are best-effort: failures are logged and traced but
never propagated. The AI pipeline must not crash because a DB write
failed. This matches the existing ``backend/db/client.py`` pattern.

The service also provides session restore: on startup, the most recent
active session for an owner can be loaded from Supabase so the AI
continues from the previous state after a restart.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.diagnostics_system import trace_step, trace_error
from backend.diagnostics_system.metrics import record_latency

from backend.ai.database.manager import get_repository_manager
from backend.ai.database.session_repository import SessionRecord
from backend.ai.database.message_repository import MessageRecord
from backend.ai.database.usage_repository import UsageRecord
from backend.ai.database.tool_history_repository import ToolHistoryRecord

logger = logging.getLogger(__name__)


class AIPersistenceService:
    """Best-effort persistence bridge between runtime and database.

    Every method wraps its DB call in try/except and returns a safe
    default on failure. No method ever raises.
    """

    __slots__ = ("_repos",)

    def __init__(self) -> None:
        self._repos = get_repository_manager()

    @property
    def repos(self) -> Any:
        return self._repos

    def persist_session_create(self, owner_id: int, session_id: str,
                               provider: str = "dummy", model: str = "dummy-1") -> None:
        t0 = time.perf_counter()
        try:
            record = SessionRecord(
                session_id=session_id,
                owner_id=owner_id,
                provider=provider,
                model=model,
                status="active",
            )
            self._repos.session.create(record)
            record_latency("db_latency", t0, table="ai_sessions", operation="insert")
            trace_step("ai_persistence", "persistence", "session_create",
                       function="persist_session_create", status="success",
                       session_id=session_id, owner_id=owner_id)
        except Exception as exc:
            trace_error("ai_persistence", "persistence", "persist_session_create", exc,
                        session_id=session_id, owner_id=owner_id)
            logger.warning("AIPersistence: session create failed: %s", exc)

    def persist_session_update(self, session_id: str, owner_id: int,
                               total_tokens: int = 0, message_count: int = 0,
                               provider: str | None = None, status: str | None = None) -> None:
        t0 = time.perf_counter()
        try:
            updates: dict[str, Any] = {
                "total_tokens": total_tokens,
                "message_count": message_count,
            }
            if provider:
                updates["provider"] = provider
            if status:
                updates["status"] = status
            self._repos.session.update(session_id, updates)
            record_latency("db_latency", t0, table="ai_sessions", operation="update")
            trace_step("ai_persistence", "persistence", "session_update",
                       function="persist_session_update", status="success",
                       session_id=session_id)
        except Exception as exc:
            trace_error("ai_persistence", "persistence", "persist_session_update", exc,
                        session_id=session_id)
            logger.warning("AIPersistence: session update failed: %s", exc)

    def persist_message(self, session_id: str, owner_id: int, role: str,
                        content: str, token_count: int = 0,
                        provider: str = "", model: str = "") -> None:
        t0 = time.perf_counter()
        try:
            record = MessageRecord(
                id=None,
                session_id=session_id,
                owner_id=owner_id,
                role=role,
                content=content,
                token_count=token_count,
                provider=provider,
                model=model,
            )
            self._repos.message.create(record)
            record_latency("db_latency", t0, table="ai_messages", operation="insert")
            trace_step("ai_persistence", "persistence", "message_persisted",
                       function="persist_message", status="success",
                       session_id=session_id, role=role, token_count=token_count)
        except Exception as exc:
            trace_error("ai_persistence", "persistence", "persist_message", exc,
                        session_id=session_id, role=role)
            logger.warning("AIPersistence: message persist failed: %s", exc)

    def persist_usage(self, owner_id: int, session_id: str, provider: str,
                      model: str, prompt_tokens: int, completion_tokens: int,
                      total_tokens: int, latency_ms: float) -> None:
        t0 = time.perf_counter()
        try:
            record = UsageRecord(
                id=None,
                owner_id=owner_id,
                session_id=session_id,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
            )
            self._repos.usage.create(record)
            record_latency("db_latency", t0, table="ai_usage", operation="insert")
            trace_step("ai_persistence", "persistence", "usage_persisted",
                       function="persist_usage", status="success",
                       owner_id=owner_id, total_tokens=total_tokens)
        except Exception as exc:
            trace_error("ai_persistence", "persistence", "persist_usage", exc,
                        owner_id=owner_id)
            logger.warning("AIPersistence: usage persist failed: %s", exc)

    def persist_provider_stats(self, provider_name: str, owner_id: int,
                               success: bool, prompt_tokens: int,
                               completion_tokens: int, latency_ms: float) -> None:
        t0 = time.perf_counter()
        try:
            self._repos.provider_stats.record_request(
                provider_name=provider_name,
                owner_id=owner_id,
                success=success,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )
            record_latency("db_latency", t0, table="ai_provider_stats", operation="update")
            trace_step("ai_persistence", "persistence", "provider_stats_persisted",
                       function="persist_provider_stats", status="success",
                       provider=provider_name, success=success)
        except Exception as exc:
            trace_error("ai_persistence", "persistence", "persist_provider_stats", exc,
                        provider=provider_name)
            logger.warning("AIPersistence: provider stats persist failed: %s", exc)

    def persist_tool_history(self, owner_id: int, session_id: str, tool_name: str,
                             arguments: dict[str, Any], result_success: bool,
                             result_message: str, latency_ms: float) -> None:
        t0 = time.perf_counter()
        try:
            record = ToolHistoryRecord(
                id=None,
                owner_id=owner_id,
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                result_success=result_success,
                result_message=result_message,
                latency_ms=latency_ms,
            )
            self._repos.tool_history.create(record)
            record_latency("db_latency", t0, table="ai_tool_history", operation="insert")
            trace_step("ai_persistence", "persistence", "tool_history_persisted",
                       function="persist_tool_history", status="success",
                       tool_name=tool_name, success=result_success)
        except Exception as exc:
            trace_error("ai_persistence", "persistence", "persist_tool_history", exc,
                        tool_name=tool_name)
            logger.warning("AIPersistence: tool history persist failed: %s", exc)

    def restore_session(self, owner_id: int) -> dict[str, Any] | None:
        """Restore the most recent active session for an owner.

        Returns a dict with session_id, provider, model, and message
        history, or None if no session exists.
        """
        t0 = time.perf_counter()
        try:
            sessions = self._repos.session.list_sessions(owner_id, limit=1)
            if not sessions:
                trace_step("ai_persistence", "persistence", "session_restore",
                           function="restore_session", status="not_found",
                           owner_id=owner_id)
                return None
            session = sessions[0]
            messages = self._repos.message.list_messages(session.session_id, limit=50)
            record_latency("db_latency", t0, table="ai_sessions+ai_messages", operation="select")
            trace_step("ai_persistence", "persistence", "session_restore",
                       function="restore_session", status="success",
                       session_id=session.session_id,
                       message_count=len(messages))
            return {
                "session_id": session.session_id,
                "provider": session.provider,
                "model": session.model,
                "status": session.status,
                "total_tokens": session.total_tokens,
                "message_count": session.message_count,
                "messages": [
                    {
                        "role": m.role,
                        "content": m.content,
                        "token_count": m.token_count,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in messages
                ],
            }
        except Exception as exc:
            trace_error("ai_persistence", "persistence", "restore_session", exc,
                        owner_id=owner_id)
            logger.warning("AIPersistence: session restore failed: %s", exc)
            return None

    def restore_memory(self, owner_id: int) -> dict[str, list[Any]]:
        """Restore long-term and permanent memory for an owner.

        Returns a dict with "long" and "permanent" keys, each a list
        of memory entry dicts.
        """
        from backend.ai.memory.types import MemoryTier
        t0 = time.perf_counter()
        try:
            long_entries = self._repos.memory.query(
                type("Q", (), {"owner_id": owner_id, "tier": MemoryTier.LONG,
                                "category": None, "query_text": "",
                                "limit": 50, "min_importance": 0.0})()
            )
            permanent_entries = self._repos.memory.query(
                type("Q", (), {"owner_id": owner_id, "tier": MemoryTier.PERMANENT,
                                "category": None, "query_text": "",
                                "limit": 50, "min_importance": 0.0})()
            )
            record_latency("db_latency", t0, table="ai_memories", operation="select")
            trace_step("ai_persistence", "persistence", "memory_restore",
                       function="restore_memory", status="success",
                       long_count=len(long_entries),
                       permanent_count=len(permanent_entries))
            return {
                "long": [e.as_dict() for e in long_entries],
                "permanent": [e.as_dict() for e in permanent_entries],
            }
        except Exception as exc:
            trace_error("ai_persistence", "persistence", "restore_memory", exc,
                        owner_id=owner_id)
            logger.warning("AIPersistence: memory restore failed: %s", exc)
            return {"long": [], "permanent": []}


_persistence: AIPersistenceService | None = None


def get_persistence() -> AIPersistenceService:
    """Return the process-wide AIPersistenceService singleton."""
    global _persistence
    if _persistence is None:
        _persistence = AIPersistenceService()
    return _persistence
