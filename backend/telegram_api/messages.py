"""
Messages module — send, edit, delete, forward, search, iterate.

Every method has a bounded timeout and returns plain dicts or simple
types. Callers never touch Telethon objects.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.telegram_api._helpers import serialize_message
from backend.telegram_api.exceptions import (
    TelegramAPIError,
    TelegramTimeoutError,
)
from backend.diagnostics_system import trace_step, trace_error
from backend.diagnostics_system.metrics import record_latency

logger = logging.getLogger(__name__)

_RPC_TIMEOUT = 30.0


async def send_message(client: Any, chat_id: int | str, text: str, **kwargs: Any) -> dict[str, Any]:
    """Send a text message. Returns serialized message dict."""
    try:
        t0 = time.perf_counter()
        msg = await asyncio.wait_for(
            client.send_message(chat_id, text, **kwargs),
            timeout=_RPC_TIMEOUT,
        )
        record_latency("telethon_rpc", t0, function="send_message")
        return serialize_message(msg)
    except asyncio.TimeoutError:
        record_latency("telethon_rpc", t0, function="send_message", result="timeout")
        raise TelegramTimeoutError(f"send_message timed out after {_RPC_TIMEOUT}s")
    except Exception as exc:
        if isinstance(exc, TelegramAPIError):
            raise
        trace_error("telegram_api", "messages", "send_message", exc, function="send_message")
        raise TelegramAPIError(f"send_message failed: {exc}") from exc


async def edit_message(client: Any, chat_id: int | str, msg_id: int, text: str, **kwargs: Any) -> dict[str, Any]:
    """Edit a message's text. Returns serialized message dict."""
    try:
        t0 = time.perf_counter()
        msg = await asyncio.wait_for(
            client.edit_message(chat_id, msg_id, text, **kwargs),
            timeout=_RPC_TIMEOUT,
        )
        record_latency("telethon_rpc", t0, function="edit_message")
        return serialize_message(msg)
    except asyncio.TimeoutError:
        record_latency("telethon_rpc", t0, function="edit_message", result="timeout")
        raise TelegramTimeoutError(f"edit_message timed out after {_RPC_TIMEOUT}s")
    except Exception as exc:
        if isinstance(exc, TelegramAPIError):
            raise
        trace_error("telegram_api", "messages", "edit_message", exc, function="edit_message")
        raise TelegramAPIError(f"edit_message failed: {exc}") from exc


async def delete_messages(client: Any, chat_id: int | str, msg_ids: list[int]) -> int:
    """Delete messages by ID. Returns count of deleted messages."""
    if not msg_ids:
        return 0
    try:
        t0 = time.perf_counter()
        await asyncio.wait_for(
            client.delete_messages(chat_id, msg_ids),
            timeout=_RPC_TIMEOUT,
        )
        record_latency("telethon_rpc", t0, function="delete_messages")
        return len(msg_ids)
    except asyncio.TimeoutError:
        record_latency("telethon_rpc", t0, function="delete_messages", result="timeout")
        raise TelegramTimeoutError(f"delete_messages timed out after {_RPC_TIMEOUT}s")
    except Exception as exc:
        if isinstance(exc, TelegramAPIError):
            raise
        trace_error("telegram_api", "messages", "delete_messages", exc, function="delete_messages")
        raise TelegramAPIError(f"delete_messages failed: {exc}") from exc


async def get_message(client: Any, chat_id: int | str, msg_id: int) -> dict[str, Any]:
    """Get a single message by ID. Returns serialized dict."""
    try:
        msg = await asyncio.wait_for(
            client.get_messages(chat_id, ids=msg_id),
            timeout=_RPC_TIMEOUT,
        )
        return serialize_message(msg)
    except asyncio.TimeoutError:
        raise TelegramTimeoutError(f"get_message timed out after {_RPC_TIMEOUT}s")
    except Exception as exc:
        if isinstance(exc, TelegramAPIError):
            raise
        raise TelegramAPIError(f"get_message failed: {exc}") from exc


async def get_messages(client: Any, chat_id: int | str, ids: list[int]) -> list[dict[str, Any]]:
    """Get multiple messages by ID. Returns list of serialized dicts."""
    try:
        msgs = await asyncio.wait_for(
            client.get_messages(chat_id, ids=ids),
            timeout=_RPC_TIMEOUT,
        )
        if msgs is None:
            return []
        if isinstance(msgs, list):
            return [serialize_message(m) for m in msgs]
        return [serialize_message(msgs)]
    except asyncio.TimeoutError:
        raise TelegramTimeoutError(f"get_messages timed out after {_RPC_TIMEOUT}s")
    except Exception as exc:
        if isinstance(exc, TelegramAPIError):
            raise
        raise TelegramAPIError(f"get_messages failed: {exc}") from exc


async def forward_messages(
    client: Any,
    dest_chat_id: int | str,
    msg_ids: list[int] | int,
    from_chat_id: int | str,
) -> list[dict[str, Any]]:
    """Forward message(s) from one chat to another. Returns serialized forwarded messages."""
    if isinstance(msg_ids, int):
        msg_ids = [msg_ids]
    try:
        t0 = time.perf_counter()
        result = await asyncio.wait_for(
            client.forward_messages(dest_chat_id, msg_ids, from_peer=from_chat_id),
            timeout=_RPC_TIMEOUT,
        )
        record_latency("telethon_rpc", t0, function="forward_messages")
        if result is None:
            return []
        if isinstance(result, list):
            return [serialize_message(m) for m in result]
        return [serialize_message(result)]
    except asyncio.TimeoutError:
        record_latency("telethon_rpc", t0, function="forward_messages", result="timeout")
        raise TelegramTimeoutError(f"forward_messages timed out after {_RPC_TIMEOUT}s")
    except Exception as exc:
        if isinstance(exc, TelegramAPIError):
            raise
        trace_error("telegram_api", "messages", "forward_messages", exc, function="forward_messages")
        raise TelegramAPIError(f"forward_messages failed: {exc}") from exc


async def iter_messages(
    client: Any,
    chat_id: int | str,
    limit: int = 100,
    from_user: str | None = None,
    min_id: int | None = None,
) -> list[dict[str, Any]]:
    """Iterate messages in a chat. Returns list of serialized dicts."""
    kwargs: dict[str, Any] = {"limit": limit}
    if from_user:
        kwargs["from_user"] = from_user
    if min_id is not None:
        kwargs["min_id"] = min_id
    try:
        results: list[dict[str, Any]] = []
        async for msg in client.iter_messages(chat_id, **kwargs):
            results.append(serialize_message(msg))
            if len(results) >= limit:
                break
        return results
    except asyncio.TimeoutError:
        raise TelegramTimeoutError("iter_messages timed out")
    except Exception as exc:
        if isinstance(exc, TelegramAPIError):
            raise
        raise TelegramAPIError(f"iter_messages failed: {exc}") from exc


async def search_messages(
    client: Any,
    chat_id: int | str,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search messages in a chat by text. Returns list of serialized dicts."""
    try:
        results: list[dict[str, Any]] = []
        async for msg in client.iter_messages(chat_id, search=query, limit=limit):
            results.append(serialize_message(msg))
            if len(results) >= limit:
                break
        return results
    except asyncio.TimeoutError:
        raise TelegramTimeoutError("search_messages timed out")
    except Exception as exc:
        if isinstance(exc, TelegramAPIError):
            raise
        raise TelegramAPIError(f"search_messages failed: {exc}") from exc
