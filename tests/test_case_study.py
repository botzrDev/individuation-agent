"""The case-study harness must be reproducible with the scripted model and must show the two
behaviours the paper's case study is for: a resolve accepted, and governance refusing on a breach."""

import json
import runpy
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("case")
    store = tmp / "store.jsonl"
    out = tmp / "out"
    sys.argv = ["case_study.py", "--fake", "--store", str(store), "--out", str(out)]
    sys.path.insert(0, str(EXAMPLES))
    try:
        with pytest.raises(SystemExit) as e:
            runpy.run_path(str(EXAMPLES / "case_study.py"), run_name="__main__")
    finally:
        sys.path.remove(str(EXAMPLES))
    assert e.value.code == 0
    return json.loads((out / "trace.json").read_text(encoding="utf-8")), (out / "trace.md").read_text(encoding="utf-8")


def test_five_cycles_recorded(run):
    trace, _ = run
    assert trace["model"] == "scripted"
    assert trace["cycles_run"] == 5
    assert [c["cycle"] for c in trace["cycles"]] == [1, 2, 3, 4, 5]


def test_cycle_one_probes_all_four_classes_and_resolves_the_contradiction(run):
    trace, _ = run
    c1 = trace["cycles"][0]
    classes = sorted(i["class"] for i in c1["s2"]["probed"])
    assert classes == ["blind_spot", "contradiction", "unused_capability", "unused_capability"]
    assert c1["s2"]["sources"]["collective_unconscious"]["status"] == "BLIND"
    assert [a["action"] for a in c1["s4"]["accepted"]] == ["resolve"]
    assert c1["s4"]["accepted"][0]["tier"] == "INFERRED"  # model-authored, capped
    assert c1["s4"]["es"] == 0.25


def test_breached_obligation_fails_governance_in_cycle_two(run):
    trace, _ = run
    c2 = trace["cycles"][1]
    assert "BREACHED" in c2["note"]
    assert c2["s4"]["governance"]["obligation_check"] == "FAIL"
    assert c2["s4"]["accepted"] == []
    # the contradiction resolved in cycle 1 is gone; the open blind spot and the unused tools carry forward
    assert sorted(i["class"] for i in c2["s2"]["probed"]) == ["blind_spot", "unused_capability", "unused_capability"]


def test_discharge_restores_pass(run):
    trace, _ = run
    assert trace["cycles"][2]["s4"]["governance"]["obligation_check"] == "PASS"


def test_markdown_mirrors_json(run):
    trace, md = run
    assert md.count("## Cycle ") == 5
    assert "obligation=FAIL" in md
    assert "I am a release manager" in md
