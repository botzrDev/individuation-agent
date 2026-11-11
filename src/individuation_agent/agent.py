"""IndividuationAgent: runs cycles on identity events, with a default rate-limit policy."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from .graph import CycleDeps, build_graph
from .models import Event, S4StageRecord

ALWAYS: frozenset[str] = frozenset({"session_start", "session_end", "role_switch"})


class IndividuationAgent:
    def __init__(self, deps: CycleDeps):
        self.deps = deps
        self.graph = build_graph(deps)
        self._seen: set[str] = set()
        self._last_cycle_at: datetime | None = None

    def should_cycle(self, event: Event) -> bool:
        """Default policy: always on session boundaries and role switches; other event classes once per session."""
        if event in ALWAYS:
            return True
        return event not in self._seen

    def run_cycle(self, event: Event, context_text: str) -> S4StageRecord:
        cycle_id = f"cycle:{uuid4()}"
        state = {
            "event": event,
            "cycle_id": cycle_id,
            "session_id": self.deps.session_id,
            "context_text": context_text,
            "since": self._last_cycle_at,
        }
        out = self.graph.invoke(state, config={"configurable": {"deps": self.deps}})
        self._seen.add(event)
        self._last_cycle_at = out["s4"].closed_at
        return out["s4"]
