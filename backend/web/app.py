"""
FastAPI micro web server — keeps Render's HTTP health check satisfied
and exposes read-only API endpoints for the dashboard UI.
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.db import client as db_client
from backend.health import snapshot as health_snapshot
from backend.services import settings_service
from backend.diagnostics_system import new_trace, trace_step, trace_error, get_metrics_snapshot
from backend.diagnostics_system.metrics import drain_metrics
from backend.diagnostics_system.performance import get_performance_snapshot

logger = logging.getLogger(__name__)

app = FastAPI(title="LifeOS", docs_url=None, redoc_url=None)

_DIST = Path(__file__).parent.parent / "dist"

_owner_id: int = 0


def set_owner_id(owner_id: int) -> None:
    global _owner_id
    _owner_id = owner_id


@app.get("/health")
async def health():
    new_trace(correlation_id="health-check")
    trace_step("web", "app", "health_check", function="health", status="success")
    return health_snapshot()


@app.get("/api/saves")
async def list_saves(limit: int = 50, offset: int = 0):
    new_trace(correlation_id=f"api:saves:{offset}")
    trace_step("web", "app", "api_saves_list", function="list_saves",
               status="started", limit=limit, offset=offset)
    try:
        items, total = await db_client.list_saves(_owner_id, limit=limit, offset=offset)
        trace_step("web", "app", "api_saves_list", function="list_saves",
                   status="success", count=len(items) if items else 0, total=total)
        return {"items": items, "total": total}
    except Exception as exc:
        trace_error("web", "app", "list_saves", exc)
        logger.error("api/saves error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/saves/{save_code}")
async def get_save(save_code: str):
    new_trace(correlation_id=f"api:save:{save_code}")
    trace_step("web", "app", "api_save_get", function="get_save",
               status="started", save_code=save_code)
    try:
        row = await db_client.query_save(save_code)
        if not row:
            trace_step("web", "app", "api_save_get", function="get_save",
                       status="not_found", save_code=save_code)
            raise HTTPException(status_code=404, detail="Not found")
        trace_step("web", "app", "api_save_get", function="get_save",
                   status="success", save_code=save_code)
        return row
    except HTTPException:
        raise
    except Exception as exc:
        trace_error("web", "app", "get_save", exc, save_code=save_code)
        logger.error("api/saves/%s error: %s", save_code, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/bio")
async def get_bio():
    new_trace(correlation_id="api:bio")
    trace_step("web", "app", "api_bio", function="get_bio", status="started")
    try:
        state = await db_client.get_bio_state(_owner_id)
        trace_step("web", "app", "api_bio", function="get_bio", status="success")
        return state or {}
    except Exception as exc:
        trace_error("web", "app", "get_bio", exc)
        logger.error("api/bio error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/settings")
async def get_settings():
    new_trace(correlation_id="api:settings")
    trace_step("web", "app", "api_settings", function="get_settings", status="started")
    try:
        result = settings_service.get_all()
        trace_step("web", "app", "api_settings", function="get_settings", status="success")
        return result
    except Exception as exc:
        trace_error("web", "app", "get_settings", exc)
        logger.error("api/settings error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/logs")
async def get_logs(limit: int = 100):
    new_trace(correlation_id="api:logs")
    trace_step("web", "app", "api_logs", function="get_logs", status="started", limit=limit)
    try:
        logs = await db_client.list_logs(_owner_id, limit=limit)
        trace_step("web", "app", "api_logs", function="get_logs",
                   status="success", count=len(logs) if logs else 0)
        return {"logs": logs}
    except Exception as exc:
        trace_error("web", "app", "get_logs", exc)
        logger.error("api/logs error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/diagnostics/traces")
async def get_traces(limit: int = 50, layer: str | None = None):
    new_trace(correlation_id="api:diag:traces")
    try:
        from backend.diagnostics_system.batch_writer import _trace_buffer
        traces = list(_trace_buffer[-limit:])
        if layer:
            traces = [t for t in traces if t.get("layer") == layer]
        trace_step("web", "app", "api_diag_traces", function="get_traces",
                   status="success", count=len(traces))
        return {"traces": traces}
    except Exception as exc:
        trace_error("web", "app", "get_traces", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/diagnostics/metrics")
async def get_metrics():
    new_trace(correlation_id="api:diag:metrics")
    try:
        metrics = get_metrics_snapshot()
        trace_step("web", "app", "api_diag_metrics", function="get_metrics",
                   status="success", count=len(metrics))
        return {"metrics": metrics}
    except Exception as exc:
        trace_error("web", "app", "get_metrics", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/diagnostics/performance")
async def get_performance():
    new_trace(correlation_id="api:diag:perf")
    try:
        snapshot = get_performance_snapshot()
        trace_step("web", "app", "api_diag_performance", function="get_performance",
                   status="success")
        return snapshot
    except Exception as exc:
        trace_error("web", "app", "get_performance", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/diagnostics/config")
async def get_diag_config():
    from backend.diagnostics_system.debug_config import is_debug, get_trace_level, get_session_id
    new_trace(correlation_id="api:diag:config")
    try:
        config_info = {
            "debug_enabled": is_debug(),
            "trace_level": get_trace_level().name,
            "session_id": get_session_id(),
        }
        trace_step("web", "app", "api_diag_config", function="get_diag_config",
                   status="success")
        return config_info
    except Exception as exc:
        trace_error("web", "app", "get_diag_config", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/diagnostics/timeline")
async def get_timeline_endpoint():
    from backend.diagnostics_system.timeline import get_timeline
    new_trace(correlation_id="api:diag:timeline")
    try:
        tl = get_timeline()
        result = tl.to_dict()
        trace_step("web", "app", "api_diag_timeline", function="get_timeline_endpoint",
                   status="success", step_count=result.get("step_count", 0))
        return result
    except Exception as exc:
        trace_error("web", "app", "get_timeline_endpoint", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/ai/status")
async def get_ai_status():
    new_trace(correlation_id="api:ai:status")
    try:
        from backend.ai.engine.engine import get_engine
        from backend.ai.database.manager import get_repository_manager
        engine = get_engine()
        repos = get_repository_manager()
        result = {
            "engine_health": engine.engine_health(),
            "active_provider": engine.provider_manager.get_active_name(),
            "providers": engine.provider_manager.list_providers(),
            "metrics": engine.metrics_snapshot(),
            "repository_backend": "supabase" if repos.supabase_available else "in-memory",
        }
        trace_step("web", "app", "api_ai_status", function="get_ai_status", status="success")
        return result
    except Exception as exc:
        trace_error("web", "app", "get_ai_status", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/ai/sessions")
async def get_ai_sessions(limit: int = 10):
    new_trace(correlation_id="api:ai:sessions")
    try:
        from backend.ai.database.manager import get_repository_manager
        repos = get_repository_manager()
        sessions = repos.session.list_sessions(_owner_id, limit=limit)
        trace_step("web", "app", "api_ai_sessions", function="get_ai_sessions",
                   status="success", count=len(sessions))
        return {"sessions": [s.as_dict() for s in sessions]}
    except Exception as exc:
        trace_error("web", "app", "get_ai_sessions", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/ai/preferences")
async def get_ai_preferences():
    new_trace(correlation_id="api:ai:preferences")
    try:
        from backend.ai.database.manager import get_repository_manager
        repos = get_repository_manager()
        prefs = repos.preferences.get_or_create(_owner_id)
        trace_step("web", "app", "api_ai_preferences", function="get_ai_preferences",
                   status="success")
        return prefs.as_dict()
    except Exception as exc:
        trace_error("web", "app", "get_ai_preferences", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/ai/usage")
async def get_ai_usage(limit: int = 50):
    new_trace(correlation_id="api:ai:usage")
    try:
        from backend.ai.database.manager import get_repository_manager
        repos = get_repository_manager()
        records = repos.usage.recent(_owner_id, limit=limit)
        total = repos.usage.total_tokens(_owner_id)
        trace_step("web", "app", "api_ai_usage", function="get_ai_usage",
                   status="success", count=len(records), total_tokens=total)
        return {"records": [r.as_dict() for r in records], "total_tokens": total}
    except Exception as exc:
        trace_error("web", "app", "get_ai_usage", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/ai/provider-stats")
async def get_ai_provider_stats():
    new_trace(correlation_id="api:ai:provider-stats")
    try:
        from backend.ai.database.manager import get_repository_manager
        repos = get_repository_manager()
        stats = repos.provider_stats.list_all(_owner_id)
        trace_step("web", "app", "api_ai_provider_stats", function="get_ai_provider_stats",
                   status="success", count=len(stats))
        return {"stats": [s.as_dict() for s in stats]}
    except Exception as exc:
        trace_error("web", "app", "get_ai_provider_stats", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/ai/memory")
async def get_ai_memory():
    new_trace(correlation_id="api:ai:memory")
    try:
        from backend.ai.database.manager import get_repository_manager
        from backend.ai.memory.types import MemoryTier, MemoryQuery
        repos = get_repository_manager()
        long_q = MemoryQuery(owner_id=_owner_id, tier=MemoryTier.LONG, limit=50)
        perm_q = MemoryQuery(owner_id=_owner_id, tier=MemoryTier.PERMANENT, limit=50)
        long_entries = repos.memory.query(long_q)
        perm_entries = repos.memory.query(perm_q)
        trace_step("web", "app", "api_ai_memory", function="get_ai_memory",
                   status="success", long_count=len(long_entries),
                   permanent_count=len(perm_entries))
        return {
            "long": [e.as_dict() for e in long_entries],
            "permanent": [e.as_dict() for e in perm_entries],
        }
    except Exception as exc:
        trace_error("web", "app", "get_ai_memory", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def mount_static():
    if _DIST.exists():
        app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            index = _DIST / "index.html"
            if index.exists():
                return FileResponse(str(index))
            return JSONResponse({"status": "LifeOS API running"})
    else:
        @app.get("/")
        async def root():
            return {"status": "LifeOS API running — no UI build found"}


mount_static()
