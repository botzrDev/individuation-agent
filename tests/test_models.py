from datetime import datetime, timezone
from uuid import uuid4

import pytest
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from individuation_agent.models import (
    Accepted,
    ContradictionPayload,
    Governance,
    ModelCall,
    Proposal,
    Rejected,
    S1PersonaRecognition,
    S2ShadowProbe,
    S3Synthesis,
    S4StageRecord,
    ShadowItem,
    SourceReport,
    UnusedCapabilityPayload,
    validate_against_schema,
    weakest,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def env(**kw):
    base = dict(
        id=uuid4(),
        made_on=NOW,
        made_by="agent:test",
        made_in="session:1",
        tier="VERIFIED",
        status="live",
        terminal=True,
    )
    base.update(kw)
    return base


def test_weakest_tier_order():
    assert weakest(["VERIFIED", "INFERRED"]) == "INFERRED"
    assert weakest(["REPORTED", "UNKNOWN"]) == "UNKNOWN"
    assert weakest(["VERIFIED"]) == "VERIFIED"


def test_s1_round_trips_against_schema():
    s1 = S1PersonaRecognition(
        **env(),
        cycle_id="c1",
        event="session_start",
        archetype="Guardian",
        persona_id="guardian-1",
        stated_as="I am currently acting as Guardian because the user asked about security policy",
        cognitive_mode="convergent",
        capability_bounds=["grep", "read"],
    )
    validate_against_schema(s1, "s1-persona-recognition.schema.json")


def test_shadow_item_contradiction_round_trips_against_schema():
    item = ShadowItem(
        **env(),
        probe_id=uuid4(),
        class_="contradiction",
        payload=ContradictionPayload(
            atom_a=uuid4(), atom_b=uuid4(), field="statement", detected_on=NOW, severity="CRITICAL"
        ),
        probed_in="c1",
        persona_id="guardian-1",
        defer_count=0,
    )
    validate_against_schema(item, "shadow-item.schema.json")


def test_shadow_item_unused_capability_round_trips_against_schema():
    item = ShadowItem(
        **env(),
        probe_id=uuid4(),
        class_="unused_capability",
        payload=UnusedCapabilityPayload(tool_id="bash", available_since=NOW, never_called_in=["session:1"]),
        probed_in="c1",
        persona_id="guardian-1",
        defer_count=1,
    )
    validate_against_schema(item, "shadow-item.schema.json")


def test_defer_count_above_three_rejected():
    with pytest.raises(ValidationError):
        ShadowItem(
            **env(),
            probe_id=uuid4(),
            class_="unused_capability",
            payload=UnusedCapabilityPayload(tool_id="bash", available_since=NOW, never_called_in=["s"]),
            probed_in="c1",
            persona_id="p",
            defer_count=4,
        )


def test_s2_round_trips_against_schema():
    ok = SourceReport(status="OK", count=1)
    blind = SourceReport(status="BLIND", count=0)
    s2 = S2ShadowProbe(
        **env(),
        cycle_id="c1",
        persona_id="guardian-1",
        probe_ids=[uuid4()],
        sources={"memory_audit": ok, "error_log": blind, "tool_registry": blind, "collective_unconscious": blind},
    )
    validate_against_schema(s2, "s2-shadow-probe.schema.json")


def test_s3_round_trips_against_schema():
    s3 = S3Synthesis(
        **env(tier="REPORTED"),
        cycle_id="c1",
        mode="divergent",
        complement_of="guardian-1",
        model_call=ModelCall(base_model_id="fake", base_model_version="0"),
        proposals=[Proposal(id=uuid4(), action="resolve", target=uuid4(), rationale="b is newer", tier="REPORTED")],
    )
    validate_against_schema(s3, "s3-synthesis.schema.json")


def test_s4_round_trips_against_schema():
    s4 = S4StageRecord(
        **env(),
        cycle_id="c1",
        stages={"s1": uuid4(), "s2": uuid4(), "s3": uuid4()},
        accepted=[Accepted(proposal_id=uuid4(), action="resolve", appended_atom=uuid4())],
        rejected=[Rejected(proposal_id=uuid4(), blocked_by="no-em-dashes")],
        governance=Governance(constraint_check="PASS", obligation_check="PASS", reconcile="UNKNOWN"),
        es=0.5,
        closed_at=NOW,
    )
    validate_against_schema(s4, "s4-stage-record.schema.json")


def test_terminal_required_when_links_empty():
    s1 = S1PersonaRecognition(
        **env(terminal=False),
        cycle_id="c1",
        event="scheduled",
        archetype="Sage",
        persona_id="sage-1",
        stated_as="I am currently acting as Sage",
        cognitive_mode="divergent",
        capability_bounds=[],
    )
    with pytest.raises(SchemaError):
        validate_against_schema(s1, "s1-persona-recognition.schema.json")
