from datetime import datetime, timezone
from uuid import uuid4

import pytest

from individuation_agent.models import (
    ContradictionPayload,
    IdentityAtom,
    Proposal,
    ShadowItem,
    UnusedCapabilityPayload,
)
from individuation_agent.reorganize import apply
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def identity(statement):
    return IdentityAtom(
        id=uuid4(), made_on=NOW, made_by="a", made_in="s1", about="self.role", terminal=True, tier="VERIFIED",
        statement=statement, atom_kind="fact", confidence=0.9,
    )


def contradiction_item(a, b):
    return ShadowItem(
        id=uuid4(), made_on=NOW, made_by="d", made_in="s", terminal=True, tier="VERIFIED",
        probe_id=uuid4(), class_="contradiction",
        payload=ContradictionPayload(atom_a=a.id, atom_b=b.id, field="statement", detected_on=NOW, severity="CRITICAL"),
        probed_in="c1", persona_id="g", defer_count=0,
    )


def unused_item(tool_id="bash", defer_count=0):
    return ShadowItem(
        id=uuid4(), made_on=NOW, made_by="d", made_in="s", terminal=True, tier="VERIFIED",
        probe_id=uuid4(), class_="unused_capability",
        payload=UnusedCapabilityPayload(tool_id=tool_id, available_since=NOW, never_called_in=["s"]),
        probed_in="c1", persona_id="g", defer_count=defer_count,
    )


def proposal(target, action, rationale="because", new_atom=None):
    return Proposal(id=uuid4(), action=action, target=target, rationale=rationale, tier="REPORTED", new_atom=new_atom)


@pytest.fixture
def store(tmp_path):
    return AtomStore(tmp_path / "atoms.jsonl")


def live_item(store, probe_id):
    live = [i for i in store.all(kind="shadow.item", status="live") if i.probe_id == probe_id]
    assert len(live) == 1
    return live[0]


def test_resolve_supersedes_both_conflicting_atoms(store):
    a, b = identity("I am Guardian"), identity("I am Trickster")
    store.append(a)
    store.append(b)
    it = contradiction_item(a, b)
    store.append(it)
    p = proposal(it.probe_id, "resolve", rationale="I am Guardian", new_atom={"statement": "I am Guardian"})

    [acc] = apply(store, [p], {it.probe_id: it}, "g", "c1", "s")

    assert acc.proposal_id == p.id and acc.action == "resolve"
    assert store.get(a.id).status == "superseded"
    assert store.get(b.id).status == "superseded"
    new = store.get(acc.appended_atom)
    assert new.kind == "self.identity_atom" and new.statement == "I am Guardian" and new.status == "live"
    assert new.tier == "REPORTED"
    assert live_item(store, it.probe_id).resolution.action == "resolve"
    # the replacement references what it replaced (I9)
    assert new.supersedes == a.id
    assert set(new.links) == {a.id, b.id}
    assert new.terminal is False


def test_adopt_appends_capability_atom(store):
    it = unused_item("bash")
    store.append(it)
    [acc] = apply(store, [proposal(it.probe_id, "adopt")], {it.probe_id: it}, "g", "c1", "s")
    cap = store.get(acc.appended_atom)
    assert cap.kind == "persona.capability"
    assert cap.model_extra["persona_id"] == "g" and cap.model_extra["tool_id"] == "bash"
    assert live_item(store, it.probe_id).resolution.by_atom == cap.id


def test_revise_appends_value_atom(store):
    it = unused_item("bash")
    store.append(it)
    [acc] = apply(store, [proposal(it.probe_id, "revise", rationale="I value thoroughness")], {it.probe_id: it}, "g", "c1", "s")
    v = store.get(acc.appended_atom)
    assert v.kind == "self.identity_atom" and v.atom_kind == "value" and v.statement == "I value thoroughness"


def test_defer_increments_defer_count_via_supersede(store):
    it = unused_item("bash", defer_count=1)
    store.append(it)
    [acc] = apply(store, [proposal(it.probe_id, "defer")], {it.probe_id: it}, "g", "c1", "s")
    assert store.get(it.id).status == "superseded"
    current = live_item(store, it.probe_id)
    assert current.defer_count == 2
    assert current.resolution.action == "defer"
    assert acc.appended_atom == current.id


def test_store_only_grows(store):
    a, b = identity("x"), identity("y")
    store.append(a)
    store.append(b)
    it = contradiction_item(a, b)
    store.append(it)
    first = store.path.read_bytes().splitlines()[:3]
    before = store.line_count()
    apply(store, [proposal(it.probe_id, "resolve", new_atom={"statement": "x"})], {it.probe_id: it}, "g", "c1", "s")
    assert store.line_count() > before
    assert store.path.read_bytes().splitlines()[:3] == first
