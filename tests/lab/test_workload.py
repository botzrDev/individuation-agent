"""Plane 1 of the lab: the deterministic workload. One scenario, identical bytes for every condition and
every run. Lab plan section 6: 15 sessions in five epochs, 320 probe-eligible facts balanced over four
categories, artifact mounts for VERIFIED claims, one fault seed per Shadow class, governance traps in
epoch IV, noise in epoch V, frozen by hash."""

import hashlib
import json
from collections import Counter

import pytest

from lab.workload.generate import ARCHETYPE_SCHEDULE, ROUTING, build_scenario, load_scenario, write_scenario

CATEGORIES = ("identity_fact", "decision", "commitment", "preference")


@pytest.fixture(scope="module")
def sc():
    return build_scenario()


def test_scenario_is_deterministic():
    a, b = build_scenario(), build_scenario()
    assert a.manifest["sha256"] == b.manifest["sha256"]
    assert a.manifest["scenario_id"] == "rio-lab-v1"


def test_counts(sc):
    assert len(sc.sessions) == 15
    assert len(sc.facts) == 320
    assert Counter(f.category for f in sc.facts) == {c: 80 for c in CATEGORIES}
    assert all(8 <= len(s.turns) <= 12 for s in sc.sessions)
    assert [s.index for s in sc.sessions] == list(range(1, 16))


def test_every_fact_is_delivered_in_exactly_one_turn(sc):
    turns = {(s.index, t.turn_id): t for s in sc.sessions for t in s.turns}
    delivered = Counter()
    for t in turns.values():
        for fid in t.establishes:
            delivered[fid] += 1
    assert delivered == {f.fact_id: 1 for f in sc.facts}
    for f in sc.facts:
        t = turns[(f.session_index, f.turn_id)]
        assert f.fact_id in t.establishes
        assert f.delivered_as in t.user_prompt


def test_fact_statements_are_distinct_and_twinned(sc):
    canon = [f.canonical_statement for f in sc.facts]
    assert len(set(canon)) == 320
    for f in sc.facts:
        assert f.canonical_statement != f.wrong_twin
        assert f.first_person_question.strip().endswith("?")
        assert f.component


def test_facts_are_spread_across_sessions_and_categories(sc):
    per_session = Counter(f.session_index for f in sc.facts)
    assert set(per_session) == set(range(1, 16))
    assert all(20 <= n <= 23 for n in per_session.values())
    for s in range(1, 16):
        cats = Counter(f.category for f in sc.facts if f.session_index == s)
        assert all(cats[c] >= 4 for c in CATEGORIES)


def test_contradiction_seed_is_a_reported_twin_before_a_verified_artifact(sc):
    seeded = [f for f in sc.facts if f.seeded_contradiction_in is not None]
    assert len(seeded) == 1
    f = seeded[0]
    assert f.session_index == 5 and f.seeded_contradiction_in == 4
    assert f.artifact_ref and f.artifact_excerpt
    s4 = next(s for s in sc.sessions if s.index == 4)
    assert any(f.wrong_twin_delivered_as in t.user_prompt for t in s4.turns)
    s5 = next(s for s in sc.sessions if s.index == 5)
    assert f.artifact_ref in s5.mounts


def test_blind_spot_seed_repeats_one_error_signature_in_two_sessions(sc):
    sigs = {s.index: s.injected_faults.get("query_db") for s in sc.sessions}
    assert sigs[7] == sigs[8] and sigs[7] is not None
    assert all(v is None for i, v in sigs.items() if i not in (7, 8))


def test_governance_traps_sit_in_epoch_four(sc):
    s11 = next(s for s in sc.sessions if s.index == 11)
    assert any(t.trap == "constraint" for t in s11.turns)
    s12 = next(s for s in sc.sessions if s.index == 12)
    edit = next(t.ledger_edit for t in s12.turns if t.ledger_edit)
    assert edit["kind"] == "obligation" and edit["obligation_status"] == "BREACHED"
    assert any(f.category == "commitment" and edit["name"] in f.canonical_statement for f in sc.facts)


def test_a_mounted_artifact_changes_in_epoch_five_for_the_freshness_gate(sc):
    by_index = {s.index: s for s in sc.sessions}
    ref = next(r for r in by_index[14].mounts if any(r in by_index[i].mounts for i in range(1, 14)))
    earlier = next(by_index[i].mounts[ref] for i in range(1, 14) if ref in by_index[i].mounts)
    assert by_index[14].mounts[ref].sha256 != earlier.sha256


def test_mount_hashes_match_their_content(sc):
    n = 0
    for s in sc.sessions:
        for m in s.mounts.values():
            assert m.sha256 == hashlib.sha256(m.content.encode("utf-8")).hexdigest()
            n += 1
    assert n >= 5


def test_archetype_schedule_and_routing_keywords(sc):
    for s in sc.sessions:
        assert s.archetype == ARCHETYPE_SCHEDULE[s.index]
        if s.archetype != "Sage":
            assert any(k in s.context_text for k in ROUTING[s.archetype])
        else:
            assert not any(k in s.context_text for a, ks in ROUTING.items() for k in ks)


def test_write_and_load_round_trip(sc, tmp_path):
    out = tmp_path / "scenario-v1"
    write_scenario(sc, out)
    assert (out / "manifest.json").exists() and (out / "sessions.jsonl").exists() and (out / "facts.jsonl").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == sc.manifest["sha256"]
    assert manifest["facts"] == 320 and manifest["sessions"] == 15
    loaded = load_scenario(out)
    assert loaded.manifest["sha256"] == sc.manifest["sha256"]
    assert [t.turn_id for s in loaded.sessions for t in s.turns] == [t.turn_id for s in sc.sessions for t in s.turns]
    # mounts are materialised as files so an ArtifactMount can read them
    for s in sc.sessions:
        for ref, m in s.mounts.items():
            assert (out / "mounts" / f"s{s.index:02d}" / ref).read_bytes() == m.content.encode("utf-8")


# Strings that must never appear in the synthetic workload (key material markers, a workspace host and real
# organization names). They are kept as (length, SHA-256) pairs so that this public test does not itself
# disclose them; the check hashes every substring of that length.
BANNED_DIGESTS = {
    (5, "9773c51acdc6199d630e2a2b7c69471d36d865135a290a601b16bc9d6dc8b5ed"),
    (6, "ea83182c4b01ad677d71cd6fc69e9d5969cc5df473b930530be28bd9d299dc68"),
    (8, "587133f1d87bf050b7b97ceaa0f7ee9a776096b84da33e7a0e7928daa2cd46e3"),
    (8, "70ba70cdd7a8f1e95df370ec8b77c68d841cce2bfecdbae6f45c21b502b0d2e9"),
    (9, "57fff70c15770f045ee85cd210c158b1884a4b5713da161448f32ffbcd19fd3a"),
    (10, "43987e80713406439531727a8c0c579ec199d87946f939d9d142cac8aedc91f7"),
    (13, "b39b036dacda42c29eeb7a4e6eb894747e93600654e48d26e1425687efb453d7"),
}


def test_no_real_world_sensitive_strings(sc):
    blob = json.dumps([s.model_dump() for s in sc.sessions] + [f.model_dump() for f in sc.facts]).lower().encode("utf-8")
    for n in {n for n, _ in BANNED_DIGESTS}:
        seen = {hashlib.sha256(blob[i:i + n]).hexdigest() for i in range(len(blob) - n + 1)}
        assert not {(n, h) for h in seen} & BANNED_DIGESTS
