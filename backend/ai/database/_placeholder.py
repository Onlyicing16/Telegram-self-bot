from backend.diagnostics_system import trace_step, trace_error
from backend.diagnostics_system.metrics import record_latency

from backend.ai.memory.types import MemoryEntry, MemoryQuery, MemoryTier, MemoryCategory

logger = logging.getLogger(__name__)


def _get_client() -> Any:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def _safe_execute(label, table, operation, fn):
    t0 = time.perf_counter()
    try:
        result = fn()
        duration = (time.perf_counter() - t0) * 1000
        record_latency("db_latency", t0, table=table, operation=operation)
        count = len(result.data) if hasattr(result, 'data') and result.data else 0
        trace_step("database", "ai_repo", operation, function=label, status="success", table=table, operation=operation, duration_ms=round(duration, 2), affected_rows=count)
        return result
    except Exception as exc:
        duration = (time.perf_counter() - t0) * 1000
        trace_error("database", "ai_repo", label, exc, table=table, operation=operation, duration_ms=round(duration, 2))
        logger.warning("Supabase AI repo error in %s (%s.%s): %s", label, table, operation, exc)
        return None