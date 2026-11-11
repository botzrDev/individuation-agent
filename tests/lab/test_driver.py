"""Plane 2 of the lab: the session driver. One run = the whole scenario under one condition with one model.
With the scripted model this is the plumbing test (lab plan phase A): every tool fires, every fault seed
reaches the substrate, the transcript holds the establishing turn of every fact, and the control
condition stores the same content with none of the eight properties."""

import json
from pathlib import Path

import pytest

from individuation_agent.store import AtomStore
from lab.driver.run import run_condition
from lab.driver.scripted import LabScriptedModel
from lab.workload.generate import BLIND_SPOT_SIGNATURE, BREACHED_OBLIGATION, build_scenario, write_scenario


@pytest.fixture(scope="module")
def scenario_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("scenario")
    write_scenario(build_scenario(), d)
    return d


@pytest.fixture(scope="module")
def p_run(scenario_dir, tmp_path_factory):
    run_dir = tmp_path_factory.mktemp("run_p")
    return run_condition("C_P", scenario_dir, run_dir, LabScriptedModel(), model_id="scripted")


@pytest.fixture(scope="module")
def c_run(scenario_dir, tmp_path_factory):
    run_dir = tmp_path_factory.mktemp("run_c")
    return run_condition("C_0", scenario_dir, run_dir, LabScriptedModel(), model_id="scripted")


def _store(run) -> AtomStore:
    return AtomStore(Path(run.run_dir) / "store.jsonl")


def _transcript(run, index: int) -> list[dict]:
    p = Path(run.run_dir) / "transcripts" / f"s{index:02d}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l]


def test_run_manifest_is_complete(p_run, scenario_dir):
    m = json.loads((Path(p_run.run_dir) / "run.json").read_text(encoding="utf-8"))
    assert m["condition"] == "C_P" and m["model_id"] == "scripted" and m["status"] == "complete"
    assert m["scenario_sha256"] == json.loads((scenario_dir / "manifest.json").read_text())["sha256"]
    assert len(m["sessions"]) == 15 and all(s["turns"] >= 8 for s in m["sessions"])
    assert m["provider_calls"] > 0 and m["total_latency_ms"] >= 0


def test_p_agent_recorded_every_delivered_fact(p_run):
    store = _store(p_run)
    statements = [a.statement for a in store.all(kind="self.identity_atom") if a.made_by.startswith("agent:")]
    assert len(statements) >= 320
    sc = build_scenario()
    missing = [f.fact_id for f in sc.facts if not any(f.delivered_as in s for s in statements)]
    assert missing == []


def test_p_agent_store_validates_every_row(p_run):
    from individuation_agent.models import validate_row
    rows = [json.loads(l) for l in (Path(p_run.run_dir) / "store.jsonl").read_text(encoding="utf-8").splitlines() if l]
    for r in rows:
        validate_row(r, "atom-envelope.schema.json")


def test_verified_claims_carry_the_artifact_hash(p_run):
    store = _store(p_run)
    verified = [a for a in store.all(kind="self.identity_atom") if a.tier == "VERIFIED" and getattr(a, "artifact_sha256", None)]
    refs = {a.artifact_ref for a in verified}
    assert "etc/agent/retry_policy.toml" in refs and "docs/conventions.md" in refs


def test_contradiction_seed_reaches_the_shadow_log(p_run):
    store = _store(p_run)
    items = [i for i in store.all(kind="shadow.item") if i.class_ == "contradiction"]
    assert any("max_retries" in (i.payload.statement_a or "") or "max_retries" in (i.payload.statement_b or "") for i in items)


def test_tool_fault_is_an_error_atom_and_a_blind_spot(p_run):
    store = _store(p_run)
    errors = [e for e in store.all(kind="ego.error") if e.error_signature == BLIND_SPOT_SIGNATURE]
    assert {e.made_in for e in errors} >= {"s07", "s08"}
    assert any(i.class_ == "blind_spot" and i.payload.error_signature == BLIND_SPOT_SIGNATURE
               for i in store.all(kind="shadow.item"))


def test_every_task_tool_call_is_recorded(p_run):
    store = _store(p_run)
    called = {c.tool_id for c in store.all(kind="ego.tool_call")}
    assert {"read_file", "query_db"} <= called


def test_cycles_fire_at_every_session_boundary(p_run):
    store = _store(p_run)
    records = store.all(kind="self.stage_record")
    assert len(records) == 30  # session_start or role_switch, then session_end, for 15 sessions
    s1 = [store.get(r.stages.s1) for r in records]
    assert {x.event for x in s1} == {"session_start", "role_switch", "session_end"}
    assert [x.archetype for x in s1][6] == "Harvester"  # session 4's start cycle routed by the context text


def test_ledger_breach_blocks_proposals_in_session_twelve(p_run):
    store = _store(p_run)
    records = [r for r in store.all(kind="self.stage_record") if r.made_in == "s12"]
    assert records[-1].governance.obligation_check == "FAIL"
    assert all(r.blocked_by == f"obligation:{BREACHED_OBLIGATION}" for r in records[-1].rejected) or records[-1].rejected == []
    ledger = (Path(p_run.run_dir) / "ledger.jsonl").read_text(encoding="utf-8")
    assert "BREACHED" in ledger


def test_gate_fails_when_the_mounted_conventions_file_changes(p_run):
    store = _store(p_run)
    reports = {r.made_in: r for r in store.all(kind="ego.gate_report")}
    assert reports["s14"].model_extra["gate_status"] == "FAIL" and reports["s14"].model_extra["stale"]
    assert reports["s13"].model_extra["gate_status"] == "PASS"
    acks = store.all(kind="ego.gate_ack")
    assert any(a.made_in == "s15" and reports["s14"].id in a.links for a in acks)


def test_transcript_holds_the_establishing_turn_of_every_fact(p_run):
    sc = build_scenario()
    for f in sc.facts:
        rows = _transcript(p_run, f.session_index)
        users = [r for r in rows if r["role"] == "user" and r.get("turn_id") == f.turn_id]
        assert len(users) == 1 and f.delivered_as in users[0]["content"]


def test_transcript_records_provider_calls_with_latency(p_run):
    rows = _transcript(p_run, 1)
    calls = [r for r in rows if r["role"] == "provider_call"]
    assert calls and all("latency_ms" in r and "prompt_sha256" in r for r in calls)


def test_control_stores_the_same_content_in_free_form_notes(c_run):
    run_dir = Path(c_run.run_dir)
    assert not (run_dir / "store.jsonl").exists() and not (run_dir / "ledger.jsonl").exists()
    notes = (run_dir / "notes.md").read_text(encoding="utf-8")
    sc = build_scenario()
    assert all(f.delivered_as in notes for f in sc.facts)
    assert "max_retries is 2" in notes  # the reported twin is kept beside the verified value: no supersession
    m = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert m["condition"] == "C_0" and m["status"] == "complete" and len(m["sessions"]) == 15


def test_control_and_treatment_see_identical_user_turns(p_run, c_run):
    for i in range(1, 16):
        p = [r["content"] for r in _transcript(p_run, i) if r["role"] == "user"]
        c = [r["content"] for r in _transcript(c_run, i) if r["role"] == "user"]
        assert p == c


def test_substrate_only_condition_runs_no_cycles(scenario_dir, tmp_path):
    run = run_condition("C_S", scenario_dir, tmp_path / "run_s", LabScriptedModel(), model_id="scripted")
    store = _store(run)
    assert store.all(kind="self.stage_record") == []
    assert len([a for a in store.all(kind="self.identity_atom")]) >= 320
    assert store.all(kind="ego.gate_report")  # the substrate's gate still runs without the loop
