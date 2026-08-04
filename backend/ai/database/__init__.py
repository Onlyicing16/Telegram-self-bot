"""
Database interface layer for the AI subsystem.

This package defines repository interfaces for every AI database table.
Each repository has:
  - An abstract interface class (the contract)
  - An in-memory fallback implementation (working without Supabase)
  - A Supabase-backed implementation (used when Supabase is available)

The RepositoryManager automatically selects the appropriate implementation
based on whether Supabase env vars are present.

Repository mapping to tables:
  SessionRepository        → ai_sessions
  MessageRepository        → ai_messages
  MemoryRepository         → ai_memories
  ProviderStatsRepository  → ai_provider_stats
  UsageRepository          → ai_usage
  PreferencesRepository    → ai_preferences
  ToolHistoryRepository    → ai_tool_history

The AIPersistenceService bridges the runtime conversation layer and
the repository layer, providing best-effort persistence for sessions,
messages, usage, provider stats, and tool history.
"""
from backend.ai.database.manager import RepositoryManager, get_repository_manager
from backend.ai.database.memory_repository import (
    InMemoryMemoryRepository,
    MemoryRepository,
)
from backend.ai.database.message_repository import (
    InMemoryMessageRepository,
    MessageRepository,
    MessageRecord,
)
from backend.ai.database.preferences_repository import (
    InMemoryPreferencesRepository,
    PreferencesRecord,
    PreferencesRepository,
)
from backend.ai.database.provider_stats_repository import (
    InMemoryProviderStatsRepository,
    ProviderStatsRecord,
    ProviderStatsRepository,
)
from backend.ai.database.session_repository import (
    InMemorySessionRepository,
    SessionRecord,
    SessionRepository,
)
from backend.ai.database.tool_history_repository import (
    InMemoryToolHistoryRepository,
    ToolHistoryRecord,
    ToolHistoryRepository,
)
from backend.ai.database.usage_repository import (
    InMemoryUsageRepository,
    UsageRecord,
    UsageRepository,
)

__all__ = [
    # Manager
    "RepositoryManager",
    "get_repository_manager",
    # Memory
    "MemoryRepository",
    "InMemoryMemoryRepository",
    # Sessions
    "SessionRepository",
    "InMemorySessionRepository",
    "SessionRecord",
    # Messages
    "MessageRepository",
    "InMemoryMessageRepository",
    "MessageRecord",
    # Provider stats
    "ProviderStatsRepository",
    "InMemoryProviderStatsRepository",
    "ProviderStatsRecord",
    # Usage
    "UsageRepository",
    "InMemoryUsageRepository",
    "UsageRecord",
    # Preferences
    "PreferencesRepository",
    "InMemoryPreferencesRepository",
    "PreferencesRecord",
    # Tool history
    "ToolHistoryRepository",
    "InMemoryToolHistoryRepository",
    "ToolHistoryRecord",
]
