"""Property 6, constraint-bound, sharpened: the lab's evidence constraint is an id-based check, not a
vocabulary regex. A rationale cites evidence when it names an atom id, a probe id or a session id
that exists in the store. (The live case study showed the regex proxy biting on wording.)"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from individuation_agent.checks import evaluate
from individuation_agent.governance import Governance
from individuation_agent.models import Check, ConstraintAtom, IdentityAtom, Proposal, ShadowItem, UnusedCapabilityPayload
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = AtomStore(tmp_path / "atoms.jsonl")
    s.append(IdentityAtom(id=uuid4(), made_on=NOW, made_by="agent:t", made_in="session:hist-04", about="self.role",
                          terminal=True, tier="REPORTED", status="live", statement="I am a release manager",
                          atom_kind="fact", confidence=0.6))
    return s


def _item():
    return ShadowItem(id=uuid4(), made_on=NOW, made_by="d", made_in="s", terminal=True, tier="VERIFIED",
                      probe_id=uuid4(), class_="unused_capability",
                      payload=UnusedCapabilityPayload(tool_id="grep", available_since=NOW, never_called_in=["s"]),
                      probed_in="c1", persona_id="g", defer_count=0)


def test_cites_evidence_passes_on_an_atom_id_in_the_store(store):
    atom_id = store.all(kind="self.identity_atom")[0].id
    assert evaluate(Check(kind="cites_evidence"), f"the claim in {atom_id} is newer", store=store) == "PASS"


def test_cites_evidence_passes_on_a_session_id_in_the_store(store):
    assert evaluate(Check(kind="cites_evidence"), "stated in session:hist-04 by the user", store=store) == "PASS"


def test_cites_evidence_fails_on_vocabulary_alone(store):
    assert evaluate(Check(kind="cites_evidence"), "the newer statement in the log stands", store=store) == "FAIL"


def test_cites_evidence_fails_on_an_id_that_is_not_in_the_store(store):
    assert evaluate(Check(kind="cites_evidence"), f"see {uuid4()}", store=store) == "FAIL"


def test_cites_evidence_is_unknown_without_a_store():
    assert evaluate(Check(kind="cites_evidence"), "anything") == "UNKNOWN"


def test_governance_applies_the_evidence_constraint_by_id(store):
    store.append(ConstraintAtom(id=uuid4(), made_on=NOW, made_by="agent:t", made_in="s", terminal=True, tier="VERIFIED",
                                status="live", name="evidence-cited", applies_to="cycle.proposals",
                                check=Check(kind="cites_evidence")))
    it = _item()
    store.append(it)  # Stage 2 appends every probed item before governance runs
    cited = Proposal(id=uuid4(), action="adopt", target=it.probe_id, rationale=f"bound since {it.probe_id}", tier="VERIFIED")
    bare = Proposal(id=uuid4(), action="adopt", target=it.probe_id, rationale="the tool is useful", tier="VERIFIED")
    accepted, rejected, verdicts = Governance(store).filter([cited, bare], {it.probe_id: it})
    assert [p.id for p in accepted] == [cited.id]
    assert rejected[0].proposal_id == bare.id and rejected[0].blocked_by == "evidence-cited"


def test_evaluate_reports_unknown_when_the_store_raises():
    """Honesty state: a crashing evidence source is UNKNOWN, never an exception escaping the router."""
    class Broken:
        def all(self):
            raise RuntimeError("store unreadable")

    assert evaluate(Check(kind="cites_evidence"), "cites nothing", store=Broken()) == "UNKNOWN"
