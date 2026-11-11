"""Plane 3 of the lab: the blind exam. Pool from the workload facts; stratified draw seeded per run;
24-hour wall-clock eligibility; each probe asked in a fresh context; grader inputs carry no run or
condition; low-confidence grades go to a tie-break queue for Austin's hand; scoring refuses until the
queue is empty."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lab.driver.run import run_condition
from lab.driver.scripted import LabScriptedModel
from lab.exam.grade import ScriptedGrader, apply_tiebreaks, deterministic_check, grade_run
from lab.exam.pool import EligibilityError, build_pool, draw_battery
from lab.exam.runner import ExamAlreadyRun, run_exam
from lab.exam.score import NotYetGraded, score_run
from lab.workload.generate import build_scenario, write_scenario

CATEGORIES = ("identity_fact", "decision", "commitment", "preference")
LATER = datetime.now(timezone.utc) + timedelta(days=2)


@pytest.fixture(scope="module")
def scenario_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("scenario")
    write_scenario(build_scenario(), d)
    return d


@pytest.fixture(scope="module")
def p_run(scenario_dir, tmp_path_factory):
    run_dir = tmp_path_factory.mktemp("exam_p")
    run_condition("C_P", scenario_dir, run_dir, LabScriptedModel(), model_id="scripted")
    return run_dir


@pytest.fixture(scope="module")
def c_run(scenario_dir, tmp_path_factory):
    run_dir = tmp_path_factory.mktemp("exam_c")
    run_condition("C_0", scenario_dir, run_dir, LabScriptedModel(), model_id="scripted")
    return run_dir


def test_pool_has_every_fact_with_its_establishing_time(p_run, scenario_dir):
    pool = build_pool(scenario_dir, p_run)
    assert len(pool) == 320
    assert all(p.established_at.tzinfo is not None for p in pool)
    assert {p.category for p in pool} == set(CATEGORIES)
    assert all(p.first_person_question and p.canonical_statement and p.wrong_twin for p in pool)


def test_draw_is_stratified_seeded_and_without_replacement(p_run, scenario_dir):
    pool = build_pool(scenario_dir, p_run)
    a = draw_battery(pool, run_id="run-a", scenario_sha="x", eval_time=LATER)
    b = draw_battery(pool, run_id="run-a", scenario_sha="x", eval_time=LATER)
    c = draw_battery(pool, run_id="run-b", scenario_sha="x", eval_time=LATER)
    assert len(a) == 60 and len({p.probe_id for p in a}) == 60
    assert all(sum(1 for p in a if p.category == cat) == 15 for cat in CATEGORIES)
    assert [p.probe_id for p in a] == [p.probe_id for p in b]
    assert [p.probe_id for p in a] != [p.probe_id for p in c]


def test_draw_refuses_probes_younger_than_24_hours(p_run, scenario_dir):
    pool = build_pool(scenario_dir, p_run)
    with pytest.raises(EligibilityError):
        draw_battery(pool, run_id="run-a", scenario_sha="x", eval_time=datetime.now(timezone.utc))
    assert len(draw_battery(pool, run_id="run-a", scenario_sha="x", eval_time=datetime.now(timezone.utc),
                            min_age=timedelta(0))) == 60


@pytest.fixture(scope="module")
def p_exam(p_run, scenario_dir):
    return run_exam(p_run, scenario_dir, LabScriptedModel(), model_id="scripted", min_age=timedelta(0))


@pytest.fixture(scope="module")
def c_exam(c_run, scenario_dir):
    return run_exam(c_run, scenario_dir, LabScriptedModel(), model_id="scripted", min_age=timedelta(0))


def test_exam_asks_every_drawn_probe_in_a_fresh_context(p_run, p_exam):
    answers = [json.loads(l) for l in (p_run / "exam" / "answers.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert len(answers) == 60
    assert all(a["answer"] and a["latency_ms"] >= 0 and a["provider_calls"] >= 1 for a in answers)
    rows = [json.loads(l) for l in (p_run / "exam" / "transcript.jsonl").read_text(encoding="utf-8").splitlines() if l]
    users = [r for r in rows if r["role"] == "user"]
    assert len(users) == 60 and all(r["fresh_context"] for r in users)
    battery = json.loads((p_run / "exam" / "battery.json").read_text(encoding="utf-8"))
    assert len(battery["probe_ids"]) == 60 and battery["min_age_hours"] == 0


def test_exam_refuses_to_run_twice(p_run, scenario_dir, p_exam):
    with pytest.raises(ExamAlreadyRun):
        run_exam(p_run, scenario_dir, LabScriptedModel(), model_id="scripted", min_age=timedelta(0))


def test_exam_agent_has_memory_search_only(p_run, p_exam):
    rows = [json.loads(l) for l in (p_run / "exam" / "transcript.jsonl").read_text(encoding="utf-8").splitlines() if l]
    names = {r["name"] for r in rows if r["role"] == "tool"}
    assert names == {"memory_search"}


def test_deterministic_check_decides_only_unambiguous_cases():
    assert deterministic_check("I owe the QA guild the migration guide by 2026-11-26.",
                               "I owe the QA guild the migration guide by 2026-12-03.",
                               "you owe the QA guild the migration guide by 2026-11-26") == "HIT"
    assert deterministic_check("The tool grep is within my capability bounds.", "The tool grep is outside my capability bounds.",
                               "grep is outside my bounds") == "MISS_CONTRADICTION"
    assert deterministic_check("max_retries is 5, decided on 2026-11-14.", "max_retries is 2.",
                               "the canonical max_retries is 5 (it used to be 2)") is None
    assert deterministic_check("My name is Scribe.", "My name is Quill.", "I cannot recall that.") == "MISS_REFUSAL"


def test_grader_inputs_are_blind_and_low_confidence_goes_to_the_queue(p_run, p_exam):
    report = grade_run(p_run, ScriptedGrader(), threshold=0.9)
    grades = [json.loads(l) for l in (p_run / "exam" / "grades.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert len(grades) == 60
    for g in grades:
        assert set(g) >= {"probe_hash", "outcome", "confidence", "needs_tiebreak"}
        assert "run_id" not in g and "condition" not in g and "probe_id" not in g
    queue = [json.loads(l) for l in (p_run / "exam" / "tiebreak-queue.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert report.queued == len(queue) == sum(1 for g in grades if g["needs_tiebreak"])
    assert all(set(q) == {"probe_hash", "question", "canonical", "wrong_twin", "answer"} for q in queue)
    assert report.queued >= 1  # the scripted answers include ambiguous ones by construction


def test_score_refuses_until_the_queue_is_resolved_then_reports(p_run, p_exam):
    grade_run(p_run, ScriptedGrader(), threshold=0.9)
    with pytest.raises(NotYetGraded):
        score_run(p_run)
    queue = [json.loads(l) for l in (p_run / "exam" / "tiebreak-queue.jsonl").read_text(encoding="utf-8").splitlines() if l]
    decisions = p_run / "exam" / "tiebreak-decisions.jsonl"
    decisions.write_text("".join(json.dumps({"probe_hash": q["probe_hash"], "outcome": "HIT"}) + "\n" for q in queue), encoding="utf-8")
    applied = apply_tiebreaks(p_run, decisions)
    assert applied == len(queue)
    result = score_run(p_run)
    assert result["status"] == "graded" and result["n_probes"] == 60
    assert 0.0 <= result["sc"] <= 1.0 and result["hits"] + result["contradictions"] + result["refusals"] == 60
    assert set(result["by_category"]) == set(CATEGORIES)
    assert result["mean_latency_to_correct_ms"] is None or result["mean_latency_to_correct_ms"] >= 0
    saved = json.loads((p_run / "exam" / "result.json").read_text(encoding="utf-8"))
    assert saved["sc"] == result["sc"]
    # the join from blind hash back to probe id happens here, inside the run directory, nowhere else
    assert all("probe_id" in item and "category" in item for item in result["items"])


def test_control_exam_runs_and_grades_the_same_way(c_run, c_exam):
    rows = [json.loads(l) for l in (c_run / "exam" / "transcript.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert {r["name"] for r in rows if r["role"] == "tool"} == {"notes_search"}
    report = grade_run(c_run, ScriptedGrader(), threshold=0.9)
    assert report.graded == 60
