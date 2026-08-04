"""
AI Session Restore — loads previous AI state from Supabase on startup.

After a Render restart, crash, or Telegram reconnect, this module
restores the most recent active session and conversation history so
the AI can continue from where it left off.

This is called once during engine initialization (or on demand) and
is best-effort: if Supabase is unavailable or no session exists,
the AI starts fresh — no error propagated.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.diagnostics_system import trace_step, trace_error

logger = logging.getLogger(__name__)


def restore_ai_state(owner_id: int) -> dict[str, Any] | None:
    """Restore the most recent AI session and history for an owner.

    Returns a dict with:
        - session_id:   The restored session ID
        - provider:     Provider name
        - model:        Model name
        - messages:     List of {role, content, token_count, created_at}
        - memory:       Dict with "long" and "permanent" memory entries

    Returns None if no session exists or Supabase is unavailable.
    Never raises.
    """
    from backend.ai.database.persistence_service import get_persistence

    try:
        persistence = get_persistence()
        session_data = persistence.restore_session(owner_id)
        if session_data is None:
            trace_step("ai_engine", "session_restore", "no_session",
                       function="restore_ai_state", status="not_found",
                       owner_id=owner_id)
            return None

        memory_data = persistence.restore_memory(owner_id)

        trace_step("ai_engine", "session_restore", "restored",
                   function="restore_ai_state", status="success",
                   owner_id=owner_id,
                   session_id=session_data.get("session_id"),
                   message_count=len(session_data.get("messages", [])),
                   long_memory_count=len(memory_data.get("long", [])),
                   permanent_memory_count=len(memory_data.get("permanent", [])))

        logger.info(
            "AI session restore: owner=%s, session=%s, messages=%d, long_mem=%d, perm_mem=%d",
            owner_id,
            session_data.get("session_id"),
            len(session_data.get("messages", [])),
            len(memory_data.get("long", [])),
            len(memory_data.get("permanent", [])),
        )

        return {
            "session_id": session_data.get("session_id"),
            "provider": session_data.get("provider", "dummy"),
            "model": session_data.get("model", "dummy-1"),
            "messages": session_data.get("messages", []),
            "memory": memory_data,
        }
    except Exception as exc:
        trace_error("ai_engine", "session_restore", "restore_ai_state", exc,
                    owner_id=owner_id)
        logger.warning("AI session restore failed for owner %s: %s", owner_id, exc)
        return None


def load_restored_history(conversation_manager: Any, owner_id: int,
                          messages: list[dict[str, Any]]) -> int:
    """Load restored message history into a ConversationManager.

    Returns the number of messages loaded. Never raises.
    """
    loaded = 0
    try:
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if not content:
                continue
            if role == "user":
                conversation_manager.add_user_message(owner_id=owner_id, content=content)
            elif role == "assistant":
                conversation_manager.add_assistant_message(owner_id=owner_id, content=content)
            elif role == "tool":
                conversation_manager.add_tool_result(
                    owner_id=owner_id,
                    tool_name="restored",
                    result=content,
                )
            loaded += 1
        trace_step("ai_engine", "session_restore", "history_loaded",
                   function="load_restored_history", status="success",
                   owner_id=owner_id, loaded_count=loaded)
    except Exception as exc:
        trace_error("ai_engine", "session_restore", "load_restored_history", exc,
                    owner_id=owner_id)
        logger.warning("History load failed: %s", exc)
    return loaded
