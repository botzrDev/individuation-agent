"""Property 8 of the pre-registered substrate: a formal precedence relation between the atom store and a
second, user-owned store (the ledger) resolves conflicts so they do not accumulate. Precedence: the
ledger wins for obligation state; the store wins for self-claims. Every conflict and its resolution is
on the record, and governance's reconcile verdict is computed, not stubbed, when a ledger is wired."""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from individuation_agent.governance import Governance
from individuation_agent.models import IdentityAtom, ObligationAtom, Proposal, ShadowItem, UnusedCapabilityPayload
from individuation_agent.reconcile import Ledger, reconcile
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def obligation(name, status="live"):
    return ObligationAtom(id=uuid4(), made_on=NOW, made_by="agent:t", made_in="session:1", terminal=True,
                          tier="VERIFIED", status="live", name=name, owed_to="party:a", obligation_status=status)


def self_claim(about, statement):
    return IdentityAtom(id=uuid4(), made_on=NOW, made_by="agent:t", made_in="session:1", about=about, terminal=True,
                        tier="VERIFIED", status="live", statement=statement, atom_kind="fact", confidence=0.9)


def ledger_with(tmp_path, *entries):
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return Ledger(path)


@pytest.fixture
def store(tmp_path):
    return AtomStore(tmp_path / "atoms.jsonl")


def test_ledger_wins_for_obligation_state(store, tmp_path):
    o = obligation("weekly-summary", "live")
    store.append(o)
    ledger = ledger_with(tmp_path, {"kind": "obligation", "name": "weekly-summary", "obligation_status": "discharged"})
    report = reconcile(store, ledger, session_id="session:2", now=NOW)
    assert report.unresolved == 0 and report.resolved == 1
    assert report.conflicts[0].precedence == "ledger" and report.conflicts[0].name == "weekly-summary"
    assert store.get(o.id).status == "superseded"
    live = store.all(kind="ego.obligation", status="live")
    assert len(live) == 1 and live[0].obligation_status == "discharged" and live[0].supersedes == o.id


def test_store_wins_for_self_claims(store, tmp_path):
    a = self_claim("self.role", "I am a documentation assistant")
    store.append(a)
    ledger = ledger_with(tmp_path, {"kind": "self_claim", "about": "self.role", "statement": "I am a release manager"})
    report = reconcile(store, ledger, session_id="session:2", now=NOW)
    assert report.resolved == 1 and report.conflicts[0].precedence == "store"
    assert store.get(a.id).status == "live"
    assert len(store.all(kind="self.identity_atom")) == 1  # nothing appended for a store-wins conflict


def test_ledger_obligation_absent_from_store_is_appended_as_reported(store, tmp_path):
    ledger = ledger_with(tmp_path, {"kind": "obligation", "name": "sign-audit", "obligation_status": "live",
                                    "owed_to": "party:b"})
    report = reconcile(store, ledger, session_id="session:2", now=NOW)
    assert report.resolved == 1 and report.conflicts[0].precedence == "ledger"
    live = store.all(kind="ego.obligation", status="live")
    assert len(live) == 1 and live[0].name == "sign-audit" and live[0].tier == "REPORTED" and live[0].owed_to == "party:b"


def test_agreeing_stores_produce_an_empty_report(store, tmp_path):
    store.append(obligation("weekly-summary", "live"))
    ledger = ledger_with(tmp_path, {"kind": "obligation", "name": "weekly-summary", "obligation_status": "live"})
    report = reconcile(store, ledger, session_id="session:2", now=NOW)
    assert report.conflicts == [] and report.resolved == 0
    rec = store.get(report.atom_id)
    assert rec.kind == "ego.reconcile_report" and rec.model_extra["resolved"] == 0


def _item():
    return ShadowItem(id=uuid4(), made_on=NOW, made_by="d", made_in="s", terminal=True, tier="VERIFIED",
                      probe_id=uuid4(), class_="unused_capability",
                      payload=UnusedCapabilityPayload(tool_id="grep", available_since=NOW, never_called_in=["s"]),
                      probed_in="c1", persona_id="g", defer_count=0)


def test_governance_reconciles_before_judging_when_a_ledger_is_wired(store, tmp_path):
    o = obligation("weekly-summary", "live")
    store.append(o)
    ledger = ledger_with(tmp_path, {"kind": "obligation", "name": "weekly-summary", "obligation_status": "BREACHED"})
    it = _item()
    p = Proposal(id=uuid4(), action="adopt", target=it.probe_id, rationale="grep is bound", tier="VERIFIED")
    accepted, rejected, verdicts = Governance(store, ledger=ledger).filter([p], {it.probe_id: it})
    assert verdicts.reconcile == "PASS"
    assert verdicts.obligation_check == "FAIL"  # the breach came in through the ledger
    assert accepted == [] and rejected[0].blocked_by == "obligation:weekly-summary"


def test_governance_without_a_ledger_keeps_the_documented_single_store_pass(store):
    it = _item()
    p = Proposal(id=uuid4(), action="adopt", target=it.probe_id, rationale="grep is bound", tier="VERIFIED")
    _, _, verdicts = Governance(store).filter([p], {it.probe_id: it})
    assert verdicts.reconcile == "PASS"


def test_governance_reconcile_is_unknown_when_the_ledger_cannot_be_read(store, tmp_path):
    ledger = Ledger(tmp_path / "missing.jsonl")
    it = _item()
    p = Proposal(id=uuid4(), action="adopt", target=it.probe_id, rationale="grep is bound", tier="VERIFIED")
    _, _, verdicts = Governance(store, ledger=ledger).filter([p], {it.probe_id: it})
    assert verdicts.reconcile == "UNKNOWN"
