from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from individuation_agent.models import ErrorAtom, IdentityAtom, ToolCallAtom
from individuation_agent.registers import Persona
from individuation_agent.shadow import (
    BlindSpotDetector,
    ContradictionDetector,
    SuppressedCompletionDetector,
    UnusedCapabilityDetector,
    run_detectors,
)
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
SESSION = "session:9"


def identity(statement, about="self.role", session="session:1", status="live", tier="VERIFIED"):
    return IdentityAtom(
        id=uuid4(), made_on=NOW, made_by="agent:test", made_in=session, about=about, terminal=True,
        tier=tier, status=status, statement=statement, atom_kind="fact", confidence=0.9,
    )


def error(signature, session):
    return ErrorAtom(
        id=uuid4(), made_on=NOW, made_by="agent:test", made_in=session, terminal=True,
        tier="VERIFIED", error_signature=signature,
    )


def tool_call(tool_id, when=NOW):
    return ToolCallAtom(
        id=uuid4(), made_on=when, made_by="agent:test", made_in="session:1", terminal=True,
        tier="VERIFIED", tool_id=tool_id,
    )


@pytest.fixture
def store(tmp_path):
    return AtomStore(tmp_path / "atoms.jsonl")


@pytest.fixture
def persona():
    return Persona(id="g", archetype="Guardian", display_name="G", cognitive_mode="convergent",
                   capability_bounds=["grep", "read", "bash"])


def test_contradiction_detected_on_conflicting_identity_atoms(store, persona):
    a = identity("I am Guardian")
    b = identity("I am Trickster")
    store.append(a)
    store.append(b)
    report, items = ContradictionDetector().probe(store, persona, None, "c1", SESSION)
    assert report.status == "OK" and report.count == 1
    assert items[0].class_ == "contradiction"
    assert {items[0].payload.atom_a, items[0].payload.atom_b} == {a.id, b.id}
    assert items[0].payload.severity == "CRITICAL"


def test_no_contradiction_when_superseded(store, persona):
    a = identity("I am Guardian")
    store.append(a)
    store.supersede(a.id, identity("I am Trickster"))
    report, items = ContradictionDetector().probe(store, persona, None, "c1", SESSION)
    assert report.status == "OK" and report.count == 0 and items == []


def test_blind_spot_needs_two_sessions(store, persona):
    store.append(error("E_TIMEOUT", "session:1"))
    store.append(error("E_TIMEOUT", "session:1"))
    _, items = BlindSpotDetector().probe(store, persona, None, "c1", SESSION)
    assert items == []
    store.append(error("E_TIMEOUT", "session:2"))
    report, items = BlindSpotDetector().probe(store, persona, None, "c1", SESSION)
    assert report.count == 1
    assert items[0].class_ == "blind_spot"
    assert items[0].payload.occurrences == 3
    assert sorted(items[0].payload.sessions) == ["session:1", "session:2"]


def test_blind_spot_counts_sessions_across_history_but_needs_a_new_occurrence_since_last_cycle(store, persona):
    old = error("E_TIMEOUT", "session:1")
    store.append(old.model_copy(update={"made_on": NOW - timedelta(days=2)}))
    since = NOW - timedelta(days=1)
    # nothing new since the last cycle: no finding, even though the history holds the signature
    _, items = BlindSpotDetector().probe(store, persona, since, "c1", SESSION)
    assert items == []
    # one new occurrence in a second session: the recurrence is across sessions, so it is a blind spot
    store.append(error("E_TIMEOUT", "session:2"))
    report, items = BlindSpotDetector().probe(store, persona, since, "c2", SESSION)
    assert report.count == 1 and sorted(items[0].payload.sessions) == ["session:1", "session:2"]
    # a signature seen only in the window's own session, with no earlier history, is not a blind spot
    store.append(error("E_OTHER", "session:2"))
    _, items = BlindSpotDetector().probe(store, persona, since, "c3", SESSION)
    assert [i.payload.error_signature for i in items] == ["E_TIMEOUT"]


def test_unused_capability_lists_uncalled_tools(store, persona):
    store.append(tool_call("grep"))
    store.append(tool_call("bash", when=NOW - timedelta(days=2)))
    report, items = UnusedCapabilityDetector().probe(store, persona, NOW - timedelta(days=1), "c1", SESSION)
    assert report.status == "OK"
    # "unused" means never called, not "not called since the last cycle" (I1)
    assert sorted(i.payload.tool_id for i in items) == ["read"]
    assert all(i.class_ == "unused_capability" for i in items)


def test_unused_capability_blind_when_no_bounds(store):
    bare = Persona(id="s", archetype="Sage", display_name="S", cognitive_mode="divergent")
    report, items = UnusedCapabilityDetector().probe(store, bare, None, "c1", SESSION)
    assert report.status == "BLIND" and report.count == 0 and items == []


def test_suppressed_completion_default_is_blind(store, persona):
    report, items = SuppressedCompletionDetector().probe(store, persona, None, "c1", SESSION)
    assert report.status == "BLIND" and items == []


class Raiser:
    name = "error_log"

    def probe(self, store, persona, since, cycle_id, session_id):
        raise RuntimeError("boom")


def test_run_detectors_marks_raiser_unknown_and_continues(store, persona):
    store.append(identity("A"))
    store.append(identity("B"))
    sources, items = run_detectors([ContradictionDetector(), Raiser()], store, persona, None, "c1", SESSION)
    assert sources["error_log"].status == "UNKNOWN"
    assert sources["memory_audit"].status == "OK"
    assert len(items) == 1


def test_run_detectors_appends_items_to_store(store, persona):
    store.append(identity("A"))
    store.append(identity("B"))
    before = store.line_count()
    _, items = run_detectors([ContradictionDetector()], store, persona, None, "c1", SESSION)
    assert store.line_count() == before + 1
    assert store.get(items[0].id).kind == "shadow.item"
    assert store.get(items[0].id).made_in == SESSION


def test_contradiction_item_carries_weakest_atom_tier_and_both_statements(store, persona):
    store.append(identity("I am Guardian", tier="VERIFIED"))
    store.append(identity("I am Trickster", tier="REPORTED"))
    _, [item] = ContradictionDetector().probe(store, persona, None, "c1", SESSION)
    assert item.tier == "REPORTED"
    assert {item.payload.statement_a, item.payload.statement_b} == {"I am Guardian", "I am Trickster"}


def test_run_detectors_reuses_open_item_instead_of_minting_duplicate(store, persona):
    store.append(identity("A"))
    store.append(identity("B"))
    _, [first] = run_detectors([ContradictionDetector()], store, persona, None, "c1", SESSION)
    before = store.line_count()
    _, [again] = run_detectors([ContradictionDetector()], store, persona, None, "c2", SESSION)
    assert again.probe_id == first.probe_id
    assert store.line_count() == before
    assert len(store.all(kind="shadow.item", status="live")) == 1


def test_open_item_not_refound_is_still_probed(store, persona):
    """An open finding leaves the probe set only by resolution, adoption, revision or the deferral limit.
    A blind spot seen once (since=None) must still be probed in a later cycle whose ``since`` excludes its errors."""
    store.append(error("boom", "session:1"))
    store.append(error("boom", "session:2"))
    dets = [BlindSpotDetector()]
    _, first = run_detectors(dets, store, persona, None, "c1", SESSION)
    assert [i.class_ for i in first] == ["blind_spot"]
    later = NOW + timedelta(days=1)  # no errors since: the detector re-finds nothing
    report, second = run_detectors(dets, store, persona, later, "c2", SESSION)
    assert report["error_log"].count == 0
    assert [i.probe_id for i in second] == [first[0].probe_id]
    assert store.line_count() == 3  # nothing new minted for the carried item
