import json

from individuation_agent.cli import main


def test_demo_fake_writes_s4(tmp_path, capsys):
    store = tmp_path / "demo.jsonl"
    assert main(["demo", "--store", str(store), "--fake"]) == 0
    capsys.readouterr()
    assert main(["show", "--store", str(store)]) == 0
    out = capsys.readouterr().out
    record = json.loads(out)
    assert record["kind"] == "self.stage_record"
    assert record["es"] == 0.5
    assert [a["action"] for a in record["accepted"]] == ["resolve"]


def test_usage_error_exit_2(capsys):
    assert main(["bogus"]) == 2
    assert main([]) == 2
