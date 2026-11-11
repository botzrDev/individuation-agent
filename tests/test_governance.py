from datetime import datetime, timezone
from uuid import uuid4

import pytest

from individuation_agent.governance import Governance
from individuation_agent.models import (
    Check,
    ConstraintAtom,
    ObligationAtom,
    Proposal,
    ShadowItem,
    UnusedCapabilityPayload,
)
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def item(defer_count=0):
    return ShadowItem(
        id=uuid4(), made_on=NOW, made_by="d", made_in="s", terminal=True, tier="VERIFIED",
        probe_id=uuid4(), class_="unused_capability",
        payload=UnusedCapabilityPayload(tool_id="bash", available_since=NOW, never_called_in=["s"]),
        probed_in="c1", persona_id="g", defer_count=defer_count,
    )


def proposal(target, action="adopt", rationale="bash is useful"):
    return Proposal(id=uuid4(), action=action, target=target, rationale=rationale, tier="VERIFIED")


def constraint(name, check, status="live"):
    return ConstraintAtom(
        id=uuid4(), made_on=NOW, made_by="austin", made_in="s", terminal=True, tier="VERIFIED", status=status,
        name=name, applies_to="proposals", check=check, unchecked_because=None,
    )


def obligation(name, obligation_status, status="live"):
    return ObligationAtom(
        id=uuid4(), made_on=NOW, made_by="austin", made_in="s", terminal=True, tier="VERIFIED", status=status,
        name=name, owed_to="counterparty", obligation_status=obligation_status,
    )


@pytest.fixture
def store(tmp_path):
    return AtomStore(tmp_path / "atoms.jsonl")


def test_pass_when_no_constraints(store):
    it = item()
    accepted, rejected, verdicts = Governance(store).filter([proposal(it.probe_id)], {it.probe_id: it})
    assert len(accepted) == 1 and rejected == []
    assert verdicts.constraint_check == "PASS"
    assert verdicts.obligation_check == "PASS"
    assert verdicts.reconcile == "PASS"


def test_text_forbidden_constraint_rejects_with_name(store):
    store.append(constraint("no-critical", Check(kind="text_forbidden", patterns=[r"\bCritical\b"])))
    it = item()
    bad = proposal(it.probe_id, rationale="this is Critical")
    good = proposal(it.probe_id, rationale="this is routine")
    accepted, rejected, verdicts = Governance(store).filter([bad, good], {it.probe_id: it})
    assert [p.id for p in accepted] == [good.id]
    assert rejected[0].proposal_id == bad.id and rejected[0].blocked_by == "no-critical"
    assert verdicts.constraint_check == "FAIL"


def test_manual_constraint_records_unknown_but_does_not_reject(store):
    store.append(constraint("hand-check", Check(kind="manual")))
    it = item()
    accepted, rejected, verdicts = Governance(store).filter([proposal(it.probe_id)], {it.probe_id: it})
    assert len(accepted) == 1 and rejected == []
    assert verdicts.constraint_check == "UNKNOWN"


def test_retired_constraint_is_ignored(store):
    store.append(constraint("old", Check(kind="text_forbidden", patterns=["bash"]), status="retired"))
    it = item()
    accepted, rejected, verdicts = Governance(store).filter([proposal(it.probe_id)], {it.probe_id: it})
    assert len(accepted) == 1 and verdicts.constraint_check == "PASS"


def test_breached_obligation_rejects_all(store):
    store.append(obligation("deliver-report", "BREACHED"))
    it = item()
    p1, p2 = proposal(it.probe_id), proposal(it.probe_id)
    accepted, rejected, verdicts = Governance(store).filter([p1, p2], {it.probe_id: it})
    assert accepted == []
    assert {r.blocked_by for r in rejected} == {"obligation:deliver-report"}
    assert verdicts.obligation_check == "FAIL"


def test_fourth_defer_rejected_max_defer(store):
    it = item(defer_count=3)
    accepted, rejected, _ = Governance(store).filter([proposal(it.probe_id, action="defer")], {it.probe_id: it})
    assert accepted == []
    assert rejected[0].blocked_by == "max_defer"


def test_check_exception_yields_unknown(store, monkeypatch):
    store.append(constraint("boom", Check(kind="pattern", patterns=["x"])))
    import individuation_agent.governance as gov

    def explode(check, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(gov, "evaluate", explode)
    it = item()
    accepted, rejected, verdicts = Governance(store).filter([proposal(it.probe_id)], {it.probe_id: it})
    assert verdicts.constraint_check == "UNKNOWN"
    assert len(accepted) == 1


def test_superseded_breached_obligation_is_ignored(store):
    store.append(obligation("old-promise", "BREACHED", status="superseded"))
    it = item()
    accepted, rejected, verdicts = Governance(store).filter([proposal(it.probe_id)], {it.probe_id: it})
    assert len(accepted) == 1 and rejected == []
    assert verdicts.obligation_check == "PASS"


def test_resolve_without_valid_new_atom_rejected(store):
    it = item()
    no_atom = proposal(it.probe_id, action="resolve")
    bad_conf = Proposal(id=uuid4(), action="revise", target=it.probe_id, rationale="r", tier="INFERRED",
                        new_atom={"statement": "I value care", "atom_kind": "value", "confidence": "high"})
    bad_kind = Proposal(id=uuid4(), action="resolve", target=it.probe_id, rationale="r", tier="INFERRED",
                        new_atom={"statement": "x", "atom_kind": "opinion"})
    good = Proposal(id=uuid4(), action="resolve", target=it.probe_id, rationale="r", tier="INFERRED",
                    new_atom={"statement": "I am Guardian", "atom_kind": "fact", "confidence": 0.8})
    accepted, rejected, _ = Governance(store).filter([no_atom, bad_conf, bad_kind, good], {it.probe_id: it})
    assert [p.id for p in accepted] == [good.id]
    assert {r.blocked_by for r in rejected} == {"new_atom_invalid"}
