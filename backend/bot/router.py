"""
Handler registration — wires all command handlers onto the Telethon client.

Each handler module is registered in isolation. If one crashes during
registration, the error is logged and the remaining handlers still register.

Runtime hooks are registered before command handlers so the supervisor can
track last_update timestamps from incoming Telegram events.
"""
import asyncio
import logging
import sys
import time
import traceback

from telethon import events

from backend.bot.handlers import misc, save, retrieve, delete, organize, bio, discover, database, username, ai
from backend.runtime.tracer import trace_handler_exception
from backend.diagnostics_system import new_trace, trace_step, trace_error, new_request
from backend.diagnostics_system.exc_context import exc_context_scope
from backend.diagnostics_system.timeline import new_timeline, get_timeline
from backend.diagnostics_system.debug_config import get_session_id as get_session_id_safe
from backend.diagnostics_system.trace_context import get_trace_id as get_trace_id_safe

logger = logging.getLogger(__name__)

_HANDLER_TIMEOUT = 30.0


def register_runtime_hooks(client) -> None:
    """Register runtime event hooks before command handlers.

    These hooks track last_update timestamps for health telemetry.
    They must be registered first so they fire before any command handler.
    """
    @client.on(events.NewMessage(outgoing=True))
    async def _runtime_command_trace(event):
        from backend.health import set_last_update, set_last_telethon_event, set_last_event_dispatch
        raw = event.raw_text or ""
        if not raw.startswith("."):
            return
        new_trace(correlation_id=f"cmd:{event.chat_id}:{event.message.id}")
        new_timeline(get_trace_id_safe(), f"req:{event.message.id}", get_session_id_safe())
        with exc_context_scope(
            command=raw[:80],
            chat_id=str(event.chat_id),
            msg_id=str(event.message.id),
            user_id=str(event.sender_id),
            handler="router",
        ):
            try:
                set_last_update()
                set_last_telethon_event()
                set_last_event_dispatch()
            except Exception:
                pass
            logger.info("COMMAND_RECEIVED '%s' chat=%s msg=%s", raw[:80], event.chat_id, event.message.id)
            trace_step("router", "router", "command_received",
                        function="_runtime_command_trace",
                        status="received",
                        command=raw[:80], chat_id=str(event.chat_id), msg_id=str(event.message.id))

    @client.on(events.NewMessage())
    async def _runtime_update_hook(event):
        from backend.health import set_last_update, set_last_telethon_event, set_last_event_dispatch
        try:
            set_last_update()
            set_last_telethon_event()
            set_last_event_dispatch()
        except Exception:
            pass

    @client.on(events.MessageEdited())
    async def _runtime_edit_hook(event):
        from backend.health import set_last_telethon_event, set_last_event_dispatch
        try:
            set_last_telethon_event()
            set_last_event_dispatch()
        except Exception:
            pass

    @client.on(events.Raw)
    async def _raw_hook(event):
        from backend.health import set_last_telethon_event
        try:
            set_last_telethon_event()
        except Exception:
            pass


def register_all(client, owner_id: int, tz_str: str):
    logger.info("REGISTER_ALL: client id=%s, owner_id=%s, tz=%s", id(client), owner_id, tz_str)

    register_runtime_hooks(client)

    handlers = [
        ("misc", lambda: misc.register(client, owner_id)),
        ("save", lambda: save.register(client, owner_id, tz_str)),
        ("retrieve", lambda: retrieve.register(client, owner_id)),
        ("delete", lambda: delete.register(client, owner_id)),
        ("organize", lambda: organize.register(client, owner_id)),
        ("bio", lambda: bio.register(client, owner_id, tz_str)),
        ("discover", lambda: discover.register(client, owner_id, tz_str)),
        ("database", lambda: database.register(client, owner_id, tz_str)),
        ("username", lambda: username.register(client, owner_id, tz_str)),
        ("ai", lambda: ai.register(client, owner_id)),
    ]

    for name, fn in handlers:
        try:
            fn()
            logger.info("REGISTER_ALL: handler '%s' registered OK on client id(%s)", name, id(client))
            trace_step("router", "router", "handler_registered",
                        function="register_all",
                        status="success", handler=name)
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            logger.error("REGISTER_ALL: handler '%s' registration FAILED on client id(%s): %s", name, id(client), exc)
            trace_error("router", "router", "register_all", exc, handler=name)
            trace_handler_exception(f"register:{name}", exc)
