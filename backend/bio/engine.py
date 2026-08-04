"""
Bio Engine — renders the Telegram profile bio ("about") using a template.
"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.db import client as db_client
from backend.diagnostics import record_event
from backend.diagnostics_system import trace_step
from backend.profile import scheduler as profile_scheduler
from backend.runtime.tracer import trace

logger = logging.getLogger(__name__)

_STOP_TIMEOUT = 10.0
_registered = False


def _get_tz(tz_str: str):
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, Exception):
        logger.warning("Timezone '%s' not found — falling back to UTC.", tz_str)
        return timezone.utc


def render_bio(template: str, mood: str, text: str, tz_str: str) -> str:
    tz = _get_tz(tz_str)
    now = datetime.now(tz)
    return (template or "🕒 {time} | 💭 {mood}").replace("{time}", now.strftime("%H:%M")).replace("{mood}", mood or "😊").replace("{text}", text or "")


async def _bio_updater(owner_id: int, tz_str: str) -> dict[str, str] | None:
    state = await db_client.get_bio_state(owner_id)
    if not state or not state.get("is_active"):
        return None
    tmpl = state.get("template", "🕒 {time} | 💭 {mood}")
    mood = state.get("mood", "😊")
    ctxtxt = state.get("custom_text", "")
    new_bio = render_bio(tmpl, mood, ctxtxt, tz_str)
    last_bio = state.get("last_bio")
    if new_bio == (last_bio or ""):
        return None
    tz = _get_tz(tz_str)
    await db_client.update_bio_state(owner_id, {"last_bio": new_bio, "updated_at": datetime.now(tz).isoformat()})
    return {"about": new_bio}


def _ensure_registered() -> None:
    global _registered
    if _registered:
        return
    profile_scheduler.register_updater("bio", _bio_updater)
    _registered = True


def start_cron(client, owner_id: int, tz_str: str) -> None:
    _ensure_registered()
    profile_scheduler.start_cron(client, owner_id, tz_str)
    trace("BIO_CRON_START_REQUESTED")
    record_event("bio", "start_cron", 0, "SUCCESS")
    trace_step("bio", "engine", "start_cron", function="start_cron", status="success", owner_id=owner_id)


def update_client(client) -> None:
    profile_scheduler.update_client(client)


async def stop_cron() -> None:
    trace("BIO_CRON_STOP_REQUESTED")
    trace_step("bio", "engine", "stop_cron", function="stop_cron", status="started")
    await profile_scheduler.stop_cron()
    record_event("bio", "stop_cron", 0, "SUCCESS")
    trace_step("bio", "engine", "stop_cron", function="stop_cron", status="success")


def is_running() -> bool:
    return profile_scheduler.is_running()
