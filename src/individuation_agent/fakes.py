"""Test and demo support: a scripted chat model and a seeded demo store. No provider calls."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .governance import Governance
from .models import Check, IdentityAtom, ToolCallAtom
from .registers import ArchetypeEntry, ArchetypeTable, Persona, PersonaRegister
from .shadow import BlindSpotDetector, ContradictionDetector, SuppressedCompletionDetector, UnusedCapabilityDetector
from .store import AtomStore
from .synthesis import Synthesizer

_LINE = re.compile(r"^([0-9a-f-]{36}): (\w+): (.*)$", re.MULTILINE)
_SIDE_B = re.compile(r"b='(.*)'$")


class ScriptedModel(BaseChatModel):
    """Deterministic stand-in for a provider.

    behavior="resolve_first": resolves the first ``resolve_n`` contradiction items, keeping side b
    (the newer statement) as the claim; proposes nothing else.
    behavior="defer_all": defers every item it is shown.
    """

    resolve_n: int = 1
    behavior: str = "resolve_first"

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs) -> ChatResult:
        text = messages[-1].content
        proposals = []
        for probe_id, cls, rest in _LINE.findall(text):
            if self.behavior == "defer_all":
                proposals.append({"action": "defer", "target": probe_id, "rationale": "not yet"})
            elif cls == "contradiction" and len(proposals) < self.resolve_n:
                m = _SIDE_B.search(rest)
                statement = m.group(1) if m else "the newer statement stands"
                proposals.append({
                    "action": "resolve", "target": probe_id, "rationale": "newest statement stands",
                    "new_atom": {"statement": statement, "atom_kind": "fact", "confidence": 0.7},
                })
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=json.dumps(proposals)))])


def seed_demo_store(path: Path) -> AtomStore:
    """Two conflicting identity atoms and one tool call, so one bound tool goes unused."""
    store = AtomStore(path)
    t0 = datetime.now(timezone.utc) - timedelta(days=2)
    store.append(IdentityAtom(
        id=uuid4(), made_on=t0, made_by="agent:demo", made_in="session:seed-1", about="self.role",
        terminal=True, tier="VERIFIED", statement="I am a research assistant", atom_kind="fact", confidence=0.9,
    ))
    store.append(IdentityAtom(
        id=uuid4(), made_on=t0 + timedelta(hours=1), made_by="agent:demo", made_in="session:seed-2", about="self.role",
        terminal=True, tier="REPORTED", statement="I am a security reviewer", atom_kind="fact", confidence=0.6,
    ))
    store.append(ToolCallAtom(
        id=uuid4(), made_on=t0 + timedelta(hours=2), made_by="agent:demo", made_in="session:seed-2",
        terminal=True, tier="VERIFIED", tool_id="read",
    ))
    return store


def demo_register() -> PersonaRegister:
    return PersonaRegister(
        personas=[
            Persona(id="sage-1", archetype="Sage", display_name="Sage", cognitive_mode="divergent",
                    capability_bounds=["read", "grep"]),
            Persona(id="guardian-1", archetype="Guardian", display_name="Guardian", cognitive_mode="convergent",
                    capability_bounds=["read", "grep"],
                    context_filters=[Check(kind="text_forbidden", patterns=[r"\bCritical\b"])]),
        ],
        active="sage-1",
    )


def demo_table() -> ArchetypeTable:
    return ArchetypeTable(
        entries=[ArchetypeEntry(archetype="Guardian", activation_conditions=[Check(kind="pattern", patterns=["security", "policy"])],
                                default_cognitive_mode="convergent")],
        default="Sage",
    )


def demo_deps(store: AtomStore, model: BaseChatModel, base_model_id: str, base_model_version: str, session_id: str):
    from .graph import CycleDeps

    return CycleDeps(
        store=store,
        persona_register=demo_register(),
        archetype_table=demo_table(),
        detectors=[ContradictionDetector(), BlindSpotDetector(), UnusedCapabilityDetector(), SuppressedCompletionDetector()],
        synthesizer=Synthesizer(model, base_model_id=base_model_id, base_model_version=base_model_version),
        governance=Governance(store),
        session_id=session_id,
        made_by="agent:individuation-agent",
    )
