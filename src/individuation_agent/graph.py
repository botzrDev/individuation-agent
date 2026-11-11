"""The four-stage individuation cycle as a LangGraph StateGraph.

START -> recognize (S1) -> probe (S2) -> synthesize (S3) -> reorganize (S4) -> END

Each node appends its stage atom to the store and returns the partial state
the next node needs. Dependencies travel in ``config["configurable"]["deps"]``
so the node functions stay plain and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from .governance import Governance
from .models import (
    Event,
    Governance as GovernanceVerdicts,
    Proposal,
    Rejected,
    S1PersonaRecognition,
    S2ShadowProbe,
    S3Synthesis,
    S4StageRecord,
    ShadowItem,
    SourceReport,
    Stages,
)
from .registers import ArchetypeTable, Persona, PersonaRegister
from .reorganize import apply
from .shadow import ShadowDetector, run_detectors
from .store import AtomStore
from .synthesis import Synthesizer


@dataclass
class CycleDeps:
    store: AtomStore
    persona_register: PersonaRegister
    archetype_table: ArchetypeTable
    detectors: list[ShadowDetector]
    synthesizer: Synthesizer
    governance: Governance
    session_id: str
    made_by: str


class CycleState(TypedDict, total=False):
    event: Event
    cycle_id: str
    session_id: str
    context_text: str
    since: datetime | None
    persona: Persona
    s1: S1PersonaRecognition
    items: list[ShadowItem]
    sources: dict[str, SourceReport]
    s2: S2ShadowProbe
    s3: S3Synthesis
    accepted: list[Proposal]
    rejected: list[Rejected]
    governance: GovernanceVerdicts
    s4: S4StageRecord


def _deps(config: RunnableConfig) -> CycleDeps:
    return config["configurable"]["deps"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ nodes


def recognize(state: CycleState, config: RunnableConfig) -> dict[str, Any]:
    d = _deps(config)
    archetype = d.archetype_table.route(state["context_text"])
    persona = d.persona_register.resolve(archetype)
    s1 = S1PersonaRecognition(
        id=uuid4(), made_on=_now(), made_by=d.made_by, made_in=state["session_id"], terminal=True,
        tier="VERIFIED", status="live",
        cycle_id=state["cycle_id"], event=state["event"], archetype=archetype, persona_id=persona.id,
        stated_as=f"I am currently acting as {archetype} because: {state['context_text'][:200]}",
        reason=state["context_text"][:200],
        cognitive_mode=persona.cognitive_mode, capability_bounds=list(persona.capability_bounds),
        context_filters=list(persona.context_filters),
    )
    d.store.append(s1)
    return {"persona": persona, "s1": s1}


def probe(state: CycleState, config: RunnableConfig) -> dict[str, Any]:
    d = _deps(config)
    sources, items = run_detectors(
        d.detectors, d.store, state["persona"], state.get("since"), state["cycle_id"], state["session_id"]
    )
    s2 = S2ShadowProbe(
        id=uuid4(), made_on=_now(), made_by=d.made_by, made_in=state["session_id"],
        links=[state["s1"].id], tier="VERIFIED", status="live",
        cycle_id=state["cycle_id"], persona_id=state["persona"].id, since=state.get("since"),
        probe_ids=[i.probe_id for i in items], sources=sources,
    )
    d.store.append(s2)
    return {"items": items, "sources": sources, "s2": s2}


def synthesize(state: CycleState, config: RunnableConfig) -> dict[str, Any]:
    d = _deps(config)
    s3 = d.synthesizer.run(state["persona"], state["items"], state["context_text"], state["cycle_id"], state["session_id"])
    s3 = s3.model_copy(update={"links": [state["s2"].id, *s3.links], "terminal": False})
    d.store.append(s3)
    return {"s3": s3}


def reorganize(state: CycleState, config: RunnableConfig) -> dict[str, Any]:
    d = _deps(config)
    items_by_id: dict[UUID, ShadowItem] = {i.probe_id: i for i in state["items"]}
    accepted, rejected, verdicts = d.governance.filter(state["s3"].proposals, items_by_id)
    applied = apply(d.store, accepted, items_by_id, state["persona"].id, state["cycle_id"], state["session_id"])

    probed = len(state["items"])
    gained = sum(1 for a in applied if a.action in ("resolve", "adopt"))
    es = (gained / probed) if probed else None

    s4 = S4StageRecord(
        id=uuid4(), made_on=_now(), made_by=d.made_by, made_in=state["session_id"],
        links=[state["s1"].id, state["s2"].id, state["s3"].id], tier=state["s3"].tier, status="live",
        cycle_id=state["cycle_id"], stages=Stages(s1=state["s1"].id, s2=state["s2"].id, s3=state["s3"].id),
        accepted=applied, rejected=rejected, governance=verdicts, es=es, closed_at=_now(),
    )
    d.store.append(s4)
    return {"accepted": accepted, "rejected": rejected, "governance": verdicts, "s4": s4}


# ------------------------------------------------------------------ graph


def build_graph(deps: CycleDeps):
    g = StateGraph(CycleState)
    g.add_node("recognize", recognize)
    g.add_node("probe", probe)
    g.add_node("synthesize", synthesize)
    g.add_node("reorganize", reorganize)
    g.add_edge(START, "recognize")
    g.add_edge("recognize", "probe")
    g.add_edge("probe", "synthesize")
    g.add_edge("synthesize", "reorganize")
    g.add_edge("reorganize", END)
    return g.compile()
