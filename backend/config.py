"""
Environment variable loader.

Required vars hard-fail; optional vars use sensible defaults.
Supabase is optional — the bot runs without it (in-memory fallback).
"""
import os
import sys

from backend.diagnostics_system import trace_step

REQUIRED = [
    "API_ID",
    "API_HASH",
    "SESSION_STRING",
    "BOT_OWNER_ID",
]


def load() -> dict:
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        print(f"[FATAL] Missing required environment variables: {', '.join(missing)}", flush=True)
        sys.exit(1)

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    bot_token = os.getenv("BOT_TOKEN", "")

    trace_step("runtime", "config", "config_loaded", function="load", status="success",
               supabase_available=bool(supabase_url and supabase_key))

    return {
        "API_ID": int(os.environ["API_ID"]),
        "API_HASH": os.environ["API_HASH"],
        "SESSION_STRING": os.environ["SESSION_STRING"],
        "OWNER_ID": int(os.environ["BOT_OWNER_ID"]),
        "BOT_TOKEN": bot_token,
        "HELPER_BOT_ENABLED": bool(bot_token),
        "SUPABASE_URL": supabase_url,
        "SUPABASE_KEY": supabase_key,
        "SUPABASE_AVAILABLE": bool(supabase_url and supabase_key),
        "DATABASE_URL": os.getenv("DATABASE_URL", ""),
        "TZ": os.getenv("TZ", "Asia/Tehran"),
        "PORT": int(os.getenv("PORT", "8000")),
        "GHOST_ROOM_ID": os.getenv("GHOST_ROOM_ID", ""),
        "DEST_CHANNEL_ID": os.getenv("DEST_CHANNEL_ID", ""),
        "BIO_UPDATE_ENABLED": os.getenv("BIO_UPDATE_ENABLED", "false").lower() == "true",
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO").upper(),
        "DEBUG": os.getenv("DEBUG", "false").lower() in ("true", "1", "yes", "on"),
        "TRACE_LEVEL": os.getenv("TRACE_LEVEL", "off").upper(),
    }
