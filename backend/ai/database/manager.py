"""
RepositoryManager — central owner of all AI database repositories.

The manager holds one instance of each repository and provides access
to them. When Supabase is available, Supabase-backed implementations
are used. When Supabase is not available, in-memory fallbacks are used.

This follows the same pattern as ``backend/db/client.py`` — the bot
works with or without Supabase. Every repository call is wrapped in
error handling that degrades gracefully.

The RepositoryManager is a singleton (one per process), accessed via
``get_repository_manager()``. It is constructed on first access.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from backend.ai.database.memory_repository import InMemoryMemoryRepository, MemoryRepository
from backend.ai.database.message_repository import InMemoryMessageRepository, MessageRepository
from backend.ai.database.preferences_repository import InMemoryPreferencesRepository, PreferencesRepository
from backend.ai.database.provider_stats_repository import InMemoryProviderStatsRepository, ProviderStatsRepository
from backend.ai.database.session_repository import InMemorySessionRepository, SessionRepository
from backend.ai.database.tool_history_repository import InMemoryToolHistoryRepository, ToolHistoryRepository
from backend.ai.database.usage_repository import InMemoryUsageRepository, UsageRepository

from backend.diagnostics_system import trace_step, trace_error

logger = logging.getLogger(__name__)


def _create_supabase_client() -> Any:
    """Create a Supabase client from env vars. Returns None on failure."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as exc:
        logger.warning("RepositoryManager: Supabase client init failed: %s", exc)
        trace_error("database", "ai_repo_manager", "_create_supabase_client", exc)
        return None


class RepositoryManager:
    """Central manager for all AI database repositories.

    When Supabase is available, uses Supabase-backed implementations.
    When not available, uses in-memory fallbacks (data lost on restart).
    """

    __slots__ = (
        "_memory", "_session", "_message", "_provider_stats",
        "_usage", "_preferences", "_tool_history",
        "_supabase_available", "_client",
    )

    def __init__(self, supabase_available: bool = False, client: Any = None) -> None:
        self._supabase_available = supabase_available
        self._client = client

        if supabase_available and client is not None:
            from backend.ai.database.supabase_repos import (
                SupabaseSessionRepository,
                SupabaseMessageRepository,
            )
            from backend.ai.database.supabase_repos_ext import (
                SupabaseMemoryRepository,
                SupabasePreferencesRepository,
                SupabaseProviderStatsRepository,
                SupabaseUsageRepository,
                SupabaseToolHistoryRepository,
            )
            self._session = SupabaseSessionRepository(client)
            self._message = SupabaseMessageRepository(client)
            self._memory = SupabaseMemoryRepository(client)
            self._preferences = SupabasePreferencesRepository(client)
            self._provider_stats = SupabaseProviderStatsRepository(client)
            self._usage = SupabaseUsageRepository(client)
            self._tool_history = SupabaseToolHistoryRepository(client)
            logger.info("RepositoryManager: Supabase-backed repositories initialized")
            trace_step("database", "ai_repo_manager", "repos_initialized",
                       function="__init__", status="success", backend="supabase")
        else:
            self._session = InMemorySessionRepository()
            self._message = InMemoryMessageRepository()
            self._memory = InMemoryMemoryRepository()
            self._preferences = InMemoryPreferencesRepository()
            self._provider_stats = InMemoryProviderStatsRepository()
            self._usage = InMemoryUsageRepository()
            self._tool_history = InMemoryToolHistoryRepository()
            logger.info("RepositoryManager: in-memory fallback repositories initialized")
            trace_step("database", "ai_repo_manager", "repos_initialized",
                       function="__init__", status="success", backend="in-memory")

    @property
    def memory(self) -> MemoryRepository:
        return self._memory

    @property
    def session(self) -> SessionRepository:
        return self._session

    @property
    def message(self) -> MessageRepository:
        return self._message

    @property
    def provider_stats(self) -> ProviderStatsRepository:
        return self._provider_stats

    @property
    def usage(self) -> UsageRepository:
        return self._usage

    @property
    def preferences(self) -> PreferencesRepository:
        return self._preferences

    @property
    def tool_history(self) -> ToolHistoryRepository:
        return self._tool_history

    @property
    def supabase_available(self) -> bool:
        return self._supabase_available

    def status(self) -> dict[str, Any]:
        return {
            "supabase_available": self._supabase_available,
            "backend": "supabase" if self._supabase_available else "in-memory",
            "repositories": [
                "memory", "session", "message",
                "provider_stats", "usage", "preferences", "tool_history",
            ],
        }


_repository_manager: RepositoryManager | None = None


def get_repository_manager() -> RepositoryManager:
    """Return the process-wide RepositoryManager instance.

    Constructs it on first call. This is the single instance — no
    duplicated managers.
    """
    global _repository_manager
    if _repository_manager is None:
        client = _create_supabase_client()
        available = client is not None
        _repository_manager = RepositoryManager(supabase_available=available, client=client)
    return _repository_manager


def reset_repository_manager() -> None:
    """Reset the singleton (for testing or reconnection)."""
    global _repository_manager
    _repository_manager = None
