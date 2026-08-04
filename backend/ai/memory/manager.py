"""
MemoryManager — the unified entry point for all three memory tiers.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.ai.memory.long import LongMemory
from backend.ai.memory.permanent import PermanentMemory
from backend.ai.memory.short import ShortMemory
from backend.ai.memory.types import MemoryCategory, MemoryQuery, MemoryTier
from backend.diagnostics_system import trace_step
from backend.diagnostics_system.metrics import record_latency

logger = logging.getLogger(__name__)


class MemoryManager:
    __slots__ = ("_short", "_long", "_permanent")

    def __init__(self, long_repository: Any | None = None, permanent_repository: Any | None = None, retention_days: int = 90) -> None:
        self._short = ShortMemory()
        self._long = LongMemory(repository=long_repository, retention_days=retention_days)
        self._permanent = PermanentMemory(repository=permanent_repository)

    @property
    def short(self) -> ShortMemory:
        return self._short

    @property
    def long(self) -> LongMemory:
        return self._long

    @property
    def permanent(self) -> PermanentMemory:
        return self._permanent

    def new_turn(self) -> None:
        self._short.clear()

    def retrieve_for_prompt(self, owner_id: int, query_text: str = "") -> dict[str, str]:
        t0 = time.perf_counter()
        permanent_text = self._permanent.as_text(owner_id)
        long_entries = self._long.retrieve(MemoryQuery(owner_id=owner_id, tier=MemoryTier.LONG, query_text=query_text, limit=10, min_importance=0.3))
        long_text = self._long.as_text(long_entries)
        short_text = self._short.as_text()
        record_latency("memory_retrieval", t0, function="retrieve_for_prompt")
        trace_step("memory", "manager", "retrieve_complete", function="retrieve_for_prompt", status="success", owner_id=owner_id)
        return {"permanent": permanent_text, "long": long_text, "short": short_text}

    def store_long(self, owner_id: int, content: str, category: MemoryCategory = MemoryCategory.SUMMARY, importance: float = 0.5, metadata: dict[str, Any] | None = None) -> Any:
        return self._long.store(owner_id, content, category, importance, metadata)

    def store_permanent(self, owner_id: int, content: str, category: MemoryCategory = MemoryCategory.FACT, importance: float = 1.0, metadata: dict[str, Any] | None = None) -> Any:
        return self._permanent.store(owner_id, content, category, importance, metadata)

    def status(self) -> dict[str, Any]:
        return {"short_count": self._short.count(), "long_available": self._long._repository is not None, "permanent_available": self._permanent._repository is not None}
