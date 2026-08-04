"""
ToolExecutor — executes tool calls from provider responses.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.ai.tools.base import PermissionLevel, ToolResult
from backend.ai.tools.context import ToolContext
from backend.ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOLS_PER_TURN = 5
TOOL_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_name: str
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    needs_confirmation: bool = False
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "message": self.message,
            "data": dict(self.data),
            "latency_ms": self.latency_ms,
            "needs_confirmation": self.needs_confirmation,
            "error": self.error,
        }


class ToolExecutor:
    __slots__ = ("_registry", "_context", "_history_repo")

    def __init__(self, registry: ToolRegistry, context: ToolContext, history_repo: Any | None = None) -> None:
        self._registry = registry
        self._context = context
        self._history_repo = history_repo

    def execute_calls(self, tool_calls: list[dict[str, Any]], owner_id: int = 0, session_id: str = "") -> list[ToolExecutionResult]:
        results: list[ToolExecutionResult] = []
        for i, call in enumerate(tool_calls):
            if i >= MAX_TOOLS_PER_TURN:
                logger.warning("ToolExecutor: hit max %d tools per turn", MAX_TOOLS_PER_TURN)
                results.append(ToolExecutionResult(tool_name="(overflow)", success=False, message="Tool call limit reached.", error="max_tools_exceeded"))
                break
            result = self._execute_single(call, owner_id, session_id)
            results.append(result)
        return results

    def _execute_single(self, call: dict[str, Any], owner_id: int, session_id: str) -> ToolExecutionResult:
        tool_name = call.get("name", "") or call.get("tool", "")
        arguments = call.get("arguments", {}) or call.get("parameters", {})
        if not tool_name:
            return ToolExecutionResult(tool_name="(unknown)", success=False, message="Missing 'name' field.", error="missing_name")
        tool = self._registry.get(tool_name)
        if tool is None:
            return ToolExecutionResult(tool_name=tool_name, success=False, message=f"Tool '{tool_name}' not registered.", error="not_found")
        if not self._is_auto_executable(tool):
            return ToolExecutionResult(tool_name=tool_name, success=False, message=f"Tool '{tool_name}' requires confirmation.", needs_confirmation=True)
        start = time.perf_counter()
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            tool_result: ToolResult = loop.run_until_complete(asyncio.wait_for(tool.execute(self._context, arguments), timeout=TOOL_TIMEOUT_SECONDS))
            latency_ms = (time.perf_counter() - start) * 1000
            from backend.diagnostics_system import trace_step
            from backend.diagnostics_system.metrics import record_latency
            record_latency("tool_execution", start, tool=tool_name)
            trace_step("tool_executor", "executor", "tool_executed", function="_execute_single", status="success" if tool_result.success else "failure", tool=tool_name, latency_ms=round(latency_ms, 1))
            self._record_history(owner_id, session_id, tool_name, arguments, tool_result, latency_ms)
            return ToolExecutionResult(tool_name=tool_name, success=tool_result.success, message=tool_result.message, data=tool_result.data, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            error_msg = f"{type(exc).__name__}: {exc}"
            from backend.diagnostics_system import trace_error
            from backend.diagnostics_system.metrics import record_latency
            record_latency("tool_execution", start, tool=tool_name, result="error")
            trace_error("tool_executor", "executor", "_execute_single", exc, tool=tool_name)
            logger.warning("ToolExecutor: tool '%s' failed: %s", tool_name, exc)
            return ToolExecutionResult(tool_name=tool_name, success=False, message=f"Tool error: {error_msg}", latency_ms=latency_ms, error=error_msg)

    def _is_auto_executable(self, tool: Any) -> bool:
        return tool.permission_level in (PermissionLevel.READ_ONLY, PermissionLevel.READ_WRITE)

    def _record_history(self, owner_id: int, session_id: str, tool_name: str, arguments: dict[str, Any], result: ToolResult, latency_ms: float) -> None:
        if self._history_repo is None:
            return
        try:
            from backend.ai.database.tool_history_repository import ToolHistoryRecord
            record = ToolHistoryRecord(id=str(uuid.uuid4()), owner_id=owner_id, session_id=session_id, tool_name=tool_name, arguments=arguments, result_success=result.success, result_message=result.message, result_data=result.data, latency_ms=latency_ms)
            self._history_repo.create(record)
        except Exception as exc:
            logger.warning("ToolExecutor: history record failed: %s", exc)
