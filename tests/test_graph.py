from datetime import datetime, timezone
from uuid import uuid4

import pytest

from individuation_agent.agent import IndividuationAgent
from individuation_agent.fakes import ScriptedModel
from individuation_agent.governance import Governance
from individuation_agent.graph import CycleDeps
from individuation_agent.models import Check, ConstraintAtom, IdentityAtom, validate_against_schema
from individuation_agent.registers import ArchetypeEntry, ArchetypeTable, Persona, PersonaRegister
from individuation_agent.shadow import (
    BlindSpotDetector,
    ContradictionDetector,
    SuppressedCompletionDetector,
    UnusedCapabilityDetector,
)
from individuation_agent.store import AtomStore
from individuation_agent.synthesis import Synthesizer

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def identity(statement, about):
    return IdentityAtom(
        id=uuid4(), made_on=NOW, made_by="a", made_in="s0", about=about, terminal=True, tier="VERIFIED",
        statement=statement, atom_kind="fact", confidence=0.9,
    )


@pytest.fixture
def deps(tmp_path):
    store = AtomStore(tmp_path / "atoms.jsonl")
    personas = PersonaRegister(
        personas=[
            Persona(id="sage-1", archetype="Sage", display_name="Sage", cognitive_mode="divergent"),
            Persona(id="guardian-1", archetype="Guardian", display_name="Guardian", cognitive_mode="convergent"),
        ],
        active="sage-1",
    )
    table = ArchetypeTable(
        entries=[ArchetypeEntry(archetype="Guardian", activation_conditions=[Check(kind="pattern", patterns=["security"])],
                                default_cognitive_mode="convergent")],
        default="Sage",
    )
    return CycleDeps(
        store=store,
        persona_register=personas,
        archetype_table=table,
        detectors=[ContradictionDetector(), BlindSpotDetector(), UnusedCapabilityDetector(), SuppressedCompletionDetector()],
        synthesizer=Synthesizer(ScriptedModel(), base_model_id="scripted", base_model_version="0"),
        governance=Governance(store),
        session_id="session:test",
        made_by="agent:test",
    )


def seed_two_contradictions(store):
    store.append(identity("I am Guardian", "self.role"))
    store.append(identity("I am Trickster", "self.role"))
    store.append(identity("I use grep", "self.tools"))
    store.append(identity("I never use grep", "self.tools"))


def test_full_cycle_appends_s1_s2_s3_s4_in_order(deps):
    seed_two_contradictions(deps.store)
    agent = IndividuationAgent(deps)
    s4 = agent.run_cycle("session_start", "the user asked about security policy")
    kinds = [a.kind for a in deps.store.all() if a.kind.startswith("cycle.") or a.kind == "self.stage_record"]
    assert kinds == ["cycle.s1_persona_recognition", "cycle.s2_shadow_probe", "cycle.s3_synthesis", "self.stage_record"]
    s1 = deps.store.get(s4.stages.s1)
    assert s1.archetype == "Guardian" and s1.persona_id == "guardian-1"
    assert s1.stated_as.startswith("I am currently acting as Guardian")


def test_s4_validates_against_schema(deps):
    seed_two_contradictions(deps.store)
    s4 = IndividuationAgent(deps).run_cycle("session_start", "hello")
    validate_against_schema(s4, "s4-stage-record.schema.json")
    validate_against_schema(deps.store.get(s4.stages.s2), "s2-shadow-probe.schema.json")


def test_es_is_resolved_plus_adopted_over_probed(deps):
    seed_two_contradictions(deps.store)
    s4 = IndividuationAgent(deps).run_cycle("session_start", "hello")
    assert s4.es == 0.5
    assert [a.action for a in s4.accepted] == ["resolve"]
    s2 = deps.store.get(s4.stages.s2)
    assert s2.sources["memory_audit"].count == 2
    assert s2.sources["tool_registry"].status == "BLIND"


def test_es_none_when_nothing_probed(deps):
    s4 = IndividuationAgent(deps).run_cycle("session_start", "hello")
    assert s4.es is None
    assert s4.accepted == [] and s4.rejected == []


def test_should_cycle_rate_limits_scheduled(deps):
    agent = IndividuationAgent(deps)
    assert agent.should_cycle("scheduled") is True
    agent.run_cycle("scheduled", "tick")
    assert agent.should_cycle("scheduled") is False
    assert agent.should_cycle("session_start") is True
    agent.run_cycle("session_start", "x")
    assert agent.should_cycle("session_start") is True


def test_governance_unknown_recorded_in_s4(deps):
    seed_two_contradictions(deps.store)
    deps.store.append(ConstraintAtom(
        id=uuid4(), made_on=NOW, made_by="austin", made_in="s0", terminal=True, tier="VERIFIED",
        name="hand-check", applies_to="proposals", check=Check(kind="manual"),
    ))
    s4 = IndividuationAgent(deps).run_cycle("session_start", "hello")
    assert s4.governance.constraint_check == "UNKNOWN"
    assert len(s4.accepted) == 1


def test_deferred_item_carries_forward_and_hits_max_defer(deps):
    seed_two_contradictions(deps.store)
    deps.synthesizer.model = ScriptedModel(behavior="defer_all")
    agent = IndividuationAgent(deps)
    records = [agent.run_cycle("scheduled", f"tick {i}") for i in range(4)]
    s2_probe_counts = [len(deps.store.get(r.stages.s2).probe_ids) for r in records]
    assert s2_probe_counts == [2, 2, 2, 2]
    live = [i for i in deps.store.all(kind="shadow.item", status="live")]
    assert len(live) == 2
    assert {i.defer_count for i in live} == {3}
    assert [r.blocked_by for r in records[3].rejected] == ["max_defer", "max_defer"]
    assert records[0].rejected == [] and records[2].rejected == []
